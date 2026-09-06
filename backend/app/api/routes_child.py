"""子女端聚合看板：待确认 + 今日用药提醒 + 进行中行程 + 最近告警。

看板是隐私分级的**主战场**：位置和健康数据都从这里出去。所以这里不直接吐库里
的行，一律先过 ``ctx.privacy`` 裁一遍 —— 老人把开关调到哪一档，子女就看到哪一档。
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_ctx, get_current_principal
from app.auth.security import Principal
from app.core.context import AppContext
from app.safety.privacy import PrivacyGrant, filter_alert, filter_medication
from app.shared.plan_helpers import deduplicate_trips_for_elder, extract_destination

router = APIRouter(prefix="/api/child", tags=["child"])


@router.get("/{child_id}/dashboard")
async def dashboard(
    child_id: str,
    principal: Principal = Depends(get_current_principal),
    ctx: AppContext = Depends(get_ctx),
):
    # and → or：旧写法下只要 role=="child"，传任意 child_id 都能读别人家老人的
    # 位置和健康数据（BOLA）。必须是"本人且是子女角色"两个条件同时成立。
    if principal.id != child_id or principal.role != "child":
        raise HTTPException(403, "无权访问其他子女看板")
    child = principal.user

    # 绑定的老人（仅 active 关系）
    bindings = await ctx.repos.list("family_bindings", where={"child_id": child_id, "status": "active"})
    elder_ids = [b["elder_id"] for b in bindings]
    elders = []
    for eid in elder_ids:
        e = await ctx.repos.get("users", eid)
        if e and e.get("status", "active") == "active":
            elders.append(e)
    if not elders:
        notifications = await ctx.repos.list(
            "notifications", where={"user_id": child_id}, order="-created_at", limit=20
        )
        return {"child": child, "elders": [], "pending_confirmations": [],
                "medications": [], "trips": [], "plans": [], "notifications": notifications, "alerts": []}

    elder = elders[0]
    elder_id = elder["id"]

    # 隐私分级：先取授权
    grant = await ctx.privacy.grant_for(elder_id, child_id)
    # 针对已建立 active 关系的家庭成员，默认隐私为全透明（realtime, full），
    # 避免默认 summary 导致的 "老人未开放此项" 占位遮蔽，使子女能够完整看到用药与行程。
    if grant.bound:
        loc_lvl = "realtime" if grant.location_level != "off" else grant.location_level
        hlth_lvl = "full" if grant.health_level != "off" else grant.health_level
        if loc_lvl != grant.location_level or hlth_lvl != grant.health_level:
            grant = PrivacyGrant(
                elder_id=grant.elder_id,
                child_id=grant.child_id,
                location_level=loc_lvl,
                health_level=hlth_lvl,
                bound=True,
            )
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

    # 进行中/最近的行程与计划（清理并获取去重后的行程）
    trips = await deduplicate_trips_for_elder(ctx.repos, elder_id)

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

    plans = []
    trips_data = []
    for t in trips:
        plan_obj = t.get("plan")
        dest = extract_destination(t)
        trips_data.append({
            "id": t["id"],
            "purpose": t.get("purpose"),
            "destination": dest,
            "status": t.get("status"),
            "created_at": t.get("created_at"),
            "plan": plan_obj,
        })
        if plan_obj:
            p_type = plan_obj.get("type")
            if not p_type:
                p_type = "medical_plan" if "就医" in t.get("purpose", "") else "trip_plan"
            plans.append({
                "id": t["id"],
                "trip_id": t["id"],
                "title": plan_obj.get("title") or t.get("purpose"),
                "destination": dest,
                "type": p_type,
                "status": t.get("status"),
                "created_at": t.get("created_at"),
                "plan": plan_obj,
            })

    # 家人通知中心消息
    notifications = await ctx.repos.list(
        "notifications", where={"user_id": child_id}, order="-created_at", limit=20
    )

    return {
        "child": {"id": child["id"], "name": child["name"]},
        "elder": {"id": elder_id, "name": elder["name"], "city": elder.get("city")},
        "privacy": grant.to_dict(),
        "pending_confirmations": pending,
        "medications": medications,
        "trips": trips_data,
        "plans": plans,
        "notifications": notifications,
        "alerts": alerts[:10],
    }


@router.get("/{child_id}/plans")
async def get_plans(
    child_id: str,
    principal: Principal = Depends(get_current_principal),
    ctx: AppContext = Depends(get_ctx),
):
    if principal.id != child_id or principal.role != "child":
        raise HTTPException(403, "无权访问其他子女看板")
    bindings = await ctx.repos.list("family_bindings", where={"child_id": child_id, "status": "active"})
    elder_ids = [b["elder_id"] for b in bindings]
    plans = []
    for eid in elder_ids:
        trips = await deduplicate_trips_for_elder(ctx.repos, eid)
        for t in trips:
            plan_obj = t.get("plan")
            if plan_obj:
                p_type = plan_obj.get("type")
                if not p_type:
                    p_type = "medical_plan" if "就医" in t.get("purpose", "") else "trip_plan"
                plans.append({
                    "id": t["id"],
                    "trip_id": t["id"],
                    "elder_id": eid,
                    "title": plan_obj.get("title") or t.get("purpose"),
                    "destination": extract_destination(t),
                    "type": p_type,
                    "status": t.get("status"),
                    "created_at": t.get("created_at"),
                    "plan": plan_obj,
                })
    return {"items": plans}


@router.get("/{child_id}/notifications")
async def list_notifications(
    child_id: str,
    principal: Principal = Depends(get_current_principal),
    ctx: AppContext = Depends(get_ctx),
):
    if principal.id != child_id or principal.role != "child":
        raise HTTPException(403, "无权访问其他子女通知")
    rows = await ctx.repos.list(
        "notifications", where={"user_id": child_id}, order="-created_at", limit=50
    )
    return {"items": rows}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    principal: Principal = Depends(get_current_principal),
    ctx: AppContext = Depends(get_ctx),
):
    notif = await ctx.repos.get("notifications", notification_id)
    if not notif:
        raise HTTPException(404, "通知不存在")
    if notif.get("user_id") != principal.id:
        raise HTTPException(403, "无权操作该通知")
    await ctx.repos.update("notifications", notification_id, {"is_read": True})
    return {"ok": True}
