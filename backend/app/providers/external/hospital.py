"""医院挂号 Provider（演示 Mock：内置三甲医院/科室/号源；正式落地对接挂号平台开放 API）。

"就近就医"要成立，医院列表就必须是**按离家远近排的**，而不是 fixture 里的书写
顺序：列表第一条会被 health_tools 拿去做默认推荐，也会印在《就医出行计划书》上。
所以每家医院在 hospitals.json 里都带 ``location``，每座城市都有一个 ``elder_homes``
参考点，距离由这里的 ``_haversine_km`` 现算。
"""
from __future__ import annotations

import asyncio
import math
import random

from app.providers.external.base import derive_no, load_fixture, resolve_date


def _haversine_km(a: dict, b: dict) -> float:
    """两个经纬度点之间的球面大圆距离（公里）。

    公式只有六行，所以在这里自成一份，不去 import amap_service 的 —— 医院
    provider 不该为了一个距离函数依赖地图 provider 的文件。
    """
    lng1, lat1, lng2, lat2 = a["lng"], a["lat"], b["lng"], b["lat"]
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    h = (math.sin(d_phi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return 6371.0 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _resolve_city(raw: str, cities: list[str]) -> str:
    """"南京市" / "南京鼓楼区" / "南京" 都认成 ``cities`` 里的"南京"；认不出返回空串。

    认不出就返回空串，调用方据此**宁可不给医院，也不跨城** —— 把北京的医院端给
    一个在苏州的老人，等于让他照着一条走不通的路出门。
    """
    text = (raw or "").replace("市", "").strip()
    if not text:
        return ""
    for city in sorted(cities, key=len, reverse=True):
        if city.replace("市", "") in text:
            return city
    return ""


def _city_home(data: dict, city_key: str) -> dict | None:
    """老人常住地的参考点（演示里固定写在 hospitals.json 的 ``elder_homes``）。

    这是"就近"的零点。真做要拿老人的实时定位（见 docs/FEASIBILITY.md），
    演示阶段用档案城市里的一个固定点，至少保证"近的排在前面"是有依据的。
    """
    return (data.get("elder_homes") or {}).get(city_key)


class HospitalProvider:
    async def search(self, city: str, department: str) -> list[dict]:
        raise NotImplementedError

    async def suggest_department(self, symptom: str) -> str | None:
        raise NotImplementedError

    async def register(self, hospital: str, department: str, doctor: str,
                       slot_date: str | None = None) -> dict:
        raise NotImplementedError


class MockHospitalProvider(HospitalProvider):
    name = "mock_hospital"

    async def search(self, city: str, department: str) -> list[dict]:
        await asyncio.sleep(random.uniform(0.2, 0.5))
        data = load_fixture("hospitals")
        cities = data.get("cities") or []
        raw = (city or "").strip()
        # 没给城市（""）→ 落回列表第一座城，与"默认北京"的历史行为一致；
        # 给了但认不出（"苏州""杭州"）→ 返回空，上游会如实说"没查到这个城市的医院"。
        city_key = _resolve_city(raw, cities) if raw else (cities[0] if cities else "")
        if raw and not city_key:
            return []
        home = _city_home(data, city_key)
        out = []
        dep_clean = (department or "").replace("科", "").strip()
        for h in data["hospitals"]:
            # 同城硬过滤：异地医院不是"远一点的选择"，是今天走不到的选择
            if city_key and h["city"] != city_key:
                continue
            distance = (round(_haversine_km(home, h["location"]), 1)
                        if home and h.get("location") else None)
            for dep in h["departments"]:
                d_name = dep["name"]
                if (not department or department in d_name or d_name in department
                        or (dep_clean and dep_clean in d_name)
                        or ("心血管" in department and "心内" in d_name)):
                    out.append({
                        "hospital": h["name"], "level": h["level"],
                        "specialty": h["specialty"], "address": h["address"],
                        "city": h["city"],
                        "accessible": h["accessible"],
                        # 离家多远：老人和模型看得懂的那句话，也是下面的排序键
                        "distance_km": distance,
                        "from_home": home["name"] if home else "",
                        "distance_text": (f"离家约 {distance} 公里"
                                          if distance is not None else ""),
                        "department": dep["name"],
                        "doctors": [
                            {
                                "doctor": d["name"], "title": d["title"],
                                "fee": d["fee"],
                                "slots": [
                                    {**s, "date": resolve_date(s["date"])}
                                    for s in d["slots"]
                                ],
                            }
                            for d in dep["doctors"]
                        ],
                    })
        # 就近排序：算不出距离的排最后，不混进"就近"里冒充近的
        out.sort(key=lambda e: e["distance_km"]
                 if e["distance_km"] is not None else float("inf"))
        return out

    async def suggest_department(self, symptom: str) -> str | None:
        mapping = load_fixture("hospitals")["symptom_to_department"]
        s_clean = symptom or ""
        for key, dep in mapping.items():
            if key in s_clean or (s_clean and s_clean in key):
                return dep
        return None

    async def register(self, hospital: str, department: str, doctor: str,
                       slot_date: str | None = None) -> dict:
        await asyncio.sleep(random.uniform(0.4, 0.9))
        data = load_fixture("hospitals")
        for h in data["hospitals"]:
            if h["name"] != hospital and hospital not in h["name"] and h["name"] not in hospital:
                continue
            for dep in h["departments"]:
                if (department not in dep["name"] and dep["name"] not in department
                        and not ("心血管" in department and "心内" in dep["name"])):
                    continue
                for d in dep["doctors"]:
                    if d["name"] == doctor or not doctor:
                        # 号源要按请求日期挑，不能一律拿第一个：否则"日期是 +3、
                        # 时段是第一个号的上午"这种自相矛盾会一路印到计划书上，
                        # 老人照着去就是白跑一趟。
                        when = resolve_date(slot_date) if slot_date else None
                        slot = next(
                            (s for s in d["slots"]
                             if resolve_date(s["date"]) == when),
                            None)
                        if slot is None and not when:
                            # 没指定日期 → 给最近的一个号，这不是替换，是默认
                            slot = d["slots"][0] if d["slots"] else None
                        if slot is None:
                            # 指定了日期却没号 —— 真实挂号平台此时就是"约不上"。
                            # 退到别的日子的时段等于替老人改了行程：宁可失败，
                            # 把有号的日子如实报回去，让上游重新挑。
                            avail = "、".join(
                                f"{resolve_date(s['date'])} {s['time']}"
                                for s in d["slots"]) or "近期暂未放号"
                            return {"ok": False,
                                    "error": (f"{d['name']}医生 {when} 没有号。"
                                              f"有号的时间：{avail}")}
                        when = when or resolve_date(slot["date"])
                        reg_no = derive_no("R", hospital, doctor, when)
                        return {
                            "ok": True,
                            "registration_no": reg_no,
                            "hospital": h["name"], "department": dep["name"],
                            "city": h["city"],
                            "doctor": d["name"], "title": d["title"],
                            "date": when, "time": slot["time"],
                            "fee": d["fee"],
                            "address": h["address"],
                            "announce": (f"号挂好啦！{h['name']} {dep['name']}，"
                                         f"{d['name']}医生，{when} {slot['time']}。"
                                         f"带上医保卡和身份证，直接去科室报到。"),
                        }
        return {"ok": False, "error": f"未找到 {hospital} {department} {doctor} 的号源"}


class RealHospitalProvider(HospitalProvider):
    """正式版：对接健康160/微医等挂号平台开放 API。"""

    name = "real_hospital"
