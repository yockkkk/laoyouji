"""Unit and Contract Tests for Topic Anchor & Context Anti-Drift Engine.

Verifies:
1. TopicAnchor data model initialization, defaults, and Pydantic serialization.
2. ActivityType enum parsing and normalization.
3. Activity detection heuristics (detect_activity_from_text).
4. Park destination extraction (extract_destination).
5. State machine transitions and lock_turns_remaining behavior (update_topic_anchor).
6. Conflict interception guard (can_transition_to).
7. Negative constraints rendering in system prompt directives (render_prompt_directive).
8. Boundary conditions and resilience against corrupted inputs.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.topic_anchor import (
    ActivityType,
    TopicAnchor,
    detect_activity_from_text,
    extract_destination,
    update_topic_anchor,
    EXPLICIT_MEDICAL_KEYWORDS,
    GENERIC_MOVEMENT_WORDS,
    LEISURE_WALK_KEYWORDS,
)


# ==============================================================================
# 1. TopicAnchor Data Model & Pydantic Validation
# ==============================================================================

def test_topic_anchor_default_initialization():
    """Verify default field values of a freshly initialized TopicAnchor."""
    anchor = TopicAnchor()
    assert anchor.activity_type == ActivityType.IDLE
    assert anchor.target_destination is None
    assert anchor.origin == "家"
    assert anchor.target_spot is None
    assert anchor.health_constraints == []
    assert anchor.confirmed_steps == []
    assert anchor.lock_turns_remaining == 0
    assert not anchor.is_locked()


def test_topic_anchor_custom_initialization():
    """Verify initialization with custom parameters."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        origin="华夏路社区家属院",
        target_spot="年嘉湖畔",
        health_constraints=["避开台阶", "坡度<3%"],
        confirmed_steps=["意图确认：休闲散步", "锁定目的地：烈士公园年嘉湖"],
        lock_turns_remaining=4,
    )
    assert anchor.activity_type == ActivityType.LEISURE_WALK
    assert anchor.target_destination == "烈士公园年嘉湖"
    assert anchor.origin == "华夏路社区家属院"
    assert anchor.target_spot == "年嘉湖畔"
    assert len(anchor.health_constraints) == 2
    assert len(anchor.confirmed_steps) == 2
    assert anchor.lock_turns_remaining == 4
    assert anchor.is_locked()


def test_topic_anchor_serialization_roundtrip():
    """Verify model dump and restoration preserves all state accurately."""
    original = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="橘子洲头",
        origin="家",
        health_constraints=["防滑防摔", "沿途长椅"],
        confirmed_steps=["确认散步"],
        lock_turns_remaining=3,
    )
    dumped = original.model_dump()
    assert dumped["activity_type"] == "leisure_walk"
    assert dumped["target_destination"] == "橘子洲头"
    assert dumped["lock_turns_remaining"] == 3

    restored = TopicAnchor.model_validate(dumped)
    assert restored.activity_type == original.activity_type
    assert restored.target_destination == original.target_destination
    assert restored.health_constraints == original.health_constraints
    assert restored.lock_turns_remaining == original.lock_turns_remaining


def test_activity_type_normalization():
    """Verify ActivityType enum handles casing and missing values gracefully."""
    assert ActivityType("idle") == ActivityType.IDLE
    assert ActivityType("leisure_walk") == ActivityType.LEISURE_WALK
    assert ActivityType("medical_escort") == ActivityType.MEDICAL_ESCORT
    assert ActivityType("daily_companion") == ActivityType.DAILY_COMPANION

    # Case insensitivity test
    assert ActivityType("LEISURE_WALK") == ActivityType.LEISURE_WALK
    assert ActivityType("Medical_Escort") == ActivityType.MEDICAL_ESCORT


# ==============================================================================
# 2. Activity Intent Detection (detect_activity_from_text)
# ==============================================================================

def test_detect_activity_leisure_walk():
    """Verify walk phrases are classified as LEISURE_WALK."""
    walk_phrases = [
        "想去散步",
        "今天天气好，想出门走走",
        "带我去公园逛逛",
        "年嘉湖边上溜达溜达",
        "湖边散步路线",
        "去烈士公园漫步",
    ]
    for phrase in walk_phrases:
        detected = detect_activity_from_text(phrase)
        assert detected == ActivityType.LEISURE_WALK, f"Failed for phrase: {phrase}"


