"""Empirical Challenge Test Suite by Challenger 1 (Milestone 1).

Adversarially tests TopicAnchor and Context Anti-Drift Engine against:
1. Dialect variants ('出去溜个弯', '下楼透透气', '遛个弯', '溜弯').
2. Cascading drift / failure in 5-turn park walk sequence initiated by dialect variant.
3. Destination preservation and specificity degradation ('烈士公园年嘉湖' vs '年嘉湖').
4. Destination switching with negation ('不去烈士公园，去橘子洲').
5. Rapid turn sequences and lock decrement pinning.
6. Topic anchor breakout / cancellation to daily companion.
"""
from __future__ import annotations

import pytest
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


def test_dialect_variant_downstairs_air_recognized():
    """Verify '下楼透透气' is recognized as LEISURE_WALK."""
    detected = detect_activity_from_text("下楼透透气")
    assert detected == ActivityType.LEISURE_WALK
    anchor = update_topic_anchor(None, "下楼透透气")
    assert anchor.activity_type == ActivityType.LEISURE_WALK
    assert anchor.lock_turns_remaining >= 3


def test_dialect_variant_liu_wan_fails_empirical_proof():
    """EMPIRICAL VERIFICATION OF REMEDIATION:
    '出去溜个弯', '遛个弯', '溜弯' are common dialect/colloquial Chinese phrases
    for leisure walk, and are now successfully detected.
    """
    colloquial_variants = [
        "出去溜个弯",
        "溜弯去",
        "下楼遛弯",
        "遛个弯",
        "出去溜溜",
        "下楼遛遛",
    ]
    failures = []
    for text in colloquial_variants:
        detected = detect_activity_from_text(text)
        anchor = update_topic_anchor(None, text)
        if detected != ActivityType.LEISURE_WALK or anchor.activity_type != ActivityType.LEISURE_WALK:
            failures.append((text, detected, anchor.activity_type))

    # All colloquial variants must now successfully pass
    assert len(failures) == 0, (
        f"Expected all dialect variants to pass, but some failed: {failures}"
    )


def test_cascading_idle_drift_from_unrecognized_dialect_opening():
    """EMPIRICAL VERIFICATION OF CASCADE RESOLUTION:
    When an elder opens with '出去溜个弯', the entire 5-turn walk conversation
    correctly maintains LEISURE_WALK.
    """
    turns = [
        "出去溜个弯",
        "安静一点",
        "现在就走",
        "导航路线怎么不给我",
        "我要跟着导航走",
    ]
    anchor = None
    for turn in turns:
        anchor = update_topic_anchor(anchor, turn)

    assert anchor.activity_type == ActivityType.LEISURE_WALK
    assert anchor.lock_turns_remaining >= 1
    assert "LEISURE_WALK" in anchor.render_prompt_directive()


def test_destination_specificity_degradation():
    """EMPIRICAL VERIFICATION OF SPECIFICITY PRESERVATION:
    When destination is locked to '烈士公园年嘉湖', mentioning the sub-spot '到年嘉湖走走'
    preserves the full park destination instead of degrading to '年嘉湖'.
    """
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        target_spot="年嘉湖",
        lock_turns_remaining=3,
    )
    updated = update_topic_anchor(anchor, "到年嘉湖走走")
    # Verified: target_destination preserves '烈士公园年嘉湖'
    assert updated.target_destination == "烈士公园年嘉湖"


def test_destination_change_negation_order_bias():
    """EMPIRICAL VERIFICATION OF NEGATION HANDLING:
    '不去烈士公园，去橘子洲' extracts '橘子洲' because '不去烈士公园' is filtered by negation.
    """
    extracted = extract_destination("不去烈士公园，去橘子洲")
    assert extracted == "橘子洲"


def test_lock_turns_decrement_pinning():
    """Verify rapid turn sequences without movement words decrement naturally to 0 without artificial pinning."""
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        lock_turns_remaining=5,
    )
    for _ in range(10):
        anchor = update_topic_anchor(anchor, "好的收到")
    assert anchor.activity_type == ActivityType.LEISURE_WALK
    assert anchor.lock_turns_remaining == 0


def test_lock_blocks_companion_switch():
    """EMPIRICAL PROOF OF LOCK TRAPPING:
    While locked in LEISURE_WALK, user cannot switch to companion chit-chat.
    """
    anchor = TopicAnchor(
        activity_type=ActivityType.LEISURE_WALK,
        target_destination="烈士公园年嘉湖",
        lock_turns_remaining=3,
    )
    updated = update_topic_anchor(anchor, "我不去散步了，陪我聊聊天讲个笑话吧")
    # Still trapped in LEISURE_WALK because only EXPLICIT_MEDICAL_KEYWORDS can break lock
    assert updated.activity_type == ActivityType.LEISURE_WALK
