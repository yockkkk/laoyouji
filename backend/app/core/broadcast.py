"""会话级 SSE 广播器：把事件推给该会话当前所有活跃连接。

用途：子女批准高危操作后，老人端（若仍在线）立即收到播报；
若老人端已断线，事件也已持久化进 session_events，轮询恢复可拉取。
"""
from __future__ import annotations

import asyncio
from typing import Any

from app.core.sse import SSEEvent


class SessionBroadcast:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}

    def register(self, session_id: str, queue: asyncio.Queue) -> None:
        self._queues.setdefault(session_id, []).append(queue)

    def unregister(self, session_id: str, queue: asyncio.Queue) -> None:
        queues = self._queues.get(session_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._queues.pop(session_id, None)

    async def push(self, session_id: str, event: SSEEvent) -> None:
        for queue in list(self._queues.get(session_id, [])):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover
                pass

    def push_sync(self, session_id: str, event: SSEEvent) -> None:
        for queue in list(self._queues.get(session_id, [])):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover
                pass

    def live_sessions(self) -> list[str]:
        return list(self._queues)
