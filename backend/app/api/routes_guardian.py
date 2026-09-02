"""行程守护 API：行程详情 / 位置上报（演示模拟）→ 偏航判定与告警。"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import get_ctx
from app.core.events import durable_type
from app.core.sse import SSEEvent
from app.safety.privacy import filter_checkpoint

router = APIRouter(prefix="/api/trips", tags=["guardian"])

# 演示行程的预期途经点（与 MockMapProvider 的折线一致）
_EXPECTED_POINTS = ["南京南站", "济南西站", "北京南站", "积水潭医院"]


class CheckpointIn(BaseModel):
    location: str
    lng: float | None = None
    lat: float | None = None


@router.get("/{trip_id}")
async def trip_detail(trip_id: str, child_id: str | None = None):
    """行程详情。

    ``child_id`` 在场即"子女在看"，位置轨迹要按老人的授权档裁一遍；
    不带就是老人看自己的行程，原样返回 —— 自己的数据没有越级问题。
    """
    ctx = get_ctx()
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    checkpoints = await ctx.repos.list(
        "trip_checkpoints", where={"trip_id": trip_id}, order="created_at")

    if not child_id:
        return {"trip": trip, "checkpoints": checkpoints, "precision": "owner"}

    grant = await ctx.privacy.grant_for(trip.get("elder_id") or "", child_id)
    await ctx.privacy.audit(grant, "trip_detail")
    graded = [c for c in (filter_checkpoint(grant, x) for x in checkpoints) if c]
    return {"trip": trip, "checkpoints": graded,
            "precision": "off" if grant.location_off else grant.location_level,
            "privacy": grant.to_dict()}


@router.post("/{trip_id}/checkpoints")
async def report_checkpoint(trip_id: str, body: CheckpointIn):
    """模拟位置上报（演示用）：判定 normal / off_route / arrived，异常即告警子女端。"""
    return await process_checkpoint(get_ctx(), trip_id, body)


async def process_checkpoint(ctx, trip_id: str, body: CheckpointIn):
    """守护判定的核心逻辑（API 路由与冒烟脚本共用）。"""
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")

    if trip.get("status") == "planned":
        await ctx.repos.update("trips", trip_id, {
            "status": "ongoing", "started_at": _now()})

    # 守护判定（演示规则）：地点在预期途经点上 → normal/arrived；否则 off_route
    status, note = "normal", ""
    if any(p in body.location for p in _EXPECTED_POINTS):
        if "医院" in body.location:
            status = "arrived"
            note = "已安全到达目的地"
            await ctx.repos.update("trips", trip_id, {
                "status": "completed", "ended_at": _now()})
        else:
            note = f"途经 {body.location}，一切正常"
    else:
        status = "off_route"
        note = f"位置偏离规划路线：{body.location}，请关注"

    cp = await ctx.repos.insert("trip_checkpoints", {
        "trip_id": trip_id, "location": body.location,
        "lng": body.lng, "lat": body.lat, "status": status, "note": note,
    })

    alert_sent = False
    if status == "off_route":
        # 告警写会话日志（子女端 dashboard 轮询可见）+ 老人端广播
        elder_id = trip.get("elder_id")
        binding = await ctx.repos.find_one(
            "family_bindings", {"elder_id": elder_id})
        sessions = await ctx.repos.list(
            "sessions", where={"user_id": elder_id}, order="-created_at", limit=1)
        session_id = sessions[0]["id"] if sessions else None
        if session_id:
            payload = {
                "trip_id": trip_id, "location": body.location,
                "note": note, "elder": elder_id,
            }
            await ctx.event_log.hydrate(session_id)
            ctx.event_log.append(session_id, elder_id,
                                 durable_type("guardian_alert"), payload)
            ctx.broadcast.push_sync(session_id, SSEEvent("guardian_alert", payload))
            await ctx.event_log.flush(session_id)
        await ctx.repos.insert("audit_log", {
            "actor_id": None, "action": "guardian_alert",
            "target": trip_id, "detail": {"location": body.location},
        })
        alert_sent = True

    return {"checkpoint": cp, "status": status, "alert_sent": alert_sent}


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
