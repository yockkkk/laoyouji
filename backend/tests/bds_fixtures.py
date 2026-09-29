"""BDS Competition Test Fixtures and Reference Specification Oracle.

第八届湖南省大学生智能导航科技创新大赛（科技创意类赛道）
《银发导航智能体：基于多Agent协同的老年人安心出行伴侣》
E2E 竞赛交付测试夹具与基准规约定义。

提供：
1. BDS 高精度时空与 NMEA-0183 $BDGGA 规约模型与解算器
2. 适老微地形代价函数 Cost(E) 权威评测预言机 (Oracle)
3. 动态步行安全走廊电子围栏 (Corridor Geofence) 与异常滞留评测器
4. 反诈拦截 (Scam Interceptor) 与突发应急绿通 (SOS Green Channel) 预言机
5. 长沙实景地理拓扑（湖南省人民医院、中南大学湘雅医院、湖南烈士公园等）数据夹具
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

# ==============================================================================
# 1. BDS 接口规约模型 (PROJECT.md Interface Contracts)
# ==============================================================================

class BdsTelemetry(BaseModel):
    """北斗高精度定位与卫星遥测模型。"""
    timestamp: str
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude_m: float
    satellites_in_view: int = Field(..., ge=0, le=40)     # 18-24 BDS active
    satellites_used: int = Field(..., ge=0, le=36)        # 14-18 used
    fix_quality: str                                      # "RTK_FIXED" | "DGPS" | "STANDALONE"
    horizontal_accuracy_m: float                          # 0.35m sub-meter
    hdop: float                                           # < 0.9
    vdop: float                                           # < 1.2
    raw_nmea_sentence: str                                # "$BDGGA,..."


class ElderEscortRouteRequest(BaseModel):
    """适老多Agent导航规划请求。"""
    elder_id: str
    origin: tuple[float, float]                           # (lng, lat)
    destination_name: str                                 # e.g., "湖南省人民医院" or "烈士公园"
    destination_coords: Optional[tuple[float, float]] = None
    health_conditions: list[str] = Field(default_factory=list)  # ["膝关节退行性病变", "轻度高血压"]
    avoid_stairs: bool = True
    max_slope_percent: float = 4.0
    prefer_rest_benches: bool = True
    weather_condition: Optional[str] = "晴"                 # 气象约束注入


class ElderEscortRouteResponse(BaseModel):
    """适老多Agent导航规划响应（确定性交付方案）。"""
    plan_id: str
    route_name: str
    total_distance_m: int
    estimated_duration_min: int
    bds_satellite_count: int
    bds_accuracy_m: float
    barrier_free_score: float                             # 0.0 - 1.0 (e.g. 0.98)
    stairs_count: int                                     # 0
    max_gradient_percent: float                           # <= 4.0
    rest_benches_count: int                               # >= 3
    steps: list[dict]                                     # title, instruction, landmark, voice_hint, icon, coords
    geofence_corridor: list[tuple[float, float]]          # dynamic corridor points
    emergency_hospitals_nearby: list[dict] = Field(default_factory=list)


class BdsCheckpointPayload(BaseModel):
    """北斗高精轨迹周期上报 Payload。"""
    trip_id: str
    lng: float
    lat: float
    altitude_m: float = 50.0
    satellites: int = 18
    speed_kmh: float = 2.5
    timestamp: str


class BdsCheckpointEvaluation(BaseModel):
    """北斗轨迹点安全评估与异常判定回执。"""
    is_safe: bool
    status: str                                           # "NORMAL" | "OFF_ROUTE" | "ABNORMAL_DWELL" | "ARRIVED"
    distance_to_corridor_m: float
    dwell_duration_seconds: int
    alert_message: Optional[str] = None
    audio_reassurance: Optional[str] = None


# ==============================================================================
# 2. 地理空间与球面几何算法 (Geospatial Math)
# ==============================================================================

def haversine_distance_m(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """计算两点经纬度之间的地球表面大圆距离（米）。p = (lng, lat)"""
    lng1, lat1 = p1
    lng2, lat2 = p2
    r = 6371000.0  # 地球半径（米）

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def point_to_segment_distance_m(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """计算点 p 到线段 ab 的最短空间投影距离（米）。坐标格式 (lng, lat)"""
    px, py = p
    ax, ay = a
    bx, by = b

    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return haversine_distance_m(p, a)

    # 投影参数 t
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    closest = (ax + t * dx, ay + t * dy)
    return haversine_distance_m(p, closest)


def min_distance_to_corridor_m(point: tuple[float, float], corridor: list[tuple[float, float]]) -> float:
    """计算点到折线走廊的最短距离。"""
    if not corridor:
        return 0.0
    if len(corridor) == 1:
        return haversine_distance_m(point, corridor[0])

    min_dist = float("inf")
    for i in range(len(corridor) - 1):
        d = point_to_segment_distance_m(point, corridor[i], corridor[i + 1])
        if d < min_dist:
            min_dist = d
    return min_dist


# ==============================================================================
# 3. 适老微地形代价函数与算法预言机 (Elderly Cost Function Oracle)
# ==============================================================================

class PathSegment:
    """路网段特征。"""
    def __init__(
        self,
        name: str,
        start_point: tuple[float, float],
        end_point: tuple[float, float],
        length_m: float,
        slope_percent: float = 0.0,
        stairs_count: int = 0,
        has_elevator: bool = False,
        has_benches: bool = False,
        has_shade: bool = False,
        is_sheltered: bool = False,
    ):
        self.name = name
        self.start_point = start_point
        self.end_point = end_point
        self.length_m = length_m
        self.slope_percent = slope_percent
        self.stairs_count = stairs_count
        self.has_elevator = has_elevator
        self.has_benches = has_benches
        self.has_shade = has_shade
        self.is_sheltered = is_sheltered


def calculate_segment_cost(
    seg: PathSegment,
    avoid_stairs: bool = True,
    max_slope_percent: float = 4.0,
    is_rainy: bool = False,
    prefer_rest_benches: bool = True,
) -> float:
    """计算单个路段的生理与安全代价 Cost(e)。
    
    Formula from PROJECT.md:
      Cost(E) = sum( L(e) * (1 + C_slope(e) + C_stairs(e) + C_weather(e) - B_amenity(e)) )
      - C_slope = 5.0 * ((slope - 4.0)/4.0 + 1.0) if slope > 4% else 0.0
      - C_stairs = 100.0 * stairs if without elevator and avoid_stairs else 0.0
      - C_weather = 2.0 (slip factor on unsheltered wet surfaces)
      - B_amenity = 0.3 for rest benches and shaded avenues
    """
    length = seg.length_m

    # 1. 坡度惩罚 C_slope
    c_slope = 0.0
    if seg.slope_percent > max_slope_percent:
        excess = seg.slope_percent - max_slope_percent
        # 坡度超标施加高昂惩罚，极端坡度呈二次激增
        c_slope = 5.0 * (1.0 + (excess / 4.0) ** 2)

    # 2. 台阶惩罚 C_stairs
    c_stairs = 0.0
    if seg.stairs_count > 0 and not seg.has_elevator:
        if avoid_stairs:
            # 严格避开台阶：每级台阶施加 100.0 惩罚，大台阶直接阻断 (相当于无穷大)
            c_stairs = 100.0 * seg.stairs_count
        else:
            c_stairs = 20.0 * seg.stairs_count

    # 3. 气象惩罚 C_weather
    c_weather = 0.0
    if is_rainy and not seg.is_sheltered:
        c_weather = 2.0  # 露天湿滑地面惩罚因子
        if seg.slope_percent > 2.0:
            c_weather += 3.0  # 雨天坡道湿滑加剧

    # 4. 友好设施奖励 B_amenity
    b_amenity = 0.0
    if prefer_rest_benches and seg.has_benches:
        b_amenity += 0.3
    if seg.has_shade:
        b_amenity += 0.15

    # 综合乘子（必须 >= 0.1 防止负代价）
    multiplier = max(0.1, 1.0 + c_slope + c_stairs + c_weather - b_amenity)
    return length * multiplier


def evaluate_route_barrier_free_score(segments: list[PathSegment]) -> float:
    """评估路径无障碍指数 (0.0 - 1.0)。"""
    if not segments:
        return 1.0
    total_len = sum(s.length_m for s in segments)
    if total_len == 0:
        return 1.0

    penalty_points = 0.0
    for s in segments:
        if s.stairs_count > 0 and not s.has_elevator:
            penalty_points += min(1.0, s.stairs_count * 0.05) * (s.length_m / total_len)
        if s.slope_percent > 4.0:
            penalty_points += min(1.0, (s.slope_percent - 4.0) * 0.1) * (s.length_m / total_len)

    score = max(0.0, 1.0 - penalty_points)
    return round(score, 2)


# ==============================================================================
# 4. NMEA-0183 $BDGGA 遥测生成与解析器
# ==============================================================================

def generate_bdgga_sentence(
    lat: float,
    lng: float,
    altitude_m: float = 50.0,
    satellites: int = 18,
    hdop: float = 0.85,
    fix_quality: int = 4,  # 4 = RTK Fixed, 2 = DGPS, 1 = Standalone
) -> str:
    """生成标准北斗 NMEA-0183 $BDGGA 语句及校验和。"""
    utc_now = datetime.now(timezone.utc).strftime("%H%M%S.00")

    # 纬度转 DDMM.MMMM 格式
    lat_deg = int(abs(lat))
    lat_min = (abs(lat) - lat_deg) * 60.0
    lat_dir = "N" if lat >= 0 else "S"
    lat_str = f"{lat_deg:02d}{lat_min:07.4f}"

    # 经度转 DDDMM.MMMM 格式
    lng_deg = int(abs(lng))
    lng_min = (abs(lng) - lng_deg) * 60.0
    lng_dir = "E" if lng >= 0 else "W"
    lng_str = f"{lng_deg:03d}{lng_min:07.4f}"

    payload = f"BDGGA,{utc_now},{lat_str},{lat_dir},{lng_str},{lng_dir},{fix_quality},{satellites:02d},{hdop:.2f},{altitude_m:.1f},M,-15.0,M,1.0,0000"

    # 计算 XOR 校验和
    checksum = 0
    for char in payload:
        checksum ^= ord(char)
    checksum_hex = f"{checksum:02X}"

    return f"${payload}*{checksum_hex}"


def parse_bdgga_sentence(nmea: str) -> dict[str, Any]:
    """解析 NMEA $BDGGA 语句并校验。"""
    nmea = nmea.strip()
    if not nmea.startswith("$") or "*" not in nmea:
        raise ValueError("Invalid NMEA sentence format")

    content, reported_checksum = nmea[1:].split("*", 1)

    # 校验和复核
    computed_checksum = 0
    for char in content:
        computed_checksum ^= ord(char)
    if f"{computed_checksum:02X}" != reported_checksum.upper():
        raise ValueError(f"Checksum mismatch: computed {computed_checksum:02X} vs reported {reported_checksum}")

    fields = content.split(",")
    talker = fields[0]  # "BDGGA"
    if not talker.startswith("BD"):
        raise ValueError(f"Not a BDS talker identifier: {talker}")

    time_str = fields[1]
    lat_raw = fields[2]
    lat_dir = fields[3]
    lng_raw = fields[4]
    lng_dir = fields[5]
    fix_quality = int(fields[6])
    satellites = int(fields[7])
    hdop = float(fields[8])
    altitude_m = float(fields[9])

    # 转换纬度
    lat_deg = float(lat_raw[:2])
    lat_min = float(lat_raw[2:])
    lat = lat_deg + lat_min / 60.0
    if lat_dir == "S":
        lat = -lat

    # 转换经度
    lng_deg = float(lng_raw[:3])
    lng_min = float(lng_raw[3:])
    lng = lng_deg + lng_min / 60.0
    if lng_dir == "W":
        lng = -lng

    fix_map = {1: "STANDALONE", 2: "DGPS", 4: "RTK_FIXED"}

    return {
        "talker": talker,
        "utc_time": time_str,
        "latitude": round(lat, 6),
        "longitude": round(lng, 6),
        "fix_quality": fix_map.get(fix_quality, "UNKNOWN"),
        "satellites": satellites,
        "hdop": hdop,
        "altitude_m": altitude_m,
    }


# ==============================================================================
# 5. 反诈目的地语义拦截预言机 (Scam Interception Oracle)
# ==============================================================================

SCAM_PATTERNS = [
    r"免费.{0,6}(领鸡蛋|体验|理疗)",
    r"(生物科技|健康生活馆|养生会所|健康|养生).{0,8}(讲座|宣讲|会议)",
    r"祖传.{0,4}(秘方|神药)",
    r"(投资|原始股|高额分红|养老项目|股权投资)",
    r"(偏僻|偏远).{0,10}(厂房|仓库|工业园)",
    r"涉诈|传销|保健品骗局",
]

LEGITIMATE_WHITELIST = [
    "医院", "社区卫生服务中心", "门诊", "药房", "药店",
    "公园", "广场", "社区", "居委会", "老友驿站", "家",
]


def evaluate_scam_risk(destination: str, context_notes: str = "") -> dict[str, Any]:
    """评测目的地与行程背景是否存在涉诈高危风险。"""
    text = f"{destination} {context_notes}".strip()

    # 检查正规白名单：正规三甲医院或公园直接放行
    is_whitelisted = any(wl in destination for wl in LEGITIMATE_WHITELIST)

    for pattern in SCAM_PATTERNS:
        match = re.search(pattern, text)
        if match and not (is_whitelisted and "讲座" not in destination):
            return {
                "verdict": "DENY",
                "is_scam": True,
                "matched_pattern": match.group(0),
                "elder_warning": "张奶奶，这个地方近期有涉嫌非正规保健品虚假讲座的投诉，老友记建议您不要前往！",
                "guardian_alert": f"长辈出行目的地【{destination}】疑似涉嫌虚假诈骗（匹配特征：{match.group(0)}），系统已主动拦截！",
            }

    return {
        "verdict": "ALLOW",
        "is_scam": False,
        "matched_pattern": None,
        "elder_warning": None,
        "guardian_alert": None,
    }


# ==============================================================================
# 6. 北斗电子围栏与异常滞留预言机 (Geofence & Dwell Oracle)
# ==============================================================================

def evaluate_bds_checkpoint(
    payload: BdsCheckpointPayload,
    corridor_polyline: list[tuple[float, float]],
    destination_coords: Optional[tuple[float, float]] = None,
    registered_rest_benches: Optional[list[tuple[float, float]]] = None,
    consecutive_dwell_seconds: int = 0,
    corridor_tolerance_m: float = 100.0,
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

    # 4. 检查异常滞留 (停留 > 15分钟 = 900秒 且速度极慢)
    if consecutive_dwell_seconds >= 900 and payload.speed_kmh < 0.5:
        # 检查是否在预设长椅或休息亭处休整
        is_at_bench = False
        if registered_rest_benches:
            for bench in registered_rest_benches:
                if haversine_distance_m(point, bench) <= 25.0:
                    is_at_bench = True
                    break

        if not is_at_bench:
            # 非休整区长时间静止 -> 触发异常滞留高危警报
            return BdsCheckpointEvaluation(
                is_safe=False,
                status="ABNORMAL_DWELL",
                distance_to_corridor_m=corridor_dist,
                dwell_duration_seconds=consecutive_dwell_seconds,
                alert_message=f"长辈在当前位置连续停留超过 {consecutive_dwell_seconds // 60} 分钟，疑似身体不适或走失受困！",
                audio_reassurance="张阿姨，您在此处停留较长时间，是否需要呼叫家人或急救服务？",
            )

    # 5. 检查走廊偏航 (距离 > 100米)
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
        audio_reassurance=None,
    )


# ==============================================================================
# 7. 突发应急绿通重划预言机 (Emergency SOS Green Channel Oracle)
# ==============================================================================

CHANGSHA_TERTIARY_HOSPITALS = [
    {
        "name": "湖南省人民医院(天心阁院区)",
        "level": "三级甲等综合医院",
        "emergency_dept": "急诊医学中心(24小时)",
        "coords": (112.9772, 28.1915),
        "barrier_free_ramp": True,
        "phone": "0731-83929120",
    },
    {
        "name": "中南大学湘雅医院",
        "level": "三级甲等综合医院",
        "emergency_dept": "急诊科与胸痛中心",
        "coords": (112.9858, 28.2163),
        "barrier_free_ramp": True,
        "phone": "0731-84327120",
    },
    {
        "name": "湖南省中医院(湖南中医药大学第二附属医院)",
        "level": "三级甲等中医院",
        "emergency_dept": "急诊创伤科",
        "coords": (112.9785, 28.2045),
        "barrier_free_ramp": True,
        "phone": "0731-84917120",
    },
]


def dispatch_sos_green_channel(
    current_coords: tuple[float, float],
    elder_name: str = "张桂芳",
    max_radius_km: float = 3.5,
) -> dict[str, Any]:
    """突发不适或跌倒 SOS 触发：毫秒级重划就近三甲医院绿通路线。"""
    nearby_hospitals = []
    for hosp in CHANGSHA_TERTIARY_HOSPITALS:
        dist_m = haversine_distance_m(current_coords, hosp["coords"])
        if dist_m <= max_radius_km * 1000.0:
            nearby_hospitals.append({**hosp, "distance_m": int(dist_m)})

    nearby_hospitals.sort(key=lambda h: h["distance_m"])

    if not nearby_hospitals:
        # 兜底选择最近的一家
        closest = min(CHANGSHA_TERTIARY_HOSPITALS, key=lambda h: haversine_distance_m(current_coords, h["coords"]))
        dist_m = haversine_distance_m(current_coords, closest["coords"])
        nearby_hospitals = [{**closest, "distance_m": int(dist_m)}]

    target_hosp = nearby_hospitals[0]

    # 生成直达急诊通道的无障碍绿通折线
    green_corridor = [
        current_coords,
        ((current_coords[0] + target_hosp["coords"][0]) / 2.0, (current_coords[1] + target_hosp["coords"][1]) / 2.0),
        target_hosp["coords"],
    ]

    return {
        "status": "EMERGENCY_DISPATCHED",
        "elder_name": elder_name,
        "bds_location": current_coords,
        "target_hospital": target_hosp["name"],
        "hospital_coords": target_hosp["coords"],
        "distance_m": target_hosp["distance_m"],
        "estimated_emergency_arrival_min": max(3, int(target_hosp["distance_m"] / 40.0)),  # 步行/接驳转运预估
        "green_corridor": green_corridor,
        "emergency_phone": target_hosp["phone"],
        "dispatch_notice": f"已启动北斗紧急救助绿通！正在为您切换至最近三甲医院【{target_hosp['name']}】急诊通道（距您 {target_hosp['distance_m']} 米），已同步通知家人与急救中枢！",
        "audio_announcement": f"张阿姨别慌，老友记已为您启动就近三甲医院应急通道，前往{target_hosp['name']}，请原地在安全处稍候，家人马上赶到！",
    }


# ==============================================================================
# 8. 长沙实景演示地理拓扑 (Changsha Scenario Geometries)
# ==============================================================================

CHANGSHA_NODES = {
    "华夏路社区": (112.9862, 28.2154),
    "年嘉湖西路": (112.9895, 28.2141),
    "东风路口": (112.9880, 28.2090),
    "营盘路口": (112.9830, 28.2050),
    "烈士公园西门": (112.9932, 28.2125),
    "烈士公园南门": (112.9975, 28.2078),
    "烈士公园高台阶过街天桥": (112.9960, 28.2085),
    "湘雅路入口": (112.9858, 28.2163),
    "省人民医院急诊门前": (112.9772, 28.1915),
}

CHANGSHA_REST_BENCHES = [
    (112.9875, 28.2148),  # 华夏路社区街心花园长椅
    (112.9895, 28.2141),  # 年嘉湖西路林荫道长椅 1
    (112.9910, 28.2135),  # 年嘉湖西路林荫道长椅 2
    (112.9930, 28.2128),  # 烈士公园西门便民休息亭
]
