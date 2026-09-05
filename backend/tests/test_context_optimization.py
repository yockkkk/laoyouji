"""测试上下文优化：用户档案锚定、安全轮次截断、无孤儿工具消息。"""
from __future__ import annotations

import pytest

from app.core.events import (
    SessionEventLog,
    USER_MESSAGE,
    ASSISTANT_MESSAGE,
    TOOL_RESULT,
    _drop_orphan_tool_messages,
    _slice_turn_safe,
)


def test_slice_turn_safe_avoids_orphan_tool_message():
    """测试当 limit 发生截断时，绝不以孤立的 role:tool 消息开头。"""
    messages = [
        {"role": "user", "content": "我想去医院"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "search_hospital", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "已查到南京鼓楼医院"},
        {"role": "assistant", "content": "给您查到南京鼓楼医院啦"},
        {"role": "user", "content": "帮我挂号"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_2", "type": "function", "function": {"name": "register_appointment", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_2", "content": "挂号成功"},
        {"role": "assistant", "content": "挂好号了"},
    ]

    sliced = _slice_turn_safe(messages, limit=3)
    assert len(sliced) > 0
    assert sliced[0]["role"] != "tool"
    call_ids = set()
    for m in sliced:
        if m["role"] == "assistant":
            for c in m.get("tool_calls") or []:
                call_ids.add(c["id"])
        elif m["role"] == "tool":
            assert m["tool_call_id"] in call_ids, f"发现未配对的孤儿 tool 消息: {m}"


def test_slice_turn_safe_starts_at_turn_boundary():
    """当有多轮对话截断时，优先对齐到完整的 user 轮次边界。"""
    messages = [
        {"role": "user", "content": "第1轮"},
        {"role": "assistant", "content": "第1轮回答"},
        {"role": "user", "content": "第2轮"},
        {"role": "assistant", "content": "第2轮回答"},
        {"role": "user", "content": "第3轮"},
        {"role": "assistant", "content": "第3轮回答"},
    ]
    sliced = _slice_turn_safe(messages, limit=3)
    assert len(sliced) == 2
    assert sliced[0]["role"] == "user"
    assert sliced[0]["content"] == "第3轮"


def test_main_agent_prompt_rules():
    """检查总智能体提示词已包含行动优先与本地就医解耦规则。"""
    from app.agents.main_agent import SYSTEM_PROMPT
    assert "拒绝口头空话，行动优先" in SYSTEM_PROMPT
    assert "本地同城就医" in SYSTEM_PROMPT
    assert "禁止重复追问" in SYSTEM_PROMPT
