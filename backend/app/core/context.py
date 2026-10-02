"""AppContext（应用级装配）与 TurnContext（单轮对话上下文）。

AppContext 在 ``bootstrap.build_context`` 里按 .env 装配：注册全部 provider、
挂钩子、组装 guards、实例化智能体 —— 这就是"一切皆插件"的唯一组合根。

TurnContext 是**环境**（ambient）：会话 id、用户、SSE 队列，外加当前作用域
（``agent_id`` / ``turn_id`` / ``step_id``）。``scoped()`` 派生出子智能体的视角：
**队列共享**（前端仍看到全部动静），**作用域不同**（模型历史各自隔离）。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from app.core.broadcast import SessionBroadcast
from app.core.bus import EventBus
from app.core.events import MAIN_SCOPE, SessionEventLog, durable_type
from app.core.guard import Guard
from app.core.registry import ServiceRegistry
from app.core.sse import SSEEvent
from app.core.tool import ConfirmationPort, PostToolFilter, ToolDispatcher, ToolRegistry
from app.core.topic_anchor import TopicAnchor, update_topic_anchor
from app.core.turn_gate import SessionTurnGate


def _log_get_topic_anchor(self: SessionEventLog, session_id: str) -> TopicAnchor:
    if not hasattr(self, "_topic_anchors"):
        self._topic_anchors: dict[str, TopicAnchor] = {}
    if session_id not in self._topic_anchors:
        anchor = TopicAnchor()
        events = getattr(self, "_events", {}).get(session_id, [])
        for ev in events:
            if getattr(ev, "type", "") == "user/message":
                payload = getattr(ev, "payload", {})
                if isinstance(payload, dict):
                    text = payload.get("text", "")
                    if text:
                        anchor = update_topic_anchor(anchor, text)
        self._topic_anchors[session_id] = anchor
    return self._topic_anchors[session_id]


def _log_set_topic_anchor(self: SessionEventLog, session_id: str, anchor: TopicAnchor) -> None:
    if not hasattr(self, "_topic_anchors"):
        self._topic_anchors = {}
    self._topic_anchors[session_id] = anchor


def _log_update_topic_anchor(self: SessionEventLog, session_id: str, user_text: str) -> TopicAnchor:
    current = self.get_topic_anchor(session_id)
    updated = update_topic_anchor(current, user_text)
    self.set_topic_anchor(session_id, updated)
    return updated


if not hasattr(SessionEventLog, "get_topic_anchor"):
    SessionEventLog.get_topic_anchor = _log_get_topic_anchor  # type: ignore[attr-defined]
if not hasattr(SessionEventLog, "set_topic_anchor"):
    SessionEventLog.set_topic_anchor = _log_set_topic_anchor  # type: ignore[attr-defined]
if not hasattr(SessionEventLog, "update_topic_anchor"):
    SessionEventLog.update_topic_anchor = _log_update_topic_anchor  # type: ignore[attr-defined]


@dataclass
class AppContext:
    settings: Any
    registry: ServiceRegistry
    repos: Any                       # Repository 协议实现
    event_log: SessionEventLog
    tools: ToolRegistry
    bus: EventBus = field(default_factory=EventBus)
    broadcast: SessionBroadcast = field(default_factory=SessionBroadcast)
    # 同一会话的轮次闸门：老人连点两次发送时后一句排队，而不是两轮交错跑
    turn_gate: SessionTurnGate = field(default_factory=SessionTurnGate)
    guards: list[Guard] = field(default_factory=list)
    post_filters: list[PostToolFilter] = field(default_factory=list)
    confirmation: ConfirmationPort | None = None
    privacy: Any = None                                   # PrivacyService
    agents: dict[str, Any] = field(default_factory=dict)  # name -> BaseAgent
    subagents: Any = None                                 # SubagentRegistry
    topic_anchors: dict[str, TopicAnchor] = field(default_factory=dict)
    # bootstrap 里构建一次的单例。以前这是个 @property，每次访问都新建对象，
    # 于是中间件、指标、重复调用记账全都附着不上 —— 状态一访问就没了。
    dispatcher: ToolDispatcher | None = None
    # bootstrap 挂上的总线监听者的卸载句柄。"注册是可逆副作用"这条不只是说法：
    # 测试可以整体摘掉插件跑裸内核，答辩现场也能演示拆一个装一个。
    disposers: list[Callable[[], None]] = field(default_factory=list)

    def resolve(self, name: str) -> Any:
        return self.registry.resolve(name)

    def dispose(self) -> None:
        """卸载 bootstrap 装上的全部监听者（幂等）。"""
        while self.disposers:
            self.disposers.pop()()


@dataclass
class TurnContext:
    """一次对话轮次的环境：会话、用户、SSE 队列、当前作用域。

    emit() 是智能体产出事件的唯一通道：persist=True 时先落 SessionEventLog
    （唯一事实源，带作用域标签），再进 SSE 队列推给前端。
    两个命名空间由 ``durable_type()`` 单点翻译。
    """

    ctx: AppContext
    session_id: str
    user: dict
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    agent_id: str = MAIN_SCOPE
    turn_id: str | None = None
    step_id: str | None = None

    @property
    def topic_anchor(self) -> TopicAnchor:
        """获取当前会话的主题锚点状态。"""
        if hasattr(self.ctx, "event_log") and hasattr(self.ctx.event_log, "get_topic_anchor"):
            return self.ctx.event_log.get_topic_anchor(self.session_id)
        if self.session_id not in self.ctx.topic_anchors:
            self.ctx.topic_anchors[self.session_id] = TopicAnchor()
        return self.ctx.topic_anchors[self.session_id]

    @topic_anchor.setter
    def topic_anchor(self, anchor: TopicAnchor) -> None:
        if hasattr(self.ctx, "event_log") and hasattr(self.ctx.event_log, "set_topic_anchor"):
            self.ctx.event_log.set_topic_anchor(self.session_id, anchor)
        self.ctx.topic_anchors[self.session_id] = anchor

    def scoped(self, agent_id: str) -> TurnContext:
        """派生子智能体视角：共享队列（前端可见全部），作用域独立（历史隔离）。"""
        return replace(self, agent_id=agent_id, queue=self.queue,
                       turn_id=None, step_id=None)

    async def emit(self, event: str, payload: dict, *, persist: bool = True) -> None:
        if persist:
            # 同步追加：热路径不等 I/O，落库排到轮次结束的 session/flush
            self.ctx.event_log.append(
                self.session_id, self.user.get("id"), durable_type(event), payload,
                agent_id=self.agent_id, turn_id=self.turn_id, step_id=self.step_id,
            )
            # 用户发言自动触发主题锚点防漂移状态机更新
            if event in ("user_msg", "user/message") and isinstance(payload, dict):
                text = payload.get("text", "")
                if text:
                    if hasattr(self.ctx.event_log, "update_topic_anchor"):
                        self.ctx.event_log.update_topic_anchor(self.session_id, text)
                    elif hasattr(self.ctx, "topic_anchors"):
                        curr = self.ctx.topic_anchors.get(self.session_id, TopicAnchor())
                        self.ctx.topic_anchors[self.session_id] = update_topic_anchor(curr, text)
        await self.queue.put(SSEEvent(event, payload))

    async def status(self, agent: str, text: str) -> None:
        """agent_status 只走 SSE 不落库（过程性信息）。"""
        await self.queue.put(SSEEvent("agent_status", {"agent": agent, "text": text}))
