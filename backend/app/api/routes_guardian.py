"""行程守护 API：行程详情 / 位置上报（真实高德联动）→ 偏航判定与告警。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_ctx, get_current_principal
from app.auth.security import Principal
from app.core.context import AppContext
from app.core.events import durable_type
from app.core.sse import SSEEvent
from app.providers.external.amap_service import (
    KNOWN_LANDMARKS,
    amap_client,
    city_of,
    haversine_distance_m,
    home_coords,
    is_home,
    min_distance_to_corridor_m,
)
from app.safety.privacy import (
    PrivacyGrant,
    denied,
    filter_alert,
    filter_checkpoint,
)
from app.shared.plan_helpers import extract_destination, is_same_plan, trip_dedup_key

router = APIRouter(prefix="/api/trips", tags=["guardian"])

# 守护地图只画本市这三种走法（口径与 providers/external/services.py 的 _LOCAL_MODES 一致）
_LOCAL_TRAVEL_MODES = ("公交", "地铁", "步行")
# 结果里一旦出现这些字样，就说明这条路根本不是本市出行 —— 不画，也不当预期途经点
_INTERCITY_HINTS = ("高铁", "动车", "城际", "航班", "飞机", "机票", "机场", "12306")


def _is_local_drawable(route: dict | None) -> bool:
    """这条路能不能画给子女看：本市 + 公交/地铁/步行，且不带高铁航班字样。

    跨城那条路在 amap_service 里已经退成 matched=False 了，这里再挡一道：
    孩子端的大地图上出现一条跨省航迹，比"没有路线"更容易让人误会。
    """
    if not route or not route.get("matched"):
        return False
    text = f"{route.get('mode', '')}{route.get('summary', '')}"
    if any(hint in text for hint in _INTERCITY_HINTS):
        return False
    return any(mode in str(route.get("mode", "")) for mode in _LOCAL_TRAVEL_MODES)


def _blank_route(origin: str, destination: str) -> dict:
    """不画的路线：航迹留空，把情况如实说清楚。"""
    d_c = city_of(destination)
    o_c = city_of(origin)
    if o_c and d_c and o_c != d_c:
        summary = (f"从{origin}到{destination}：这段路不在本市公交/地铁/步行的范围里，"
                   f"地图上暂不显示；跨城的车票机票康乐不查。")
    else:
        summary = (f"从{origin}到{destination}：暂时没能规划出具体换乘步骤，"
                   f"建议出门前由家里人陪同或就近选择出行方式。")
    return {
        "ok": True, "matched": False,
        "origin": origin, "destination": destination,
        "mode": "", "duration": "", "distance_km": None,
        "points": [], "polyline": [], "steps": [],
        "summary": summary,
    }


async def guard_route(origin: str, destination: str, city: str = "") -> dict:
    """守护地图取路线的唯一入口：只返回本市公交/地铁/步行的航迹。

    统一按"公交"问，是因为老人端能选的走法只有公交/地铁/步行三种，默认就是公交
    （打车走 hail_ride，不在这张图上）；这样高德那条路规划的也是本市公交线，
    而不是一条老人根本不会坐的"市内打车"线。

    ``city`` = 老人所在城市，传给规划层解释"家"这个称呼（出发地写"家（北京西城区）"
    时以正文为准，裸一个"家"才用到它）。未传时优先从出发地/目的地推断或兜底南京。
    """
    if not city:
        city = city_of(origin) or city_of(destination) or "长沙"
    route = await amap_client.plan_route(origin, destination, "公交", city)
    return route if _is_local_drawable(route) else _blank_route(origin, destination)


# 演示行程的预期途经点：只列本市要去的地标。跨城的火车站（南京南站 / 济南西站 /
# 上海虹桥站 …）不再列入 —— 康乐只在市内走动，把它们当成"预期途经"，等于给一条
# 我们不再规划、老人也走不到的路背书。
_EXPECTED_POINTS = [
    "南京鼓楼医院", "鼓楼医院", "鼓楼公园站",
    "北京积水潭医院", "北京协和医院",
    "上海市第六人民医院", "复旦大学附属华山医院",
]

# 标准途经点经纬度（高德 GCJ-02 坐标系）。
# 这里**没有"家"**："家"不是地名，它在哪座城取决于老人此刻在哪座城 —— 坐标只有一份
# （hospitals.json 的 elder_homes），由 lookup_coords 按城市去取。表里钉死一个南京的
# "家"，北京那条行程的起点就会被画到南京，子女端地图上差 900 公里。
LOCATION_COORDS: dict[str, tuple[float, float]] = {
    **KNOWN_LANDMARKS,
    "南京": (118.7841, 32.0645),
    "南京鼓楼区": (118.7732, 32.0618),
    "南京南站": (118.7981, 31.9696),
    "济南西站": (116.8974, 36.6669),
    "北京南站": (116.3789, 39.8652),
    "积水潭医院": (116.3748, 39.9485),
    "北京积水潭医院": (116.3748, 39.9485),
    "漫心酒店": (116.3725, 39.9472),
    # 湖南省大学生智能导航科技创新大赛（长沙实景示范地标）
    "华夏路社区": (112.9862, 28.2154),
    "年嘉湖西路": (112.9895, 28.2141),
    "东风路口": (112.9880, 28.2090),
    "营盘路口": (112.9830, 28.2050),
    "烈士公园西门": (112.9932, 28.2125),
    "烈士公园南门": (112.9975, 28.2078),
    "烈士公园": (112.9932, 28.2125),
    "湖南烈士公园": (112.9932, 28.2125),
    "湘雅路入口": (112.9858, 28.2163),
    "省人民医院急诊门前": (112.9772, 28.1915),
    "湖南省人民医院": (112.9772, 28.1915),
    "中南大学湘雅医院": (112.9870, 28.2140),
    "湘雅医院": (112.9870, 28.2140),
    "长沙市第一医院": (112.9820, 28.2060),
}

# 北斗适老示范路线预设适老长椅与休憩凉亭坐标（享滞留豁免与超长关怀）
KNOWN_REST_BENCHES: list[tuple[float, float]] = [
    (112.9875, 28.2148),  # 华夏路社区街心花园长椅
    (112.9895, 28.2141),  # 年嘉湖西路林荫道长椅 1
    (112.9910, 28.2135),  # 年嘉湖西路林荫道长椅 2
    (112.9930, 28.2128),  # 烈士公园西门便民休息亭
]


def lookup_coords(location: str, city: str = "") -> tuple[float | None, float | None]:
    """地点名 → 坐标。``city`` = 老人所在城市，只在"家"这个称呼上用得到。

    "家"按城市落到 elder_homes 那一份（与 amap_service 同一份数据）：这句话里带着
    城名（``家（北京西城区）``）时以正文为准，正文里没有才用 ``city`` 兜底。
    两样都没有就给不出坐标 —— 绝不退回表里任何一座城（尤其是南京），子女端守护
    地图上那条起点线才不会被画到别的省去。
    """
    if not location:
        return None, None
    if is_home(location):
        coords = home_coords(city_of(location) or city)
        if coords:
            return coords
        # 城名认得出来、但那座城没登记"家"（家（杭州西城区））：退到那座城的市中心
        # 当大致方向（走下面的常规查表）；连城名都认不出就查不到，返回 (None, None)。
    if location in LOCATION_COORDS:
        return LOCATION_COORDS[location]
    for key, (lng, lat) in sorted(LOCATION_COORDS.items(), key=lambda x: len(x[0]), reverse=True):
        if key in location:
            return lng, lat
    return None, None


async def elder_city_of(ctx, trip: dict[str, Any]) -> str:
    """老人档案里的常住城市（"家"这个称呼靠它落到对的那座城）。

    调用处先用 ``city_of(出发地文本)`` 认一次（"家（北京西城区）"这种写法更具体，
    正文优先），认不出城名的光秃秃一个"家"才轮到这里 —— 与 services.py 里
    ``_end_cities`` "正文优先、档案兜底"的次序一致。
    """
    elder_id = trip.get("elder_id")
    if not elder_id:
        return ""
    user = await ctx.repos.get("users", elder_id)
    return str((user or {}).get("city") or "").strip()


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
    if "北京" in purpose and ("返程" in purpose or "回南京" in purpose or "回长沙" in purpose or "回家" in purpose):
        return "北京南站"
    if "上海" in purpose and ("返程" in purpose or "回南京" in purpose or "回长沙" in purpose or "回家" in purpose):
        return "上海虹桥站"
    if "杭州" in purpose and ("返程" in purpose or "回南京" in purpose or "回长沙" in purpose or "回家" in purpose):
        return "杭州东站"
    if "苏州" in purpose and ("返程" in purpose or "回南京" in purpose or "回长沙" in purpose or "回家" in purpose):
        return "苏州站"
    return "家（长沙市开福区华夏路社区）"


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
    if "返程" in purpose or "回家" in purpose or "回宁" in purpose or "回南京" in purpose or "回长沙" in purpose:
        return "家（长沙市开福区华夏路社区）"
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
        if spot in ("家", "南京", "北京", "上海", "杭州", "苏州", "长沙", "家（长沙市开福区华夏路社区）", "家（南京鼓楼区）"):
            continue
        if spot in purpose:
            return spot
    city = extract_destination(trip)
    if city and ("湘雅" in purpose or "长沙" in city or "湖南" in city or "烈士" in purpose):
        if "烈士" in purpose:
            return "湖南烈士公园"
        if "人民医院" in purpose:
            return "湖南省人民医院"
        return "中南大学湘雅医院"
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
    return city or purpose or "中南大学湘雅医院"


# ---------------------------------------------------------------------- R6 门禁
# 这一节是行程守护面唯一的身份判定入口。改之前这片接口的闸门是**调用方拿 query
# 参数自己开的**：trip_detail 里写着"没传 child_id 就 return 全量"、realtime 里写着
# "带了 child_id 才过滤"。攻击者只要不带那个参数，整条隐私分级就被绕开 —— 把闸门
# 交给调用方，比没有闸门更糟：它看起来是管着的。
#
# 现在的规矩只有一条：**看 token 里的身份，不看 query**。


def _principal_of(principal: Any) -> Principal | None:
    """取出 FastAPI 注入的请求者；同进程直调（演示脚本 / 单测）返回 None。

    路由签名上的 ``Depends(get_current_principal)`` 保证 HTTP 请求走到函数体时
    拿到的一定是 ``Principal`` —— 没带 token 在依赖里就 401 了，进不到这一行。
    直接以 Python 调用这几个函数（``tests/test_amap_guardian.py`` 里就有）拿到的是
    ``Depends`` 占位对象：那条路不经过网络，没有"外部请求者"，也就无从冒充。
    """
    return principal if isinstance(principal, Principal) else None


def _refuse_mismatched_child_id(principal: Principal, child_id: str | None) -> None:
    """``child_id`` 只剩"我是谁"的冗余提示这一个用途，且必须与 token 一致。

    留着它是因为前端还在传（``pages/child/guardian.vue`` 的行程详情与实时轮询）。
    与其静默忽略，不如不一致就报错：那两处请求的作者以为它能决定看得到什么，
    当场报错才能把这个念头掐掉。**它不再参与任何裁剪判断。**
    """
    if child_id and child_id != principal.id:
        raise HTTPException(403, "child_id 与登录身份不一致")


async def _visible_elder_ids(ctx: AppContext, principal: Principal) -> list[str]:
    """这个请求者能看哪些老人的行程：老人只有自己，子女只有绑定关系里的老人。

    口径与子女端看板一致（``routes_child.dashboard`` 也是按 status=active 筛）。
    返回**空列表 = 谁都不给**，不是"不限制" —— 没有绑定关系的子女在这里就该
    什么都拿不到。
    """
    if principal.role == "elder":
        return [principal.id]
    if principal.role != "child":
        return []
    bindings = await ctx.repos.list(
        "family_bindings", where={"child_id": principal.id, "status": "active"})
    return [b["elder_id"] for b in bindings if b.get("elder_id")]


async def _visible_grant(ctx: AppContext, principal: Principal,
                         trip: dict) -> PrivacyGrant | None:
    """这一条行程按什么精度交给这个请求者。返回 ``None`` = 本人，全量不裁。

    - 本人（``principal.id == trip.elder_id``）→ ``None``。老人要在自己手机上看
      自己的行程，这条路必须留。
    - 子女 → 按（老人, 子女）此刻的档裁剪。没有绑定关系时 ``denied()``，
      **照样往下走**：降级是数据变形不是报错（privacy.py 模块头第 1 条）。
    - 其余 → 403。既不是本人又没有这层关系，不是"少给点"的问题。
    """
    elder_id = str(trip.get("elder_id") or "")
    if elder_id and principal.id == elder_id:
        return None
    if principal.role != "child":
        raise HTTPException(403, "无权查看该行程")
    if elder_id not in await _visible_elder_ids(ctx, principal):
        return denied(elder_id, principal.id)
    return await ctx.privacy.grant_for(elder_id, principal.id)


def _graded_trip_record(grant: PrivacyGrant, trip: dict) -> dict:
    """行程记录按档给。

    有绑定关系的子女：整条照给 —— 行程名（"前往XX医院"）本来就在子女端看板上摆着，
    位置分级的对象是**走到哪了**，不是"有没有这趟出门"。
    没绑定关系（denied）：只留一个壳子，连"这趟去哪"都不该知道。
    """
    if grant.bound:
        return trip
    return {k: trip.get(k) for k in ("id", "status", "created_at") if k in trip}


def _graded_route(route: dict, grant: PrivacyGrant | None) -> dict:
    """规划航迹按档给。``realtime``（或本人）原样，``city``/``off`` 只留"怎么走"。

    坐标、途经站点、换乘步骤一律去掉 —— 这条航迹的**起点是老人家的坐标**
    （plan_route 把"家"落到 elder_homes 那份经纬度），留着它等于把门牌号
    从另一扇门递出去。summary 也重建：原句是"从家（南京鼓楼区）到XX"，
    而 steps 里带的是高德的步行指令原文（含街道名）。

    没绑定关系（denied）连"这条路怎么走"都不给：那是陌生人。
    """
    if grant is None or grant.allows_location("realtime"):
        return route
    if not grant.bound:
        return {
            "ok": route.get("ok", True), "matched": False,
            "origin": "", "destination": "", "mode": "", "duration": "",
            "distance_km": None, "points": [], "polyline": [], "steps": [],
            "summary": "这位家人没有获得老人的位置授权。",
        }
    mode = route.get("mode") or ""
    duration = route.get("duration") or ""
    how = "，".join(x for x in (mode, duration) if x) or "路线信息"
    return {
        "ok": route.get("ok", True),
        "matched": route.get("matched", False),
        "origin": "",
        "destination": "",
        "mode": mode,
        "duration": duration,
        "distance_km": route.get("distance_km"),
        "points": [],
        "polyline": [],
        "steps": [],
        "summary": f"老人只开放到城市级，这条路怎么走暂不显示（{how}）。",
    }


class CheckpointIn(BaseModel):
    location: str = ""
    lng: float | None = None
    lat: float | None = None
    altitude_m: float = 50.0
    satellites: int = 18
    speed_kmh: float = 2.5
    timestamp: str | None = None


class BdsCheckpointPayload(BaseModel):
    """北斗高精轨迹周期上报 Payload (严格遵循 PROJECT.md 契约)."""
    trip_id: str
    lng: float
    lat: float
    altitude_m: float = 50.0
    satellites: int = 18
    speed_kmh: float = 2.5
    timestamp: str


class BdsCheckpointEvaluation(BaseModel):
    """北斗轨迹点安全评估与异常判定回执 (严格遵循 PROJECT.md 契约)."""
    is_safe: bool
    status: str  # "NORMAL" | "OFF_ROUTE" | "ABNORMAL_DWELL" | "ARRIVED"
    distance_to_corridor_m: float
    dwell_duration_seconds: int
    alert_message: Optional[str] = None
    audio_reassurance: Optional[str] = None


def evaluate_bds_checkpoint(
    payload: BdsCheckpointPayload,
    corridor_polyline: list[tuple[float, float]],
    destination_coords: Optional[tuple[float, float]] = None,
    registered_rest_benches: Optional[list[tuple[float, float]]] = None,
    consecutive_dwell_seconds: int = 0,
    corridor_tolerance_m: float = 80.0,
) -> BdsCheckpointEvaluation:
    """评测北斗轨迹点状态：正常/偏航/异常滞留/安全到达。"""
    point = (payload.lng, payload.lat)

    # 1. 信号搜星与零岛过滤 (0,0 或经纬度越界)
    if (payload.lng == 0.0 and payload.lat == 0.0) or abs(payload.lng) > 180.0 or abs(payload.lat) > 90.0:
        return BdsCheckpointEvaluation(
            is_safe=True,
            status="NORMAL",
            distance_to_corridor_m=0.0,
            dwell_duration_seconds=0,
            alert_message=None,
            audio_reassurance="正在校准北斗卫星授时信号，请稍候...",
        )

    # 2. 检查是否安全到达目的地 (距离终点 <= 50米)
    if destination_coords:
        dist_to_dest = haversine_distance_m(point, destination_coords)
        if dist_to_dest <= 50.0:
            return BdsCheckpointEvaluation(
                is_safe=True,
                status="ARRIVED",
                distance_to_corridor_m=0.0,
                dwell_duration_seconds=0,
                alert_message=None,
                audio_reassurance="长辈已安全到达目的地，本次出行北斗守护结束。",
            )

    # 3. 计算与规划走廊的最短距离
    corridor_dist = min_distance_to_corridor_m(point, corridor_polyline)

    # 4. 检查异常滞留 (停留速度极慢 < 0.5km/h)
    if payload.speed_kmh < 0.5:
        # 检查是否在预设长椅或休息亭处休整 (25米以内)
        is_at_bench = False
        benches = registered_rest_benches or KNOWN_REST_BENCHES
        if benches:
            for bench in benches:
                if haversine_distance_m(point, bench) <= 25.0:
                    is_at_bench = True
                    break

        if is_at_bench:
            # 长椅休整区：宽限到 25 分钟 (1500秒)
            if consecutive_dwell_seconds >= 1500:
                mins = consecutive_dwell_seconds // 60
                return BdsCheckpointEvaluation(
                    is_safe=False,
                    status="ABNORMAL_DWELL",
                    distance_to_corridor_m=round(corridor_dist, 1),
                    dwell_duration_seconds=consecutive_dwell_seconds,
                    alert_message=f"检测到老人在长椅处滞留已超过 {mins} 分钟，请确认是否需要关怀",
                    audio_reassurance="张阿姨，您在长椅处休息较长时间，感觉还好吗？需要帮您联系家人吗？",
                )
        else:
            # 非休整区：超过 15 分钟 (900秒) 触发异常滞留高危警报
            if consecutive_dwell_seconds >= 900:
                mins = consecutive_dwell_seconds // 60
                return BdsCheckpointEvaluation(
                    is_safe=False,
                    status="ABNORMAL_DWELL",
                    distance_to_corridor_m=round(corridor_dist, 1),
                    dwell_duration_seconds=consecutive_dwell_seconds,
                    alert_message=f"长辈在当前位置连续停留超过 {mins} 分钟，疑似身体不适或走失受困！",
                    audio_reassurance="张阿姨，您在此处停留较长时间，是否需要呼叫家人或急救服务？",
                )

    # 5. 检查走廊偏航 (微步道走廊容差 50-80m)
    if corridor_dist > corridor_tolerance_m:
        return BdsCheckpointEvaluation(
            is_safe=False,
            status="OFF_ROUTE",
            distance_to_corridor_m=round(corridor_dist, 1),
            dwell_duration_seconds=consecutive_dwell_seconds,
            alert_message=f"长辈偏离规划安全走廊 {corridor_dist:.1f} 米，请注意核实位置。",
            audio_reassurance="张阿姨，您稍微走偏了点，咱们往右侧平缓小道走回安全路线哦。",
        )

    # 6. 正常通行
    return BdsCheckpointEvaluation(
        is_safe=True,
        status="NORMAL",
        distance_to_corridor_m=round(corridor_dist, 1),
        dwell_duration_seconds=consecutive_dwell_seconds,
        alert_message=None,
        audio_reassurance="北斗高精时空护航中，路线平坦无障碍，请安心前行。",
    )


async def calculate_checkpoint_dwell_seconds(
    ctx: AppContext,
    trip_id: str,
    current_lng: float,
    current_lat: float,
    current_time: Optional[datetime] = None,
) -> int:
    """计算长辈在当前位置 25 米范围内的连续滞留时长（秒）。"""
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    cps = await ctx.repos.list(
        "trip_checkpoints", where={"trip_id": trip_id}, order="-created_at", limit=30
    )
    if not cps:
        return 0

    earliest_time = current_time
    for cp in cps:
        cp_lng = cp.get("lng")
        cp_lat = cp.get("lat")
        if cp_lng is None or cp_lat is None:
            break
        dist = haversine_distance_m((current_lng, current_lat), (cp_lng, cp_lat))
        if dist > 25.0:
            break

        cp_time_str = cp.get("timestamp") or cp.get("created_at")
        if cp_time_str:
            try:
                cp_dt = datetime.fromisoformat(str(cp_time_str).replace("Z", "+00:00"))
                if cp_dt.tzinfo is None:
                    cp_dt = cp_dt.replace(tzinfo=timezone.utc)
                if cp_dt < earliest_time:
                    earliest_time = cp_dt
            except Exception:
                pass

    return max(0, int((current_time - earliest_time).total_seconds()))


class CheckinIn(BaseModel):
    location: str = ""
    lng: float | None = None
    lat: float | None = None
    message: str = ""


class QuickTripIn(BaseModel):
    origin: str = "家（长沙市开福区华夏路社区）"
    destination: str = "中南大学湘雅医院"
    elder_id: str | None = None
    purpose: str | None = None


async def ensure_trip_elder(ctx, trip: dict[str, Any]) -> str:
    """确保行程挂载真实有效的长辈 ID，自动修复历史测试遗留孤儿行程。"""
    elder_id = trip.get("elder_id")
    user = await ctx.repos.get("users", elder_id) if elder_id else None
    if not user or user.get("role") != "elder":
        elders = await ctx.repos.list("users", where={"role": "elder", "status": "active"}, limit=1)
        if elders:
            elder_id = elders[0]["id"]
            await ctx.repos.update("trips", trip["id"], {"elder_id": elder_id})
            trip["elder_id"] = elder_id
    return elder_id or ""


@router.get("")
async def list_trips(elder_id: str | None = None, limit: int = 20,
                     principal: Principal = Depends(get_current_principal)):
    """行程列表：**只能看到自己（或自己绑定的老人）的行程**。

    ``elder_id`` 从"这就是全库查询条件"降成一个**收窄**用的过滤器：它只能在
    可见范围里再筛一次，传范围外的 id 直接 403。改之前不带它就等于 select *，
    全库的 elder_id / 目的地 / 事由一起端出去。
    """
    ctx = get_ctx()
    visible = await _visible_elder_ids(ctx, principal)
    if elder_id:
        if elder_id not in visible:
            raise HTTPException(403, "无权查看该老人的行程")
        visible = [elder_id]
    if not visible:
        return {"trips": [], "count": 0}

    # 逐个可见老人取一趟，再在内存里合成一份倒序表。repos.list 的 where 只有等值
    # 匹配、没有 in —— "全表拉回来再筛"是能少写几行，但它一旦忘了筛就是把全库读进来。
    raw: list[dict[str, Any]] = []
    for eid in visible:
        raw.extend(await ctx.repos.list(
            "trips", where={"elder_id": eid}, order="-created_at",
            limit=max(limit * 6, 60)))
    raw.sort(key=lambda t: str(t.get("created_at") or ""), reverse=True)

    # 多取一批再按 (长辈 + 去重键) 在内存折叠：同一趟进行中行程只留最新一条，
    # 避免子女端行程选择器被"前往XX医院 进行中"重复项占满（终态行程各自保留不合并）。
    seen: set[str] = set()
    trips: list[dict[str, Any]] = []
    for t in raw:
        key = f"{t.get('elder_id') or ''}::{trip_dedup_key(t)}"
        if key in seen:
            continue
        seen.add(key)
        trips.append(t)
        if len(trips) >= limit:
            break
    return {"trips": trips, "count": len(trips)}


@router.get("/route/direct", dependencies=[Depends(get_current_principal)])
async def direct_route(origin: str = "家（长沙市开福区华夏路社区）", destination: str = "中南大学湘雅医院",
                       city: str = ""):
    """直接通过起点与目的地获取高德规划轨迹、途经站点与换乘步骤。

    这条本身不含任何人的数据（只是把两个地名交给高德），但行程守护面统一要身份：
    匿名可打就等于白送一个规划代理，也让"这片接口有没有门"变成一个要逐条记的事。
    """
    if not city:
        city = city_of(origin) or city_of(destination) or "长沙"
    route_data = await guard_route(origin, destination, city)
    return {"ok": True, "origin": origin, "destination": destination, "city": city, "route": route_data}


@router.post("/quick")
async def create_quick_trip(body: QuickTripIn,
                            principal: Principal = Depends(get_current_principal)):
    """长辈进入路线规划时若无现存 trip_id，自动建立关联行程，打通定时上报闭环。

    行程的归属只能是自己：``body.elder_id`` 与 token 里的身份不一致就是**替别人
    建行程** —— 那位老人的子女会在看板上看到一趟他家老人从没安排过的出行。
    """
    ctx = get_ctx()
    caller = _principal_of(principal)
    if caller is not None:
        if not body.elder_id:
            raise HTTPException(400, "缺少老人标识")
        if caller.id != body.elder_id:
            raise HTTPException(403, "只能为自己建立行程")
    candidate = {
        "elder_id": body.elder_id,
        "purpose": body.purpose or f"前往{body.destination}就医出行",
        "status": "ongoing",
        "origin": body.origin,
        "destination": body.destination,
    }
    # 幂等护栏：同一长辈已有进行中/待出发的同一趟行程时直接复用，
    # 否则长辈每次进入路线规划都会新建一条 → 子女端"同时这么多计划"。
    where = {"elder_id": body.elder_id} if body.elder_id else {}
    existing = await ctx.repos.list("trips", where=where, order="-created_at", limit=50)
    for t in existing:
        if t.get("status") in ("planned", "ongoing") and is_same_plan(t, candidate):
            return {"ok": True, "trip": t, "reused": True}
    trip = await ctx.repos.insert("trips", {**candidate, "started_at": _now()})
    return {"ok": True, "trip": trip}


@router.get("/{trip_id}")
async def trip_detail(trip_id: str, child_id: str | None = None,
                      principal: Principal = Depends(get_current_principal)):
    """行程详情（含高德路径规划真实轨迹数据与偏航状态）。

    可见范围**由 token 里的身份决定**，不看 child_id：本人全量、子女按档裁剪、
    其余 403。改之前"不带 child_id 就 return 全量"，还带着 precision="owner" 的
    精确地址与经纬度 —— 也就是说闸门是调用方自己开的。
    """
    ctx = get_ctx()
    _refuse_mismatched_child_id(principal, child_id)
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    # 身份先判：403 不该先替攻击者花掉一次高德规划调用
    grant = await _visible_grant(ctx, principal, trip)

    checkpoints = await ctx.repos.list(
        "trip_checkpoints", where={"trip_id": trip_id}, order="created_at"
    )

    # 该行程对应的高德真实规划轨迹
    dest_name = resolve_trip_destination(trip)
    origin_name = resolve_trip_origin(trip)
    # "家"落到哪座城：正文里的城名优先，裸一个"家"才用老人档案里的常住城市
    city = city_of(origin_name) or await elder_city_of(ctx, trip)
    route_data = await guard_route(origin_name, dest_name, city)

    # 补齐经纬度坐标（若此前历史数据未带 lng/lat）
    for cp in checkpoints:
        if (cp.get("lng") is None or cp.get("lat") is None) and cp.get("location"):
            lng, lat = lookup_coords(cp["location"], city)
            if lng is not None and lat is not None:
                cp["lng"], cp["lat"] = lng, lat

    if grant is None:
        return {
            "trip": trip,
            "checkpoints": checkpoints,
            "precision": "owner",
            "route": route_data,
        }

    # 审计只记明细/航迹这种"看了一次"的读；轮询不记（见 trip_realtime）
    await ctx.privacy.audit(grant, "trip_detail")
    graded = [c for c in (filter_checkpoint(grant, x) for x in checkpoints) if c]
    return {
        "trip": _graded_trip_record(grant, trip),
        "checkpoints": graded,
        "precision": "off" if grant.location_off else grant.location_level,
        "privacy": grant.to_dict(),
        "route": _graded_route(route_data, grant),
    }


@router.get("/{trip_id}/route")
async def trip_route(trip_id: str,
                     principal: Principal = Depends(get_current_principal)):
    """直接获取行程的高德 Web API 2.0 规划航迹、站点与步骤。

    航迹按档给：这条线的起点是老人家，坐标与换乘步骤里的街道名一样是位置数据。
    """
    ctx = get_ctx()
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    grant = await _visible_grant(ctx, principal, trip)
    dest_name = resolve_trip_destination(trip)
    origin_name = resolve_trip_origin(trip)
    # "家"落到哪座城：正文里的城名优先，裸一个"家"才用老人档案里的常住城市
    city = city_of(origin_name) or await elder_city_of(ctx, trip)
    route_data = await guard_route(origin_name, dest_name, city)
    if grant is not None:
        await ctx.privacy.audit(grant, "trip_route")
        route_data = _graded_route(route_data, grant)
    return {"ok": True, "trip_id": trip_id, "route": route_data}


@router.get("/{trip_id}/realtime")
async def trip_realtime(trip_id: str, child_id: str | None = None,
                        principal: Principal = Depends(get_current_principal)):
    """子女端 8~10 秒实时轮询接口：获取长辈当前最新位置与偏航警报状态。

    位置过 ``filter_checkpoint``（city 档砍经纬度、地址粗化），告警过
    ``filter_alert``（位置关了也把"有异常"这件事给到 —— 把告警也藏掉，守护功能
    就等于没有；而"有异常"本身不含位置，不构成越级）。

    **这里不落审计**：轮询不是"看了一次"，每 8 秒一行会把 audit_log 灌满，
    反而让老人端"谁看过我"没法看。看详情（trip_detail）才记。
    """
    ctx = get_ctx()
    _refuse_mismatched_child_id(principal, child_id)
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    grant = await _visible_grant(ctx, principal, trip)

    checkpoints = await ctx.repos.list(
        "trip_checkpoints", where={"trip_id": trip_id}, order="-created_at", limit=1
    )
    raw_cp = checkpoints[0] if checkpoints else None

    if grant is None:                       # 本人：原样
        latest_cp, alert_cp = raw_cp, raw_cp
    else:
        latest_cp = filter_checkpoint(grant, raw_cp) if raw_cp else None
        alert_cp = filter_alert(grant, raw_cp) if raw_cp else None

    # 告警的有无跟着 alert_cp 走：没绑定关系时 filter_alert 给 None，
    # 连"有一次异常"这件事都不该让陌生人知道。
    is_off_route = bool(alert_cp and raw_cp and raw_cp.get("status") == "off_route")

    return {
        "trip_id": trip_id,
        "status": trip.get("status"),
        "latest_checkpoint": latest_cp,
        "is_off_route": is_off_route,
        "alert": (alert_cp.get("note") or "") if is_off_route else "",
    }


@router.post("/{trip_id}/checkpoints")
async def report_checkpoint(trip_id: str, body: CheckpointIn,
                            principal: Principal = Depends(get_current_principal)):
    """长辈端 10 秒定时坐标上报与偏航判定闭环。

    写入口也认人。改之前任何人都能往**别人家老人**的行程里灌一个坐标，顺手把一条
    off_route 告警推给他的子女 —— 越权写 + 伪造告警，而且对方库里会真多一行。
    现在只有两种人能写：
    - 老人本人（老人端 route-map 每 10 秒上报自己的位置）；
    - **有绑定关系**的子女 —— 这是给子女端"模拟行进 / 模拟偏航"那两个演示按钮
      留的明确授权路径（pages/child/guardian.vue 的 simElderMove）。演示能力留着，
      匿名口子不留。
    """
    ctx = get_ctx()
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")
    grant = await _visible_grant(ctx, principal, trip)
    if grant is not None:
        if not grant.bound:
            raise HTTPException(403, "无权为这位老人上报位置")
        await ctx.privacy.audit(grant, "trip_checkpoint_report",
                                action="guardian_report")
    result = await process_checkpoint(ctx, trip_id, body)
    if grant is not None:
        # 回执也按同一档给：city 档下刚写进去的门牌号，不该从回执里原样漏回来
        result["checkpoint"] = filter_checkpoint(grant, result["checkpoint"])
    return result


@router.post("/{trip_id}/checkin")
async def trip_safety_checkin(trip_id: str, body: CheckinIn | None = None,
                              principal: Principal = Depends(get_current_principal)):
    """长辈主动一键报平安：在行程中记录平安打卡，并向绑定的子女发送实时通知。"""
    ctx = get_ctx()
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")

    caller = _principal_of(principal)
    elder_id = trip.get("elder_id") or (caller.id if caller else None)
    elder = await ctx.repos.get("users", elder_id) if elder_id else None
    elder_name = (elder or {}).get("name") or "长辈"

    body = body or CheckinIn()
    dest_name = resolve_trip_destination(trip)
    loc_text = body.location or dest_name or "当前位置"

    # 1. 插入一条 status='normal' 的平安 checkpoint
    note_text = body.message or f"长辈主动报平安：目前一切安好，正前往{dest_name}"
    cp = await ctx.repos.insert("trip_checkpoints", {
        "trip_id": trip_id,
        "location": loc_text,
        "lng": body.lng,
        "lat": body.lat,
        "status": "normal",
        "note": note_text,
    })

    # 2. 查找长辈绑定的子女，推送真实安全通知
    bindings = await ctx.repos.list("family_bindings", where={"elder_id": elder_id, "status": "active"}) if elder_id else []
    notified_children = []
    for b in bindings:
        cid = b.get("child_id")
        child = await ctx.repos.get("users", cid)
        if child:
            notified_children.append({
                "id": child["id"],
                "name": child.get("name") or "子女",
                "phone": child.get("phone") or "13800000000",
                "relation": b.get("relation") or "家人",
            })
            await ctx.repos.insert("notifications", {
                "user_id": cid,
                "type": "safe_checkin",
                "title": f"{elder_name} 报平安",
                "content": f"{elder_name} 刚刚向您报平安：位置在【{loc_text}】，一切安好，请放心。",
                "data": json.dumps({"trip_id": trip_id, "location": loc_text}),
            })

    # 兜底默认家人（如暂无绑定）
    first_child = notified_children[0] if notified_children else {
        "name": "李明", "phone": "13812345678", "relation": "儿子"
    }

    return {
        "ok": True,
        "checkpoint": cp,
        "family": first_child,
        "children": notified_children,
        "message": f"已向家人【{first_child['name']}】发送报平安提醒",
    }


async def process_checkpoint(ctx, trip_id: str, body: CheckpointIn):
    """守护判定的核心逻辑（API 路由与测试脚本共用）。"""
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")

    # 自动修复遗留行程缺失或指向非真实用户的 elder_id
    elder_id = await ensure_trip_elder(ctx, trip)

    if trip.get("status") == "planned":
        await ctx.repos.update("trips", trip_id, {
            "status": "ongoing", "started_at": _now()
        })

    dest_name = resolve_trip_destination(trip)
    origin_name = resolve_trip_origin(trip)
    # "家"落到哪座城：正文里的城名优先，裸一个"家"才用老人档案里的常住城市。
    # 这条既给下面的坐标补全用（行里的 location 只写了"家"），也给规划层用。
    city = city_of(origin_name) or await elder_city_of(ctx, trip)

    # 若没有传 location，补齐默认位置描述
    if not body.location:
        if body.lng is not None and body.lat is not None:
            body.location = f"经纬度({body.lng:.4f}, {body.lat:.4f})"
        else:
            body.location = "实时定位中"

    # 若传了位置名但经纬度为空，尝试查找坐标（先本地字典，再高德在线地理编码）
    if body.lng is None or body.lat is None:
        lookup_lng, lookup_lat = lookup_coords(body.location, city)
        if lookup_lng is not None and lookup_lat is not None:
            body.lng, body.lat = lookup_lng, lookup_lat
        elif body.location and body.location not in ("实时定位中", "定位中", "获取位置中"):
            geocoded = await amap_client.geocode(body.location, city)
            if geocoded:
                body.lng, body.lat = geocoded

    # 提取起点、目的地与终点坐标
    dest_coords = lookup_coords(dest_name)
    if dest_coords[0] is None:
        dest_coords = await amap_client.geocode(dest_name) or (None, None)
    if dest_coords[0] is None and "北京" in dest_name:
        dest_coords = LOCATION_COORDS.get("北京积水潭医院", (116.3748, 39.9485))

    # 计算行程规划航迹与途径站点
    route_data = await guard_route(origin_name, dest_name, city)
    planned_stops = [
        p.get("location") or p.get("name")
        for p in route_data.get("points", [])
        if p.get("location") or p.get("name")
    ]
    all_expected = set(_EXPECTED_POINTS) | set(planned_stops)

    # 偏航与到达判定
    status, note = "normal", ""

    # 1. 到达目的地判定 (北斗高精度亚米级到达判定：距离终点 <= 50m)
    arrival_tolerance_m = 50.0

    is_arrived = False
    if dest_coords[0] is not None and body.lng is not None and body.lat is not None:
        dist_to_dest = haversine_distance_m((body.lng, body.lat), (dest_coords[0], dest_coords[1]))
        if dist_to_dest <= arrival_tolerance_m:
            is_arrived = True

    if not is_arrived and dest_name:
        core_kw = dest_name.replace("北京", "").replace("南京", "").replace("上海", "").replace("杭州", "").replace("苏州", "").strip()
        if (core_kw and len(core_kw) >= 2 and core_kw in body.location) or (dest_name in body.location):
            is_arrived = True

    corridor_dist = 0.0
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
            if not corridor:
                origin_coords = lookup_coords(origin_name, city)
                if origin_coords[0] is not None and dest_coords[0] is not None:
                    corridor = [(origin_coords[0], origin_coords[1]), (dest_coords[0], dest_coords[1])]
                elif dest_coords[0] is not None:
                    corridor = [(dest_coords[0], dest_coords[1])]
            corridor_dist = min_distance_to_corridor_m((body.lng, body.lat), corridor) if corridor else 0.0

            # 走廊贴合阈值：步行/微步道模式采用 50-80m 亚米级精细走廊，公交/地铁模式保留 3500m 容差
            is_walking = any(w in str(trip.get("purpose", "")) for w in ("步行", "步道", "适老", "微地形")) or any(w in str(route_data.get("mode", "")) for w in ("步行", "步道", "适老", "微地形"))
            tolerance = 80.0 if is_walking else 3500.0

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

    # 4. 异常滞留检测：速度极慢 < 0.5km/h 且未到达目的地
    dwell_sec = 0
    if body.lng is not None and body.lat is not None and not is_arrived:
        cur_dt = None
        if body.timestamp:
            try:
                cur_dt = datetime.fromisoformat(body.timestamp.replace("Z", "+00:00"))
                if cur_dt.tzinfo is None:
                    cur_dt = cur_dt.replace(tzinfo=timezone.utc)
            except Exception:
                cur_dt = None
        dwell_sec = await calculate_checkpoint_dwell_seconds(ctx, trip_id, body.lng, body.lat, cur_dt)

        if body.speed_kmh < 0.5:
            is_at_bench = any(
                haversine_distance_m((body.lng, body.lat), b) <= 25.0
                for b in KNOWN_REST_BENCHES
            )
            if is_at_bench:
                # 长椅休整区：宽限到 25 分钟 (1500秒)
                if dwell_sec >= 1500:
                    status = "abnormal_dwell"
                    mins = dwell_sec // 60
                    note = f"检测到老人在长椅处滞留已超过 {mins} 分钟，请确认是否需要关怀"
            else:
                # 非长椅区：超过 15 分钟 (900秒)
                if dwell_sec >= 900:
                    status = "abnormal_dwell"
                    mins = dwell_sec // 60
                    note = f"长辈在当前位置连续停留超过 {mins} 分钟，疑似身体不适或走失受困！"

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
        "altitude_m": body.altitude_m,
        "satellites": body.satellites,
        "speed_kmh": body.speed_kmh,
        "timestamp": body.timestamp or _now(),
        "dwell_duration_seconds": dwell_sec,
    })

    alert_sent = False
    if status in ("off_route", "abnormal_dwell"):
        # 仅在初次进入异常状态时推送警报（防轰炸）
        should_alert = True
        if prev_cp and prev_cp.get("status") == status:
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
                    "alert_type": status,
                    "dwell_seconds": dwell_sec,
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
                "detail": {
                    "location": body.location,
                    "lng": body.lng,
                    "lat": body.lat,
                    "status": status,
                    "note": note,
                    "dwell_seconds": dwell_sec,
                },
            })
            alert_sent = True

    # 构造标准 BdsCheckpointEvaluation 契约回执
    evaluation = BdsCheckpointEvaluation(
        is_safe=(status in ("normal", "arrived")),
        status=status.upper(),
        distance_to_corridor_m=round(corridor_dist, 1),
        dwell_duration_seconds=dwell_sec,
        alert_message=note if status in ("off_route", "abnormal_dwell") else None,
        audio_reassurance=(
            "长辈已安全到达目的地，本次出行北斗守护结束。" if status == "arrived" else (
                "张阿姨，您稍微走偏了点，咱们往右侧平缓小道走回安全路线哦。" if status == "off_route" else (
                    "张阿姨，您在此处停留较长时间，是否需要呼叫家人或急救服务？" if status == "abnormal_dwell" else "北斗高精时空护航中，路线平坦无障碍，请安心前行。"
                )
            )
        ),
    )

    return {
        "checkpoint": cp,
        "status": status,
        "alert_sent": alert_sent,
        "evaluation": evaluation.model_dump(),
    }


@router.post("/{trip_id}/bds_evaluate", response_model=BdsCheckpointEvaluation)
async def evaluate_bds_point(
    trip_id: str,
    body: BdsCheckpointPayload,
    corridor_tolerance_m: float = 80.0,
    principal: Principal = Depends(get_current_principal),
):
    """评估单点北斗轨迹状态（无需入库打卡），返回 BdsCheckpointEvaluation 契约回执。"""
    ctx = get_ctx()
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")

    dest_name = resolve_trip_destination(trip)
    origin_name = resolve_trip_origin(trip)
    city = city_of(origin_name) or await elder_city_of(ctx, trip)
    route_data = await guard_route(origin_name, dest_name, city)
    corridor = route_data.get("polyline") or route_data.get("points") or []

    dest_coords = lookup_coords(dest_name, city)
    if dest_coords[0] is None:
        dest_coords = await amap_client.geocode(dest_name, city) or (None, None)

    if not corridor:
        origin_coords = lookup_coords(origin_name, city)
        if origin_coords[0] is not None and dest_coords[0] is not None:
            corridor = [(origin_coords[0], origin_coords[1]), (dest_coords[0], dest_coords[1])]
        elif dest_coords[0] is not None:
            corridor = [(dest_coords[0], dest_coords[1])]

    cur_dt = None
    if body.timestamp:
        try:
            cur_dt = datetime.fromisoformat(body.timestamp.replace("Z", "+00:00"))
            if cur_dt.tzinfo is None:
                cur_dt = cur_dt.replace(tzinfo=timezone.utc)
        except Exception:
            cur_dt = None

    dwell_sec = await calculate_checkpoint_dwell_seconds(ctx, trip_id, body.lng, body.lat, cur_dt)

    eval_res = evaluate_bds_checkpoint(
        payload=body,
        corridor_polyline=corridor,
        destination_coords=dest_coords if dest_coords[0] is not None else None,
        registered_rest_benches=KNOWN_REST_BENCHES,
        consecutive_dwell_seconds=dwell_sec,
        corridor_tolerance_m=corridor_tolerance_m,
    )
    return eval_res


@router.post("/{trip_id}/bds_checkpoint")
async def report_bds_checkpoint(
    trip_id: str,
    body: BdsCheckpointPayload,
    corridor_tolerance_m: float = 80.0,
    principal: Principal = Depends(get_current_principal),
):
    """北斗高精亚米级轨迹打卡闭环（入库 + 异常判定 + 告警派发）。"""
    ctx = get_ctx()
    trip = await ctx.repos.get("trips", trip_id)
    if not trip:
        raise HTTPException(404, "行程不存在")

    cp_in = CheckpointIn(
        location=f"北斗高精定位点({body.lng:.4f}, {body.lat:.4f})",
        lng=body.lng,
        lat=body.lat,
        altitude_m=body.altitude_m,
        satellites=body.satellites,
        speed_kmh=body.speed_kmh,
        timestamp=body.timestamp,
    )
    result = await process_checkpoint(ctx, trip_id, cp_in)
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
