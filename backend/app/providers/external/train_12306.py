"""火车票 Provider（演示 Mock：12306；正式落地对接 12306 官方接口/授权分销）。"""
from __future__ import annotations

import asyncio
import random

from app.providers.external.base import derive_no, load_fixture, resolve_date


class TrainProvider:
    async def search(self, from_city: str, to_city: str,
                     date: str | None = None) -> list[dict]:
        raise NotImplementedError

    async def book(self, train_no: str, date: str | None, passenger: str,
                   seat_type: str = "二等座") -> dict:
        raise NotImplementedError


class MockTrainProvider(TrainProvider):
    name = "mock_train"

    async def search(self, from_city: str, to_city: str,
                     date: str | None = None) -> list[dict]:
        await asyncio.sleep(random.uniform(0.2, 0.5))
        data = load_fixture("trains")
        fc_clean = (from_city or "").replace("市", "").strip()
        tc_clean = (to_city or "").replace("市", "").strip()
        for route in data["routes"]:
            rfc = route["from_city"].replace("市", "").strip()
            rtc = route["to_city"].replace("市", "").strip()
            fc_match = (route["from_city"] == from_city or fc_clean == rfc or (fc_clean and fc_clean in rfc) or (rfc and rfc in fc_clean))
            tc_match = (route["to_city"] == to_city or tc_clean == rtc or (tc_clean and tc_clean in rtc) or (rtc and rtc in tc_clean))
            if fc_match and tc_match:
                date_iso = resolve_date(date)
                return [
                    {
                        "train_no": t["train_no"], "date": date_iso,
                        "from_station": route["from_station"],
                        "to_station": route["to_station"],
                        "depart": t["depart"], "arrive": t["arrive"],
                        "duration": t["duration"], "seats": t["seats"],
                    }
                    for t in route["trains"]
                ]
        return []

    async def book(self, train_no: str, date: str | None, passenger: str,
                   seat_type: str = "二等座") -> dict:
        await asyncio.sleep(random.uniform(0.4, 1.0))
        data = load_fixture("trains")
        for route in data["routes"]:
            for t in route["trains"]:
                if t["train_no"] == train_no:
                    seat = next((s for s in t["seats"]
                                 if s["seat_type"] == seat_type), t["seats"][0])
                    date_iso = resolve_date(date)
                    ticket_no = derive_no("E", train_no, date_iso, passenger, seat_type)
                    carriage = 3 + int(ticket_no[-1]) % 12
                    seat_no = f"{1 + int(ticket_no[-2]) % 18:02d}{'ABCDF'[int(ticket_no[-3]) % 5]}"
                    return {
                        "ok": True,
                        "ticket_no": ticket_no,
                        "train_no": train_no, "date": date_iso,
                        "from_station": route["from_station"],
                        "to_station": route["to_station"],
                        "depart": t["depart"], "arrive": t["arrive"],
                        "seat": f"{carriage}号车厢 {seat_no}（{seat_type}）",
                        "price": seat["price"],
                        "passenger": passenger,
                        "announce": (f"票买好啦！{date_iso} {train_no} 次，"
                                     f"{carriage}号车厢 {seat_no}，"
                                     f"{t['depart']} 从{route['from_station']}发车。"
                                     f"别迟到了，提前半小时到站。"),
                    }
        return {"ok": False, "error": f"未找到车次 {train_no}"}


class RealTrainProvider(TrainProvider):
    """正式版：对接 12306 出票接口（需企业资质）。"""

    name = "real_train"
