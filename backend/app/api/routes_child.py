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
from app.safety.privacy import filter_alert, filter_medication, filter_checkpoint
from app.shared.plan_helpers import extract_destination, list_trips_for_display
from app.api.routes_guardian import lookup_coords

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

    # 隐私分级：老人在"我的位置/我的健康"里调到哪一档，子女就看到哪一档。
    # 后端不替他改答案 —— 存了不用的开关比没有开关更糟。子女看到
    # "老人未开放此项"占位时，正确解法是引导老人授权，不是在看板出口架空分级。
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

    # 进行中/最近的行程与计划（只读折叠展示，绝不在这个 GET 里删库：
    # 前端每 5 秒轮询一次，删就是永久丢用户数据）
    trips = await list_trips_for_display(ctx.repos, elder_id)

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

    # 查找长辈当前最新的实时位置（无论哪个行程）
    latest_location = None
    recent_trips = await ctx.repos.list(
        "trips", where={"elder_id": elder_id}, order="-created_at", limit=10
    )
    # 也把没有挂 elder_id 的活跃遗留行程纳入检索并回填
    unassigned_trips = await ctx.repos.list(
        "trips", where={"elder_id": None}, order="-created_at", limit=5
    )
    for ut in unassigned_trips:
        await ctx.repos.update("trips", ut["id"], {"elder_id": elder_id})
        recent_trips.append(ut)

    for tr in recent_trips:
        cps = await ctx.repos.list(
            "trip_checkpoints", where={"trip_id": tr["id"]}, order="-created_at", limit=1
        )
        if cps:
            cp = cps[0]
            if (cp.get("lng") is None or cp.get("lat") is None) and cp.get("location"):
                lng, lat = lookup_coords(cp["location"])
                if lng is not None and lat is not None:
                    cp["lng"], cp["lat"] = lng, lat

            filtered_cp = filter_checkpoint(grant, cp)
            if filtered_cp:
                latest_location = {
                    "trip_id": tr["id"],
                    "purpose": tr.get("purpose") or "出行行程",
                    "trip_status": tr.get("status"),
                    "destination": extract_destination(tr),
                    "is_off_route": cp.get("status") == "off_route",
                    **filtered_cp,
                }
                break

    # 家人通知中心消息
    notifications = await ctx.repos.list(
        "notifications", where={"user_id": child_id}, order="-created_at", limit=20
    )

    return {
        "child": {"id": child["id"], "name": child["name"]},
        "elder": {"id": elder_id, "name": elder["name"], "city": elder.get("city")},
        "privacy": grant.to_dict(),
        "latest_location": latest_location,
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
        trips = await list_trips_for_display(ctx.repos, eid)
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
