"""backend/app/agents/guardian_agent.py —— 亲情守护管家智能体 (GuardianAgent).

职责：
1. 北斗时空安全走廊围栏监控 (monitor_safety_corridor)：亚米级走廊贴合度与偏航研判；
2. 异常滞留与跌倒受困研判 (detect_abnormal_dwell)：长椅休整宽限 (25min) 与常规区域滞留告警 (15min)；
3. 突发急症三甲医院急救绿色通道救援调度 (trigger_sos_reroute)：一键直连湘雅/省人民医院，生成应急走廊。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.agents.base import BaseAgent
from app.providers.external.amap_service import (
    haversine_distance_m,
    min_distance_to_corridor_m,
)
from app.services.elder_routing_service import elder_routing_service
from app.tools.common import fail, make_tool, ok

logger = logging.getLogger(__name__)

# 北斗适老示范路线预设适老长椅与休憩凉亭坐标（享滞留豁免与超长关怀）
KNOWN_REST_BENCHES: list[tuple[float, float]] = [
    (112.9875, 28.2148),  # 华夏路社区街心花园长椅
    (112.9895, 28.2141),  # 年嘉湖西路林荫道长椅 1
    (112.9910, 28.2135),  # 年嘉湖西路林荫道长椅 2
    (112.9930, 28.2128),  # 烈士公园西门便民休息亭
]

SYSTEM_PROMPT = """你是"亲情守护"，老年人安全监护与紧急救助专家，隶属于"老友记·康乐"智能体家族。

# 职责
1. 监控长辈在北斗适老安全走廊内的行进动态：
   - 步行微步道走廊精细容差为 50-80 米，超出即研判为偏航；
   - 发现偏航时给出温暖亲切的方向修正提示，绝不大惊小怪吓唬老人。
2. 研判长辈在途中的停留与异常滞留：
   - 识别预设爱心长椅/遮阳凉亭（25米内）：长椅休整给予 25 分钟宽限；
   - 非休整区域停留超过 15 分钟触发异常滞留预警，提示家属关注。
3. 突发急症与跌倒急救绿色通道：
   - 长辈呼救或检测到突发不适时，一键调取北斗高精度定位直连就近三甲医院急诊绿色通道；
   - 规划应急避险走廊，推送亲情防慌乱安抚语音。

