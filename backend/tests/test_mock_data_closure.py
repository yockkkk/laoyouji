"""闭环护栏：没有第三方 API 的工具，假数据必须够整条链走完。

这些工具（查车次/查医院/查酒店/规划路线/叫车/天气）背后没有真接口，全靠
``app/data/*.json``。它们中间**任何一环查不到**，主智能体拆出来的那条任务链就断在
那儿：子智能体只能回一句"没查到"，《就医出行计划书》缺页，演示当场停住。

所以这一组断言不测业务逻辑，测的是"数据够不够把流程走通"：
症状能落到科室、科室在城市里有医院、医院旁边有酒店、去程有车回程也有车。
以前 fixture 里 ``上海`` 在 cities 里却没有一家医院、symptom_to_department 指向
四个根本不存在的科室 —— 那些都是能查到但走不通的死路，这里就是防它们回来的。
"""
from __future__ import annotations

import asyncio

import pytest

from app.providers.external.base import load_fixture
from app.providers.external.services import MockMapProvider, MockRideProvider

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


# ------------------------------------------------------------------ 酒店

def test_every_hospital_has_nearby_hotels():
    """``search_hotel`` 按 city + near_hospital 精确过滤，没配酒店的医院就订不到房。"""
    hospitals = load_fixture("hospitals")["hospitals"]
    hotels = load_fixture("hotels")["hotels"]
    for h in hospitals:
        near = [x for x in hotels
                if x["city"] == h["city"] and x["near_hospital"] == h["name"]]
        assert len(near) >= MIN_RECORDS, \
            f"{h['name']} 附近只有 {len(near)} 家酒店，家属陪住就没得选"
        for x in near:
            assert x["accessible"], f"{x['name']} 不是无障碍房，不该进演示库"
            assert x["walk_min"] > 0 and x["distance_m"] > 0


# ------------------------------------------------------------------ 车次

def test_train_routes_have_a_way_back():
    """只有去程没有回程 —— 老人到了北京就回不来了，计划书第二页缺一半。"""
    routes = load_fixture("trains")["routes"]
    pairs = {(r["from_city"], r["to_city"]) for r in routes}
    for from_city, to_city in pairs:
        assert (to_city, from_city) in pairs, f"{from_city}→{to_city} 没有回程"


def test_every_train_route_has_choices_and_unique_numbers():
    """车次号全局唯一：``book`` 是拿号在所有线路里找第一个匹配的。

    两条线路重名的话，订南京→上海会订到南京→北京那趟车上去，
    出票信息里的车站和时刻全是另一条线的。
    """
    routes = load_fixture("trains")["routes"]
    assert len(routes) >= MIN_RECORDS
    seen: dict[str, str] = {}
    for route in routes:
        assert len(route["trains"]) >= MIN_RECORDS, \
            f"{route['from_city']}→{route['to_city']} 只有一趟车"
        for train in route["trains"]:
            no = train["train_no"]
            line = f"{route['from_city']}→{route['to_city']}"
            assert no not in seen, f"车次 {no} 在 {seen.get(no)} 和 {line} 里重名"
            seen[no] = line
            assert train["seats"], f"{no} 没有座位等级"


# ------------------------------------------------------------------ 天气

def test_weather_bias_covers_every_hospital_city():
    """每个城市都得有温差偏移，否则南京和北京的天气一模一样，一眼假。"""
    bias = load_fixture("weather")["city_bias"]
    cities = {h["city"] for h in load_fixture("hospitals")["hospitals"]}
    assert not (cities - set(bias)), f"这些城市没有温差配置：{sorted(cities - set(bias))}"


# ------------------------------------------------------------------ 路线 / 叫车

async def test_map_routes_are_matched_by_loose_place_names():
    """模型填的地名粒度是不定的（北京 / 北京南站 / 北京积水潭医院），都得认。"""
    provider = MockMapProvider()
    route = await provider.plan_route("家（南京鼓楼区）", "北京积水潭医院")
    assert route["matched"] is True
    assert len(route["polyline"]) >= MIN_RECORDS
    assert route["steps"] and route["duration"]


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


# ------------------------------------------------------------------ 社区 / 反诈

@pytest.mark.parametrize("fixture,key", [
    ("canteen_menu", "meals"),
    ("canteen_menu", "activities"),
    ("scam_corpus", "corpus"),
])
def test_community_fixtures_have_enough_records(fixture, key):
    assert len(load_fixture(fixture)[key]) >= MIN_RECORDS


def test_service_catalog_has_providers_for_both_service_types():
    providers = load_fixture("canteen_menu")["providers"]
    for service_type in ("cleaning", "accompany"):
        assert len(providers.get(service_type, [])) >= MIN_RECORDS, service_type
