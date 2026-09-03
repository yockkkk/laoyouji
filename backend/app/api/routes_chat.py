"""对话主入口：POST /api/chat/stream（SSE 流式）。"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_ctx, get_optional_principal
from app.auth.security import Principal
from app.core.bus import SESSION_FLUSH
from app.core.context import TurnContext

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)


class ChatIn(BaseModel):
    session_id: str | None = None
    user_id: str | None = None
    text: str


@router.post("/chat/stream")
async def chat_stream(body: ChatIn, principal: Principal | None = Depends(get_optional_principal)):
    ctx = get_ctx()
    # 优先从 Bearer Token 取真实身份，无 Token 时兼容历史测试传入的 user_id
    if principal:
        user = principal.user
        if body.user_id and body.user_id != principal.id:
            raise HTTPException(403, "请求参数与当前认证身份不一致")
    elif body.user_id:
        user = await ctx.repos.get("users", body.user_id)
    else:
        raise HTTPException(401, "未提供认证身份")

    if not user:
        raise HTTPException(404, "用户不存在")

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
