"""Unit & Integration Tests for SSE Real-time Thinking & Handoff Stream.

覆盖需求: R2 (实时心智思考流与拟人化交接显像)
对应特性: F5 (SSE Thinking Stream), F6 (Thinking Bubble & Handoff Card), F7 (5-Agent Execution Tree & Swarm Board)
"""
from __future__ import annotations

import json
import pytest
from tests.swarm_fixtures import (
    AGENT_AVATAR_TITLES,
    AGENT_THEME_COLORS,
    AgentHandoffChunk,
    PeerMessageChunk,
    TaskBoardSyncChunk,
    ThinkingDeltaChunk,
    create_agent_handoff_card,
    create_elder_thinking_bubble,
    format_sse_event,
)


class TestSSEThinkingStream:
    """F5: SSE 心智流序列化与事件规范测试。"""

    def test_sse_thinking_delta_format(self):
        chunk = ThinkingDeltaChunk(agent="health", delta="调取体检中...", color="#67C23A")
        sse = format_sse_event(chunk.event, chunk.model_dump())
        assert sse.startswith("event: thinking_delta\ndata: ")
        assert "调取体检中" in sse

    def test_sse_agent_handoff_format(self):
        chunk = AgentHandoffChunk(from_agent="health", to_agent="bds_nav", reason="体能红线确认")
        sse = format_sse_event(chunk.event, chunk.model_dump())
        assert sse.startswith("event: agent_handoff\ndata: ")
        assert "体能红线确认" in sse


class TestElderThinkingBubbleAndHandoffCard:
    """F6: 前端长辈关怀心智气泡与交接卡片契约。"""

    def test_thinking_bubble_elder_phrasing(self):
        bubble = create_elder_thinking_bubble("bds_nav", "calculating micro-terrain costs")
        assert "北斗高精定位正在为您勘测" in bubble["elder_text"]
        assert bubble["color"] == "#409EFF"

    def test_agent_handoff_card_styling(self):
        card = create_agent_handoff_card("main", "weather", "检查室外天气")
        assert card["transition_title"] == "@main ▶ @weather"
        assert card["from_color"] == "#E65100"
        assert card["to_color"] == "#E6A23C"


class TestSwarmExecutionTree:
    """F7: 5-Agent 协同执行树与群智态势看板。"""

    def test_all_five_agents_present(self):
        expected = {"main", "health", "bds_nav", "weather", "guardian"}
        assert set(AGENT_THEME_COLORS.keys()) == expected
        assert set(AGENT_AVATAR_TITLES.keys()) == expected
