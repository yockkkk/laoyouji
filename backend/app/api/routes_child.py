"""子女端聚合看板：待确认 + 今日用药提醒 + 进行中行程 + 最近告警。

看板是隐私分级的**主战场**：位置和健康数据都从这里出去。所以这里不直接吐库里
的行，一律先过 ``ctx.privacy`` 裁一遍 —— 老人把开关调到哪一档，子女就看到哪一档。
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from app.api.deps import get_ctx
from app.safety.privacy import filter_alert, filter_medication

router = APIRouter(prefix="/api/child", tags=["child"])


@router.get("/{child_id}/dashboard")
async def dashboard(child_id: str):
    ctx = get_ctx()
    child = await ctx.repos.get("users", child_id)
    if not child:
        raise HTTPException(404, "用户不存在")

    # 绑定的老人
    bindings = await ctx.repos.list("family_bindings", where={"child_id": child_id})
    elder_ids = [b["elder_id"] for b in bindings]
    elders = []
    for eid in elder_ids:
        e = await ctx.repos.get("users", eid)
        if e:
            elders.append(e)
    if not elders:
        return {"child": child, "elders": [], "pending_confirmations": [],
                "medications": [], "trips": [], "alerts": []}

    elder = elders[0]
    elder_id = elder["id"]

    # 隐私分级：先取授权，后面每一项出库数据都按它裁。
    # 没绑定关系 → denied()，位置和健康全 off（fail-closed 在身份那一层）。
    grant = await ctx.privacy.grant_for(elder_id, child_id)
    await ctx.privacy.audit(grant, "child_dashboard")

    pending = await ctx.confirmation.list_for_child(child_id, status="pending")

    # 今日用药
    meds = await ctx.repos.list(
        "medication_plans", where={"elder_id": elder_id, "active": True})
    today_logs = []
    for m in meds:
        rows = await ctx.repos.list(
            "medication_logs",
            where={"plan_id": m["id"], "scheduled_for": date.today().isoformat()})
        today_logs.extend(rows)

    # 进行中/最近的行程
    trips = await ctx.repos.list(
        "trips", where={"elder_id": elder_id}, order="-created_at", limit=5)

    # 最近守护告警（最近的异常 checkpoint）
    raw_alerts = []
    for trip in trips[:3]:
        checkpoints = await ctx.repos.list(
            "trip_checkpoints", where={"trip_id": trip["id"]}, order="-created_at",
            limit=10)
        raw_alerts.extend(
            {"trip_id": trip["id"], "purpose": trip.get("purpose"), **cp}
            for cp in checkpoints if cp.get("status") not in (None, "normal", "arrived")
        )
    alerts = [a for a in (filter_alert(grant, x) for x in raw_alerts) if a]

    medications = []
    for m in meds:
        item = {"drug": m["drug_name"], "dose": m.get("dose", ""),
                "times": m.get("times", []),
                "taken_today": {lg.get("scheduled_time"): lg.get("status")
                                for lg in today_logs if lg.get("plan_id") == m["id"]}}
        graded = filter_medication(grant, item)
        if graded:
            medications.append(graded)

    return {
        "child": {"id": child["id"], "name": child["name"]},
        "elder": {"id": elder_id, "name": elder["name"], "city": elder.get("city")},
        "privacy": grant.to_dict(),
        "pending_confirmations": pending,
        "medications": medications,
        "trips": [
            {"id": t["id"], "purpose": t.get("purpose"), "status": t.get("status"),
             "created_at": t.get("created_at")}
            for t in trips
        ],
        "alerts": alerts[:10],
    }
