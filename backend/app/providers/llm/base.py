"""LLM Provider 协议 —— 大模型接缝（DeepSeek | Mock 可互换）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass
class ToolCallReq:
    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCallReq] = field(default_factory=list)
    # provider 报回的 token 用量（DeepSeek 有，Mock 没有）。
    # Budget 优先用它，拿不到才退回字符数粗估 —— 见 core/session._tokens_of。
    usage: dict = field(default_factory=dict)


# 流式增量回调：on_delta(text_fragment) 由 AgentLoop 提供（转发为 SSE delta）
DeltaCallback = Callable[[str], Awaitable[None]]


class LLMProvider:
    """协议基类：子类实现 chat()。"""

    name: str = "llm"

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   on_delta: DeltaCallback | None = None) -> LLMResponse:
        raise NotImplementedError
