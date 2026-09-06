"""杂项 API：健康检查 / 演示数据复位 / 会话事件增量拉取（轮询兜底）/ 演示家庭。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_ctx, get_optional_principal, valid_session_id
from app.auth.security import Principal
from app.core.context import AppContext
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
async def seed(principal: Principal | None = Depends(get_optional_principal)):
    """演示数据复位。无鉴权裸奔的版本等于把"重置全库"挂在公网上。

    门禁两层：调试环境（settings.debug）直接放行，demo/联调不受影响；
    非调试环境要求管理员身份，其余一律 403。
    """
    ctx = get_ctx()
    if not ctx.settings.debug:
        if principal is None or principal.role != "admin":
            raise HTTPException(403, "数据复位仅限调试环境或管理员")
    result = await seed_demo(ctx.repos)
    return {
        "ok": True,
        "elder": {"id": result["elder"]["id"], "name": result["elder"]["name"]},
        "child": {"id": result["child"]["id"], "name": result["child"]["name"]},
    }


def _public_user(row: dict) -> dict:
    """出库用户行 → 可给前端的形状。password_hash 永远不出库。"""
    return {k: v for k, v in row.items() if k != "password_hash"}


@router.get("/demo/family")
async def demo_family():
    """登录页用：返回演示家庭（老人/子女）信息。"""
    ctx = get_ctx()
    elders = await ctx.repos.list("users", where={"role": "elder"}, limit=5)
    children = await ctx.repos.list("users", where={"role": "child"}, limit=5)
    if not elders or not children:
        result = await seed_demo(ctx.repos)
        elders, children = [result["elder"]], [result["child"]]
    return {"elders": [_public_user(u) for u in elders],
            "children": [_public_user(u) for u in children]}


@router.get("/weather")
async def weather(city: str = "南京", date_offset: str | None = None):
    """首页天气卡片（走 Weather Provider 接缝，mock/真实可换）。"""
    ctx = get_ctx()
    provider = ctx.registry.resolve("weather")
    return await provider.get(city, date_offset)


@router.get("/sessions/{session_id}/events")
async def session_events(session_id: str, after_seq: int = 0,
                         ctx: AppContext = Depends(get_ctx)):
    """轮询兜底 / 断线恢复 / 会话回放（append-only 唯一事实源）。

    ctx 走 ``Depends`` 而不是函数体里 ``get_ctx()``：后者绕过
    ``app.dependency_overrides``，测试里换不掉，于是 HTTP 级用例会打到真库
    （还会顺手拉一条 SSH 隧道）—— 这条路径是前端断线后唯一的兜底，必须能测。
    """
    session_id = valid_session_id(session_id)
    # 会话不存在必须给 404，别拿"200 + 空列表"糊过去：前端 SSE 断线后会退到这个
    # 接口轮询，空列表在它看来是"还没轮到我"，于是空转 60 轮 x 2 秒 = 两分钟，
    # 最后一句话都不说。老人看到的就是"处理中"转半天然后没了。
    if not await ctx.repos.get("sessions", session_id):
        raise HTTPException(404, "会话不存在")
    rows = await ctx.event_log.after(session_id, after_seq)
    return {"items": rows, "latest_seq": rows[-1]["seq"] if rows else after_seq}


@router.get("/sessions/{session_id}")
async def session_detail(session_id: str):
    ctx = get_ctx()
    session_id = valid_session_id(session_id)
    session = await ctx.repos.get("sessions", session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    events = await ctx.event_log.recent(session_id, limit=200)
    session["events"] = events
    return session
