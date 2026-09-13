"""健康 API：用药计划 CRUD + 服药打卡 + 左翼·身体核心（指标/分诊/慢病）。

文件里有两个子 router（用药、身体核心），末尾用一个**无前缀的外层 router** 把两者
一起挂上 —— main.py 里 include 的仍是这个文件模块级的 ``router``，所以新增一条
``/api/health`` 不用碰 main.py，也不会碰到别的并行工作流正在改的那个文件。
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_ctx, get_current_principal
from app.auth.security import Principal
from app.safety import health_rules as hr
from app.safety.privacy import filter_health_overview, filter_medication
from app.safety.risk_rules import GENERIC_DISCLAIMER
from app.tools.health_tools import (
    _active_conditions,
    _grouped_history,
    _trends_by_type,
    record_reading,
    triage_overview,
)

# 用药那一段沿用原来的前缀。改名成 medication_router 只是为了让末尾那层 include
# 能同时收下它和身体核心，四条既有路径一个字符都没动。
medication_router = APIRouter(prefix="/api/medications", tags=["health"])

# 打卡记录的 id 由 (计划, 日期, 时段) 直接算出来，同一格永远是同一个 id。
# 这样"重复打卡"在数据库层就撞主键，而不是靠先查后插那道会被并发穿过的缝。
_TAKEN_NS = uuid.UUID("6f9b1e2c-5a47-4d8e-9c31-7b0a2f4d8e10")

# 同进程内的抢跑还是要挡：老人手抖连点，两个请求同时走到"没查到 -> 插入"，
# 主键会让第二个失败，但那会在日志里留一串刺眼的 IntegrityError。锁在前面拦掉。
_taken_locks: dict[str, asyncio.Lock] = {}
_taken_locks_guard = asyncio.Lock()


def _log_id(plan_id: str, day: str, slot: str) -> str:
    return str(uuid.uuid5(_TAKEN_NS, f"{plan_id}|{day}|{slot}"))


async def _lock_for(key: str) -> asyncio.Lock:
    async with _taken_locks_guard:
        lock = _taken_locks.get(key)
        if lock is None:
            # 键里带日期，天然按天增长；到量了把没人拿着的清掉，别无限涨
            if len(_taken_locks) > 512:
                for k in [k for k, v in _taken_locks.items() if not v.locked()]:
                    del _taken_locks[k]
            lock = _taken_locks[key] = asyncio.Lock()
        return lock


def _is_active(plan: dict) -> bool:
    # 没有 active 字段的老数据按"在用"算，别让它凭空消失
    return plan.get("active", True) is not False


class MedicationIn(BaseModel):
    elder_id: str
    drug_name: str
    dose: str = ""
    times: list[str] = ["08:00"]
    notes: str = ""


async def _medication_summaries(ctx, plans: list[dict]) -> list[dict]:
    """用药计划 → ``privacy.filter_medication`` 认的形状（drug/dose/times/taken_today）。

    这个形状与子女看板 ``routes_child.dashboard`` 里那一份**逐字一致** —— 同一条
    隐私规则的两个出口必须喂同一种输入，否则同一个档位在两个屏幕上会裁出两种
    结果（那边给药名、这边不给，老人就会以为自己调了个没用的开关）。
    """
    today = date.today().isoformat()
    items = []
    for p in plans:
        logs = await ctx.repos.list(
            "medication_logs",
            where={"plan_id": p["id"], "scheduled_for": today})
        items.append({
            "drug": p.get("drug_name", ""),
            "dose": p.get("dose", ""),
            "times": list(p.get("times") or []),
            "taken_today": {lg.get("scheduled_time"): lg.get("status")
                            for lg in logs},
        })
    return items


@medication_router.get("")
async def list_medications(
    elder_id: str,
    with_logs: bool = False,
    principal: Principal = Depends(get_current_principal),
):
    """用药列表。**本人全量；绑定子女按 privacy 档裁剪；其余 403。**

    这条路由原先**无鉴权**：换一个 ``?elder_id=`` 不打任何头就 200，直出任意老人的
    药名/剂量/服药时间。``filter_medication`` 的 docstring 写着"药名才是敏感的那
    一半"—— 这条接口本来就是它存在的理由，却一直没接上。
    """
    ctx = get_ctx()
    plans = await ctx.repos.list(
        "medication_plans", where={"elder_id": elder_id}, order="-created_at")
    plans = [p for p in plans if _is_active(p)]

    if principal.id == elder_id:
        # 本人：老人端"我的用药"读的就是它，全量、不裁剪。
        if not with_logs:
            return {"items": plans}
        today = date.today().isoformat()
        out = []
        for p in plans:
            logs = await ctx.repos.list(
                "medication_logs",
                where={"plan_id": p["id"], "scheduled_for": today})
            out.append({**p, "logs": logs})
        return {"items": out}

    # 不是本人：只可能是绑定的子女。不是子女角色就是根本没有这层关系 → 403。
    if principal.role != "child":
        raise HTTPException(403, "无权访问该老人的用药数据")

    # grant_for 对没有 family_bindings 的一对直接给 denied（health_off），
    # filter_medication 逐条返回 None，于是这里自然得到空列表 —— **降级是数据
    # 变形，不是报错**：子女端不该看到红叉，该看到"这项没开放"。与
    # /api/health/overview 同一口径。
    grant = await ctx.privacy.grant_for(elder_id, principal.id)
    await ctx.privacy.audit(grant, "medications_api")   # 老人端"谁看过我"要用
    summaries = await _medication_summaries(ctx, plans)
    return {"items": [g for g in (filter_medication(grant, s) for s in summaries) if g]}


@medication_router.post("")
async def create_medication(
    body: MedicationIn,
    principal: Principal = Depends(get_current_principal),
):
    """新增用药计划。**只允许本人** —— 替别人写是根本没有这个权利。

    实测过的越级：不加头 ``POST`` 就能往任意老人的 medication_plans 里插一行
    （"真替别人入库"）。归属先于内容校验：药名空不空是你填得对不对，
    替别人建方案是另一回事。
    """
    _require_own_elder_id(principal, body.elder_id)
    ctx = get_ctx()
    times = [t.strip() for t in body.times if t and t.strip()]
    if not times:
        raise HTTPException(400, "请至少填一个服药时间，例如 08:00")
    row = await ctx.repos.insert("medication_plans", {
        "elder_id": body.elder_id, "drug_name": body.drug_name.strip(),
        "dose": body.dose, "times": times,
        "notes": body.notes or "医生已开，遵医嘱服用", "active": True,
    })
    return row


@medication_router.delete("/{plan_id}")
async def delete_medication(
    plan_id: str,
    principal: Principal = Depends(get_current_principal),
):
    """停用一条用药计划（只允许本人）。

    做的是软删除：病历性质的数据不该真删，子女端和审计还要看得见历史打卡。
    列表接口会把 active=false 的过滤掉，所以老人端看着就是"没了"。
    """
    ctx = get_ctx()
    plan = await ctx.repos.get("medication_plans", plan_id)
    if not plan:
        raise HTTPException(404, "用药计划不存在")
    if plan.get("elder_id") != principal.id:
        # 停别人的药是**改变他吃不吃**，比读他的药名更重，一律 403。
        raise HTTPException(403, "无权代他人停用用药计划")
    if not _is_active(plan):
        return plan  # 已经停用过了，重复请求当成功（前端可能点了两下）
    updated = await ctx.repos.update("medication_plans", plan_id, {
        "active": False,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    })
    if updated is None:
        raise HTTPException(404, "用药计划不存在")
    return updated


@medication_router.post("/{plan_id}/taken")
async def mark_taken(
    plan_id: str,
    scheduled_time: str = "",
    principal: Principal = Depends(get_current_principal),
):
    """服药打卡（只允许本人）。替别人打卡等于伪造他的服药记录。"""
    ctx = get_ctx()
    plan = await ctx.repos.get("medication_plans", plan_id)
    if not plan:
        raise HTTPException(404, "用药计划不存在")
    if plan.get("elder_id") != principal.id:
        raise HTTPException(403, "无权代他人记录服药")

    today = date.today().isoformat()
    slot = scheduled_time or (plan.get("times") or [""])[0]
    log_id = _log_id(plan_id, today, slot)

    async with await _lock_for(log_id):
        existing = await ctx.repos.get("medication_logs", log_id)
        if existing is None:
            # 兜早期数据：那时的 id 是随机 uuid，按 id 查不到，得按字段找一遍
            existing = await ctx.repos.find_one("medication_logs", {
                "plan_id": plan_id, "scheduled_for": today, "scheduled_time": slot,
            })
        if existing:
            if existing.get("status") == "taken":
                return existing  # 已经吃过了，幂等返回，不再写一条
            return await ctx.repos.update("medication_logs", existing["id"], {
                "status": "taken",
                "taken_at": datetime.now(timezone.utc).isoformat(),
            })
        return await ctx.repos.insert("medication_logs", {
            "id": log_id,
            "plan_id": plan_id, "scheduled_for": today,
            "scheduled_time": slot,
            "status": "taken", "taken_at": datetime.now(timezone.utc).isoformat(),
        })


# ---------------------------------------------------------------- 左翼·身体核心（REST）
# 这一段的取数与分诊**一行判断都不自己写**：history/conditions/分诊全部转手给
# app/tools/health_tools.py 里那四个已经抽好的函数。老人对着手机点"记血压"和
# 跟康乐说一句"血压 178/105"，必须落在同一段代码上 —— 各写一遍的话，同一个数
# 会在聊天里是"建议就医"、在页面上是别的档，而这种不一致比没有页面更糟。
health_router = APIRouter(prefix="/api/health", tags=["health"])


class ReadingIn(BaseModel):
    elder_id: str
    metric_type: str
    # 数值放宽成 float | str：coerce_reading 认 "178/105" 这种整串（health_rules._num），
    # 前端只发两个数字，但没必要把聊天那边已经容下来的写法在 REST 上又堵回去。
    value: float | str | None = None
    systolic: float | str | None = None
    diastolic: float | str | None = None
    context: str = ""
    measured_at: str = ""
    note: str = ""
    source: str = "手动记录"


class ConditionIn(BaseModel):
    elder_id: str
    name: str
    diagnosed_at: str = ""
    severity: str = ""
    notes: str = ""


async def _health_grant(ctx, principal: Principal, elder_id: str):
    """三个**读**接口共用的可见范围判定：只有两种人配看老人的健康数据。

    - 老人本人（``principal.id == elder_id`` 且 ``role == "elder"``）→ 返回 ``None``，
      意思是"全量、不裁剪"。老人端 ``pages/elder/health.vue`` 读的就是这几个接口，
      读的是自己的数据，这条路必须留。
    - 子女（``role == "child"``）→ ``grant_for`` 拿这一对（老人, 子女）此刻的档。
      没有绑定关系时它返回 ``denied()``（health_off），照样往下走 —— **降级是数据
      变形不是报错**，这是 privacy.py 模块头的第 1 条设计前提。子女端自己在
      summary/off 两档都有中性文案，后端不该替它编一句宽心话。
    - 其余（不是本人、也不是子女）→ 403。这不是"少给点"的问题，是根本没有这层关系。

    子女这一支顺带落一条 audit：老人端"谁看过我"要用它。本人自读不记 ——
    审计记的是"别人看了我什么"。
    """
    if principal.id == elder_id and principal.role == "elder":
        return None
    if principal.role != "child":
        raise HTTPException(403, "无权访问该老人的健康数据")
    grant = await ctx.privacy.grant_for(elder_id, principal.id)
    await ctx.privacy.audit(grant, "health_api")
    return grant


def _require_own_elder_id(principal: Principal, elder_id: str) -> None:
    """写接口的归属校验：**看 id，不看 role**。

    一个 ``role=child`` 的用户写自己的 ``elder_id`` 是允许的（tests 里就有这么用的），
    所以这里不能写成"必须是 elder 角色"。要挡的只有一件事：替**别人**写。
    """
    if principal.id != elder_id:
        raise HTTPException(403, "无权代他人登记健康数据")


@health_router.get("/metrics")
async def list_metrics():
    """记指标表单的选项来源 —— 指标表跟着 health_rules 走，前端不另抄一份。

    这一条**保持公开**：它是静态选项表（label/unit/normal），不含任何人的数据。
    """
    return {"items": [{"metric_type": k, **v} for k, v in hr.METRICS.items()]}


@health_router.get("/readings")
async def list_readings(
    elder_id: str,
    window: int = 7,
    principal: Principal = Depends(get_current_principal),
):
    """按 metric_type 分组的近 window 次读数 + 趋势 + 每点档位（VitalTrend 画图用）。"""
    ctx = get_ctx()
    grant = await _health_grant(ctx, principal, elder_id)
    if grant is not None and not grant.allows_health("full"):
        # summary/off 档：读数每条都带 "178/105 mmHg"，属"健康明细"。**连出库都不出**
        # —— 取回来再让前端藏，等于把闸门开在客户端。子女端在 summary 档下本来也
        # 不发这个请求（只有 full 档才发），这里是那道闸门的后端一侧。
        return {"items": [], "window": window}
    grouped = await _grouped_history(ctx.repos, elder_id, window=window)
    trends = _trends_by_type(grouped)          # 与 triage_overview 同一段趋势算法
    items = []
    for mtype in hr.METRICS:                   # 固定顺序：页面每行位置不跳
        rows = grouped.get(mtype)
        if not rows:
            continue
        points = []
        for r in rows:
            level, _ = hr.classify_reading(
                mtype, value=r.get("value"), systolic=r.get("systolic"),
                diastolic=r.get("diastolic"), context=r.get("context"))
            points.append({
                "measured_at": r.get("measured_at") or r.get("created_at") or "",
                "value": hr.metric_scalar(r),   # 血压取收缩压，其余取 value
                "display": hr.format_reading({**r, "metric_type": mtype}),
                "level": level,
            })
        items.append({
            "metric_type": mtype, "label": hr.metric_label(mtype),
            "unit": hr.metric_unit(mtype), "normal": hr.METRICS[mtype]["normal"],
            "points": points, "trend": trends.get(mtype, "平稳"),
            "display": points[-1]["display"], "level": points[-1]["level"],
        })
    return {"items": items, "window": window}


@health_router.post("/readings")
async def create_reading(
    body: ReadingIn,
    principal: Principal = Depends(get_current_principal),
):
    """记一条指标。**走 record_reading**：校验 → 分诊 → 入库都在它里面。"""
    elder_id = (body.elder_id or "").strip()
    if not elder_id:
        raise HTTPException(400, "缺少老人标识")
    # 登记的是"谁的身体"。归属先于内容校验：名字空不空是你自己填得对不对，
    # 而替别人登记是根本没有这个权利。
    _require_own_elder_id(principal, elder_id)
    result = await record_reading(
        get_ctx().repos, elder_id, body.model_dump(exclude={"elder_id"}))
    if not result.get("ok"):
        # 没记上是请求的问题（血压缺一半、指标不认识、数字填不进），不是 200。
        # 200 会让前端把一条根本没入库的数当成功弹给老人看。
        raise HTTPException(400, result.get("summary") or "这条记录没记上")
    return {**result["data"], "disclaimer": GENERIC_DISCLAIMER}


@health_router.get("/overview")
async def health_overview(
    elder_id: str,
    symptom: str = "",
    principal: Principal = Depends(get_current_principal),
):
    """分诊概览：分组历史 + 慢病（+可选症状）→ 一次完整分诊，与 assess_health 同源。

    子女读到的是**裁剪后**的概览（见 ``privacy.filter_health_overview``）：默认的
    summary 档只给档位和一句不含数的说明。不裁的话，headline 里那句
    "血压 178/105，中重度偏高……"会把数值原样印在子女屏幕上。
    """
    ctx = get_ctx()
    grant = await _health_grant(ctx, principal, elder_id)
    grouped = await _grouped_history(ctx.repos, elder_id)
    conditions = await _active_conditions(ctx.repos, elder_id)
    overview = triage_overview(grouped, conditions, symptom=symptom or None)
    if grant is not None:                      # 本人（None）原样全量出
        overview = filter_health_overview(grant, overview)
    return {**overview, "disclaimer": GENERIC_DISCLAIMER}   # R4：裁剪与否都要带


@health_router.get("/conditions")
async def list_conditions(
    elder_id: str,
    principal: Principal = Depends(get_current_principal),
):
    ctx = get_ctx()
    grant = await _health_grant(ctx, principal, elder_id)
    if grant is not None and not grant.allows_health("full"):
        # 慢病名单属病历：summary 档只说"有没有"，不给是哪几种病
        return {"items": []}
    return {"items": await _active_conditions(ctx.repos, elder_id)}


@health_router.post("/conditions")
async def create_condition(
    body: ConditionIn,
    principal: Principal = Depends(get_current_principal),
):
    """登记慢病。字段与聊天侧的 add_condition（health_tools.py）保持一致。

    只记不判断：这条病是**医生说过的**，康乐负责记下来，不负责下结论（红线 R1）。
    """
    elder_id = (body.elder_id or "").strip()
    if not elder_id:
        raise HTTPException(400, "缺少老人标识")
    _require_own_elder_id(principal, elder_id)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(400, "请填上慢性病名称")
    return await get_ctx().repos.insert("health_conditions", {
        "elder_id": elder_id, "name": name,
        "diagnosed_at": body.diagnosed_at or "", "severity": body.severity or "",
        "notes": body.notes or "", "active": True,
    })


# 无前缀外层：main.py 照旧 include routes_health.router，两个前缀同时挂上。
# 放在文件最末是因为要等两个子 router 都定义完才 include 得进来。
router = APIRouter()
router.include_router(medication_router)
router.include_router(health_router)
