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
        out = [
            h for h in data["hotels"]
            if h["city"] == city
            and (not near_hospital or h["near_hospital"] == near_hospital)
            and (not accessible or h["accessible"])
        ]
        return sorted(out, key=lambda h: h["distance_m"])

    async def book(self, hotel_name: str, checkin: str | None, nights: int = 1,
                   guest: str = "") -> dict:
        await asyncio.sleep(random.uniform(0.4, 0.8))
        data = load_fixture("hotels")
        for h in data["hotels"]:
            if h["name"] == hotel_name:
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

# 演示用静态坐标（南京 → 北京 关键点位，供子女端守护地图画线）
_ROUTE_POINTS = [
    {"location": "家（南京鼓楼区）", "lng": 118.77, "lat": 32.06},
    {"location": "南京南站", "lng": 118.79, "lat": 31.97},
    {"location": "济南西站", "lng": 116.90, "lat": 36.66},
    {"location": "北京南站", "lng": 116.37, "lat": 39.86},
    {"location": "北京积水潭医院", "lng": 116.37, "lat": 39.94},
]


class MapProvider:
    async def plan_route(self, origin: str, destination: str) -> dict:
        raise NotImplementedError


class MockMapProvider(MapProvider):
    name = "mock_map"

    async def plan_route(self, origin: str, destination: str) -> dict:
        await asyncio.sleep(random.uniform(0.2, 0.4))
        points = [p for p in _ROUTE_POINTS
                  if origin in p["location"] or destination in p["location"]
                  or p["location"] == "济南西站"]
        return {
            "ok": True, "origin": origin, "destination": destination,
            "polyline": points,
            "summary": f"从{origin}到{destination}：高铁直达，全程约4小时20分钟。",
        }


# ---------------------------------------------------------------- 叫车

class RideProvider:
    async def hail(self, origin: str, destination: str) -> dict:
        raise NotImplementedError


class MockRideProvider(RideProvider):
    name = "mock_ride"
    _PLATES = ["苏A88888", "苏A66666", "苏A12345"]

    async def hail(self, origin: str, destination: str) -> dict:
        await asyncio.sleep(3.0)  # 模拟司机接单等待
        plate = self._PLATES[int(hashlib.md5(origin.encode()).hexdigest()[0], 16) % 3]
        return {
            "ok": True,
            "order_no": derive_no("D", origin, destination, date.today()),
            "driver": "王师傅", "plate": plate, "rating": 4.9,
            "eta_min": 5,
            "announce": f"车叫好啦！王师傅的车（{plate}）5分钟到，"
                        f"从{origin}去{destination}。到车了他会给您打电话。",
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
