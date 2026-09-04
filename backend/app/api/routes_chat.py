"""对话主入口：POST /api/chat/stream（SSE 流式）与会话历史接口。"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_ctx, get_optional_principal, valid_session_id
from app.auth.security import Principal
from app.core.bus import SESSION_FLUSH
from app.core.context import AppContext, TurnContext
from app.core.events import (
    ARTIFACT_CARD,
    ASSISTANT_MESSAGE,
    CONFIRM_SUSPENDED,
    MAIN_SCOPE,
    TODO_WRITE,
    USER_MESSAGE,
)
from app.core.turn_gate import QUEUED_HINT, TurnBusy

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)

# 断线后仍在跑的轮次。**必须留强引用** —— asyncio 只弱引用 task，
# 没人持有的话事件循环可能在它落库之前就把它回收了，
# 那正好是"老人锁屏，回来发现计划书没了"的成因。
_detached: set[asyncio.Task] = set()


def _detach(task: asyncio.Task, session_id: str) -> None:
    """老人断线了，但这一轮继续跑到底。

    不取消是刻意的：事件已经在写后缓冲里，轮次末尾的 ``session/flush`` 才落库。
    这时候取消，办到一半的活儿就只剩半截 —— 而老人那边可能只是锁了个屏、
    过隧道断了几秒。让它跑完，他回来一拉 ``/sessions/{id}/events`` 就是完整的。
    预算墙钟（默认 90 秒）保证它不会永远跑。
    """
    _detached.add(task)

    def _done(t: asyncio.Task) -> None:
        _detached.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.warning("断线后的轮次异常收尾 session=%s: %s",
                           session_id, t.exception())

    task.add_done_callback(_done)


async def _resolve_user(
    ctx: AppContext,
    principal: Principal | None,
    user_id: str | None,
) -> dict:
    if principal:
        user = principal.user
        if user_id and user_id != principal.id:
            raise HTTPException(403, "请求参数与当前认证身份不一致")
        return user
    elif user_id:
        user = await ctx.repos.get("users", user_id)
        if not user:
            raise HTTPException(404, "用户不存在")
        return user
    else:
        raise HTTPException(401, "未提供认证身份")


# 新建会话时还不知道老人要问什么，只能先叫"新对话"。第一句话到了才有标题。
_PLACEHOLDER_TITLES = {"", "新对话"}


async def _backfill_title(ctx: AppContext, session: dict, text: str) -> None:
    """把占位标题换成第一句话。会话列表里全是"新对话"就等于没有列表。"""
    if (session.get("title") or "").strip() not in _PLACEHOLDER_TITLES:
        return
    title = (text or "").strip()[:20]
    if not title:
        return
    try:
        await ctx.repos.update("sessions", session["id"], {"title": title})
    except Exception as exc:  # noqa: BLE001 —— 标题是锦上添花，不能挡住对话
        logger.warning("会话标题回填失败 session=%s: %s", session.get("id"), exc)


class ChatIn(BaseModel):
    session_id: str | None = None
    user_id: str | None = None
    text: str


class SessionNewIn(BaseModel):
    user_id: str | None = None
    title: str | None = None


@router.post("/chat/stream")
async def chat_stream(
    body: ChatIn,
    principal: Principal | None = Depends(get_optional_principal),
    ctx: AppContext = Depends(get_ctx),
):
    # 优先从 Bearer Token 取真实身份，无 Token 时兼容历史测试传入的 user_id
    user = await _resolve_user(ctx, principal, body.user_id)

    if (body.session_id or "").strip():
        session_id = valid_session_id(body.session_id)
        session = await ctx.repos.get("sessions", session_id)
        if not session:
            raise HTTPException(404, "会话不存在")
        await ctx.event_log.hydrate(session_id)
        await _backfill_title(ctx, session, body.text)
    else:
        session = await ctx.event_log.create_session(
            user["id"], body.text[:20])
        session_id = session["id"]

    turn = TurnContext(ctx=ctx, session_id=session_id, user=user)
    ctx.broadcast.register(session_id, turn.queue)

    async def announce_queued() -> None:
        """前一轮还在跑时说一句。只在真需要等的时候被调一次。"""
        await turn.status("main", QUEUED_HINT)

    async def run_main_agent() -> None:
        # 闸门包住**整轮**（含 user_msg 的追加）：同一会话的两轮不能交错，
        # 否则派生给模型的历史是"问A 答A 问B 答B"混在一起的一锅粥，
        # 模型分不清哪句回答对着哪句提问，下一步的工具参数就可能张冠李戴。
        async with ctx.turn_gate.hold(session_id, on_wait=announce_queued):
            await turn.emit("user_msg", {"text": body.text})
            # flush 放 finally：user/message 在轮次一开头就进了写后缓冲，
            # 智能体中途抛异常时若不落库，这一问一答就只活在内存里，
            # 老人下次进来看到的是"我刚才明明说过"的空白。
            try:
                final = await ctx.agents["main"].run(turn)
                await turn.emit("final", {"text": final})
            finally:
                await ctx.bus.parallel(SESSION_FLUSH,
                                       {"session_id": session_id, "ctx": ctx})

    async def event_stream():
        task = asyncio.create_task(run_main_agent())
        try:
            yield {"event": "session", "data": json.dumps(
                {"session_id": session_id}, ensure_ascii=False)}
            while True:
                if task.done() and turn.queue.empty():
                    break
                try:
                    ev = await asyncio.wait_for(turn.queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                yield ev.encode()
            exc = task.exception() if task.done() else None
            if isinstance(exc, TurnBusy):
                # 等不到闸门：说实话，别把它伪装成系统故障
                yield {"event": "error", "data": json.dumps(
                    {"message": exc.message}, ensure_ascii=False)}
            elif exc is not None:
                logger.exception("智能体执行失败", exc_info=exc)
                yield {"event": "error", "data": json.dumps(
                    {"message": "哎呀，我这儿出了点小问题，您再说一遍试试。"},
                    ensure_ascii=False)}
            elif task.done():
                while not turn.queue.empty():
                    yield turn.queue.get_nowait().encode()
        finally:
            ctx.broadcast.unregister(session_id, turn.queue)
            if not task.done():
                _detach(task, session_id)

    return EventSourceResponse(event_stream())


@router.get("/chat/sessions")
async def list_chat_sessions(
    user_id: str | None = None,
    limit: int = 30,
    principal: Principal | None = Depends(get_optional_principal),
    ctx: AppContext = Depends(get_ctx),
):
    user = await _resolve_user(ctx, principal, user_id)
    sessions = await ctx.repos.list(
        "sessions",
        where={"user_id": user["id"]},
        order="-created_at",
        limit=max(1, min(limit, 100)),
    )
    return {
        "items": sessions,
        "latest_session": sessions[0] if sessions else None,
    }


@router.get("/chat/history")
async def get_chat_history(
    session_id: str,
    user_id: str | None = None,
    principal: Principal | None = Depends(get_optional_principal),
    ctx: AppContext = Depends(get_ctx),
):
    session_id = valid_session_id(session_id)
    session = await ctx.repos.get("sessions", session_id)
    if not session:
        raise HTTPException(404, "会话不存在")

    caller_user_id = None
    if principal:
        if user_id and user_id != principal.id:
            raise HTTPException(403, "请求参数与当前认证身份不一致")
        caller_user_id = principal.id
    elif user_id:
        caller_user_id = user_id

    if caller_user_id and session.get("user_id"):
        if session["user_id"] != caller_user_id:
            raise HTTPException(403, "无权访问该会话")

    await ctx.event_log.hydrate(session_id)
    events = ctx.event_log.events(session_id)

    messages = []
    for event in events:
        payload = event.payload or {}
        if event.type == USER_MESSAGE:
            # 只有 main 作用域的 user/message 才是老人真说过的话。
            # 子智能体的 user/message 是**派给它的指令**（"…医院、科室、医生、
            # 日期、时间、挂号费照抄查询结果"），落日志是为了它自己的历史派生；
            # 渲染成老人的气泡就等于把系统内部指令当成老人的原话给他看。
            if event.agent_id != MAIN_SCOPE:
                continue
            text = (payload.get("text") or "").strip()
            if text:
                messages.append({
                    "kind": "text",
                    "text": text,
                    "isUser": True,
                })
        elif event.type == ASSISTANT_MESSAGE:
            text = (payload.get("text") or "").strip()
            if text:
                messages.append({
                    "kind": "text",
                    "text": text,
                    "isUser": False,
                    "agent": event.agent_id,
                })
        elif event.type == TODO_WRITE:
            todos = payload.get("todos", [])
            progress = payload.get("progress", {})
            if messages and messages[-1].get("kind") == "todo":
                messages[-1]["todos"] = todos
                messages[-1]["progress"] = progress
            else:
                messages.append({
                    "kind": "todo",
                    "todos": todos,
                    "progress": progress,
                })
        elif event.type == ARTIFACT_CARD:
            messages.append({
                "kind": "card",
                **payload,
            })
        elif event.type == CONFIRM_SUSPENDED:
            cid = payload.get("id") or payload.get("confirmation_id")
            messages.append({
                "kind": "suspend",
                "confirmationId": cid,
                "summary": payload.get("summary", ""),
                "status": payload.get("status", "pending"),
                "amount": payload.get("amount", 0),
            })
        elif event.type == "confirmation/resolved":
            cid = payload.get("id") or payload.get("confirmation_id")
            status = payload.get("status") or ("executed" if payload.get("ok") else "rejected")
            for m in messages:
                if m.get("kind") == "suspend" and m.get("confirmationId") == cid:
                    m["status"] = status

    latest_seq = max((e.seq for e in events), default=0)
    return {
        "session_id": session_id,
        "messages": messages,
        "latest_seq": latest_seq,
    }


@router.post("/chat/sessions/new")
async def create_new_session(
    body: SessionNewIn | None = Body(None),
    user_id: str | None = None,
    principal: Principal | None = Depends(get_optional_principal),
    ctx: AppContext = Depends(get_ctx),
):
    uid = (body.user_id if body else None) or user_id
    user = await _resolve_user(ctx, principal, uid)
    title = (body.title if body and body.title else None) or "新对话"
    session = await ctx.event_log.create_session(user["id"], title)
    return {"session_id": session["id"]}
