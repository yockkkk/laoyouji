"""酒店 / 天气 / 地图 / 叫车 / 支付 Provider（全部 Mock + Real 空壳）。"""
from __future__ import annotations

import asyncio
import hashlib
import random
from datetime import date

from app.providers.external.base import derive_no, load_fixture, resolve_date


# ---------------------------------------------------------------- 酒店

class HotelProvider:
    async def search(self, city: str, near_hospital: str | None = None,
                      accessible: bool = True) -> list[dict]:
        raise NotImplementedError

    async def book(self, hotel_name: str, checkin: str | None, nights: int = 1,
                   guest: str = "") -> dict:
        raise NotImplementedError


class MockHotelProvider(HotelProvider):
    name = "mock_hotel"

    async def search(self, city: str, near_hospital: str | None = None,
                      accessible: bool = True) -> list[dict]:
        await asyncio.sleep(random.uniform(0.2, 0.4))
        data = load_fixture("hotels")
        c_clean = (city or "").replace("市", "").strip()
        out = []
        for h in data["hotels"]:
            hc_clean = h["city"].replace("市", "").strip()
            if c_clean and (c_clean not in hc_clean and hc_clean not in c_clean):
                continue
            if near_hospital:
                nh = h.get("near_hospital", "")
                h_name = h.get("name", "")
                h_addr = h.get("address", "")
                near_clean = near_hospital.replace("附近", "").replace("周边", "").strip()
                if not (near_clean in nh or nh in near_clean or near_clean in h_name or near_clean in h_addr):
                    continue
            if accessible and not h["accessible"]:
                continue
            out.append(h)
        return sorted(out, key=lambda h: h["distance_m"])

    async def book(self, hotel_name: str, checkin: str | None, nights: int = 1,
                   guest: str = "") -> dict:
        await asyncio.sleep(random.uniform(0.4, 0.8))
        data = load_fixture("hotels")
        for h in data["hotels"]:
            if h["name"] == hotel_name or hotel_name in h["name"] or h["name"] in hotel_name:
                checkin_iso = resolve_date(checkin)
                total = h["price"] * max(1, nights)
                return {
                    "ok": True,
                    "order_no": derive_no("H", hotel_name, checkin_iso, nights),
                    "hotel": h["name"], "phone": h["phone"],
                    # 地址与步行距离是《就医出行计划书》第三页的必填项，
                    # 订房结果里就带上，免得渲染器去别处凑
                    "address": h["address"],
                    "distance_m": h["distance_m"], "walk_min": h["walk_min"],
                    "walk": f"步行约 {h['walk_min']} 分钟（{h['distance_m']} 米）",
                    "checkin": checkin_iso, "nights": nights,
                    "room_price": h["price"], "total": total,
                    "accessible_note": h["accessible_note"],
                    "announce": (f"酒店订好啦！{h['name']}，{checkin_iso} 入住，"
                                 f"住{nights}晚，一共 {total} 元。"
                                 f"离医院走路 {h['walk_min']} 分钟，有电梯。"),
                }
        return {"ok": False, "error": f"未找到酒店 {hotel_name}"}


# ---------------------------------------------------------------- 天气

class WeatherProvider:
    async def get(self, city: str, date_offset: str | int | None = None) -> dict:
        raise NotImplementedError


class MockWeatherProvider(WeatherProvider):
    name = "mock_weather"

    async def get(self, city: str, date_offset: str | int | None = None) -> dict:
        await asyncio.sleep(random.uniform(0.1, 0.3))
        data = load_fixture("weather")
        key = f"{city}|{resolve_date(date_offset)}"
        idx = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:6], 16) % len(data["templates"])
        t = data["templates"][idx]
        bias = data["city_bias"].get(city, 0)
        return {
            "ok": True, "city": city, "date": resolve_date(date_offset),
            "condition": t["condition"],
            "temp_low": t["temp_low"] + bias, "temp_high": t["temp_high"] + bias,
            # 计划书第五页直接印这一行，省得渲染器再拼一次
            "temp_range": f"{t['temp_low'] + bias}~{t['temp_high'] + bias} ℃",
            "advice": t["advice"], "umbrella": t["umbrella"],
        }


# ---------------------------------------------------------------- 地图 / 路线


def _mentions(text: str, name: str) -> bool:
    """"南京"、"南京南站"、"家（南京鼓楼区）" 指的可能是同一段路的同一头。

    地名的粒度是**模型说出口时才定的**：老人说"去北京"，模型可能填 ``北京``、
    ``北京南站``，也可能照抄上一步查到的 ``北京积水潭医院``。fixture 里只能写一种
    写法，按等号比对的话绝大多数说法都对不上 —— 对不上就没有路线，
    子智能体拿不到任何点位，子女端守护地图上是一条空线。
    """
    text, name = (text or "").strip(), (name or "").strip()
    if not text or not name:
        return False
    return name in text or text in name


