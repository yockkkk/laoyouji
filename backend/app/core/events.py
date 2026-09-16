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

import asyncio
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

# 仅这些持久事件参与 LLM 历史派生。
# ASSISTANT_FINAL 必须在内：整轮定稿（routes_chat 的 final / 确认重放的那句
# 播报）只以这个类型落日志，不收进来模型下一轮就"忘了自己刚说过什么" ——
# 多轮对话一句话说完就失忆的直接来源之一。derive_messages 里负责去重。
_MODEL_VISIBLE = {USER_MESSAGE, ASSISTANT_MESSAGE, ASSISTANT_FINAL, TOOL_RESULT}

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
    # 一条事件最多试这么多次落库。给上限是因为"永久重排队"会让一条坏事件
    # 每轮都重试、日志刷满，而它本来只是某一条 payload 有问题。
    MAX_FLUSH_ATTEMPTS = 3

    # 内存里最多同时驻留这么多个会话的日志。超了就把最久没碰过的那些让出去
    # （只让已全部落库的），下次访问自动 hydrate 回来。
    # 没有上界的话，一个长期开着的服务进程会把每个曾经打开过的会话永久留在内存里
    # —— 演示跑不出问题，连着跑一周就是慢性泄漏。
    MAX_LIVE_SESSIONS = 200

    def __init__(self, repo: Repository):
        self._repo = repo
        self._events: dict[str, list[SessionEvent]] = {}
        self._seq: dict[str, int] = {}
        self._pending: dict[str, list[SessionEvent]] = {}
        self._hydrated: set[str] = set()
        # 已确认落库的 seq。flush 可能被重复触发（轮次末尾 + 确认重放 + 断线补写），
        # 没有这张表就会往 uq_session_events_session_seq 上撞重复键。
        self._persisted: dict[str, set[int]] = {}
        self._attempts: dict[tuple[str, int], int] = {}
        # 每会话一把锁。``append`` 是纯同步的、没有读改写窗口，所以它不需要锁；
        # 但 ``hydrate`` 和 ``flush`` 中间都有 await，两个请求同时唤醒同一个冷会话时
        # 会各自读到旧的 max(seq)、各自分配同一个号：内存里后写的把先写的顶掉，
        # 库里两条都进去撞 uq_session_events_session_seq。锁就是为了关掉那个窗口。
        self._locks: dict[str, asyncio.Lock] = {}
        # 最近使用序。**不能拿 ``_hydrated`` 当 LRU** —— 它是 set，没有顺序，
        # 照它的迭代序驱逐等于随机挑一个会话让出去，可能正是老人当前在聊的那个。
        self._lru: dict[str, None] = {}

    # ---------------------------------------------------------------- 会话
    async def create_session(self, user_id: str, title: str = "") -> dict:
        session = await self._repo.insert(
            "sessions", {"user_id": user_id, "title": title or "新对话"})
        sid = session["id"]
        self._events.setdefault(sid, [])
        self._seq[sid] = 0
        self._persisted.setdefault(sid, set())
        self._hydrated.add(sid)
        self._touch(sid)
        return session

    async def hydrate(self, session_id: str) -> None:
        """续接已有会话时把历史读进内存（幂等，并发安全）。之后内存日志即权威。

        锁 + 进锁后再查一次 ``_hydrated``（双检）：两个请求同时唤醒同一个冷会话时，
        第二个进来发现第一个已经读完了就直接返回，不会把内存日志重置成刚读的那份
        —— 重置会丢掉这中间 append 进来的事件，并让 seq 计数器退回去发重号。
        """
        if session_id in self._hydrated:
            self._touch(session_id)
            return
        async with self._lock(session_id):
            if session_id in self._hydrated:     # 双检：等锁期间别人已经读好了
                self._touch(session_id)
                return
            rows = await self._repo.list(
                "session_events", where={"session_id": session_id}, order="seq")
            events = [SessionEvent.from_row(r) for r in rows]
            self._events[session_id] = events
            self._seq[session_id] = max((e.seq for e in events), default=0)
            # 读回来的都是已落库的事实，登记进去，免得后续 flush 又写一遍
            self._persisted[session_id] = {e.seq for e in events}
            self._hydrated.add(session_id)
            self._touch(session_id)

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
        self._touch(session_id)
        return event

    async def flush(self, session_id: str | None = None) -> int:
        """把写后缓冲落库（session/flush 检查点调用）。返回落库条数。

        与旧实现的两处差别，都是"聊天记录不能丢"这一条要求逼出来的：

        1. **整批一次写**。一轮对话几十条事件，逐条 insert 就是几十个网络往返，
           老人问下一句时还在排空上一句的缓冲。批量失败才退回逐条，好定位坏行。
        2. **失败重排队**。旧实现把 batch 从 ``_pending`` 摘下来就不管了，
           insert 抛异常那条事件**只存在于内存里**，进程一重启就没了 ——
           日志里留一行 warning，用户看到的是"上次说的话不见了"。
           现在失败的排回缓冲，下个检查点再试，试满 ``MAX_FLUSH_ATTEMPTS`` 才放弃。
        """
        keys = [session_id] if session_id else list(self._pending)
        written = 0
        for sid in keys:
            # 同一个会话的两次 flush 不能同时在飞：两边会各自摘走一半缓冲，
            # 失败重排队时互相覆盖 ``_pending[sid]``，被摘走的那批就凭空消失了。
            async with self._lock(sid):
                written += await self._flush_one(sid)
        return written

    async def _flush_one(self, sid: str) -> int:
        batch, self._pending[sid] = self._pending.get(sid, []), []
        done = self._persisted.setdefault(sid, set())
        batch = [e for e in batch if e.seq not in done]
        if not batch:
            return 0
        ok, failed = await self._write(batch)
        requeue = []
        for event in failed:
            key = (sid, event.seq)
            attempts = self._attempts.get(key, 0) + 1
            if attempts >= self.MAX_FLUSH_ATTEMPTS:
                self._attempts.pop(key, None)
                logger.error("事件落库连续失败 %d 次，放弃 session=%s seq=%s",
                             attempts, sid, event.seq)
            else:
                self._attempts[key] = attempts
                requeue.append(event)
        if requeue:
            self._pending[sid] = requeue + self._pending.get(sid, [])
        return ok

    async def _write(self, events: list[SessionEvent]) -> tuple[int, list[SessionEvent]]:
        """写一批事件，返回 ``(成功条数, 失败事件)``。"""
        insert_many = getattr(self._repo, "insert_many", None)
        if insert_many is not None:
            try:
                await insert_many("session_events", [e.to_row() for e in events])
                for event in events:
                    self._mark_persisted(event)
                return len(events), []
            except Exception as exc:  # noqa: BLE001 —— 整批失败退回逐条，定位坏行
                logger.warning("批量落库失败（%d 条），退回逐条：%s", len(events), exc)

        ok, failed = 0, []
        for event in events:
            try:
                await self._repo.insert("session_events", event.to_row())
                self._mark_persisted(event)
                ok += 1
            except Exception as exc:  # noqa: BLE001 —— 落库失败不该吞掉演示
                logger.warning("事件落库失败 seq=%s: %s", event.seq, exc)
                failed.append(event)
        return ok, failed

    def _mark_persisted(self, event: SessionEvent) -> None:
        self._persisted.setdefault(event.session_id, set()).add(event.seq)
        self._attempts.pop((event.session_id, event.seq), None)

    # ---------------------------------------------------------------- 内存治理
    def _lock(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = self._locks[session_id] = asyncio.Lock()
        return lock

    def _touch(self, session_id: str) -> None:
        """标记"刚碰过"，并在超出上界时让出最久未用的会话。

        用 dict 的插入序当 LRU：删掉再插回去就等于挪到队尾（Python 3.7+ 保序）。
        """
        self._lru.pop(session_id, None)
        self._lru[session_id] = None
        if len(self._events) > self.MAX_LIVE_SESSIONS:
            self._evict_idle()

    def _evict_idle(self) -> None:
        """让出最久未用的会话日志。**只让已全部落库的** —— 还有 pending 的
        一让就等于把没写进库的事件丢了，那正是持久化要防的事。
        """
        target = len(self._events) - self.MAX_LIVE_SESSIONS
        for sid in list(self._lru):            # 最久未用的排在前面
            if target <= 0:
                return
            if self._pending.get(sid):
                continue                       # 还没落库，不能让
            if self.release(sid):
                target -= 1

    def release(self, session_id: str) -> bool:
        """把一个会话的内存日志让出去（下次访问自动 hydrate 回来）。

        返回是否真的让了 —— 还有未落库事件时拒绝让出，返回 False。
        """
        if self._pending.get(session_id):
            return False
        self._events.pop(session_id, None)
        self._seq.pop(session_id, None)
        self._persisted.pop(session_id, None)
        self._pending.pop(session_id, None)
        self._hydrated.discard(session_id)
        self._lru.pop(session_id, None)
        lock = self._locks.get(session_id)
        if lock is not None and not lock.locked():
            self._locks.pop(session_id, None)
        return True

    def live_count(self) -> int:
        """内存里驻留的会话数（/health 与测试用）。"""
        return len(self._events)

    def pending_count(self, session_id: str | None = None) -> int:
        """还没落库的事件条数（0 = 内存与库一致）。测试与 /health 用得上。"""
        if session_id is not None:
            return len(self._pending.get(session_id, []))
        return sum(len(v) for v in self._pending.values())

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

            elif event.type == ASSISTANT_FINAL:
                text = payload.get("text") or ""
                if not text:
                    continue
                # 去重：正常轮次里 final 与最后一条 assistant/message 是同一份
                # 定稿（session.py 把 response.content 同时落了两处）。紧邻的
                # 上一条 assistant 正文相同就跳过，别让同一句话在历史里占两行
                # —— 既浪费 token，也让模型困惑"我是不是说了两遍"。
                last = messages[-1] if messages else None
                if (last and last.get("role") == "assistant"
                        and last.get("content") == text):
                    continue
                messages.append({"role": "assistant", "content": text})

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

        return _slice_turn_safe(messages, limit)

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


def _ensure_valid_tool_turns(messages: list[dict]) -> list[dict]:
    """严格保证 OpenAI/DeepSeek 的工具调用上下文合法性：
    1. 含有 tool_calls 的 assistant 消息，后面必须【紧跟】对应的 role: tool 消息。
    2. 绝不允许在 assistant(tool_calls) 与 tool 之间插入任何 user 或 assistant 消息。
    3. 剔除没有任何工具结果的 tool_calls；若 assistant 无内容且无有效 tool_calls，则略去该消息。
    4. 剔除孤儿 tool 消息。
    """
    all_tools: dict[str, dict] = {}
    for m in messages:
        if m.get("role") == "tool" and m.get("tool_call_id"):
            all_tools[m["tool_call_id"]] = m

    consumed_tools: set[str] = set()
    out: list[dict] = []

    for msg in messages:
        role = msg.get("role")
        if role == "tool":
            # tool 消息由 assistant 触发内联追加，跳过独立游离消息
            continue

        if role == "assistant" and msg.get("tool_calls"):
            calls = msg["tool_calls"]
            # 只保留未被消费且存在结果的 call
            valid_calls = [
                c for c in calls
                if isinstance(c, dict) and c.get("id") in all_tools and c.get("id") not in consumed_tools
            ]

            content = msg.get("content")
            if valid_calls:
                new_asst = dict(msg)
                new_asst["tool_calls"] = valid_calls
                out.append(new_asst)
                for c in valid_calls:
                    cid = c["id"]
                    out.append(all_tools[cid])
                    consumed_tools.add(cid)
            elif content:
                # 没有任何有效 tool_calls，但有文本内容，退化为普通 assistant 消息
                new_asst = dict(msg)
                new_asst.pop("tool_calls", None)
                out.append(new_asst)
            else:
                # 既无有效 tool_calls 也无 content，直接丢弃，避免 DeepSeek 400
                continue
        elif role == "assistant":
            content = msg.get("content")
            if content:
                out.append(msg)
        else:
            out.append(msg)

    # 验证不变式：确保没有任何 assistant(tool_calls) 后面缺少 tool
    for idx, m in enumerate(out):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            tcs = [c["id"] for c in m["tool_calls"]]
            subsequent_tools = []
            k = idx + 1
            while k < len(out) and out[k].get("role") == "tool":
                subsequent_tools.append(out[k].get("tool_call_id"))
                k += 1
            if tcs != subsequent_tools:
                logger.warning("工具调用与工具结果不严格配对: tool_calls=%s vs tools=%s", tcs, subsequent_tools)

    return out


def _drop_orphan_tool_messages(messages: list[dict]) -> list[dict]:
    """保证消息历史合法并剔除孤儿 tool 消息。"""
    return _ensure_valid_tool_turns(messages)


def _slice_turn_safe(messages: list[dict], limit: int | None = None) -> list[dict]:
    """按完整轮次安全截断历史消息，且绝不让 messages 以孤立的 role:tool 开头。"""
    cleaned = _ensure_valid_tool_turns(messages)
    if not limit or len(cleaned) <= limit:
        return cleaned

    sliced = cleaned[-limit:]
    # 找到截断区域里的第一个 user 消息，保证从完整轮次开始
    first_user_idx = None
    for idx, msg in enumerate(sliced):
        if msg.get("role") == "user":
            first_user_idx = idx
            break

    if first_user_idx is not None and first_user_idx > 0:
        sliced = sliced[first_user_idx:]

    # 截断后再跑一遍保证 tool 闭环
    return _ensure_valid_tool_turns(sliced)


def new_uuid() -> str:
    return str(uuid.uuid4())
