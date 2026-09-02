"""SessionEventLog —— 事件溯源的会话日志：系统唯一事实源。

对齐 deepseek-harness 的三条关键设计：

1. **同步追加，写后落库**（sync append + write-behind）
   ``append()`` 是同步函数：seq 由内存单调计数器分配、事件立刻进内存日志，
   热路径**不等 I/O**。持久化排进 ``_pending``，在轮次结束的 ``session/flush``
   检查点由 ``flush()`` 落库。旧实现"先查 max(seq) 再 +1"存在竞态，
   并发下会撞号，"append-only 全序"的承诺不成立 —— 这里彻底修掉。

2. **Model-visible means logged**
   模型看到的每一条消息都必须能追溯到已记录事件。``derive_messages()`` 是唯一的
   历史来源（不允许旁路手搓 messages），``check_invariants()`` 是它的伴随校验。

3. **作用域派生**（scoped derivation）
   事件带 ``agent_id`` 作用域标签。子智能体只派生自己作用域的历史，
   不会看到兄弟智能体的对话 —— 这才是"真多智能体"，而不是共用一锅粥。

两个命名空间刻意分开（harness 的 Session events / Agent events 之分）：
- **持久事件类型**用斜杠词表（``tool/call``），是可回放的事实
- **SSE 事件名**用前端线格式（``tool_call``），是给界面的活信号
``_SSE_TO_DURABLE`` 是两者唯一的翻译点。
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.db.repositories import Repository

logger = logging.getLogger(__name__)

# ---- 持久事件类型词表 ------------------------------------------------------
TURN_START = "turn/start"
TURN_END = "turn/end"
STEP_START = "step/start"
STEP_END = "step/end"
USER_MESSAGE = "user/message"
ASSISTANT_MESSAGE = "assistant/message"
ASSISTANT_FINAL = "assistant/final"
TOOL_CALL = "tool/call"
TOOL_RESULT = "tool/result"
TODO_WRITE = "todo/write"
# 子智能体的结构化回报。落日志的理由：交付物渲染管线的输入必须可回放、可审计
# —— 评委问"这个票价哪来的"，答案是"第 N 条 agent/report 事件里的那个字段"。
AGENT_REPORT = "agent/report"
ARTIFACT_CARD = "artifact/card"
CONFIRM_SUSPENDED = "confirmation/suspended"
CONFIRM_RESOLVED = "confirmation/resolved"
GUARDIAN_ALERT = "guardian/alert"

# SSE 线格式名（前端契约）→ 持久事件类型（内核词表）
_SSE_TO_DURABLE = {
    "user_msg": USER_MESSAGE,
    "agent_msg": ASSISTANT_MESSAGE,
    "final": ASSISTANT_FINAL,
    "tool_call": TOOL_CALL,
    "tool_result": TOOL_RESULT,
    "todo": TODO_WRITE,
    "report": AGENT_REPORT,
    "card": ARTIFACT_CARD,
    "suspended": CONFIRM_SUSPENDED,
    "confirmation_resolved": CONFIRM_RESOLVED,
    "guardian_alert": GUARDIAN_ALERT,
}

# 仅这些持久事件参与 LLM 历史派生
_MODEL_VISIBLE = {USER_MESSAGE, ASSISTANT_MESSAGE, TOOL_RESULT}

MAIN_SCOPE = "main"


def durable_type(sse_event: str) -> str:
    """SSE 名 → 持久类型。未登记的名字进 ext/ 命名空间，不会拿到垃圾类型。"""
    return _SSE_TO_DURABLE.get(sse_event, f"ext/{sse_event}")


@dataclass(frozen=True)
class SessionEvent:
    """一条不可变的会话事实。seq 在会话内严格单调，是全序的唯一依据。"""

    seq: int
    session_id: str
    type: str
    payload: dict
    agent_id: str = MAIN_SCOPE
    turn_id: str | None = None
    step_id: str | None = None
    user_id: str | None = None
    created_at: str = ""

    def to_row(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "seq": self.seq,
            "type": self.type,
            "payload": self.payload,
            "agent_id": self.agent_id,
            "turn_id": self.turn_id,
            "step_id": self.step_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_row(cls, row: dict) -> SessionEvent:
        return cls(
            seq=int(row.get("seq") or 0),
            session_id=row.get("session_id", ""),
            type=row.get("type", ""),
            payload=row.get("payload") or {},
            agent_id=row.get("agent_id") or MAIN_SCOPE,
            turn_id=row.get("turn_id"),
            step_id=row.get("step_id"),
            user_id=row.get("user_id"),
            created_at=row.get("created_at") or "",
        )


class InvariantViolation(RuntimeError):
    """派生历史与事件日志不一致 —— 属于内核 bug，不该被静默容忍。"""


class SessionEventLog:
    def __init__(self, repo: Repository):
        self._repo = repo
        self._events: dict[str, list[SessionEvent]] = {}
        self._seq: dict[str, int] = {}
        self._pending: dict[str, list[SessionEvent]] = {}
        self._hydrated: set[str] = set()

    # ---------------------------------------------------------------- 会话
    async def create_session(self, user_id: str, title: str = "") -> dict:
        session = await self._repo.insert(
            "sessions", {"user_id": user_id, "title": title or "新对话"})
        sid = session["id"]
        self._events.setdefault(sid, [])
        self._seq[sid] = 0
        self._hydrated.add(sid)
        return session

    async def hydrate(self, session_id: str) -> None:
        """续接已有会话时把历史读进内存（幂等）。之后内存日志即权威。"""
        if session_id in self._hydrated:
            return
        rows = await self._repo.list(
            "session_events", where={"session_id": session_id}, order="seq")
        events = [SessionEvent.from_row(r) for r in rows]
        self._events[session_id] = events
        self._seq[session_id] = max((e.seq for e in events), default=0)
        self._hydrated.add(session_id)

    # ---------------------------------------------------------------- 追加
    def append(self, session_id: str, user_id: str | None, type: str,
               payload: dict, *, agent_id: str = MAIN_SCOPE,
               turn_id: str | None = None,
               step_id: str | None = None) -> SessionEvent:
        """**同步**追加：内存分配 seq、立刻可见、持久化留给 flush()。

        注意这里没有 await —— 这是"热路径不等 I/O"的字面落实，
        也是 seq 单调性能被保证的原因（分配发生在单线程事件循环内，无读改写窗口）。
        """
        seq = self._seq.get(session_id, 0) + 1
        self._seq[session_id] = seq
        event = SessionEvent(
            seq=seq, session_id=session_id, type=type, payload=payload,
            agent_id=agent_id, turn_id=turn_id, step_id=step_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._events.setdefault(session_id, []).append(event)
        self._pending.setdefault(session_id, []).append(event)
        return event

    async def flush(self, session_id: str | None = None) -> int:
        """把写后缓冲落库（session/flush 检查点调用）。返回落库条数。"""
        keys = [session_id] if session_id else list(self._pending)
        written = 0
        for sid in keys:
            batch, self._pending[sid] = self._pending.get(sid, []), []
            for event in batch:
                try:
                    await self._repo.insert("session_events", event.to_row())
                    written += 1
                except Exception as exc:  # noqa: BLE001 —— 落库失败不该吞掉演示
                    logger.warning("事件落库失败 seq=%s: %s", event.seq, exc)
        return written

    # ---------------------------------------------------------------- 读取
    def events(self, session_id: str, *,
               scopes: list[str] | None = None) -> list[SessionEvent]:
        rows = self._events.get(session_id, [])
        if scopes is None:
            return list(rows)
        allowed = set(scopes)
        return [e for e in rows if e.agent_id in allowed]

    async def recent(self, session_id: str, limit: int = 30) -> list[dict]:
        await self.hydrate(session_id)
        rows = [e.to_row() for e in self._events.get(session_id, [])]
        return rows[-limit:] if limit else rows

    async def after(self, session_id: str, after_seq: int) -> list[dict]:
        await self.hydrate(session_id)
        return [e.to_row() for e in self._events.get(session_id, [])
                if e.seq > after_seq]

    # ---------------------------------------------------------------- 派生
    def derive_messages(self, session_id: str, *,
                        scopes: list[str] | None = None,
                        limit: int | None = None) -> list[dict]:
        """事件日志 → LLM 消息历史。唯一的历史来源。

        与旧实现的关键差别：工具结果派生成 ``role:"tool"`` 且带 ``tool_call_id``，
        与 assistant 消息里的 ``tool_calls`` 严格配对。旧实现把工具结果伪装成
        ``role:"assistant"`` 的 ``"[工具结果] …"`` 文本，跨轮次后模型就再也分不清
        哪个结果对应哪次调用，function-calling 的因果链是断的。
        """
        events = self.events(session_id, scopes=scopes)
        messages: list[dict] = []
        # 已记录结果的 call_id：用于剔除没有配对结果的 tool_calls（否则模型 400）
        settled = {e.payload.get("call_id") for e in events
                   if e.type == TOOL_RESULT}

        for event in events:
            if event.type not in _MODEL_VISIBLE:
                continue
            payload = event.payload

            if event.type == USER_MESSAGE:
                text = payload.get("text", "")
                if text:
                    messages.append({"role": "user", "content": text})

            elif event.type == ASSISTANT_MESSAGE:
                calls = [c for c in (payload.get("tool_calls") or [])
                         if c.get("id") in settled]
                text = payload.get("text") or ""
                if not text and not calls:
                    continue                      # 空 assistant 消息不进历史
                message: dict[str, Any] = {"role": "assistant",
                                           "content": text or None}
                if calls:
                    message["tool_calls"] = [
                        {"id": c["id"], "type": "function",
                         "function": {"name": c.get("name", ""),
                                      "arguments": json.dumps(
                                          c.get("arguments") or {},
                                          ensure_ascii=False)}}
                        for c in calls
                    ]
                messages.append(message)

            elif event.type == TOOL_RESULT:
                call_id = payload.get("call_id")
                if not call_id:
                    continue
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": payload.get("content")
                    or json.dumps(payload.get("summary") or "",
                                  ensure_ascii=False),
                })

        messages = _drop_orphan_tool_messages(messages)
        return messages[-limit:] if limit else messages

    # ---------------------------------------------------------------- 不变式
    def check_invariants(self, session_id: str) -> list[str]:
        """"Model-visible means logged" 的伴随校验。返回违反项（空 = 干净）。"""
        events = self._events.get(session_id, [])
        problems: list[str] = []

        last = 0
        for event in events:
            if event.seq <= last:
                problems.append(f"seq 非严格递增: {last} → {event.seq}")
            last = event.seq

        declared: dict[str, str] = {}       # call_id -> agent_id
        for event in events:
            if event.type == ASSISTANT_MESSAGE:
                for call in event.payload.get("tool_calls") or []:
                    cid = call.get("id")
                    if cid:
                        declared[cid] = event.agent_id
        for event in events:
            if event.type != TOOL_RESULT:
                continue
            cid = event.payload.get("call_id")
            if not cid:
                problems.append(f"tool/result 缺 call_id (seq={event.seq})")
            elif cid not in declared:
                problems.append(f"tool/result 的 call_id {cid} 没有对应的调用声明")
            elif declared[cid] != event.agent_id:
                problems.append(
                    f"call_id {cid} 跨作用域: 声明于 {declared[cid]}，"
                    f"结果落在 {event.agent_id}")

        closed_turns = {e.turn_id for e in events if e.type == TURN_END}
        settled = {e.payload.get("call_id") for e in events
                   if e.type == TOOL_RESULT}
        for event in events:
            if event.type != ASSISTANT_MESSAGE or event.turn_id not in closed_turns:
                continue
            for call in event.payload.get("tool_calls") or []:
                if call.get("id") not in settled:
                    problems.append(
                        f"已结束轮次里调用 {call.get('id')} 没有结果 —— "
                        "工具调用被静默丢弃")

        for event in events:
            if event.type == TODO_WRITE:
                for item in event.payload.get("todos") or []:
                    if item.get("status") not in ("pending", "in_progress",
                                                  "completed"):
                        problems.append(f"todo 状态非法: {item.get('status')}")
        return problems

    def assert_invariants(self, session_id: str) -> None:
        problems = self.check_invariants(session_id)
        if problems:
            raise InvariantViolation("；".join(problems))


def _drop_orphan_tool_messages(messages: list[dict]) -> list[dict]:
    """剔除没有前置声明的 role:tool 消息（防御性；正常流程不该出现）。"""
    declared: set[str] = set()
    out: list[dict] = []
    for message in messages:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                declared.add(call["id"])
            out.append(message)
        elif message.get("role") == "tool":
            if message.get("tool_call_id") in declared:
                out.append(message)
        else:
            out.append(message)
    return out


def new_uuid() -> str:
    return str(uuid.uuid4())