def _landmark(landmarks: dict, text: str) -> dict | None:
    """把一个说法落到一个坐标点上。没有对应地标就返回 None（不编坐标）。

    挑选顺序是"越具体越优先"：``南京南站`` 里同时含着 ``南京``，
    此时该认站不该认市；反过来只说 ``南京`` 时，就退回市中心那个点。
    """
    text = (text or "").strip()
    if not text:
        return None
    exact = [n for n in landmarks if n == text]
    inside = sorted((n for n in landmarks if n in text), key=len, reverse=True)
    outside = sorted((n for n in landmarks if text in n), key=len)
    picks = exact or inside or outside
    if not picks:
        return None
    name = picks[0]
    return {"location": name, **landmarks[name]}


class MapProvider:
    async def plan_route(self, origin: str, destination: str) -> dict:
        raise NotImplementedError


class MockMapProvider(MapProvider):
    """演示路线库（data/routes.json）：跨城两条 + 市内两条，另附地标坐标兜底。

    旧实现把点位写死在模块常量里，并且**无论去哪都把济南西站塞进折线** ——
    从家到南京鼓楼医院这种市内两公里的路，画出来也要经过济南。
    现在济南西站只出现在它真正在途中的那条线上（南京→北京）。
    """

    name = "mock_map"

    async def plan_route(self, origin: str, destination: str) -> dict:
        await asyncio.sleep(random.uniform(0.2, 0.4))
        data = load_fixture("routes")
        for route in data["routes"]:
            if _mentions(origin, route["from"]) and _mentions(destination, route["to"]):
                return {
                    "ok": True, "matched": True,
                    "origin": origin, "destination": destination,
                    "mode": route["mode"], "duration": route["duration"],
                    "distance_km": route.get("distance_km"),
                    "polyline": route["points"],
                    "steps": route["steps"],
                    "summary": (f"从{origin}到{destination}：{route['mode']}，"
                                f"全程{route['duration']}。"
                                + "".join(route["steps"])),
                }

        # 库里没有这条线路：只画两头的直线，并且**说出来**没有详细走法。
        # 编一个"全程约4小时20分"比承认不知道糟糕得多 —— 老人会照着那个时间出门。
        ends = [pt for pt in (_landmark(data["landmarks"], origin),
                              _landmark(data["landmarks"], destination)) if pt]
        return {
            "ok": True, "matched": False,
            "origin": origin, "destination": destination,
            "mode": "", "duration": "", "distance_km": None,
            "polyline": ends, "steps": [],
            "summary": (f"从{origin}到{destination}：这条路线我这儿只有大致方向，"
                        f"具体怎么走、要多久，出门前问一下家里人或站里的工作人员。"),
        }


class AmapMapProvider(MapProvider):
    """高德开放平台地图服务：联动真实 Web API 2.0 规划路线，全场景降级兜底。"""

    name = "amap_map"

    async def plan_route(self, origin: str, destination: str) -> dict:
        from app.providers.external.amap_service import amap_client
        return await amap_client.plan_route(origin, destination)



# ---------------------------------------------------------------- 叫车

class RideProvider:
    async def hail(self, origin: str, destination: str) -> dict:
        raise NotImplementedError


class MockRideProvider(RideProvider):
    """演示司机库（data/rides.json，3 位师傅）。"""

    name = "mock_ride"

    async def hail(self, origin: str, destination: str) -> dict:
        await asyncio.sleep(3.0)  # 模拟司机接单等待
        drivers = load_fixture("rides")["drivers"]
        # 派单按"这一趟"算，不只看出发地：老人多半都是从家出发，
        # 只用 origin 的话每次都派同一位师傅、同一块车牌，演示里一眼假。
        key = f"{origin}|{destination}"
        idx = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16) % len(drivers)
        driver = drivers[idx]
        return {
            "ok": True,
            "order_no": derive_no("D", origin, destination, date.today()),
            "driver": driver["name"], "plate": driver["plate"],
            "car": driver.get("car", ""), "rating": driver["rating"],
            "eta_min": driver["eta_min"], "phone": driver.get("phone", ""),
            "note": driver.get("note", ""),
            "announce": (f"车叫好啦！{driver['name']}的车，{driver['car']}，"
                         f"车牌{driver['plate']}，{driver['eta_min']}分钟到，"
                         f"从{origin}去{destination}。到车了他会给您打电话。"),
        }


# ---------------------------------------------------------------- 支付

class PaymentProvider:
    async def pay(self, amount: float, subject: str, payer: str) -> dict:
        raise NotImplementedError


class MockPaymentProvider(PaymentProvider):
    name = "mock_payment"

    async def pay(self, amount: float, subject: str, payer: str) -> dict:
        await asyncio.sleep(random.uniform(0.5, 1.0))
        return {
            "ok": True,
            "transaction_no": derive_no("P", amount, subject, payer),
            "amount": amount, "subject": subject,
            "channel": "模拟支付（竞赛原型，未扣真实资金）",
        }
