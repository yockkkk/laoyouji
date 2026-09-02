"""SSE 事件封装（老人端对话流协议，见 docs/API.md）。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SSEEvent:
    event: str                 # session/plan/agent_status/delta/tool_call/tool_result/card/suspended/final/error
    data: dict[str, Any] = field(default_factory=dict)

    def encode(self) -> dict[str, str]:
        """供 sse-starlette EventSourceResponse 消费。"""
        return {"event": self.event, "data": json.dumps(self.data, ensure_ascii=False)}
