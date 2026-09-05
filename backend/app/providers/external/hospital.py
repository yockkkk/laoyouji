"""医院挂号 Provider（演示 Mock：内置三甲医院/科室/号源；正式落地对接挂号平台开放 API）。"""
from __future__ import annotations

import asyncio
import random

from app.providers.external.base import derive_no, load_fixture, resolve_date


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
        out = []
        city_clean = (city or "").replace("市", "").strip()
        dep_clean = (department or "").replace("科", "").strip()
        for h in data["hospitals"]:
            h_city = h["city"].replace("市", "").strip()
            if city_clean and (city_clean not in h_city and h_city not in city_clean):
                continue
            for dep in h["departments"]:
                d_name = dep["name"]
                if not department or department in d_name or d_name in department or (dep_clean and dep_clean in d_name):
                    out.append({
                        "hospital": h["name"], "level": h["level"],
                        "specialty": h["specialty"], "address": h["address"],
                        "city": h["city"],
                        "accessible": h["accessible"],
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
                if department not in dep["name"] and dep["name"] not in department:
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
