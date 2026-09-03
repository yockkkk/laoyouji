"""对话主入口：POST /api/chat/stream（SSE 流式）与会话历史接口。"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_ctx, get_optional_principal
from app.auth.security import Principal
from app.core.bus import SESSION_FLUSH
from app.core.context import AppContext, TurnContext
from app.core.events import (
    ARTIFACT_CARD,
    ASSISTANT_MESSAGE,
    CONFIRM_SUSPENDED,
    TODO_WRITE,
    USER_MESSAGE,
)

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)


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

    if body.session_id:
        session = await ctx.repos.get("sessions", body.session_id)
        if not session:
            raise HTTPException(404, "会话不存在")
        session_id = body.session_id
        await ctx.event_log.hydrate(session_id)
    else:
        session = await ctx.event_log.create_session(
            user["id"], body.text[:20])
        session_id = session["id"]

    turn = TurnContext(ctx=ctx, session_id=session_id, user=user)
    ctx.broadcast.register(session_id, turn.queue)

    async def event_stream():
        try:
            yield {"event": "session", "data": json.dumps(
                {"session_id": session_id}, ensure_ascii=False)}
            await turn.emit("user_msg", {"text": body.text})

            async def run_main_agent() -> None:
                final = await ctx.agents["main"].run(turn)
                await turn.emit("final", {"text": final})
                await ctx.bus.parallel(SESSION_FLUSH,
                                       {"session_id": session_id, "ctx": ctx})

            task = asyncio.create_task(run_main_agent())
            while True:
                if task.done() and turn.queue.empty():
                    break
                try:
                    ev = await asyncio.wait_for(turn.queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                yield ev.encode()
            exc = task.exception() if task.done() else None
            if exc is not None:
                logger.exception("智能体执行失败", exc_info=exc)
                yield {"event": "error", "data": json.dumps(
                    {"message": "哎呀，我这儿出了点小问题，您再说一遍试试。"},
                    ensure_ascii=False)}
            elif task.done():
                while not turn.queue.empty():
                    yield turn.queue.get_nowait().encode()
        finally:
            ctx.broadcast.unregister(session_id, turn.queue)

    return EventSourceResponse(event_stream())


@router.get("/chat/sessions")
async def list_chat_sessions(
    user_id: str | None = None,
    principal: Principal | None = Depends(get_optional_principal),
    ctx: AppContext = Depends(get_ctx),
):
    user = await _resolve_user(ctx, principal, user_id)
    sessions = await ctx.repos.list(
        "sessions",
        where={"user_id": user["id"]},
        order="-created_at",
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
