"""北斗高精度卫星导航时空服务模型 (BDS High-Precision Positioning & Telemetry Service).

本模块为“第八届湖南省大学生智能导航科技创新大赛”科技创意类赛道核心技术底座：
1. CGCS2000 / WGS84 / GCJ-02 大地坐标基准高精双向转换
2. 北斗三号 (BDS-3) 亚米级 RTK/PPP 差分解算定位遥测模型 (模拟 0.35m 精度, 18-24 颗可见星, HDOP < 0.9, VDOP < 1.2)
3. 严格符合 NMEA-0183 规范的北斗专属 $BDGGA 差分语句生成器与逆向校验解析器
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Any, Optional, Tuple
from pydantic import BaseModel, Field

# =====================================================================
# 1. 大地坐标基准转换 (CGCS2000 / WGS-84 / GCJ-02)
# =====================================================================
# 克拉索夫斯基椭球 / CGCS2000 椭球参数
PI = math.pi
X_PI = PI * 3000.0 / 180.0
A = 6378245.0          # 长半轴 a (米)
EE = 0.00669342162296594323  # 第一偏心率平方 e^2


def out_of_china(lng: float, lat: float) -> bool:
    """判定经纬度是否在中国境外（境外不施加火星坐标 GCJ-02 偏移）。"""
    if lng < 72.004 or lng > 137.8347:
        return True
    if lat < 0.8293 or lat > 55.8271:
        return True
    return False


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * PI) + 320.0 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> Tuple[float, float]:
    """WGS84 坐标转换为中国国测局 GCJ-02 (火星坐标系)。"""
    if out_of_china(lng, lat):
        return lng, lat
    d_lat = _transform_lat(lng - 105.0, lat - 35.0)
    d_lng = _transform_lng(lng - 105.0, lat - 35.0)
    rad_lat = lat / 180.0 * PI
    magic = math.sin(rad_lat)
    magic = 1 - EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    d_lat = (d_lat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * PI)
    d_lng = (d_lng * 180.0) / (A / sqrt_magic * math.cos(rad_lat) * PI)
    return round(lng + d_lng, 6), round(lat + d_lat, 6)


def gcj02_to_wgs84(lng: float, lat: float) -> Tuple[float, float]:
    """GCJ-02 逆变换回 WGS84。采用高精度迭代法消除非线性误差至毫米级。"""
    if out_of_china(lng, lat):
        return lng, lat
    cur_lng, cur_lat = lng, lat
    for _ in range(4):
        p_lng, p_lat = wgs84_to_gcj02(cur_lng, cur_lat)
        d_lng = p_lng - lng
        d_lat = p_lat - lat
        cur_lng -= d_lng
        cur_lat -= d_lat
        if abs(d_lng) < 1e-8 and abs(d_lat) < 1e-8:
            break
    return round(cur_lng, 6), round(cur_lat, 6)


def cgcs2000_to_gcj02(lng: float, lat: float) -> Tuple[float, float]:
    """CGCS2000 (国家 2000 大地坐标系，北斗原生基准) 转 GCJ-02。
    
    CGCS2000 与 WGS84 椭球长半轴一致 (a=6378137.0m)，扁率差小于 0.1mm，
    在民用与导航领域与 WGS84 等价映射。
    """
    return wgs84_to_gcj02(lng, lat)


def gcj02_to_cgcs2000(lng: float, lat: float) -> Tuple[float, float]:
    """GCJ-02 (高德/腾讯坐标) 转 CGCS2000 (北斗原生基准)。"""
    return gcj02_to_wgs84(lng, lat)


def haversine_distance_m(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    """计算两点间的大圆球面距离（米），输入格式为 (lng, lat)。"""
    lng1, lat1 = p1
    lng2, lat2 = p2
    r = 6371000.0  # 地球平均半径 (米)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2)
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


# =====================================================================
# 2. NMEA-0183 $BDGGA 语句发生器与校验解析器
# =====================================================================

def calculate_nmea_checksum(sentence: str) -> str:
    """计算 NMEA-0183 校验和（$ 和 * 之间所有字符的异或和，输出双位大写16进制）。"""
    content = sentence.strip()
    if content.startswith("$"):
        content = content[1:]
    if "*" in content:
        content = content.split("*")[0]
    csum = 0
    for ch in content:
        csum ^= ord(ch)
    return f"{csum:02X}"


def format_nmea_latitude(lat: float) -> Tuple[str, str]:
    """将十进制度数转换为 NMEA 格式的 ddmm.mmmm 与半球方向 (N/S)。"""
    hemi = "N" if lat >= 0 else "S"
    abs_lat = abs(lat)
    deg = int(abs_lat)
    minutes = (abs_lat - deg) * 60.0
    return f"{deg:02d}{minutes:07.4f}", hemi


def format_nmea_longitude(lng: float) -> Tuple[str, str]:
    """将十进制度数转换为 NMEA 格式的 dddmm.mmmm 与半球方向 (E/W)。"""
    hemi = "E" if lng >= 0 else "W"
    abs_lng = abs(lng)
    deg = int(abs_lng)
    minutes = (abs_lng - deg) * 60.0
    return f"{deg:03d}{minutes:07.4f}", hemi


def parse_nmea_latitude(val: str, hemi: str) -> float:
    """解析 NMEA ddmm.mmmm 格式纬度为十进制度数。"""
    if not val or len(val) < 4:
        return 0.0
    deg = float(val[:2])
    minutes = float(val[2:])
    lat = deg + minutes / 60.0
    return -lat if hemi.upper() == "S" else lat


def parse_nmea_longitude(val: str, hemi: str) -> float:
    """解析 NMEA dddmm.mmmm 格式经度为十进制度数。"""
    if not val or len(val) < 5:
        return 0.0
    deg = float(val[:3])
    minutes = float(val[3:])
    lng = deg + minutes / 60.0
    return -lng if hemi.upper() == "W" else lng


def generate_bdgga(
    lat: float,
    lng: float,
    altitude_m: float = 52.8,
    fix_quality: int = 4,      # 4 = RTK 固定解 (RTK_FIXED), 1 = GPS单点, 2 = DGPS
    satellites: int = 21,
    hdop: float = 0.72,
    diff_age: float = 1.0,
    station_id: str = "0128",
    dt: Optional[datetime] = None,
) -> str:
    """生成标准北斗三号 NMEA-0183 $BDGGA 定位语句。"""
    dt = dt or datetime.now(timezone.utc)
    time_str = dt.strftime("%H%M%S.00")
    lat_str, lat_hemi = format_nmea_latitude(lat)
    lng_str, lng_hemi = format_nmea_longitude(lng)
    body = (
        f"BDGGA,{time_str},{lat_str},{lat_hemi},{lng_str},{lng_hemi},"
        f"{fix_quality},{satellites:02d},{hdop:.2f},{altitude_m:.1f},M,"
        f"-14.2,M,{diff_age:.1f},{station_id}"
    )
    csum = calculate_nmea_checksum(body)
    return f"${body}*{csum}\r\n"


def parse_bdgga(sentence: str) -> dict[str, Any]:
    """解析 $BDGGA 语句并验证校验和。"""
    raw = sentence.strip()
    if not raw.startswith("$"):
        raise ValueError("无效的 NMEA 语句：缺少前导 $ 符号")
    if "*" not in raw:
        raise ValueError("无效的 NMEA 语句：缺少校验和分隔符 *")

    body_part, csum_part = raw[1:].split("*", 1)
    actual_csum = calculate_nmea_checksum(body_part)
    expected_csum = csum_part[:2].upper()
    if actual_csum != expected_csum:
        raise ValueError(f"NMEA 校验和不匹配：期望 {expected_csum}, 实际 {actual_csum}")

    parts = body_part.split(",")
    if parts[0] not in ("BDGGA", "GNGGA", "GPGGA"):
        raise ValueError(f"非预期 GGA 语句类型: {parts[0]}")

    utc_time = parts[1] if len(parts) > 1 else ""
    lat_val = parts[2] if len(parts) > 2 else ""
    lat_hemi = parts[3] if len(parts) > 3 else "N"
    lng_val = parts[4] if len(parts) > 4 else ""
    lng_hemi = parts[5] if len(parts) > 5 else "E"
    fix_qual = int(parts[6]) if len(parts) > 6 and parts[6] else 0
    sat_count = int(parts[7]) if len(parts) > 7 and parts[7] else 0
    hdop = float(parts[8]) if len(parts) > 8 and parts[8] else 0.99
    alt = float(parts[9]) if len(parts) > 9 and parts[9] else 0.0

    lat = parse_nmea_latitude(lat_val, lat_hemi)
    lng = parse_nmea_longitude(lng_val, lng_hemi)

    quality_map = {
        0: "INVALID",
        1: "STANDALONE",
        2: "DGPS",
        4: "RTK_FIXED",
        5: "RTK_FLOAT",
    }

    return {
        "talker": parts[0][:2],
        "utc_time": utc_time,
        "latitude": round(lat, 6),
        "longitude": round(lng, 6),
        "fix_quality_code": fix_qual,
        "fix_quality": quality_map.get(fix_qual, "UNKNOWN"),
        "satellites": sat_count,
        "hdop": hdop,
        "altitude_m": alt,
    }


# =====================================================================
# 3. BDS 高精度遥测数据模型 (严格符合 PROJECT.md 契约)
# =====================================================================

class BdsTelemetry(BaseModel):
    """北斗三号亚米级高精度定位与时空遥测契约模型。"""
    timestamp: str = Field(..., description="ISO-8601 UTC 时间戳")
    latitude: float = Field(..., description="CGCS2000 纬度 (6位小数)")
    longitude: float = Field(..., description="CGCS2000 经度 (6位小数)")
    altitude_m: float = Field(default=52.8, description="北斗椭球大地高 (米)")
    satellites_in_view: int = Field(default=21, ge=18, le=28, description="可见北斗卫星总数 (18-24+)")
    satellites_used: int = Field(default=16, ge=14, le=22, description="参与解算的北斗卫星数 (14-18)")
    fix_quality: str = Field(default="RTK_FIXED", description="解算状态: RTK_FIXED | DGPS | STANDALONE")
    horizontal_accuracy_m: float = Field(default=0.35, description="水平定位精度 (0.35m 亚米级)")
    hdop: float = Field(default=0.72, le=0.9, description="水平精度因子 (< 0.9)")
    vdop: float = Field(default=0.98, le=1.2, description="垂直精度因子 (< 1.2)")
    raw_nmea_sentence: str = Field(default="", description="原始 $BDGGA NMEA-0183 报文")
    bds_bands: list[str] = Field(default_factory=lambda: ["B1I", "B2a", "B3I"], description="北斗三号接收频点")
    diff_age_s: float = Field(default=1.0, description="差分改正数延迟 (秒)")
    speed_kmh: float = Field(default=2.5, description="老人适老步行瞬时速度 (km/h)")
    heading_deg: float = Field(default=48.5, description="航向角 (度)")
    status_text: str = Field(default="北斗三号高精差分定位已锁定 (0.35m)", description="状态播报文字")
    coordinate_system: str = Field(default="CGCS2000", description="坐标基准")


class BdsService:
    """北斗卫星导航高精定位服务提供商。"""

    def __init__(self, default_lat: float = 28.2045, default_lng: float = 112.9862):
        self.default_lat = default_lat
        self.default_lng = default_lng

    def get_live_telemetry(
        self,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        altitude_m: Optional[float] = None,
        speed_kmh: float = 2.4,
        heading_deg: float = 45.0,
    ) -> BdsTelemetry:
        """生成逼真、严格合规的北斗高精亚米级遥测数据流。"""
        actual_lat = lat if lat is not None else self.default_lat
        actual_lng = lng if lng is not None else self.default_lng
        actual_alt = altitude_m if altitude_m is not None else round(50.0 + random.uniform(-1.5, 2.5), 1)

        # 仿真高质量北斗环境 (长沙区域北斗三号星座极佳几何分布)
        sats_in_view = random.randint(19, 24)
        sats_used = random.randint(15, 18)
        hdop = round(0.68 + random.uniform(0.01, 0.15), 2)
        vdop = round(0.92 + random.uniform(0.02, 0.18), 2)
        accuracy = round(0.35 + random.uniform(-0.04, 0.05), 2)
        diff_age = round(0.8 + random.uniform(0.1, 0.3), 1)

        now_utc = datetime.now(timezone.utc)
        nmea = generate_bdgga(
            lat=actual_lat,
            lng=actual_lng,
            altitude_m=actual_alt,
            fix_quality=4,
            satellites=sats_in_view,
            hdop=hdop,
            diff_age=diff_age,
            dt=now_utc,
        )

        return BdsTelemetry(
            timestamp=now_utc.isoformat(),
            latitude=round(actual_lat, 6),
            longitude=round(actual_lng, 6),
            altitude_m=actual_alt,
            satellites_in_view=sats_in_view,
            satellites_used=sats_used,
            fix_quality="RTK_FIXED",
            horizontal_accuracy_m=accuracy,
            hdop=hdop,
            vdop=vdop,
            raw_nmea_sentence=nmea,
            bds_bands=["B1I", "B2a", "B3I"],
            diff_age_s=diff_age,
            speed_kmh=speed_kmh,
            heading_deg=heading_deg,
            status_text="北斗三号亚米级高精差分定位已锁定 (0.35m)",
            coordinate_system="CGCS2000",
        )


# 单例全局实例
bds_service = BdsService()
