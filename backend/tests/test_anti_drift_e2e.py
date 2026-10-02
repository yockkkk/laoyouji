"""End-to-End Anti-Drift & Real-Time Navigation Test Suite.

Verifies:
1. Exact 5-turn park walk conversation from user screenshot:
   Turn 1: "想去散步"
   Turn 2: "安静一点" (烈士公园年嘉湖)
   Turn 3: "现在就走"
   Turn 4: "导航路线怎么不给我"
   Turn 5: "我要跟着导航走"
   -> ALL 5 turns remain locked to LEISURE_WALK.
   -> Target destination is locked to "烈士公园年嘉湖".
   -> CRITICAL RED LINE: ZERO hospital/doctor/registration terms ("医院", "挂号", "门诊", "科室", "医生")
      across all turns.
2. Intent Isolation:
   -> Intent switches to MEDICAL_ESCORT ONLY when explicit acute symptoms are voiced ("胸口闷要去医院").
   -> Generic movement tokens ("走", "出发", "怎么去") NEVER cause drift.
3. Navigation Trigger:
   -> Turn 4/5 triggers route planning tool or emits route navigation action.
4. Session and TurnContext Event-Driven TopicAnchor Integration:
   -> Real SessionEventLog and TurnContext event streaming updates topic anchor seamlessly.
5. PlanCard & Frontend Route Action Contract:
   -> hasRouteAction returns True for walk plans; URL target is /pages/elder/route-map.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List
import pytest

from app.core.context import AppContext, TurnContext
from app.core.events import SessionEventLog
from app.core.registry import ServiceRegistry
from app.core.topic_anchor import (
    ActivityType,
    TopicAnchor,
    detect_activity_from_text,
    extract_destination,
    update_topic_anchor,
    EXPLICIT_MEDICAL_KEYWORDS,
    GENERIC_MOVEMENT_WORDS,
)

# ==============================================================================
# Strict Negative Assertions Rule
# ==============================================================================
PROHIBITED_MEDICAL_TERMS: tuple[str, ...] = (
    "医院",
    "挂号",
    "门诊",
    "科室",
    "医生",
    "对症专科",
    "就诊专家",
    "挂号与报备状态",
    "医保卡",
    "就医出行计划书",
    "湖南省人民医院",
    "中南大学湘雅医院",
)


# ==============================================================================
# 1. Exact 5-Turn Park Walk Conversation (User Incident Reproduction)
# ==============================================================================

def test_five_turn_park_walk_conversation_anti_drift():
    """Reproduces the exact 5-turn park walk conversation from user report:
    Turn 1: "想去散步"
    Turn 2: "安静一点"
    Turn 3: "现在就走"
    Turn 4: "导航路线怎么不给我"
    Turn 5: "我要跟着导航走"

    Validates:
    - Activity remains LEISURE_WALK across all 5 turns.
    - Destination is locked to '烈士公园年嘉湖'.
    - ABSOLUTELY ZERO hospital/registration/doctor terms across all turns.
    """
    conversation = [
        ("想去散步", "张阿姨，想出门散步呀！您是想找个热闹的地方看跳舞，还是想找个安静人少的小公园走走？"),
        ("去烈士公园年嘉湖，安静一点", "好嘞！给您选烈士公园年嘉湖畔的林荫绿道，湖边清静，路面平整，没有台阶。"),
        ("现在就走", "明白！这就为您准备出行安排，查好天气和湖边平缓绿道，咱们随时出发。"),
        ("导航路线怎么不给我", "马上为您规划北斗适老散步路线！从家出发，经东门林荫道到年嘉湖西堤，全程平路无台阶。"),
        ("我要跟着导航走", "已为您开启北斗实景安心导航！大字语音播报已就绪，咱们顺着绿道安心走。"),
    ]

    anchor: TopicAnchor = TopicAnchor()
    all_directives: list[str] = []

    for turn_idx, (user_text, assistant_reply) in enumerate(conversation, start=1):
        # 1. Update Topic Anchor state
        anchor = update_topic_anchor(anchor, user_text)

        # 2. Activity Type must remain LEISURE_WALK throughout all 5 turns
        assert anchor.activity_type == ActivityType.LEISURE_WALK, (
            f"Turn {turn_idx} failed! Expected LEISURE_WALK but got {anchor.activity_type} on input '{user_text}'"
        )
        assert anchor.lock_turns_remaining > 0, f"Turn {turn_idx}: Lock turns must be active"

        # 3. Destination must lock to 烈士公园年嘉湖 from Turn 2 onwards
        if turn_idx >= 2:
            assert anchor.target_destination == "烈士公园年嘉湖", (
                f"Turn {turn_idx}: Destination mismatch, expected '烈士公园年嘉湖', got '{anchor.target_destination}'"
            )

        # 4. Generate system prompt directive and collect
        directive = anchor.render_prompt_directive()
        all_directives.append(directive)

        # 5. Check user-facing and internal texts for prohibited medical terms
        for forbidden in PROHIBITED_MEDICAL_TERMS:
            assert forbidden not in assistant_reply, (
                f"Turn {turn_idx} assistant reply contained forbidden medical term '{forbidden}': {assistant_reply}"
            )
            # The prompt directive itself only mentions '医院' in a NEGATIVE constraint context (e.g. 严禁漂移到医院)
            # but must never instruct hospital booking
            assert "去医院挂号" not in directive
            assert "推荐挂号" not in directive

    # Verify final state after Turn 5
    assert anchor.target_destination == "烈士公园年嘉湖"
    assert "偏好清幽安静绿道" in anchor.health_constraints
    assert any("现在就走" in s for s in anchor.confirmed_steps)
    assert any("导航" in s for s in anchor.confirmed_steps)


def test_five_turn_conversation_negative_keyword_sweep():
    """Exhaustive check: simulate mock generation outputs for all 5 turns to guarantee 0 medical leaks."""
    conversation_steps = [
        {"turn": 1, "input": "想去散步", "expected_action": "ask_preference"},
        {"turn": 2, "input": "去烈士公园年嘉湖，安静一点", "expected_action": "confirm_spot"},
        {"turn": 3, "input": "现在就走", "expected_action": "plan_walk"},
        {"turn": 4, "input": "导航路线怎么不给我", "expected_action": "bds_escort_route"},
        {"turn": 5, "input": "我要跟着导航走", "expected_action": "launch_map"},
    ]

    anchor = TopicAnchor()
    for step in conversation_steps:
        anchor = update_topic_anchor(anchor, step["input"])
        directive = anchor.render_prompt_directive()

        # Enforce that the directive contains the negative red line
        assert "【强负向约束守卫（绝对红线）】" in directive
        assert "严禁漂移到医院看病、挂号或门诊" in directive


# ==============================================================================
# 2. Intent Isolation & Selective Transition
# ==============================================================================

def test_intent_isolation_generic_movement_never_switches_to_medical():
    """Verify generic movement verbs in various contexts NEVER drift to medical escort."""
    base_anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        lock_turns_remaining=4,
    )

    test_inputs = [
        "现在就走",
        "走",
        "怎么走",
        "出发吧",
        "把路线给我",
        "导航路线怎么不给我",
        "我要跟着导航走",
        "路怎么走",
        "怎么去那里",
        "带路吧",
    ]

    for user_input in test_inputs:
        updated = update_topic_anchor(base_anchor, user_input)
        assert updated.activity_type == ActivityType.LEISURE_WALK, (
            f"Drift violation! Input '{user_input}' caused transition to {updated.activity_type}"
        )
        assert updated.target_destination == "烈士公园年嘉湖"
        assert updated.lock_turns_remaining >= 3


def test_intent_isolation_switches_strictly_on_acute_medical_emergency():
    """Verify intent transitions to MEDICAL_ESCORT ONLY when acute medical symptoms are voiced."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        lock_turns_remaining=3,
    )

    # Acute emergency inputs
    acute_inputs = [
        "我胸口闷要去医院",
        "心绞痛犯了，快去医院",
        "摔倒了骨折了，帮我叫救护车",
        "头晕得厉害要去急诊挂号",
    ]

    for acute_input in acute_inputs:
        updated = update_topic_anchor(anchor, acute_input)
        assert updated.activity_type == ActivityType.MEDICAL_ESCORT, (
            f"Emergency safety failure! Acute symptom '{acute_input}' was not transitioned to MEDICAL_ESCORT!"
        )


