"""Teammate Mailbox Hub —— 多智能体对等通信信箱与协作研讨中枢。

灵感源自 Claude Code (teammateMailbox.ts) 与 Nanobot (loop.py _pending_queues)：
1. 点对点与广播电文解耦：PeerMessage 支持 direct, broadcast, proposal, handoff, ack, task_assignment, emergency。
2. 双通道投递：
   - 管道 A（主动调用）：智能体通过 P2P 工具 (send_teammate_message, read_teammate_inbox) 主动磋商；
   - 管道 B（被动注水）：PRE_STEP 瀑布钩子自动将未读信件注入大模型推理上下文。
3. 严格安全与并发：
   - 单调递增序列、Hop 深度限制防死循环（hop_count <= 3）；
   - 基于 asyncio.Queue 与 asyncio.Lock 的无锁争用内存 Hub；
   - 同步通过 SSE emit 向前端推送 peer_message 事件，支持多 Agent 心智显像。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field

from app.core.bus import EventBus, Next, PRE_STEP

logger = logging.getLogger(__name__)

# 最大自动协同中继跳数，防止 A->B->A->B 无限死循环
MAX_DELIBERATION_HOPS = 3

KNOWN_AGENTS = ("main", "health", "bds_nav", "weather", "guardian", "travel", "community")


class PeerMessageType(str, Enum):
    DIRECT = "direct"
    BROADCAST = "broadcast"
    PROPOSAL = "proposal"
    HANDOFF = "handoff"
    ACK = "ack"
    TASK_ASSIGNMENT = "task_assignment"
    EMERGENCY = "emergency"


class PeerMessage(BaseModel):
    """跨智能体对等电文信封（符合 PROJECT.md 接口契约 1）。"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    from_agent: str                                # 发送方："health", "bds_nav", "weather", "guardian", "main"
    to_agent: str                                  # 接收方：具体智能体名，或 "*" 表示广播
    msg_type: str = PeerMessageType.DIRECT.value   # 消息类型
    summary: str                                   # 5-10 字人话摘要（前端实时显像）
    content: str                                   # 详细内容 / 约束条件 / 研讨提议
    data: dict[str, Any] = Field(default_factory=dict) # 结构化参数载荷
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    read: bool = False                             # 是否已读
    reply_to: str | None = None                    # 关联的前序消息 ID
    correlation_id: str | None = None              # 协同研讨会话跟踪 ID
    hop_count: int = 0                             # 当前传递跳数

    def to_sse_payload(self) -> dict[str, Any]:
        """供前端 SSE 推送与 ExecutionTree 渲染的载荷。"""
        return {
            "id": self.id,
            "from": self.from_agent,
            "to": self.to_agent,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "msg_type": self.msg_type,
            "summary": self.summary,
            "preview": (self.content[:120] + "...") if len(self.content) > 120 else self.content,
            "content": self.content,
            "data": self.data,
            "created_at": self.created_at,
            "read": self.read,
            "reply_to": self.reply_to,
            "correlation_id": self.correlation_id,
            "hop_count": self.hop_count,
        }

    def to_prompt_context(self) -> str:
        """格式化为注入给大模型的上下文文本片段。"""
        lines = [
            f"- 来自 @{self.from_agent}（类型: {self.msg_type}，摘要: {self.summary}）:",
            f"  电文正文: {self.content}",
        ]
        if self.data:
            lines.append(f"  结构化约束参数: {json.dumps(self.data, ensure_ascii=False)}")
        return "\n".join(lines)


class AgentMailbox:
    """单个智能体在特定会话中的收件箱与历史账本。"""

    def __init__(self, agent_name: str, session_id: str):
        self.agent_name = agent_name
        self.session_id = session_id
        self._inbox: asyncio.Queue[PeerMessage] = asyncio.Queue()
        self._history: list[PeerMessage] = []
        self._lock = asyncio.Lock()

    async def post(self, msg: PeerMessage) -> None:
        """投递电文至收件箱。"""
        async with self._lock:
            self._history.append(msg)
            await self._inbox.put(msg)

    def drain(self) -> list[PeerMessage]:
        """排空当前所有未读电文并标记为已读（非阻塞）。"""
        drained: list[PeerMessage] = []
        while not self._inbox.empty():
            try:
                msg = self._inbox.get_nowait()
                msg.read = True
                drained.append(msg)
            except asyncio.QueueEmpty:
                break
        return drained

    def peek(self) -> list[PeerMessage]:
        """查看收件箱中的电文但不取出。"""
        return list(self._inbox._queue)

    def unread_count(self) -> int:
        """未读电文数量。"""
        return self._inbox.qsize()

    def get_history(self, limit: int = 50) -> list[PeerMessage]:
        """获取最近的历史电文。"""
        return self._history[-limit:] if limit else list(self._history)

    def clear(self) -> None:
        """清空收件箱与历史记录。"""
        while not self._inbox.empty():
            try:
                self._inbox.get_nowait()
            except asyncio.QueueEmpty:
                break
        self._history.clear()


