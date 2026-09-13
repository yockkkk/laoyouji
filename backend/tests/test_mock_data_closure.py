"""闭环护栏：没有第三方 API 的工具，假数据必须够整条链走完。

这些工具（查医院/规划路线/叫车/天气）背后没有真接口，全靠
``app/data/*.json``。它们中间**任何一环查不到**，主智能体拆出来的那条任务链就断在
那儿：子智能体只能回一句"没查到"，《就医出行计划书》缺页，演示当场停住。

所以这一组断言不测业务逻辑，测的是"数据够不够把流程走通"：
症状能落到科室、科室在城市里有医院、医院的医生手里有号源、本地路线走得通。
以前 fixture 里 ``上海`` 在 cities 里却没有一家医院、symptom_to_department 指向
四个根本不存在的科室 —— 那些都是能查到但走不通的死路，这里就是防它们回来的。

康乐收敛为本地就近就医后，城际车次/异地酒店整条砍掉（与"就近"矛盾），
对应的"去程有车回程也有车""医院旁边有酒店"两条闭环断言随 provider 一起移除。

健康档案（`app/db/seed.py` 里那四个演示剧本）也算在闭环之内：它是**合成的**，
但合成不等于随便编 —— 四个档位各要有一份能真的走通"记录 → 分诊 → 就医"的数据，
否则答辩现场那一档就演不出来。这一条在文件末尾，不建库、只问规则。
"""
from __future__ import annotations

import asyncio

import pytest

from app.db.seed import SCENARIOS
from app.providers.external.base import load_fixture
from app.providers.external.services import MockMapProvider, MockRideProvider
from app.safety import health_rules as hr

# 每个"没有真接口"的数据源至少得有这么多条，才够演示挑一挑
MIN_RECORDS = 2


# ------------------------------------------------------------------ 医院 / 挂号

def test_every_symptom_maps_to_a_real_department_in_every_city():
    """症状 → 科室 → 医院，三段都得接得上。

    ``search_hospital`` 的 city 是模型填的（默认北京，老人说"就在本地看"就变南京）。
    只要有一个城市缺这个科室，同一句话在两个城市里就是一个能查到、一个查不到。
    """
    data = load_fixture("hospitals")
    departments = set(data["symptom_to_department"].values())
    for city in data["cities"]:
        available = {dep["name"] for h in data["hospitals"] if h["city"] == city
                     for dep in h["departments"]}
        missing = sorted(departments - available)
        assert not missing, f"{city} 没有这些科室，症状会走进死路：{missing}"


def test_every_listed_city_has_hospitals():
    data = load_fixture("hospitals")
    for city in data["cities"]:
        assert [h for h in data["hospitals"] if h["city"] == city], \
            f"{city} 在 cities 里却没有一家医院"


def test_every_doctor_has_bookable_slots():
    """号源为空的医生 = 查得到、挂不上。挂号是这条链上最后一步，断在这儿最难看。"""
    for h in load_fixture("hospitals")["hospitals"]:
        assert h["departments"], f"{h['name']} 没有科室"
        for dep in h["departments"]:
            assert dep["doctors"], f"{h['name']} {dep['name']} 没有医生"
            for doc in dep["doctors"]:
                assert doc["slots"], f"{h['name']} {doc['name']} 没有号源"
                for slot in doc["slots"]:
                    # 日期是相对的（+N），星期几只能算、不能写死；
                    # 写死的那个词会和 resolve_date 算出来的日子打架
                    assert "周" not in slot["time"], slot
                    assert any(k in slot["time"] for k in ("上午", "下午")), slot


# ------------------------------------------------------------------ 天气

def test_weather_bias_covers_every_hospital_city():
    """每个城市都得有温差偏移，否则南京和北京的天气一模一样，一眼假。"""
    bias = load_fixture("weather")["city_bias"]
    cities = {h["city"] for h in load_fixture("hospitals")["hospitals"]}
    assert not (cities - set(bias)), f"这些城市没有温差配置：{sorted(cities - set(bias))}"


# ------------------------------------------------------------------ 路线 / 叫车

