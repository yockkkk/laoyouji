"""对话主入口：POST /api/chat/stream（SSE 流式）。"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_ctx
from app.core.bus import SESSION_FLUSH
from app.core.context import TurnContext

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)


class ChatIn(BaseModel):
    session_id: str | None = None
    user_id: str
    text: str


@router.post("/chat/stream")
async def chat_stream(body: ChatIn):
    ctx = get_ctx()
    user = await ctx.repos.get("users", body.user_id)
    if not user:
        raise HTTPException(404, "用户不存在")

    if body.session_id:
        session = await ctx.repos.get("sessions", body.session_id)
        if not session:
            raise HTTPException(404, "会话不存在")
        session_id = body.session_id
        # 续接旧会话：先把历史读进内存日志。不 hydrate 就 append，seq 会从 1
        # 重新发号，把已有行撞掉，派生历史也会丢掉之前的上下文（幂等，可反复调）。
        await ctx.event_log.hydrate(session_id)
    else:
        session = await ctx.event_log.create_session(
            body.user_id, body.text[:20])
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
                # final 是在驱动器那次 session/flush 之后才 emit 的，
                # 不再补一次检查点它就只活在内存里 —— 进程重启后老人看不到结论。
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
                # 排空 final 之后残余的事件（如 card 在 final 之后入队）
                while not turn.queue.empty():
                    yield turn.queue.get_nowait().encode()
        finally:
            ctx.broadcast.unregister(session_id, turn.queue)

    return EventSourceResponse(event_stream())