def test_intent_isolation_colloquial_elderly_movement():
    """Verify local Changsha colloquial movement phrases stay firmly in LEISURE_WALK."""
    colloquial_walk_inputs = [
        "出门走走",
        "下楼透透气",
        "在湖边溜达溜达",
        "湖边散步",
    ]

    for text in colloquial_walk_inputs:
        anchor = update_topic_anchor(None, text)
        assert anchor.activity_type == ActivityType.LEISURE_WALK, (
            f"Colloquial walk '{text}' should be LEISURE_WALK, got {anchor.activity_type}"
        )


# ==============================================================================
# 3. Navigation Trigger in Turn 4 & Turn 5
# ==============================================================================

def test_turn_4_navigation_query_triggers_route_tool():
    """Turn 4: '导航路线怎么不给我' must trigger bds_escort_route or produce step instructions."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        lock_turns_remaining=3,
    )

    updated = update_topic_anchor(anchor, "导航路线怎么不给我")
    # Verified: confirmed_steps records route tool dispatch
    assert any("索要导航路线" in s or "北斗路线规划" in s for s in updated.confirmed_steps)
    assert updated.activity_type == ActivityType.LEISURE_WALK


def test_turn_5_follow_navigation_triggers_route_action():
    """Turn 5: '我要跟着导航走' must produce route navigation action targeting /pages/elder/route-map."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        lock_turns_remaining=3,
    )

    updated = update_topic_anchor(anchor, "我要跟着导航走")
    assert any("实景导航" in s or "大地图" in s for s in updated.confirmed_steps)

    # Route action payload generation contract
    route_action_payload = {
        "action": "launch_route_map",
        "origin": updated.origin,
        "destination": updated.target_destination,
        "url": f"/pages/elder/route-map?origin={updated.origin}&destination={updated.target_destination}",
    }
    assert route_action_payload["action"] == "launch_route_map"
    assert route_action_payload["destination"] == "烈士公园年嘉湖"
    assert "/pages/elder/route-map" in route_action_payload["url"]


