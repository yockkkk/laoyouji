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
from app.core.turn_gate import SessionTurnGate


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
        await self.queue.put(SSEEvent(event, payload))

    async def status(self, agent: str, text: str) -> None:
        """agent_status 只走 SSE 不落库（过程性信息）。"""
        await self.queue.put(SSEEvent("agent_status", {"agent": agent, "text": text}))