# 说话原则
- 语气温暖踏实、沉稳有力、像时刻陪在身旁的贴心儿女，称呼"您"；
- 短句表达，每句话不超过 20 个字，消除老人的孤独感与慌乱感。
"""


class GuardianAgent(BaseAgent):
    name = "guardian"
    display_name = "亲情守护"
    description = "亲情守护管家：北斗高精安全走廊围栏监控、异常滞留与走失受困研判、突发急症与跌倒三甲医院绿色通道调度"
    system_prompt = SYSTEM_PROMPT
    color = "#9B5DE5"  # 专属守护紫
    avatar = "🛡️"
    tool_names = [
        "monitor_safety_corridor",
        "detect_abnormal_dwell",
        "trigger_sos_reroute",
        "plain_say",
    ]
    report_schema = ("guardian_status",)


# ------------------------------------------------------------------ 工具实现

async def monitor_safety_corridor(turn, args: dict) -> dict:
    """监控长辈当前定位与规划安全走廊的贴合度，识别偏航风险."""
    coords_raw = args.get("current_coords") or args.get("coords")
    lng = args.get("lng")
    lat = args.get("lat")

    if coords_raw and isinstance(coords_raw, (list, tuple)) and len(coords_raw) == 2:
        point = (float(coords_raw[0]), float(coords_raw[1]))
    elif lng is not None and lat is not None:
        point = (float(lng), float(lat))
    else:
        return fail("缺少有效坐标，无法测算走廊贴合度。")

    # 过滤硬件授时阶段零岛坐标
    if (point[0] == 0.0 and point[1] == 0.0) or abs(point[0]) > 180.0 or abs(point[1]) > 90.0:
        return ok(
            summary="北斗卫星授时校准中，暂未建立空间基准。",
            data={"corridor_status": {"is_safe": True, "status": "CALIBRATING", "distance_m": 0.0}},
        )

    corridor_raw = args.get("corridor") or args.get("corridor_polyline")
    tolerance_m = float(args.get("tolerance_m") or 80.0)

    # 若未传入自定义走廊，默认使用长沙适老示范航迹
    corridor: List[Tuple[float, float]] = []
    if corridor_raw and isinstance(corridor_raw, list):
        for p in corridor_raw:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                corridor.append((float(p[0]), float(p[1])))

    if not corridor:
        corridor = [(112.9862, 28.2154), (112.9895, 28.2141), (112.9932, 28.2125)]

    dist_m = min_distance_to_corridor_m(point, corridor)
    is_safe = dist_m <= tolerance_m

    if is_safe:
        summary = f"长辈在安全走廊内平稳前行，距中心线 {dist_m:.1f} 米，状态良好。"
        voice = "路线平坦无障碍，请安心前行。"
        status = "NORMAL"
    else:
        summary = f"长辈偏离适老规划走廊 {dist_m:.1f} 米，超出 {tolerance_m} 米阈值！"
        voice = "您稍微走偏了点，咱们往右侧平缓小道走回安全路线哦。"
        status = "OFF_ROUTE"

    data = {
        "corridor_status": {
            "is_safe": is_safe,
            "status": status,
            "distance_to_corridor_m": round(dist_m, 1),
            "tolerance_m": tolerance_m,
            "alert_message": summary if not is_safe else None,
            "audio_reassurance": voice,
        }
    }
    return ok(summary=summary, announce=voice, data=data)


async def detect_abnormal_dwell(turn, args: dict) -> dict:
    """检测长辈在当前位置的停留时长，智能区分长椅休整与异常受困."""
    coords_raw = args.get("current_coords") or args.get("coords")
    lng = args.get("lng")
    lat = args.get("lat")
    if coords_raw and isinstance(coords_raw, (list, tuple)) and len(coords_raw) == 2:
        point = (float(coords_raw[0]), float(coords_raw[1]))
    elif lng is not None and lat is not None:
        point = (float(lng), float(lat))
    else:
        point = (112.9895, 28.2141)

    dwell_seconds = int(args.get("dwell_seconds") or args.get("dwell_duration_seconds") or 0)
    speed_kmh = float(args.get("speed_kmh", 0.0))

    # 判断是否位于已知爱心长椅 25 米辐射范围内
    is_at_bench = False
    for bench in KNOWN_REST_BENCHES:
        if haversine_distance_m(point, bench) <= 25.0:
            is_at_bench = True
            break

    if speed_kmh >= 0.5:
        summary = "长辈处于行进状态，无异常滞留。"
        return ok(summary=summary, data={"dwell_status": {"is_safe": True, "status": "MOVING"}})

    mins = dwell_seconds // 60
    if is_at_bench:
        if dwell_seconds >= 1500:  # 25分钟
            status = "ABNORMAL_DWELL"
            summary = f"检测到长辈在长椅处休整已达 {mins} 分钟，建议温馨提醒。"
            voice = "您在长椅处休息较长时间，感觉还好吗？需要帮您联系家人吗？"
            is_safe = False
        else:
            status = "RESTING_AT_BENCH"
            summary = f"长辈在爱心长椅处休整 {mins} 分钟，处于适老关怀允许区间。"
            voice = "好好坐着歇歇脚，咱们不赶时间。"
            is_safe = True
    else:
        if dwell_seconds >= 900:   # 15分钟
            status = "ABNORMAL_DWELL"
            summary = f"长辈在非休整路段连续停留 {mins} 分钟，疑似身体不适或走失受困！"
            voice = "您在此处停留较长时间，是否需要呼叫家人或急救服务？"
            is_safe = False
        else:
            status = "NORMAL_PAUSE"
            summary = f"长辈途中短暂停留 {mins} 分钟，各项指标平稳。"
            voice = "稍事休息，平复呼吸。"
            is_safe = True

    data = {
        "dwell_status": {
            "is_safe": is_safe,
            "status": status,
            "dwell_seconds": dwell_seconds,
            "is_at_bench": is_at_bench,
            "alert_message": summary if not is_safe else None,
            "audio_reassurance": voice,
        }
    }
    return ok(summary=summary, announce=voice, data=data)


async def trigger_sos_reroute(turn, args: dict) -> dict:
    """突发急症/跌倒一键激活三甲医院急救绿色通道 (Emergency SOS Green Channel)."""
    coords_raw = args.get("current_coords") or args.get("coords")
    lng = args.get("lng")
    lat = args.get("lat")
    if coords_raw and isinstance(coords_raw, (list, tuple)) and len(coords_raw) == 2:
        point = (float(coords_raw[0]), float(coords_raw[1]))
    elif lng is not None and lat is not None:
        point = (float(lng), float(lat))
    else:
        point = (112.9862, 28.2154)

    user = getattr(turn, "user", None) or {}
    elder_name = str(args.get("elder_name") or user.get("name") or "张阿姨")
    condition = str(args.get("condition") or "突发身体不适与心慌")

    try:
        sos_res = elder_routing_service.emergency_sos_reroute(
            current_coords=point,
            elder_name=elder_name,
            condition=condition,
        )
    except Exception as exc:
        return fail(f"激活急救绿色通道失败: {exc}")

    summary = (
        f"已激活应急救助！已锁定北斗高精位置，为{elder_name}接通{sos_res['nearest_hospital']['name']}急救通道，"
        f"直线距离 {sos_res['distance_m']} 米，家属与救护中心已同步获取高精坐标。"
    )

    return ok(
        summary=summary,
        announce=sos_res.get("voice_broadcast") or summary,
        data={
            "emergency_sos": sos_res,
            "guardian_status": sos_res,
        },
    )


# ------------------------------------------------------------------ 注册函数

def register_guardian_tools(registry) -> None:
    """在 ToolRegistry 中注册亲情守护管家专属安全工具."""
    registry.register(make_tool(
        "monitor_safety_corridor",
        "监控老人当前坐标与北斗适老安全走廊的贴合度，研判偏航并给出温暖回正语音引导。",
        {
            "current_coords": {
                "type": "array",
                "items": {"type": "number"},
                "description": "老人当前经纬度坐标 [lng, lat]",
            },
            "tolerance_m": {
                "type": "number",
                "description": "走廊允许偏航容差（米），微步道默认 80.0",
            },
        },
        monitor_safety_corridor,
        agent="guardian",
        report_key="guardian_status",
    ))

    registry.register(make_tool(
        "detect_abnormal_dwell",
        "检测长辈在特定位置的连续滞留时长，智能区分长椅休整 (25min宽限) 与非安全区异常受困 (15min报警)。",
        {
            "current_coords": {
                "type": "array",
                "items": {"type": "number"},
                "description": "老人当前经纬度坐标 [lng, lat]",
            },
            "dwell_seconds": {
                "type": "integer",
                "description": "连续滞留时长（秒）",
            },
            "speed_kmh": {
                "type": "number",
                "description": "当前移动速度 (km/h)",
            },
        },
        detect_abnormal_dwell,
        agent="guardian",
        report_key="guardian_status",
    ))

    registry.register(make_tool(
        "trigger_sos_reroute",
        "突发急症/跌倒一键激活三甲医院急救绿色通道，调取北斗高精度遥测，自动通知子女与救护中心。",
        {
            "current_coords": {
                "type": "array",
                "items": {"type": "number"},
                "description": "老人突发求救时的经纬度坐标 [lng, lat]",
            },
            "elder_name": {"type": "string", "description": "长辈姓名"},
            "condition": {"type": "string", "description": "突发症状描述（如'胸闷心绞痛'、'跌倒无法站立'）"},
        },
        trigger_sos_reroute,
        agent="guardian",
        report_key="guardian_status",
    ))
