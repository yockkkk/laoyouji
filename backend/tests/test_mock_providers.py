"""Mock Provider 确定性测试：同输入同输出（演示可复现、测试可断言）。"""
from __future__ import annotations

from app.providers.external.base import resolve_date
from app.providers.external.hospital import MockHospitalProvider
from app.providers.external.services import (
    MockHotelProvider,
    MockWeatherProvider,
)
from app.providers.external.train_12306 import MockTrainProvider


async def test_train_search_deterministic():
    p = MockTrainProvider()
    r1 = await p.search("南京", "北京", "tomorrow")
    r2 = await p.search("南京", "北京", "tomorrow")
    assert r1 == r2
    assert any(t["train_no"] == "G102" for t in r1)


async def test_train_book_deterministic():
    p = MockTrainProvider()
    t1 = await p.book("G102", "tomorrow", "张桂芳", "二等座")
    t2 = await p.book("G102", "tomorrow", "张桂芳", "二等座")
    assert t1["ticket_no"] == t2["ticket_no"]
    assert t1["price"] == 553.5
    assert t1["seat"].endswith("（二等座）")


async def test_train_book_different_passenger_different_ticket():
    p = MockTrainProvider()
    t1 = await p.book("G102", "tomorrow", "张桂芳", "二等座")
    t2 = await p.book("G102", "tomorrow", "李明", "二等座")
    assert t1["ticket_no"] != t2["ticket_no"]


async def test_weather_deterministic_by_city_date():
    p = MockWeatherProvider()
    w1 = await p.get("北京", "tomorrow")
    w2 = await p.get("北京", "tomorrow")
    assert w1 == w2
    w3 = await p.get("南京", "tomorrow")
    assert w3["city"] == "南京"


async def test_hospital_search_by_symptom_department():
    p = MockHospitalProvider()
    dep = await p.suggest_department("腿疼")
    assert dep == "骨科"
    hospitals = await p.search("北京", "骨科")
    assert any(h["hospital"] == "北京积水潭医院" for h in hospitals)


async def test_hospital_register():
    p = MockHospitalProvider()
    reg = await p.register("北京积水潭医院", "骨科", "田伟")
    assert reg["ok"] is True
    assert reg["fee"] == 100
    assert reg["doctor"] == "田伟"


async def test_hospital_register_picks_the_slot_on_the_asked_day():
    """要 +3 的号就得拿 +3 那个号 —— 日期和时段必须是同一天的。

    这一条守的是计划书第一页：``就诊时间`` 取 ``date``、``具体时段`` 取 ``time``。
    两者出自不同的号，纸上就会写着"周五去、上午的号是周三那个"。
    """
    p = MockHospitalProvider()
    reg = await p.register("北京积水潭医院", "骨科", "田伟", "+3")
    assert reg["ok"] is True
    assert reg["date"] == resolve_date("+3")
    slots = {resolve_date(s["date"]): s["time"]
             for s in (await p.search("北京", "骨科"))[0]["doctors"][0]["slots"]}
    assert reg["time"] == slots[resolve_date("+3")]


async def test_hospital_time_slots_never_name_a_weekday():
    """号源时段里不准写"周三" —— 日期是相对的，星期几只能算出来，不能写死。

    写死的那个词和 ``resolve_date`` 算出来的日子必然会打架，而这句话会被
    念给老人听、也会印在计划书上。时段只说上午/下午和钟点。
    """
    p = MockHospitalProvider()
    for hospital in await p.search("北京", "骨科"):
        for doc in hospital["doctors"]:
            for slot in doc["slots"]:
                assert "周" not in slot["time"], slot


async def test_hospital_register_fails_when_that_day_has_no_slot():
    """约不上就是约不上：退到别的日子等于替老人改了行程。"""
    p = MockHospitalProvider()
    reg = await p.register("北京积水潭医院", "骨科", "田伟", "+30")
    assert reg["ok"] is False
    assert "没有号" in reg["error"]
    # 失败得把有号的日子带回去，上游才知道改成哪天
    assert resolve_date("+3") in reg["error"]


async def test_hotel_search_prefers_accessible_nearby():
    p = MockHotelProvider()
    hotels = await p.search("北京", near_hospital="北京积水潭医院")
    assert hotels
    assert all(h["accessible"] for h in hotels)
    assert hotels[0]["distance_m"] <= hotels[-1]["distance_m"]


async def test_resolve_date():
    from datetime import date, timedelta

    assert resolve_date("tomorrow") == (date.today() + timedelta(days=1)).isoformat()
    assert resolve_date("+2") == (date.today() + timedelta(days=2)).isoformat()
    assert resolve_date("2026-10-01") == "2026-10-01"
    assert resolve_date(None) == date.today().isoformat()
