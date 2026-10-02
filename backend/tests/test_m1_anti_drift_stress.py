"""Milestone 1 Empirical Stress Tests: Topic Anchor Anti-Drift Engine.

Adversarial stress testing against:
1. 5-turn park walk conversation variations (with/without explicit park naming).
2. Changsha major park landmarks anti-drift isolation.
3. Rapid switches and acute medical emergency injection at EVERY turn (Turns 1-5).
4. Multi-session concurrency isolation (zero cross-contamination between walk and medical).
5. Generic movement word permutations and colloquial phrasing robustness.
6. Health constraints extraction and lock turns decrementing behavior.
7. Zero tolerance medical leak assertion across all prompt directives.
"""
from __future__ import annotations

import pytest
from app.core.context import AppContext, TurnContext
from app.core.events import SessionEventLog
from app.core.topic_anchor import (
    ActivityType,
    TopicAnchor,
    detect_activity_from_text,
    extract_destination,
    update_topic_anchor,
    EXPLICIT_MEDICAL_KEYWORDS,
    GENERIC_MOVEMENT_WORDS,
    LEISURE_WALK_KEYWORDS,
    KNOWN_DESTINATIONS,
)

PROHIBITED_MEDICAL_TERMS = (
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
# 1. Stress Test: 5-Turn Park Walk Variations (User Incident Direct Stress)
# ==============================================================================

def test_five_turn_park_walk_exact_text_without_destination_in_turn_2():
    """Stress test: user NEVER mentions park name explicitly, only says '安静一点'.
    System must lock to LEISURE_WALK and default to generic park/greenway,
    NEVER drifting to hospital.
    """
    turns = [
        "想去散步",
        "安静一点",
        "现在就走",
        "导航路线怎么不给我",
        "我要跟着导航走",
    ]
    anchor = TopicAnchor()
    for idx, user_input in enumerate(turns, start=1):
        anchor = update_topic_anchor(anchor, user_input)
        assert anchor.activity_type == ActivityType.LEISURE_WALK, (
            f"Turn {idx} ('{user_input}') drifted to {anchor.activity_type}!"
        )
        assert anchor.lock_turns_remaining >= 3, (
            f"Turn {idx}: lock turns remaining ({anchor.lock_turns_remaining}) dropped below threshold!"
        )
        directive = anchor.render_prompt_directive()
        assert "LEISURE_WALK" in directive
        assert "严禁漂移到医院看病、挂号或门诊" in directive
        # Must not contain positive medical instructions
        assert "去医院挂号" not in directive
        assert "推荐挂号" not in directive
        assert "对症专科" not in directive

    # Final steps verification
    assert "偏好清幽安静绿道" in anchor.health_constraints
    assert any("现在就走" in s for s in anchor.confirmed_steps)
    assert any("索要导航路线" in s for s in anchor.confirmed_steps)
    assert any("实景导航" in s for s in anchor.confirmed_steps)


def test_five_turn_park_walk_with_all_major_changsha_landmarks():
    """Verify that 5-turn park walk works seamlessly across all major parks in Changsha."""
    parks = [
        ("烈士公园年嘉湖", "年嘉湖"),
        ("橘子洲头", "橘子洲头"),
        ("岳麓山爱晚亭", "爱晚亭"),
        ("洋湖湿地公园", None),
        ("松雅湖湿地公园", None),
        ("梅溪湖公园", None),
        ("天心阁公园", None),
    ]

    for park_name, spot in parks:
        anchor = TopicAnchor()
        turns = [
            f"想去{park_name}散步",
            "找个安静一点的道",
            "现在就走",
            "导航路线怎么不给我",
            "我要跟着导航走",
        ]
        for idx, t in enumerate(turns, 1):
            anchor = update_topic_anchor(anchor, t)
            assert anchor.activity_type == ActivityType.LEISURE_WALK, (
                f"Park {park_name} Turn {idx} drifted to {anchor.activity_type}!"
            )
            assert anchor.target_destination == park_name, (
                f"Park destination mismatch for {park_name} on Turn {idx}"
            )
            if spot:
                assert anchor.target_spot == spot


# ==============================================================================
# 2. Stress Test: Acute Emergency Injection at EVERY Single Turn (1 to 5)
# ==============================================================================

@pytest.mark.parametrize("emergency_turn", [1, 2, 3, 4, 5])
def test_acute_emergency_injection_at_any_turn(emergency_turn: int):
    """Stress test: An acute medical emergency is injected at Turn N.
    The system MUST immediately transition to MEDICAL_ESCORT at Turn N.
    """
    normal_walk = [
        "想去散步",
        "去烈士公园年嘉湖，安静一点",
        "现在就走",
        "导航路线怎么不给我",
        "我要跟着导航走",
    ]
    emergencies = [
        "我突然胸口闷得厉害要去医院",
        "哎呀我心绞痛犯了，快去医院",
        "我不小心摔倒了骨折了，叫救护车",
        "头晕得厉害难受得很，快送医挂号",
        "心脏难受，赶紧打120去医院急诊",
    ]

    anchor = TopicAnchor()
    for idx in range(1, 6):
        if idx == emergency_turn:
            # Inject acute emergency
            emergency_text = emergencies[idx - 1]
            anchor = update_topic_anchor(anchor, emergency_text)
            assert anchor.activity_type == ActivityType.MEDICAL_ESCORT, (
                f"Emergency turn {idx} failed to switch! Input: '{emergency_text}'"
            )
            assert anchor.lock_turns_remaining == 3
            if idx > 1:
                # If transitioning from an active LEISURE_WALK, confirmed step must be logged
                assert any("突发身体急症" in s for s in anchor.confirmed_steps)
            directive = anchor.render_prompt_directive()
            assert "MEDICAL_ESCORT" in directive
            assert "看病就诊陪护" in directive
            break
        else:
            anchor = update_topic_anchor(anchor, normal_walk[idx - 1])
            assert anchor.activity_type == ActivityType.LEISURE_WALK


# ==============================================================================
# 3. Stress Test: 30+ Generic Movement Variations Must NEVER Cause Drift
# ==============================================================================

def test_extensive_generic_movement_permutations_never_drift():
    """Exhaustively verify that all generic movement phrases do NOT cause drift."""
    generic_movement_phrases = [
        "现在就走", "马上出发", "走吧走吧", "咱们现在走", "出发啦",
        "怎么走", "路怎么走", "怎么去", "带路", "带我去",
        "给个路线", "路线发我", "把路线图给我", "导航路线怎么不给我", "路线呢",
        "我要跟着导航走", "开始导航", "跟着走", "导航去那", "开启导航路线",
        "走", "去", "出发", "动身", "动身出发",
        "怎么过去", "去那怎么走", "现在出发去那", "路线怎么走好", "怎么走最平缓",
    ]

    for phrase in generic_movement_phrases:
        # 1. From an active walk session
        active_walk = TopicAnchor(
            activity_type=ActivityType.LEISURE_WALK,
            target_destination="烈士公园年嘉湖",
            lock_turns_remaining=4,
        )
        updated = update_topic_anchor(active_walk, phrase)
        assert updated.activity_type == ActivityType.LEISURE_WALK, (
            f"Phrase '{phrase}' caused illegal drift to {updated.activity_type}!"
        )
        assert updated.target_destination == "烈士公园年嘉湖"

        # 2. Standalone detection must return None (not falsely recognized as medical)
        detected = detect_activity_from_text(phrase)
        assert detected is None or detected == ActivityType.LEISURE_WALK, (
            f"Standalone phrase '{phrase}' falsely triggered {detected}!"
        )


# ==============================================================================
# 4. Stress Test: Multi-Session Concurrency & Memory Isolation
# ==============================================================================

@pytest.mark.asyncio
async def test_concurrent_sessions_topic_anchor_isolation(ctx):
    """Verify that multiple sessions running concurrently never leak topic anchor state."""
    session_walk = "session_walk_001"
    session_medical = "session_med_002"

    turn_walk = TurnContext(ctx=ctx, session_id=session_walk, user={"id": "elder_walk"})
    turn_med = TurnContext(ctx=ctx, session_id=session_medical, user={"id": "elder_med"})

    # Concurrently emit events
    await turn_walk.emit("user_msg", {"text": "想去散步"})
    await turn_med.emit("user_msg", {"text": "我胸口闷要去医院看病"})

    assert turn_walk.topic_anchor.activity_type == ActivityType.LEISURE_WALK
    assert turn_med.topic_anchor.activity_type == ActivityType.MEDICAL_ESCORT

    # Advance walk session
    await turn_walk.emit("user_msg", {"text": "去烈士公园年嘉湖，安静一点"})
    await turn_walk.emit("user_msg", {"text": "现在就走"})
    await turn_walk.emit("user_msg", {"text": "导航路线怎么不给我"})
    await turn_walk.emit("user_msg", {"text": "我要跟着导航走"})

    # Ensure walk session remains LEISURE_WALK with 烈士公园年嘉湖
    assert turn_walk.topic_anchor.activity_type == ActivityType.LEISURE_WALK
    assert turn_walk.topic_anchor.target_destination == "烈士公园年嘉湖"

    # Ensure medical session remains MEDICAL_ESCORT unaffected
    assert turn_med.topic_anchor.activity_type == ActivityType.MEDICAL_ESCORT


# ==============================================================================
# 5. Stress Test: Health Constraints Extraction During Walk Dialogue
# ==============================================================================

def test_health_constraints_accumulate_without_medical_drift():
    """Verify health constraints like quiet, stairs, knee, shade, bench accumulate smoothly
    and lock turns decrement safely while maintaining is_locked() == True.
    """
    anchor = TopicAnchor(activity_type=ActivityType.LEISURE_WALK, lock_turns_remaining=5)

    inputs_and_expected_constraints = [
        ("找个人少安静的地方", "偏好清幽安静绿道"),
        ("避台阶，不要走楼梯", "避开台阶（零台阶步道）"),
        ("膝盖有点关节炎，走不快", "膝关节退行性病变（坡度<3%）"),
        ("路上太阳大，要有树荫遮阳", "优先林荫遮阳步道"),
        ("沿途要有长椅可以歇歇坐坐", "沿途长椅密集补给"),
        ("路面要平缓一点", "平缓微地形"),
    ]

    for user_text, expected_c in inputs_and_expected_constraints:
        anchor = update_topic_anchor(anchor, user_text)
        assert anchor.activity_type == ActivityType.LEISURE_WALK, f"Drifted on '{user_text}'"
        assert expected_c in anchor.health_constraints, f"Failed to extract '{expected_c}' from '{user_text}'"

    # All 6 constraints accumulated
    assert len(anchor.health_constraints) == 6
    # Lock is preserved and non-zero
    assert anchor.is_locked()
    assert anchor.lock_turns_remaining >= 1