async def test_map_routes_are_matched_by_loose_place_names():
    """模型填的地名粒度是不定的（家 / 家（南京鼓楼区） / 南京鼓楼医院），都得认。

    宽松匹配还在：出发地写"家（南京鼓楼区）"，fixture 里那条路的 ``from`` 只是"家"
    —— ``name in text`` 命中，路线照样接上。但这层宽松现在多了一道**同城**门槛
    （见 ``MockMapProvider.plan_route`` 里的 ``_cross_city``）：上一版这里拿
    "家（南京鼓楼区）→北京积水潭医院"当宽松匹配的样板，那其实是一段跨城长途，
    如今如实回 ``matched=False``（跨城由 ``test_map_admits_when_it_has_no_route``
    那一族管）。所以举例换成同城的一对，宽松匹配照样要生效。
    """
    provider = MockMapProvider()
    route = await provider.plan_route("家（南京鼓楼区）", "南京鼓楼医院")
    assert route["matched"] is True
    assert len(route["polyline"]) >= MIN_RECORDS
    assert route["steps"] and route["duration"]

    # 城里仅写一个"家"（正文里没有城名）也接得上同一条线 —— 证明确实是"松散"命中，
    # 而不是把地名写死成 fixture 里那一串
    loose = await provider.plan_route("家", "南京鼓楼医院")
    assert loose["matched"] is True
    assert loose["polyline"] == route["polyline"]


async def test_map_admits_when_it_has_no_route():
    """没有的线路不许编时长 —— 老人会照着那个时间出门。"""
    provider = MockMapProvider()
    route = await provider.plan_route("南京", "拉萨")
    assert route["matched"] is False
    assert route["duration"] == ""
    assert route["steps"] == []
    assert "大致方向" in route["summary"]


def test_map_fixture_has_enough_routes():
    data = load_fixture("routes")
    assert len(data["routes"]) >= MIN_RECORDS
    for route in data["routes"]:
        assert len(route["points"]) >= MIN_RECORDS, route["from"]
        assert route["steps"] and route["mode"] and route["duration"]
    # 济南西站只该出现在它真正在途中的那条线上（旧实现无论去哪都塞进去）
    detours = [r for r in data["routes"]
               if any("济南" in p["location"] for p in r["points"])
               and not (r["from"] == "南京" and r["to"] == "北京")]
    assert not detours, f"这些线路上不该经过济南：{[r['to'] for r in detours]}"


async def test_ride_dispatches_different_drivers_for_different_trips(monkeypatch):
    """三位师傅要真的轮得到 —— 每趟都是同一块车牌，演示里一眼假。"""
    drivers = load_fixture("rides")["drivers"]
    assert len(drivers) >= MIN_RECORDS
    assert len({d["plate"] for d in drivers}) == len(drivers), "车牌重复"

    # hail 里等 3 秒模拟司机接单；这里测的是派单结果，不测那 3 秒
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    provider = MockRideProvider()
    trips = [("家", "南京鼓楼医院"), ("北京南站", "北京积水潭医院"), ("家", "南京南站")]
    results = [await provider.hail(o, d) for o, d in trips]
    assert len({r["plate"] for r in results}) >= MIN_RECORDS, "所有行程派了同一辆车"
    for r in results:
        assert r["driver"] and r["plate"] and r["eta_min"] > 0
        assert r["plate"] in r["announce"] and r["driver"] in r["announce"]
    # 同一趟必须派同一辆车（演示可复现）
    again = await provider.hail(*trips[0])
    assert again["plate"] == results[0]["plate"]


# ------------------------------------------------------------------ 社区活动 / 反诈

@pytest.mark.parametrize("fixture,key", [
    ("activities", "activities"),
    ("scam_corpus", "corpus"),
])
def test_community_fixtures_have_enough_records(fixture, key):
    assert len(load_fixture(fixture)[key]) >= MIN_RECORDS


# ------------------------------------------------------------------ 健康档案剧本

@pytest.mark.parametrize("name", list(SCENARIOS))
def test_persona_scenarios_cover_the_triage_chain(name):
    """四个剧本的展示数，喂给真规则必须落回各自声明的那一档。

    这是"假数据够不够把链走通"在健康这条线上的原意：数据是合成的，但**分诊的
    四个档位都得有一份数据能演示到**。档位一律问 ``health_rules``，不在这里手写阈值 ——
    阈值一调，测试得跟着报"这个剧本不再演示那一档"，而不是继续绿着骗人。
    """
    sc = SCENARIOS[name]
    systolic, diastolic = sc["bp_tail"][0]
    level, reason = hr.classify_reading("bp", systolic=systolic, diastolic=diastolic)
    assert level == sc["level"], \
        f"{name} 的 {systolic}/{diastolic} 现在落「{level}」：{reason}"
