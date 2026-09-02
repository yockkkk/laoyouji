"""杂项 API：健康检查 / 演示数据复位 / 会话事件增量拉取（轮询兜底）/ 演示家庭。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import get_ctx
from app.db.seed import seed_demo

router = APIRouter(prefix="/api", tags=["misc"])


@router.get("/health")
async def health():
    ctx = get_ctx()
    return {
        "ok": True,
        "providers": {
            "llm": ctx.registry.provider_name("llm"),
            "asr": ctx.registry.provider_name("asr"),
            "storage": ctx.settings.storage_backend,
        },
        "agents": list(ctx.agents),
        "tools": [t.name for t in ctx.tools.all()],
    }


@router.post("/seed")
async def seed():
    ctx = get_ctx()
    result = await seed_demo(ctx.repos)
    return {
        "ok": True,
        "elder": {"id": result["elder"]["id"], "name": result["elder"]["name"]},
        "child": {"id": result["child"]["id"], "name": result["child"]["name"]},
    }


@router.get("/demo/family")
async def demo_family():
    """登录页用：返回演示家庭（老人/子女）信息。"""
    ctx = get_ctx()
    elders = await ctx.repos.list("users", where={"role": "elder"}, limit=5)
    children = await ctx.repos.list("users", where={"role": "child"}, limit=5)
    if not elders or not children:
        result = await seed_demo(ctx.repos)
        elders, children = [result["elder"]], [result["child"]]
    return {"elders": elders, "children": children}


@router.get("/weather")
async def weather(city: str = "南京", date_offset: str | None = None):
    """首页天气卡片（走 Weather Provider 接缝，mock/真实可换）。"""
    ctx = get_ctx()
    provider = ctx.registry.resolve("weather")
    return await provider.get(city, date_offset)


@router.get("/sessions/{session_id}/events")
async def session_events(session_id: str, after_seq: int = 0):
    """轮询兜底 / 断线恢复 / 会话回放（append-only 唯一事实源）。"""
    ctx = get_ctx()
    rows = await ctx.event_log.after(session_id, after_seq)
    return {"items": rows, "latest_seq": rows[-1]["seq"] if rows else after_seq}


@router.get("/sessions/{session_id}")
async def session_detail(session_id: str):
    ctx = get_ctx()
    session = await ctx.repos.get("sessions", session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    events = await ctx.event_log.recent(session_id, limit=200)
    session["events"] = events
    return session
