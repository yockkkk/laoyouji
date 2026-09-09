"""行程守护 API：行程详情 / 位置上报（真实高德联动）→ 偏航判定与告警。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import get_ctx
from app.core.events import durable_type
from app.core.sse import SSEEvent
from app.providers.external.amap_service import (
    KNOWN_LANDMARKS,
    amap_client,
    haversine_distance_m,
    min_distance_to_corridor_m,
)
from app.safety.privacy import filter_checkpoint
from app.shared.plan_helpers import extract_destination

router = APIRouter(prefix="/api/trips", tags=["guardian"])

# 演示行程的预期途经点（与 MockMapProvider / 高德路线规划保持一致）
_EXPECTED_POINTS = [
    "南京南站", "济南西站", "北京南站", "上海虹桥站", "杭州东站", "苏州站",
    "积水潭医院", "鼓楼医院", "南京鼓楼医院", "上海市第六人民医院", "杭州市第一人民医院", "苏州大学附属第一医院",
]

# 标准途经点经纬度（高德 GCJ-02 坐标系）
LOCATION_COORDS: dict[str, tuple[float, float]] = {
    **KNOWN_LANDMARKS,
    "家": (118.7841, 32.0645),
    "南京": (118.7841, 32.0645),
    "南京鼓楼区": (118.7732, 32.0618),
    "南京南站": (118.7981, 31.9696),
    "济南西站": (116.8974, 36.6669),
    "北京南站": (116.3789, 39.8652),
    "积水潭医院": (116.3748, 39.9485),
    "北京积水潭医院": (116.3748, 39.9485),
    "漫心酒店": (116.3725, 39.9472),
}


def lookup_coords(location: str) -> tuple[float | None, float | None]:
    if not location:
        return None, None
    if location in LOCATION_COORDS:
        return LOCATION_COORDS[location]
    for key, (lng, lat) in sorted(LOCATION_COORDS.items(), key=lambda x: len(x[0]), reverse=True):
        if key in location:
            return lng, lat
    return None, None


def resolve_trip_origin(trip: dict[str, Any]) -> str:
    """提取行程的起点（优先计划书内的出发地，默认回退至长辈南京住址）。"""
    if trip.get("origin"):
        return str(trip["origin"]).strip()
    plan_obj = trip.get("plan") or {}
    if isinstance(plan_obj, str):
        try:
            plan_obj = json.loads(plan_obj)
        except Exception:
            plan_obj = {}
    if isinstance(plan_obj, dict):
        pages = plan_obj.get("pages") or []
        for p in pages:
            if isinstance(p, dict):
                for r in p.get("rows") or []:
                    if isinstance(r, dict) and r.get("label") in ("出发", "起点", "出发地", "出发站") and r.get("value"):
                        v = str(r.get("value")).strip()
                        if v:
                            return v
    plan_title = plan_obj.get("title") if isinstance(plan_obj, dict) else ""
    purpose = (trip.get("purpose") or plan_title or "").strip()
    if "北京" in purpose and ("返程" in purpose or "回南京" in purpose or "回家" in purpose):
        return "北京南站"
    if "上海" in purpose and ("返程" in purpose or "回南京" in purpose or "回家" in purpose):
        return "上海虹桥站"
    if "杭州" in purpose and ("返程" in purpose or "回南京" in purpose or "回家" in purpose):
        return "杭州东站"
    if "苏州" in purpose and ("返程" in purpose or "回南京" in purpose or "回家" in purpose):
        return "苏州站"
    return "家（南京鼓楼区）"


def resolve_trip_destination(trip: dict[str, Any]) -> str:
    """提取行程的具体目的地（优先具体医院/地标，防止被地级市名截断）。"""
    plan_obj = trip.get("plan") or {}
    if isinstance(plan_obj, str):
        try:
            plan_obj = json.loads(plan_obj)
        except Exception:
            plan_obj = {}
    plan_title = plan_obj.get("title") if isinstance(plan_obj, dict) else ""
    purpose = (trip.get("purpose") or plan_title or "").strip()
    if "返程" in purpose or "回家" in purpose or "回宁" in purpose or "回南京" in purpose:
        return "家（南京鼓楼区）"
    if trip.get("destination"):
        return str(trip["destination"]).strip()
    if isinstance(plan_obj, dict):
        pages = plan_obj.get("pages") or []
        for p in pages:
            if isinstance(p, dict):
                for r in p.get("rows") or []:
                    if isinstance(r, dict) and r.get("label") in ("医院", "到达", "目的地", "到达站") and r.get("value"):
                        v = str(r.get("value")).strip()
                        if v and "站" not in v:
                            return v
    for spot in sorted(LOCATION_COORDS.keys(), key=len, reverse=True):
        if spot in ("家", "南京", "北京", "上海", "杭州", "苏州", "家（南京鼓楼区）"):
            continue
        if spot in purpose:
            return spot
    city = extract_destination(trip)
    if city and ("北京" in city or "北京" in purpose):
        return "北京积水潭医院"
    if city and ("鼓楼" in purpose or "南京" in city):
        return "南京鼓楼医院"
    if city and ("上海" in city or "第六人民" in purpose):
        return "上海市第六人民医院"
    if city and ("杭州" in city or "浙大" in purpose or "西湖" in purpose):
        return "杭州市第一人民医院"
    if city and ("苏州" in city or "苏大" in purpose):
        return "苏州大学附属第一医院"
    return city or purpose or "北京积水潭医院"


class CheckpointIn(BaseModel):
    location: str = ""
    lng: float | None = None
    lat: float | None = None


class QuickTripIn(BaseModel):
    origin: str = "家（南京鼓楼区）"
    destination: str = "北京积水潭医院"
    elder_id: str | None = None
    purpose: str | None = None


@router.get("")
async def list_trips(elder_id: str | None = None, limit: int = 20):
    """查询行程列表，支持子女端行程选择器切换多行程与历史行程。"""
    ctx = get_ctx()
    where = {"elder_id": elder_id} if elder_id else {}
    trips = await ctx.repos.list("trips", where=where, order="-created_at", limit=limit)
    for t in trips:
        cps = await ctx.repos.list("trip_checkpoints", where={"trip_id": t["id"]}, order="-created_at", limit=1)
        if cps:
            t["has_checkpoints"] = True
            t["latest_location"] = cps[0].get("location")
            t["latest_checkpoint_at"] = cps[0].get("created_at")
        else:
            t["has_checkpoints"] = False
    return {"trips": trips, "count": len(trips)}


@router.get("/route/direct")
async def direct_route(origin: str = "家（南京鼓楼区）", destination: str = "北京积水潭医院"):
    """直接通过起点与目的地获取高德规划轨迹、途经站点与换乘步骤。"""
    route_data = await amap_client.plan_route(origin, destination)
    return {"ok": True, "origin": origin, "destination": destination, "route": route_data}


@router.post("/quick")
async def create_quick_trip(body: QuickTripIn):
    """长辈进入路线规划时若无现存 trip_id，自动建立关联行程，打通定时上报闭环。"""
    ctx = get_ctx()
    elder_id = body.elder_id
    if not elder_id:
        elders = await ctx.repos.list("users", where={"role": "elder", "status": "active"}, limit=1)
        if elders:
            elder_id = elders[0]["id"]
    trip = await ctx.repos.insert("trips", {
        "elder_id": elder_id,
        "purpose": body.purpose or f"前往{body.destination}就医出行",
        "status": "ongoing",
        "origin": body.origin,
        "destination": body.destination,
        "started_at": _now(),
    })
    return {"ok": True, "trip": trip}


@router.get("/{trip_id}")
async def trip_detail(trip_id: str, child_id: str | None = None):
    """行程详情（含高德路径规划真实轨迹数据与偏航状态）。"""
    ctx = get_ctx()
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")

    # 自动修复遗留行程缺失的 elder_id，确保隐私权限可正常关联
    elder_id = trip.get("elder_id")
    if not elder_id:
        elders = await ctx.repos.list("users", where={"role": "elder", "status": "active"}, limit=1)
        if elders:
            elder_id = elders[0]["id"]
            await ctx.repos.update("trips", trip_id, {"elder_id": elder_id})
            trip["elder_id"] = elder_id

    checkpoints = await ctx.repos.list(
        "trip_checkpoints", where={"trip_id": trip_id}, order="created_at"
    )

    # 补齐经纬度坐标（若此前历史数据未带 lng/lat）
    for cp in checkpoints:
        if (cp.get("lng") is None or cp.get("lat") is None) and cp.get("location"):
            lng, lat = lookup_coords(cp["location"])
            if lng is not None and lat is not None:
                cp["lng"], cp["lat"] = lng, lat

    # 计算该行程对应的高德真实规划轨迹
    dest_name = resolve_trip_destination(trip)
    origin_name = resolve_trip_origin(trip)
    route_data = await amap_client.plan_route(origin_name, dest_name)

    if not child_id:
        return {
            "trip": trip,
            "checkpoints": checkpoints,
            "precision": "owner",
            "route": route_data,
        }

    grant = await ctx.privacy.grant_for(elder_id or "", child_id)
    await ctx.privacy.audit(grant, "trip_detail")
    graded = [c for c in (filter_checkpoint(grant, x) for x in checkpoints) if c]
    return {
        "trip": trip,
        "checkpoints": graded,
        "precision": "off" if grant.location_off else grant.location_level,
        "privacy": grant.to_dict(),
        "route": route_data,
    }


@router.get("/{trip_id}/route")
async def trip_route(trip_id: str):
    """直接获取行程的高德 Web API 2.0 规划航迹、站点与步骤。"""
    ctx = get_ctx()
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    dest_name = resolve_trip_destination(trip)
    origin_name = resolve_trip_origin(trip)
    route_data = await amap_client.plan_route(origin_name, dest_name)
    return {"ok": True, "trip_id": trip_id, "route": route_data}


@router.get("/{trip_id}/realtime")
async def trip_realtime(trip_id: str, child_id: str | None = None):
    """子女端 10 秒实时轮询接口：获取长辈当前最新位置与偏航警报状态。"""
    ctx = get_ctx()
    if trip_id == "latest":
        trips = await ctx.repos.list("trips", order="-created_at", limit=10)
        if not trips:
            raise HTTPException(404, "暂无行程")
        trip = trips[0]
        trip_id = trip["id"]
    else:
        trip = await ctx.repos.get("trips", trip_id)
        if not trip:
            raise HTTPException(404, "行程不存在")

    # 自动修复遗留行程缺失的 elder_id
    elder_id = trip.get("elder_id")
    if not elder_id:
        elders = await ctx.repos.list("users", where={"role": "elder", "status": "active"}, limit=1)
        if elders:
            elder_id = elders[0]["id"]
            await ctx.repos.update("trips", trip_id, {"elder_id": elder_id})
            trip["elder_id"] = elder_id

    checkpoints = await ctx.repos.list(
        "trip_checkpoints", where={"trip_id": trip_id}, order="-created_at", limit=1
    )
    latest_cp = checkpoints[0] if checkpoints else None

    # 若当前行程暂无打点，但长辈近期有其他上报记录，兜底提供最新位置防白屏
    if not latest_cp and elder_id:
        other_trips = await ctx.repos.list("trips", where={"elder_id": elder_id}, order="-created_at", limit=5)
        for ot in other_trips:
            if ot["id"] == trip_id:
                continue
            alt_cps = await ctx.repos.list("trip_checkpoints", where={"trip_id": ot["id"]}, order="-created_at", limit=1)
            if alt_cps:
                latest_cp = alt_cps[0]
                break

    # 补齐经纬度（若缺失）
    if latest_cp and (latest_cp.get("lng") is None or latest_cp.get("lat") is None) and latest_cp.get("location"):
        lng, lat = lookup_coords(latest_cp["location"])
        if lng is not None and lat is not None:
            latest_cp["lng"], latest_cp["lat"] = lng, lat

    # 如果需要隐私过滤
    if latest_cp and child_id:
        grant = await ctx.privacy.grant_for(elder_id or "", child_id)
        latest_cp = filter_checkpoint(grant, latest_cp)

    is_off_route = bool(latest_cp and latest_cp.get("status") == "off_route")

    return {
        "trip_id": trip_id,
        "status": trip.get("status"),
        "latest_checkpoint": latest_cp,
        "is_off_route": is_off_route,
        "alert": latest_cp.get("note") if is_off_route else "",
    }


@router.post("/{trip_id}/checkpoints")
async def report_checkpoint(trip_id: str, body: CheckpointIn):
    """长辈端 10 秒定时坐标上报与偏航判定闭环。"""
    return await process_checkpoint(get_ctx(), trip_id, body)


async def process_checkpoint(ctx, trip_id: str, body: CheckpointIn):
    """守护判定的核心逻辑（API 路由与测试脚本共用）。"""
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")

    # 自动修复遗留行程缺失的 elder_id
    elder_id = trip.get("elder_id")
    if not elder_id:
        elders = await ctx.repos.list("users", where={"role": "elder", "status": "active"}, limit=1)
        if elders:
            elder_id = elders[0]["id"]
            await ctx.repos.update("trips", trip_id, {"elder_id": elder_id})
            trip["elder_id"] = elder_id

    if trip.get("status") == "planned":
        await ctx.repos.update("trips", trip_id, {
            "status": "ongoing", "started_at": _now()
        })

    # 若没有传 location，补齐默认位置描述
    if not body.location:
        if body.lng is not None and body.lat is not None:
            body.location = f"经纬度({body.lng:.4f}, {body.lat:.4f})"
        else:
            body.location = "实时定位中"

    # 若传了位置名但经纬度为空，尝试查找坐标（先本地字典，再高德在线地理编码）
    if body.lng is None or body.lat is None:
        lookup_lng, lookup_lat = lookup_coords(body.location)
        if lookup_lng is not None and lookup_lat is not None:
            body.lng, body.lat = lookup_lng, lookup_lat
        elif body.location and body.location not in ("实时定位中", "定位中", "获取位置中"):
            geocoded = await amap_client.geocode(body.location)
            if geocoded:
                body.lng, body.lat = geocoded

    # 提取起点、目的地与终点坐标
    origin_name = resolve_trip_origin(trip)
    dest_name = resolve_trip_destination(trip)
    dest_coords = lookup_coords(dest_name)
    if dest_coords[0] is None:
        dest_coords = await amap_client.geocode(dest_name) or (None, None)
    if dest_coords[0] is None and "北京" in dest_name:
        dest_coords = LOCATION_COORDS.get("北京积水潭医院", (116.3748, 39.9485))

    # 计算行程规划航迹与途径站点
    route_data = await amap_client.plan_route(origin_name, dest_name)
    planned_stops = [
        p.get("location") or p.get("name")
        for p in route_data.get("points", [])
        if p.get("location") or p.get("name")
    ]
    all_expected = set(_EXPECTED_POINTS) | set(planned_stops)

    # 偏航与到达判定
    status, note = "normal", ""

    # 1. 到达目的地判定
    is_arrived = False
    if dest_coords[0] is not None and body.lng is not None and body.lat is not None:
        dist_to_dest = haversine_distance_m((body.lng, body.lat), (dest_coords[0], dest_coords[1]))
        if dist_to_dest <= 1000:
            is_arrived = True

    if not is_arrived and dest_name:
        core_kw = dest_name.replace("北京", "").replace("南京", "").replace("上海", "").replace("杭州", "").replace("苏州", "").strip()
        if (core_kw and len(core_kw) >= 2 and core_kw in body.location) or (dest_name in body.location):
            is_arrived = True

    if is_arrived:
        status = "arrived"
        note = "已安全到达目的地"
        await ctx.repos.update("trips", trip_id, {
            "status": "completed", "ended_at": _now()
        })
    # 2. 预期关键站点判定
    elif any(p in body.location for p in all_expected):
        note = f"途经 {body.location}，一切正常"
    # 3. 航迹走廊贴合度判定
    elif body.lng is not None and body.lat is not None:
        if (body.lng == 0.0 and body.lat == 0.0) or abs(body.lng) > 180 or abs(body.lat) > 90:
            # 硬件 GPS 尚未完成授时定位（零岛/非法坐标兜底）
            status = "normal"
            note = "设备正在校准卫星授时信号，请稍候"
        else:
            corridor = route_data.get("polyline") or route_data.get("points") or []
            corridor_dist = min_distance_to_corridor_m((body.lng, body.lat), corridor)

            # 走廊贴合阈值：
            # 若包含高铁，城际干线（距目的地 >35km）给予 15km 容差；城市内打车接驳段（距目的地 ≤35km）执行 3.5km 走廊管控
            if "高铁" in route_data.get("mode", ""):
                dist_to_dest = (
                    haversine_distance_m((body.lng, body.lat), (dest_coords[0], dest_coords[1]))
                    if dest_coords[0] is not None
                    else 999999
                )
                if dist_to_dest > 35_000:
                    tolerance = 15000
                else:
                    tolerance = 3500
            else:
                tolerance = 3500

            if corridor_dist <= tolerance:
                note = f"途经 {body.location}，一切正常"
            else:
                status = "off_route"
                note = f"位置偏离规划路线：{body.location}，请关注"
    else:
        # 无经纬度坐标时的防抖处理：GPS 未捕获信号不误报偏航
        if body.location in ("", "实时定位中", "定位中", "获取位置中", "GPS定位中"):
            status = "normal"
            note = "等待长辈设备卫星定位信号，正在连接..."
        else:
            status = "off_route"
            note = f"位置偏离规划路线：{body.location}，请关注"

    # 查询前一条历史记录进行频控防抖
    prev_cps = await ctx.repos.list(
        "trip_checkpoints", where={"trip_id": trip_id}, order="-created_at", limit=1
    )
    prev_cp = prev_cps[0] if prev_cps else None

    cp = await ctx.repos.insert("trip_checkpoints", {
        "trip_id": trip_id,
        "location": body.location,
        "lng": body.lng,
        "lat": body.lat,
        "status": status,
        "note": note,
    })

    alert_sent = False
    if status == "off_route":
        # 仅在初次偏航时推送警报（防轰炸）
        should_alert = True
        if prev_cp and prev_cp.get("status") == "off_route":
            should_alert = False

        if should_alert:
            elder_id = trip.get("elder_id")
            binding = await ctx.repos.find_one("family_bindings", {"elder_id": elder_id})
            sessions = await ctx.repos.list(
                "sessions", where={"user_id": elder_id}, order="-created_at", limit=1
            )
            session_id = sessions[0]["id"] if sessions else None
            if session_id:
                payload = {
                    "trip_id": trip_id,
                    "location": body.location,
                    "note": note,
                    "elder": elder_id,
                    "lng": body.lng,
                    "lat": body.lat,
                }
                await ctx.event_log.hydrate(session_id)
                ctx.event_log.append(session_id, elder_id,
                                     durable_type("guardian_alert"), payload)
                ctx.broadcast.push_sync(session_id, SSEEvent("guardian_alert", payload))
                await ctx.event_log.flush(session_id)
            await ctx.repos.insert("audit_log", {
                "actor_id": None,
                "action": "guardian_alert",
                "target": trip_id,
                "detail": {"location": body.location, "lng": body.lng, "lat": body.lat},
            })
            alert_sent = True

    return {"checkpoint": cp, "status": status, "alert_sent": alert_sent}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