class SessionMailboxHub:
    """会话级多智能体信箱中枢：负责电文路由、广播克隆与实时推送。"""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.mailboxes: dict[str, AgentMailbox] = {}
        self.message_log: list[PeerMessage] = []
        self._lock = asyncio.Lock()

    def get_mailbox(self, agent_name: str) -> AgentMailbox:
        """获取或创建指定智能体的信箱（自动剥除作用域后缀如 health#1 -> health）。"""
        clean_name = agent_name.split("#")[0]
        if clean_name not in self.mailboxes:
            self.mailboxes[clean_name] = AgentMailbox(clean_name, self.session_id)
        return self.mailboxes[clean_name]

    async def send(
        self,
        msg: PeerMessage,
        *,
        turn: Any = None,
        emit_sse: bool = True,
        known_agents: tuple[str, ...] = KNOWN_AGENTS,
    ) -> PeerMessage:
        """路由并投递电文，自动处理点对点单播与群组广播。"""
        if msg.hop_count > MAX_DELIBERATION_HOPS:
            logger.warning(
                "电文 %s 超过最大跳数限制 (%d)，拦截转发以防死循环",
                msg.id, MAX_DELIBERATION_HOPS
            )
            return msg

        async with self._lock:
            self.message_log.append(msg)

        clean_from = msg.from_agent.split("#")[0]

        if msg.to_agent in ("*", "broadcast"):
            # 广播模式：分发给除发送方外的所有已知智能体及已激活信箱
            targets = set(known_agents) | set(self.mailboxes.keys())
            targets.discard(clean_from)
            for target in sorted(targets):
                box = self.get_mailbox(target)
                copy_msg = msg.model_copy(update={"to_agent": target, "hop_count": msg.hop_count + 1})
                await box.post(copy_msg)
        else:
            # 单播模式
            clean_to = msg.to_agent.split("#")[0]
            box = self.get_mailbox(clean_to)
            routed_msg = msg.model_copy(update={"hop_count": msg.hop_count + 1})
            await box.post(routed_msg)

        # 实时心智显像：向前端推 SSE 事件并同步落入事件日志
        if turn is not None and emit_sse:
            await turn.emit("peer_message", msg.to_sse_payload(), persist=True)

        return msg

    def drain(self, agent_name: str) -> list[PeerMessage]:
        return self.get_mailbox(agent_name).drain()

    def get_unread(self, agent_name: str) -> list[PeerMessage]:
        return self.get_mailbox(agent_name).peek()

    def get_unread_count(self, agent_name: str) -> int:
        return self.get_mailbox(agent_name).unread_count()

    def get_history(self, agent_name: str | None = None) -> list[PeerMessage]:
        if agent_name:
            return self.get_mailbox(agent_name).get_history()
        return list(self.message_log)

    def clear(self) -> None:
        for box in self.mailboxes.values():
            box.clear()
        self.mailboxes.clear()
        self.message_log.clear()


# 全局会话信箱注册表（内存级快速寻址）
_SESSION_HUBS: dict[str, SessionMailboxHub] = {}
_HUBS_LOCK = asyncio.Lock()


def get_session_mailbox_hub(session_id: str) -> SessionMailboxHub:
    """获取会话级信箱中枢实例（单例保序）。"""
    if session_id not in _SESSION_HUBS:
        _SESSION_HUBS[session_id] = SessionMailboxHub(session_id)
    return _SESSION_HUBS[session_id]


def clear_session_mailbox_hub(session_id: str) -> None:
    """清理会话信箱资源。"""
    hub = _SESSION_HUBS.pop(session_id, None)
    if hub:
        hub.clear()


def install_mailbox_hook(bus: EventBus) -> Callable[[], None]:
    """向 EventBus 注册 PRE_STEP 瀑布钩子，实现轮次间未读电文被动注水。"""
    async def pre_step_mailbox_inject(request: Any, next_: Next) -> Any:
        out = await next_()
        target = out if getattr(out, "messages", None) is not None else request
        try:
            turn = getattr(target, "turn", None) or getattr(request, "turn", None)
            agent = getattr(target, "agent", None) or getattr(request, "agent", None)
            if turn and agent:
                session_id = getattr(turn, "session_id", "")
                agent_name = getattr(agent, "name", "agent").split("#")[0]
                hub = get_session_mailbox_hub(session_id)
                unread = hub.drain(agent_name)
                if unread:
                    injection_block = (
                        "\n\n# 【来自队友智能体的协同信箱来信】\n"
                        "检测到其他协同智能体为您注入了以下专业约束与研讨建议，请严格在后续规划与工具调用中遵守：\n"
                    )
                    for m in unread:
                        injection_block += m.to_prompt_context() + "\n"

                    messages = list(getattr(target, "messages", []) or [])
                    if messages:
                        if messages[0].get("role") == "system":
                            messages[0]["content"] += injection_block
                        else:
                            messages.insert(0, {"role": "system", "content": injection_block})
                        target.messages = messages
        except Exception as exc:
            logger.warning("信箱 PRE_STEP 注入异常，放行主流程: %s", exc)

        return out

    return bus.on(PRE_STEP, pre_step_mailbox_inject, order=-10, label="mailbox-pre-step-inject")