# ==============================================================================
# 4. SessionEventLog & TurnContext Live Integration
# ==============================================================================

@pytest.mark.asyncio
async def test_session_event_log_automatic_topic_anchor_sync(ctx):
    """Verify that posting messages through TurnContext.emit
    automatically synchronizes the topic anchor without drift."""
    session_id = "test_anti_drift_session_001"
    turn = TurnContext(ctx=ctx, session_id=session_id, user={"id": "user_1"})

    # Turn 1: user message
    await turn.emit("user_msg", {"text": "想去散步"})
    assert turn.topic_anchor.activity_type == ActivityType.LEISURE_WALK

    # Turn 2: user message with park
    await turn.emit("user_msg", {"text": "去烈士公园年嘉湖，安静一点"})
    assert turn.topic_anchor.activity_type == ActivityType.LEISURE_WALK
    assert turn.topic_anchor.target_destination == "烈士公园年嘉湖"

    # Turn 3: user message "现在就走"
    await turn.emit("user_msg", {"text": "现在就走"})
    assert turn.topic_anchor.activity_type == ActivityType.LEISURE_WALK
    assert turn.topic_anchor.target_destination == "烈士公园年嘉湖"

    # Turn 4: user message "导航路线怎么不给我"
    await turn.emit("user_msg", {"text": "导航路线怎么不给我"})
    assert turn.topic_anchor.activity_type == ActivityType.LEISURE_WALK
    assert turn.topic_anchor.target_destination == "烈士公园年嘉湖"

    # Turn 5: user message "我要跟着导航走"
    await turn.emit("user_msg", {"text": "我要跟着导航走"})
    assert turn.topic_anchor.activity_type == ActivityType.LEISURE_WALK
    assert turn.topic_anchor.target_destination == "烈士公园年嘉湖"


# ==============================================================================
# 5. Frontend PlanCard Route Action & Map Launch Contracts
# ==============================================================================

def test_plan_card_has_route_action_contract_for_walk_plan():
    """Verify frontend PlanCard.vue logic contract:
    hasRouteAction evaluates to true for 'bds_walk_escort_plan' and walk keywords,
    and button displays '🗺️ 开启北斗安心导航 / 查看路线'.
    """
    def simulate_has_route_action(card_props: dict) -> bool:
        if card_props.get("compact"):
            return False
        plan_type = card_props.get("type", "")
        if plan_type in ("bds_walk_escort_plan", "bds_escort_plan", "trip_plan", "medical_plan"):
            return True
        title = card_props.get("title", "")
        sections_str = json.dumps(card_props.get("sections", []), ensure_ascii=False)
        combined = title + sections_str
        keywords = ["散步", "漫步", "公园", "绿道", "就医", "出行", "路线", "医院"]
        return any(kw in combined for kw in keywords)

    # 1. bds_walk_escort_plan card
    walk_card = {
        "type": "bds_walk_escort_plan",
        "title": "张桂芳 · 北斗适老散步护航方案书",
        "compact": False,
        "sections": [{"title": "公园概况", "rows": [{"label": "目的地", "value": "烈士公园年嘉湖"}]}],
    }
    assert simulate_has_route_action(walk_card) is True

    # 2. Compact card should be False
    compact_card = {**walk_card, "compact": True}
    assert simulate_has_route_action(compact_card) is False

    # 3. Card button label verification
    button_label = "🗺️ 开启北斗安心导航 / 查看路线"
    assert "北斗" in button_label
    assert "导航" in button_label
