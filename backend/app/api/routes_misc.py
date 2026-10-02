"""杂项 API：健康检查 / 演示数据复位 / 会话事件增量拉取（轮询兜底）/ 演示家庭。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import (
    get_ctx,
    get_current_principal,
    get_optional_principal,
    valid_session_id,
)
from app.auth.security import Principal
from app.core.context import AppContext
from app.db.seed import seed_demo, seed_kangle_persona

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
async def seed(principal: Principal | None = Depends(get_optional_principal),
               scenario: str | None = None,
               with_persona: bool = True):
    """演示数据复位。无鉴权裸奔的版本等于把"重置全库"挂在公网上。

    门禁两层：调试环境（settings.debug）直接放行，demo/联调不受影响；
    非调试环境要求管理员身份，其余一律 403。

    ``with_persona``（默认开）：复位后把张桂芳的 30 天指标档案一并灌上。默认开，
    是因为康乐是**以健康为中心**的产品 —— 复位完健康页空空如也，这个"复位"就没
    复位到点子上，演示时还得再开一次命令行。要一张干净的空库就传 false。

    ``scenario``：换档案剧本（key 或中文档位都认，见 ``app.db.seed.resolve_scenario``），
    答辩现场一句话切档位，不用开命令行。非法值返 400，**不静默退回默认剧本**：
    演示者以为切到了"紧急"、屏幕上却是平稳档案，他会照着自己以为的那份讲下去 ——
    那比直接报错坏得多。
    """
    ctx = get_ctx()
    if not ctx.settings.debug:
        if principal is None or principal.role != "admin":
            raise HTTPException(403, "数据复位仅限调试环境或管理员")
    result = await seed_demo(ctx.repos)
    out = {
        "ok": True,
        "elder": {"id": result["elder"]["id"], "name": result["elder"]["name"]},
        "child": {"id": result["child"]["id"], "name": result["child"]["name"]},
    }
    if with_persona:
        # 不自己抄一份默认剧本名：不传就走 seed.py 里那个默认，
        # 免得两处各写一份、改了一处另一处悄悄留着旧值。
        kwargs = {"scenario": scenario} if scenario else {}
        try:
            out["persona"] = await seed_kangle_persona(
                ctx.repos, result["elder"], **kwargs)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return out


def _public_user(row: dict) -> dict:
    """演示家庭行 → 登录页示意卡片的形状。**白名单，不是黑名单。**

    以前这里是"把整行抄一遍、只剔掉 password_hash"。那种写法是**漏的**：库里的
    用户行还带着 ``phone``（张桂芳 138****0001）、``city``、``relation_to_child``，
    而这条路由必须是公开的（见下），于是手机号和家庭关系就跟着挂在了公网上。
    黑名单的毛病是"以后加一列敏感字段就默认漏" —— 所以改成只挑出登录页真正
    用得上的四个键，库里多出什么列都不会自己跑出去。

    为什么这四个够：登录页那两张演示卡片要显示"张桂芳 / 长辈模式"和
    "李明 / 家属守护"，靠的是 ``name`` + ``role``；``username`` 是账号模式
    里回填输入框用的；``id`` 留给前端做卡片 key（不是凭据 —— 会话那两条路由
    已经要求本人身份，光有 id 换不到任何数据）。
    """
    return {
        "id": row.get("id"),
        "username": row.get("username"),
        "name": row.get("name"),
        "role": row.get("role"),
    }


@router.get("/demo/family")
async def demo_family():
    """登录页用：返回演示家庭（老人/子女）的账号卡片信息。

    **这条必须公开**：登录页要靠它把演示账号卡片渲染出来，而此刻调用方还没有
    token —— 给它加 ``get_current_principal`` 就等于登录页永远打不开。公开的口子
    到此为止：只出 ``_public_user`` 那四个键，且这两个 ``id`` 已经换不到任何健康
    数据（``/api/sessions/{id}`` 要本人、``/api/chat/sessions`` 要 token）。
    """
    ctx = get_ctx()
    elders = await ctx.repos.list("users", where={"role": "elder"}, limit=5)
    children = await ctx.repos.list("users", where={"role": "child"}, limit=5)
    if not elders or not children:
        result = await seed_demo(ctx.repos)
        elders, children = [result["elder"]], [result["child"]]
    return {"elders": [_public_user(u) for u in elders],
            "children": [_public_user(u) for u in children]}


@router.get("/weather")
async def weather(city: str = "长沙", date_offset: str | None = None):
    """首页天气卡片（走 Weather Provider 接缝，mock/真实可换）。"""
    ctx = get_ctx()
    provider = ctx.registry.resolve("weather")
    return await provider.get(city, date_offset)


def _require_session_owner(session: dict, principal: Principal) -> None:
    """会话是**私域**：只有主人本人能读，别人一律当"会话不存在"。

    实测过的事故：这两条会话路由原先**完全无鉴权**，不带任何 Authorization 头
    打 ``/api/sessions/<sid>`` 就 200，events 数组里原样是老人那句
    "我血压 178/105，胸口有点闷"，``/events`` 还连 tool_call/tool_result 里的
    医院、路线、剂量一起给 —— 一条零凭证的健康数据出口。

    **给 404 不给 403** 是刻意的：403 等于告诉一个拿着别处捡到的 session_id 的
    陌生人"这个会话是存在的，只是不归你"，那本身就成了存在性探针。会话 id 虽是
    uuid，但前端 storage、日志、分享链接都可能把它带出去 —— 宁可让"别人的会话"
    和"不存在的会话"长得一模一样（这与 ``valid_session_id`` 的"会话不存在就给
    404"是同一口径；``/chat/history`` 那边给 403，是因为它另有一套前端契约，
    这里不复用）。

    没有 ``user_id`` 的老会话同样不放行：宁可让主人重开一段，也不能把它开给任何
    **碰巧**带上这个 id 的人。
    """
    if not session.get("user_id") or session["user_id"] != principal.id:
        raise HTTPException(404, "会话不存在")


@router.get("/sessions/{session_id}/events")
async def session_events(session_id: str, after_seq: int = 0,
                         principal: Principal = Depends(get_current_principal),
                         ctx: AppContext = Depends(get_ctx)):
    """轮询兜底 / 断线恢复 / 会话回放（append-only 唯一事实源）。

    ctx 走 ``Depends`` 而不是函数体里 ``get_ctx()``：后者绕过
    ``app.dependency_overrides``，测试里换不掉，于是 HTTP 级用例会打到真库
    （还会顺手拉一条 SSH 隧道）—— 这条路径是前端断线后唯一的兜底，必须能测。

    身份走 ``Depends(get_current_principal)``：前端 ``src/api/sse.js`` 的
    pollEvents/fetchEvents 用的是 fetch 且**自己挂了 Bearer 头**，所以加鉴权
    不会打断断线轮询。
    """
    session_id = valid_session_id(session_id)
    # 会话不存在必须给 404，别拿"200 + 空列表"糊过去：前端 SSE 断线后会退到这个
    # 接口轮询，空列表在它看来是"还没轮到我"，于是空转 60 轮 x 2 秒 = 两分钟，
    # 最后一句话都不说。老人看到的就是"处理中"转半天然后没了。
    session = await ctx.repos.get("sessions", session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    _require_session_owner(session, principal)     # 不是主人 → 同样 404，不露存在性
    rows = await ctx.event_log.after(session_id, after_seq)
    return {"items": rows, "latest_seq": rows[-1]["seq"] if rows else after_seq}


@router.get("/sessions/{session_id}")
async def session_detail(session_id: str,
                         principal: Principal = Depends(get_current_principal),
                         ctx: AppContext = Depends(get_ctx)):
    """会话详情 + 全量事件。**只有会话主人本人能读**（见 ``_require_session_owner``）。"""
    session_id = valid_session_id(session_id)
    session = await ctx.repos.get("sessions", session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    _require_session_owner(session, principal)
    events = await ctx.event_log.recent(session_id, limit=200)
    session["events"] = events
    return session