def test_detect_activity_explicit_medical():
    """Verify acute symptoms and explicit medical terms trigger MEDICAL_ESCORT."""
    medical_phrases = [
        "我胸口闷要去医院",
        "腿疼得厉害帮我挂号",
        "摔倒了骨折了叫救护车",
        "去医院看门诊配降压药",
        "心脏难受去急诊",
    ]
    for phrase in medical_phrases:
        detected = detect_activity_from_text(phrase)
        assert detected == ActivityType.MEDICAL_ESCORT, f"Failed for phrase: {phrase}"


def test_detect_activity_generic_movement_returns_none():
    """Verify generic movement verbs do NOT unilaterally trigger medical intent."""
    generic_movement = [
        "现在就走",
        "导航路线怎么不给我",
        "我要跟着导航走",
        "怎么去",
        "出发吧",
        "走吧",
    ]
    for phrase in generic_movement:
        detected = detect_activity_from_text(phrase)
        assert detected is None, f"Generic movement '{phrase}' must return None, got {detected}"


def test_detect_activity_daily_companion():
    """Verify casual chit-chat maps to DAILY_COMPANION."""
    assert detect_activity_from_text("陪我聊聊天，老头子一个人挺无聊") == ActivityType.DAILY_COMPANION
    assert detect_activity_from_text("讲个笑话解解闷") == ActivityType.DAILY_COMPANION


# ==============================================================================
# 3. Park Destination Extraction (extract_destination)
# ==============================================================================

def test_extract_destination_known_landmarks():
    """Verify accurate extraction of known Changsha park landmarks."""
    assert extract_destination("我想去烈士公园年嘉湖散步") == "烈士公园年嘉湖"
    assert extract_destination("去烈士公园走走") == "烈士公园"
    assert extract_destination("去橘子洲头看江景") == "橘子洲头"
    assert extract_destination("到岳麓山爱晚亭散步") == "岳麓山爱晚亭"
    assert extract_destination("去洋湖湿地公园散心") == "洋湖湿地公园"
    assert extract_destination("松雅湖湿地公园散步") == "松雅湖湿地公园"
    assert extract_destination("去天心阁公园转转") == "天心阁公园"


def test_extract_destination_verb_guided_patterns():
    """Verify pattern extraction for destinations guided by prepositions."""
    assert extract_destination("我们前往后湖国际艺术区逛逛") == "后湖国际艺术区"
    assert extract_destination("我想逛逛西湖公园") == "西湖公园"


def test_extract_destination_none_for_generic_phrases():
    """Verify generic utterances without a destination return None."""
    assert extract_destination("现在就走") is None
    assert extract_destination("导航路线怎么不给我") is None
    assert extract_destination("安静一点") is None
    assert extract_destination("") is None


# ==============================================================================
# 4. State Machine Transitions & Lock Turns (update_topic_anchor)
# ==============================================================================

def test_update_topic_anchor_walk_initiation():
    """Turn 1: '想去散步' initiates LEISURE_WALK with locked turns >= 3."""
    initial = TopicAnchor()
    updated = update_topic_anchor(initial, "想去散步")
    assert updated.activity_type == ActivityType.LEISURE_WALK
    assert updated.lock_turns_remaining >= 3
    assert updated.is_locked()
    assert any("休闲散步" in s for s in updated.confirmed_steps)


def test_update_topic_anchor_quiet_preference():
    """Turn 2: '安静一点' records quiet constraint and keeps LEISURE_WALK locked."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        lock_turns_remaining=4,
    )
    updated = update_topic_anchor(anchor, "安静一点")
    assert updated.activity_type == ActivityType.LEISURE_WALK
    assert updated.lock_turns_remaining >= 3
    assert "偏好清幽安静绿道" in updated.health_constraints


def test_update_topic_anchor_destination_and_spot_locking():
    """Turn 2b: Specifying '烈士公园年嘉湖' sets target_destination and target_spot."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        lock_turns_remaining=3,
    )
    updated = update_topic_anchor(anchor, "那就去烈士公园年嘉湖吧，清静一点")
    assert updated.activity_type == ActivityType.LEISURE_WALK
    assert updated.target_destination == "烈士公园年嘉湖"
    assert updated.target_spot == "年嘉湖"


def test_update_topic_anchor_depart_action():
    """Turn 3: '现在就走' advances confirmed steps and maintains LEISURE_WALK."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        lock_turns_remaining=3,
    )
    updated = update_topic_anchor(anchor, "现在就走")
    assert updated.activity_type == ActivityType.LEISURE_WALK
    assert updated.target_destination == "烈士公园年嘉湖"
    assert updated.lock_turns_remaining >= 3
    assert any("现在就走" in s for s in updated.confirmed_steps)


def test_update_topic_anchor_navigation_query_no_drift():
    """Turn 4: '导航路线怎么不给我' does NOT drift to medical escort."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        lock_turns_remaining=3,
    )
    updated = update_topic_anchor(anchor, "导航路线怎么不给我")
    assert updated.activity_type == ActivityType.LEISURE_WALK
    assert updated.target_destination == "烈士公园年嘉湖"
    assert updated.lock_turns_remaining >= 3
    assert any("索要导航路线" in s for s in updated.confirmed_steps)


