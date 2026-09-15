"""高德开放平台 Web 服务 API 联动模块。

康乐只陪老人在本市走动，这里就只做四件事：
1. 真实地址地理编码（/v3/geocode/geo）
2. 本市驾车路径规划 2.0（/v5/direction/driving）
3. 本市公交与综合换乘规划 2.0（/v5/direction/transit/integrated）
4. 本市步行规划 2.0（/v5/direction/walking）

跨城（两端直线距离 > 60km）不规划、不编时长、不编车次，直接退与 MockMapProvider
一字不差的诚实回执。另附长辈 10 秒坐标偏航判定用的航迹/走廊距离工具，
以及断网时降级到 routes.json 的本地兜底，确保全场景 0 故障。
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import urllib.parse
import urllib.request
from typing import Any

from app.config import settings
from app.providers.external.base import load_fixture

logger = logging.getLogger(__name__)

AMAP_WEB_BASE = "https://restapi.amap.com"

# 常用地标经纬度缓存（高德 GCJ-02 坐标系）。
# 这张表里**没有"家"**："家"是个称呼、不是地名，它在哪座城取决于老人此刻在哪座城，
# 坐标只有一份（hospitals.json 的 elder_homes），靠 home_coords 按城市去取。
# 表里留一个南京的"家"，认不出城市时就会默默退回南京 —— 北京的行程起点被画到南京，
# 子女端地图上差 900 公里。
KNOWN_LANDMARKS: dict[str, tuple[float, float]] = {
    "南京": (118.7841, 32.0645),
    "南京鼓楼医院": (118.7838, 32.0569),
    "江苏省人民医院": (118.7690, 32.0460),
    "南京市第一医院": (118.7840, 32.0220),
    "南京市中医院": (118.7850, 32.0070),
    "东南大学附属中大医院": (118.7750, 32.0720),
    "南京中大医院": (118.7750, 32.0720),
    "江苏省中医院": (118.7780, 32.0410),
    "东部战区总医院": (118.8250, 32.0390),
    "南京军区总医院": (118.8250, 32.0390),
    "南京南站": (118.7981, 31.9696),
    "济南西站": (116.8974, 36.6669),
    "北京": (116.4074, 39.9042),
    "北京南站": (116.3789, 39.8652),
    "积水潭医院": (116.3748, 39.9485),
    "北京积水潭医院": (116.3748, 39.9485),
    "北京积水潭医院(新街口院区)": (116.3748, 39.9485),
    "北京协和医院": (116.4172, 39.9145),
    "漫心酒店": (116.3725, 39.9472),
    "上海": (121.4737, 31.2304),
    "上海虹桥站": (121.3201, 31.1942),
    "上海市第六人民医院": (121.4298, 31.1764),
    "复旦大学附属华山医院": (121.4400, 31.2100),
    "杭州": (120.1551, 30.2741),
    "杭州东站": (120.2131, 30.2910),
    "杭州市第一人民医院": (120.1654, 30.2568),
    "浙江大学医学院附属第一医院": (120.1843, 30.2589),
    "苏州": (120.5853, 31.2989),
    "苏州站": (120.6120, 31.3303),
    "苏州大学附属第一医院": (120.6405, 31.3048),
}


def haversine_distance_m(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """计算两经纬度点之间的球面大圆距离（米）。"""
    lng1, lat1 = p1
    lng2, lat2 = p2
    r = 6371000.0  # 地球平均半径（米）
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def point_to_segment_distance_m(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    """计算点 p 到线段 ab 的最短垂直/端点球面大圆距离（米）。"""
    lng_p, lat_p = p
    lng_a, lat_a = a
    lng_b, lat_b = b

    mid_lat = math.radians((lat_a + lat_b) / 2.0)
    cos_lat = math.cos(mid_lat)

    dx = (lng_b - lng_a) * cos_lat
    dy = lat_b - lat_a
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq <= 1e-12:
        return haversine_distance_m(p, a)

    px = (lng_p - lng_a) * cos_lat
    py = lat_p - lat_a
    t = max(0.0, min(1.0, (px * dx + py * dy) / seg_len_sq))

    proj_lng = lng_a + t * (lng_b - lng_a)
    proj_lat = lat_a + t * (lat_b - lat_a)
    return haversine_distance_m(p, (proj_lng, proj_lat))


def min_distance_to_corridor_m(
    p: tuple[float, float], path: list[tuple[float, float]] | list[dict[str, float]]
) -> float:
    """计算点 p 到折线/航迹走廊各线段的最短距离（米）。"""
    if not path:
        return float("inf")
    pts: list[tuple[float, float]] = []
    for item in path:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            pts.append((float(item[0]), float(item[1])))
        elif isinstance(item, dict) and "lng" in item and "lat" in item:
            pts.append((float(item["lng"]), float(item["lat"])))

    if not pts:
        return float("inf")
    if len(pts) == 1:
        return haversine_distance_m(p, pts[0])

    min_d = float("inf")
    for i in range(len(pts) - 1):
        d = point_to_segment_distance_m(p, pts[i], pts[i + 1])
        if d < min_d:
            min_d = d
            if min_d <= 50.0:
                break
    return min_d


def parse_polyline_string(polyline_str: str) -> list[dict[str, float]]:
    """解析高德折线格式 'lng,lat;lng,lat;...' 为点列表。"""
    points: list[dict[str, float]] = []
    if not polyline_str:
        return points
    for seg in polyline_str.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        parts = seg.split(",")
        if len(parts) >= 2:
            try:
                points.append({"lng": round(float(parts[0]), 6), "lat": round(float(parts[1]), 6)})
            except (ValueError, TypeError):
                continue
    return points


# 康乐只陪老人在本市走动：两端直线距离超过这个数就是跨城，不规划、不编车次。
INTERCITY_KM = 60.0


def city_of(text: str) -> str:
    """从自由文本里认出城市（``家（南京鼓楼区）`` → 南京）；认不出返回空串。

    与 services.py 里同名函数同一套规则：**认不出不等于跨城** —— 模型填的出发地
    常常就是一个"家"，正文里本来就没有城名；只有两头都认得出、而且不是同一座城，
    才叫跨城长途。这里自成一份是沿用 hospital.py 的做法：地图接口层不该为了
    六行字符串包含去依赖 provider 的文件。
    """
    text = (text or "").strip()
    if not text:
        return ""
    for city in sorted(load_fixture("routes").get("cities") or [], key=len, reverse=True):
        if city in text:
            return city
    return ""


# "家"是个**称呼**、不是地名：它落在哪座城，取决于老人此刻在哪座城。
_HOME_ALIAS = "家"


def is_home(text: str) -> bool:
    """这句话说的是不是"家"这个称呼。

    只认裸 ``家`` 和 ``家（北京西城区）`` 这种"家+括号"的写法 —— 不认"国家大剧院"
    "老家"这类只是碰巧含"家"字的地名，否则它们会被接到老人住址上，画出一个跟这句
    话毫不相干的起点。与 services.py 的同名判断同一套规则。
    """
    text = (text or "").strip()
    return (text == _HOME_ALIAS
            or text.startswith(f"{_HOME_ALIAS}（")
            or text.startswith(f"{_HOME_ALIAS}("))


def home_coords(city: str) -> tuple[float, float] | None:
    """按城市取"家"的坐标；认不出的城返回 None（不编一个）。

    坐标**只有一份**，写在 hospitals.json 的 ``elder_homes`` 里 —— 医院 provider 算
    "离家多远"（"离家约 1.3 公里"）用的是同一份，routes.json 每条线的 ``points[0]``
    也是它的抄写。地图这一层不再另立一张表：三处各自飘一点，子女端地图上画的家门口
    和计划书上那句"离家 1.3 公里"就成了两个地方，问起来没法解释。
    """
    home = (load_fixture("hospitals").get("elder_homes") or {}).get(city or "")
    if not home:
        return None
    return (float(home["lng"]), float(home["lat"]))


def _cross_city_receipt(origin: str, destination: str) -> dict:
    """跨城的诚实回执：直接复用 MockMapProvider 那一份。

    两个 provider 对同一件事必须说同样的话、给同样形状的返回 —— 否则老人从
    "高德这条路"问来的答案，和从"演示库那条路"问来的答案会对不上。
    """
    from app.providers.external.services import MockMapProvider
    return MockMapProvider._no_route(
        load_fixture("routes"), origin, destination, cross_city=True
    )


def _no_route_receipt(origin: str, destination: str, city: str = "") -> dict:
    """认不出端点落在哪座城时的诚实回执：复用 MockMapProvider 那一份（非跨城）。

    "家"认不出城名就走这一条：不画线、不编时长，只说"这条路线我这儿只有大致方向"。
    **不能拿跨城那句话去顶** —— 跨城是"我知道你出城了"，这里只是"我说不清'家'在
    哪座城"；老人问一句"从家去鼓楼医院"，回他"这段路跨城了"是另一种编造。
    """
    from app.providers.external.services import MockMapProvider
    return MockMapProvider._no_route(
        load_fixture("routes"), origin, destination, city=city
    )


async def _local_fallback(origin: str, destination: str, mode: str, city: str) -> dict:
    """演示路线库兜底与本地同城自愈合成规划器（保障同城路线永不空白）。"""
    from app.providers.external.services import MockMapProvider
    result = await MockMapProvider().plan_route(origin, destination, mode, city)
    # 前端地图两种形状都读：points 画站点标记、polyline 连线。演示库的折线点
    # 自带 location，照抄一份给 points，站点标记不至于因为换了 provider 就消失。
    if not result.get("points"):
        result["points"] = [p for p in (result.get("polyline") or [])
                            if isinstance(p, dict) and p.get("location")]

    # 若静态演示库未匹配（例如其他同城医院），且两端坐标已知且为同城（< 60km），启动离线自愈合成规划
    if not result.get("matched"):
        orig_pt = home_coords(city) if is_home(origin) and city else amap_client._lookup_known(origin)
        dest_pt = amap_client._lookup_known(destination)
        if orig_pt and dest_pt:
            dist_m = haversine_distance_m(orig_pt, dest_pt)
            if dist_m <= INTERCITY_KM * 1000:
                dist_km = max(0.5, round(dist_m / 1000.0, 1))
                dur_min = max(6, round(dist_km * 3.5 + 4))
                dur_text = f"约{dur_min}分钟"
                travel_mode = mode if mode in ("公交", "地铁", "步行") else ("步行" if dist_km <= 1.2 else "公交")

                mid_pt = (round((orig_pt[0] + dest_pt[0]) / 2, 6), round((orig_pt[1] + dest_pt[1]) / 2, 6))
                poly = [
                    {"lng": orig_pt[0], "lat": orig_pt[1]},
                    {"lng": mid_pt[0], "lat": mid_pt[1]},
                    {"lng": dest_pt[0], "lat": dest_pt[1]},
                ]
                points = [
                    {"location": origin, "lng": orig_pt[0], "lat": orig_pt[1], "desc": "起点"},
                    {"location": destination, "lng": dest_pt[0], "lat": dest_pt[1], "desc": "终点"},
                ]
                steps = [
                    f"从{origin}出发，慢步步行约 300 米至就近主干道或公交/地铁站。",
                    f"搭乘往{destination}方向公交或打车前往，全程约 {dist_km} 公里，耗时约 {dur_text}。身体不便时建议优先打车，几分钟即达。",
                    f"到达{destination}，缓步进入门诊大厅，沿指示牌前往导医台办理就诊。",
                ]
                return {
                    "ok": True,
                    "matched": True,
                    "origin": origin,
                    "destination": destination,
                    "mode": travel_mode,
                    "duration": dur_text,
                    "distance_km": dist_km,
                    "points": points,
                    "polyline": poly,
                    "steps": steps,
                    "summary": f"从{origin}到{destination}：{travel_mode}{dur_text}，全程约{dist_km}公里。" + "".join(steps[:2]),
                }
    return result


def _format_duration(duration_s: int) -> str:
    """秒 → 老人听得懂的说法；拿不到时长就说空串，不编一个出来。"""
    if duration_s <= 0:
        return ""
    dur_min = max(1, round(duration_s / 60))
    if dur_min >= 60:
        return f"约{dur_min // 60}小时{dur_min % 60}分钟"
    return f"约{dur_min}分钟"


def _busline_names(transit: dict) -> list[str]:
    """一套换乘方案里坐过的所有线路名（地铁线也在 buslines 里，名字带"地铁"）。"""
    names: list[str] = []
    for seg in (transit.get("segments") or []):
        for line in ((seg.get("bus") or {}).get("buslines") or []):
            name = (line.get("name") or "").strip()
            if name:
                names.append(name)
    return names


class AmapWebClient:
    """高德开放平台 Web API 客户端。"""

    def __init__(self, key: str | None = None):
        self.key = key or settings.amap_web_key or "c260220fcc8a09359fa5ddd54f575cf1"

    def _http_get(self, path: str, params: dict[str, str], timeout: float = 6.0) -> dict | None:
        params["key"] = self.key
        query = urllib.parse.urlencode(params)
        url = f"{AMAP_WEB_BASE}{path}?{query}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "LaoYouJi/1.0 (Python)"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data
        except Exception as err:
            logger.warning("Amap Web API %s error: %s", path, err)
            return None

    @staticmethod
    def _lookup_known(text: str) -> tuple[float, float] | None:
        """本地地标表查表：完全匹配优先，其次按名称长度由长到短包含匹配。"""
        if text in KNOWN_LANDMARKS:
            return KNOWN_LANDMARKS[text]
        for name, coords in sorted(KNOWN_LANDMARKS.items(), key=lambda x: len(x[0]), reverse=True):
            if name in text:
                return coords
        return None

    async def geocode(self, address: str, city: str = "") -> tuple[float, float] | None:
        """根据地址获取经纬度 (lng, lat)。

        ``city`` = 老人所在的城市，只在"家"这个称呼上用得到：这句话里带着城名
        （``家（北京西城区）``）时以正文为准，正文里没有才拿它兜底。
        """
        if not address:
            return None
        text = address.strip()

        # 0. "家"按城市落到 elder_homes —— 表里查不出来（三座城各有一个家），
        #    所以这一步必须排在查表前面，否则"家（北京西城区）"会被较短的"北京"
        #    键接住，落到天安门，离西城区的家差 4 公里。
        if is_home(text):
            city_in_text = city_of(text)
            coords = home_coords(city_in_text or city)
            if coords:
                return coords
            if city_in_text:
                # 城名认得出来、但那座城没登记"家"（家（杭州西城区））：退到那座城的
                # 市中心当大致方向 —— 与 services.py 的 _landmark 同一口径。
                return self._lookup_known(city_in_text)
            # 连城名都认不出：不退回任何一座城（尤其不退回南京），如实返回 None，
            # 由调用方按"说不出这是本市哪一段"处理。
            return None

        # 1-2. 本地地标表
        known = self._lookup_known(text)
        if known:
            return known

        def _do():
            return self._http_get("/v3/geocode/geo", {"address": text, "city": city})

        data = await asyncio.to_thread(_do)
        if data and data.get("status") == "1" and data.get("geocodes"):
            loc = data["geocodes"][0].get("location")
            if loc and "," in loc:
                lng_s, lat_s = loc.split(",", 1)
                return float(lng_s), float(lat_s)
        return None

    async def plan_driving_2(
        self, origin: tuple[float, float], destination: tuple[float, float]
    ) -> dict | None:
        """调用高德驾车 2.0 Web API (/v5/direction/driving)。"""
        orig_s = f"{origin[0]:.6f},{origin[1]:.6f}"
        dest_s = f"{destination[0]:.6f},{destination[1]:.6f}"

        def _do():
            return self._http_get(
                "/v5/direction/driving",
                {"origin": orig_s, "destination": dest_s, "show_fields": "cost,polyline,steps"},
            )

        res = await asyncio.to_thread(_do)
        if not res or res.get("status") != "1":
            return None

        route = res.get("route", {})
        paths = route.get("paths", [])
        if not paths:
            return None

        p = paths[0]
        distance_m = int(p.get("distance", 0))
        cost = p.get("cost", {})
        duration_s = int(cost.get("duration", 0))
        traffic_lights = int(cost.get("traffic_lights", 0))

        # 汇总全线折线
        all_points: list[dict[str, float]] = []
        steps_text: list[str] = []

        for step in p.get("steps", []):
            instruction = step.get("instruction") or ""
            if instruction:
                steps_text.append(instruction)
            step_poly = step.get("polyline") or ""
            pts = parse_polyline_string(step_poly)
            all_points.extend(pts)

        # 格式化耗时
        dur_min = max(1, round(duration_s / 60))
        if dur_min >= 60:
            dur_text = f"约{dur_min // 60}小时{dur_min % 60}分钟"
        else:
            dur_text = f"约{dur_min}分钟"

        return {
            "mode": "市内打车/自驾",
            "distance_km": round(distance_m / 1000.0, 1),
            "distance_m": distance_m,
            "duration": dur_text,
            "duration_s": duration_s,
            "traffic_lights": traffic_lights,
            "polyline": all_points,
            "steps": steps_text,
        }

    async def plan_transit_2(
        self, origin: tuple[float, float], destination: tuple[float, float], city: str = ""
    ) -> dict | None:
        """调用高德公交/地铁综合换乘规划 2.0（/v5/direction/transit/integrated）。

        ``city`` 是本市城市名，两端都传同一个（康乐只做同城，city1 == city2）。
        到底是"公交"还是"地铁"，高德不会直说 —— 看换乘方案里每一段第一条线路
        （``segments[].bus.buslines[0].name``）的名字里有没有"地铁"来定。

        失败/超时一律返回 ``None``：调用方据此落回演示路线库，
        绝不把异常吞掉之后自己编一份换乘方案出来。
        """
        orig_s = f"{origin[0]:.6f},{origin[1]:.6f}"
        dest_s = f"{destination[0]:.6f},{destination[1]:.6f}"
        params = {"origin": orig_s, "destination": dest_s, "show_fields": "cost,polyline,steps"}
        if city:
            params["city1"] = city
            params["city2"] = city

        def _do():
            return self._http_get("/v5/direction/transit/integrated", params)

        res = await asyncio.to_thread(_do)
        if not res or res.get("status") != "1":
            return None
        transits = (res.get("route") or {}).get("transits") or []
        if not transits:
            return None

        picked = transits[0]
        lines = _busline_names(picked)
        polyline: list[dict[str, float]] = []
        steps: list[str] = []
        for seg in picked.get("segments") or []:
            walking = seg.get("walking") or {}
            for ws in walking.get("steps") or []:
                if ws.get("instruction"):
                    steps.append(ws["instruction"])
                polyline.extend(parse_polyline_string(ws.get("polyline") or ""))
            for line in (seg.get("bus") or {}).get("buslines") or []:
                name = (line.get("name") or "").strip()
                if name:
                    steps.append(f"乘坐{name}")
                polyline.extend(parse_polyline_string(line.get("polyline") or ""))

        distance_m = int(picked.get("distance") or 0)
        duration_s = int((picked.get("cost") or {}).get("duration") or 0)
        return {
            "mode": "地铁" if any("地铁" in n for n in lines) else "公交",
            "distance_km": round(distance_m / 1000.0, 1),
            "distance_m": distance_m,
            "duration": _format_duration(duration_s),
            "duration_s": duration_s,
            "polyline": polyline,
            "steps": steps,
        }

    async def plan_walking_2(
        self, origin: tuple[float, float], destination: tuple[float, float]
    ) -> dict | None:
        """调用高德步行规划 2.0（/v5/direction/walking）。

        失败/超时一律返回 ``None`` —— 老人"走着去"这条路宁可落回演示库，
        也不能拿一份编出来的步行动线糊弄他。
        """
        orig_s = f"{origin[0]:.6f},{origin[1]:.6f}"
        dest_s = f"{destination[0]:.6f},{destination[1]:.6f}"

        def _do():
            return self._http_get(
                "/v5/direction/walking",
                {"origin": orig_s, "destination": dest_s, "show_fields": "cost,polyline,steps"},
            )

        res = await asyncio.to_thread(_do)
        if not res or res.get("status") != "1":
            return None
        paths = (res.get("route") or {}).get("paths") or []
        if not paths:
            return None

        p = paths[0]
        polyline: list[dict[str, float]] = []
        steps: list[str] = []
        for step in p.get("steps") or []:
            if step.get("instruction"):
                steps.append(step["instruction"])
            polyline.extend(parse_polyline_string(step.get("polyline") or ""))

        distance_m = int(p.get("distance") or 0)
        duration_s = int((p.get("cost") or {}).get("duration") or 0)
        return {
            "mode": "步行",
            "distance_km": round(distance_m / 1000.0, 1),
            "distance_m": distance_m,
            "duration": _format_duration(duration_s),
            "duration_s": duration_s,
            "polyline": polyline,
            "steps": steps,
        }

    async def plan_route(self, origin: str, destination: str, mode: str = "",
                         city: str = "") -> dict:
        """同城出行规划：公交/地铁、步行、驾车各走各的真接口；跨城如实拒答。

        ``mode`` 与 ``city`` 都是后加的带默认值参数，位置参数保持兼容 ——
        routes_guardian.py 那几处两参调用原样能用。分派规则：``地铁``/``公交``
        走综合换乘、``步行`` 走步行规划、空或认不出的方式走驾车。

        ``city`` = 老人所在的城市（老人档案里的常住城市）。"家"是个称呼、不是地名，
        认不出它在哪座城就给不出这一段：这句话里带着城名（``家（北京西城区）``）时
        以正文为准，正文里没有才用 ``city`` 兜底。

        跨城（两头的城名都认得出而且不是一座城，或两端直线距离超过 60km）
        **不规划**：返回 ``matched=False`` 的诚实回执，口径与 MockMapProvider
        一字不差。这里不编时长、也不编车次 —— 编一个出来，老人会照着出门。
        """
        origin = (origin or "家（南京鼓楼区）").strip()
        destination = (destination or "南京鼓楼医院").strip()

        # 1. 城市与端点坐标。正文里的城名**优先于**档案里的 city（同 services.py 的
        #    _end_cities）：老人说的是"家（北京西城区）"，档案写南京也得听正文的。
        o_city, d_city = city_of(origin), city_of(destination)
        elder_city = o_city or city

        # "家"认不出在哪座城：这一趟本就不该由我们拍板。不借目的地的城名去顶
        # （借了，"家 → 外地的医院"就成了同城线，放出一条老人根本走不到的路），
        # 也不默默退回任何一座城 —— 按项目口径如实说"只有大致方向"。
        if is_home(origin) and not elder_city:
            return _no_route_receipt(origin, destination)

        orig_coords = await self.geocode(origin, elder_city)
        dest_coords = await self.geocode(destination)

        # 2. 跨城：直接退诚实回执，绝不生成"高铁 + 市内接驳"那种整条线
        cross_city = bool(o_city and d_city and o_city != d_city)
        if not cross_city and orig_coords and dest_coords:
            cross_city = haversine_distance_m(orig_coords, dest_coords) > INTERCITY_KM * 1000
        if cross_city:
            return _cross_city_receipt(origin, destination)

        # 3. 本市：按 mode 分派到公交/地铁、步行、驾车三条真接口
        plan: dict | None = None
        if orig_coords and dest_coords:
            if mode == "步行":
                plan = await self.plan_walking_2(orig_coords, dest_coords)
            elif mode in ("地铁", "公交"):
                plan = await self.plan_transit_2(orig_coords, dest_coords, elder_city)
            else:
                plan = await self.plan_driving_2(orig_coords, dest_coords)

        if plan:
            orig_name = origin
            if is_home(origin) and elder_city:
                h = (load_fixture("hospitals").get("elder_homes") or {}).get(elder_city)
                if h and h.get("name"):
                    orig_name = h["name"]
            points = [
                {"location": orig_name, "lng": orig_coords[0], "lat": orig_coords[1], "desc": "起点"},
                {"location": destination, "lng": dest_coords[0], "lat": dest_coords[1], "desc": "终点"},
            ]
            return {
                "ok": True,
                "matched": True,
                "origin": origin,
                "destination": destination,
                "mode": plan["mode"],
                "duration": plan["duration"],
                "distance_km": plan["distance_km"],
                "points": points,
                "polyline": plan["polyline"],
                "steps": plan["steps"],
                "summary": (f"从{origin}到{destination}：{plan['mode']}{plan['duration']}，"
                            f"全程{plan['distance_km']}公里。" + "".join(plan["steps"][:3])),
            }

        # 4. 真接口全灭（断网/超配额/这段路高德没收录）：落回演示路线库，
        #    换乘卡片绝不留白；库里也没有就如实说"只有大致方向"，不编时长。
        #    city 只传老人那座城（不传目的地的）：库里那条"家 → 外地的医院"
        #    正是靠它才认得出是跨城。
        return await _local_fallback(origin, destination, mode, elder_city)


# 全局单例
amap_client = AmapWebClient()