def test_update_topic_anchor_follow_navigation_action():
    """Turn 5: '我要跟着导航走' retains LEISURE_WALK and triggers map escort step."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        lock_turns_remaining=3,
    )
    updated = update_topic_anchor(anchor, "我要跟着导航走")
    assert updated.activity_type == ActivityType.LEISURE_WALK
    assert updated.target_destination == "烈士公园年嘉湖"
    assert updated.lock_turns_remaining >= 3
    assert any("跟着导航走" in s or "大地图" in s for s in updated.confirmed_steps)


# ==============================================================================
# 5. Conflict Interception & Intent Isolation (can_transition_to)
# ==============================================================================

def test_can_transition_to_blocks_accidental_medical_drift():
    """When locked in LEISURE_WALK, generic queries MUST NOT transition to MEDICAL_ESCORT."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        lock_turns_remaining=3,
    )
    forbidden_queries = [
        "导航路线怎么不给我",
        "我要跟着导航走",
        "现在就走",
        "走",
        "路线在哪里",
        "怎么去那里",
        "出发吧",
    ]
    for q in forbidden_queries:
        assert not anchor.can_transition_to(ActivityType.MEDICAL_ESCORT, query=q), (
            f"Anti-drift failed! Permitted transition to MEDICAL_ESCORT for query: '{q}'"
        )


def test_can_transition_to_permits_acute_symptoms():
    """When acute symptoms are explicitly voiced, transition to MEDICAL_ESCORT is permitted."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        lock_turns_remaining=3,
    )
    acute_queries = [
        "我胸口闷要去医院",
        "突然心绞痛，帮我叫救护车",
        "哎呀我摔倒骨折了，快去急诊",
        "头晕得厉害要去医院挂号",
    ]
    for q in acute_queries:
        assert anchor.can_transition_to(ActivityType.MEDICAL_ESCORT, query=q), (
            f"Emergency blocked! Refused transition to MEDICAL_ESCORT for acute query: '{q}'"
        )


def test_update_topic_anchor_switches_on_acute_medical():
    """Verify update_topic_anchor directly switches to MEDICAL_ESCORT upon acute distress."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        lock_turns_remaining=3,
    )
    updated = update_topic_anchor(anchor, "突然胸口闷疼得厉害，快帮我叫救护车去医院")
    assert updated.activity_type == ActivityType.MEDICAL_ESCORT
    assert any("急症" in s or "就医" in s for s in updated.confirmed_steps)


# ==============================================================================
# 6. Negative Constraints & Prompt Directive Rendering
# ==============================================================================

def test_render_prompt_directive_leisure_walk():
    """Verify prompt directive contains explicit negative constraints against medical drift."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        target_spot="年嘉湖",
        health_constraints=["偏好清幽安静绿道", "避开台阶"],
        lock_turns_remaining=3,
    )
    directive = anchor.render_prompt_directive()

    # Must contain anchor context
    assert "LEISURE_WALK" in directive
    assert "烈士公园年嘉湖" in directive
    assert "年嘉湖" in directive
    assert "避开台阶" in directive

    # Must contain strong negative constraints forbidding hospital registration
    assert "严禁漂移到医院看病、挂号或门诊" in directive
    assert "绝对严禁主动推荐医院、挂专家号" in directive
    assert "bds_escort_route" in directive


def test_render_prompt_directive_idle_empty():
    """Idle anchor produces empty prompt directive."""
    anchor = TopicAnchor(activity_type=ActivityType.IDLE)
    assert anchor.render_prompt_directive() == ""


# ==============================================================================
# 7. Boundary and Edge Cases
# ==============================================================================

def test_update_topic_anchor_with_empty_or_whitespace():
    """Updating with empty string returns unchanged anchor."""
    anchor = TopicAnchor(activity_type=ActivityType.LEISURE_WALK, lock_turns_remaining=2)
    updated = update_topic_anchor(anchor, "   ")
    assert updated.activity_type == ActivityType.LEISURE_WALK
    assert updated.lock_turns_remaining == 2


def test_update_topic_anchor_from_none():
    """Updating when current anchor is None creates and updates a fresh anchor."""
    updated = update_topic_anchor(None, "想去散步")
    assert updated.activity_type == ActivityType.LEISURE_WALK
    assert updated.lock_turns_remaining >= 3
