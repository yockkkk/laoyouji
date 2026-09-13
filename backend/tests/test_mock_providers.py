"""Mock Provider 确定性测试：同输入同输出（演示可复现、测试可断言）。"""
from __future__ import annotations

import json
import re

from app.providers.external import hospital as hospital_mod
from app.providers.external.base import load_fixture, resolve_date
from app.providers.external.hospital import MockHospitalProvider
from app.providers.external.services import MockMapProvider, MockWeatherProvider


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
    # 就近排序后第一位就是离家最近的那家（积水潭离家 1.3 公里，协和 5.3 公里），
    # 不再是"fixture 里写在前面那家"
    assert hospitals[0]["hospital"] == "北京积水潭医院"


# ------------------------------------------------------------ 就近：同城 + 排前面

async def test_hospital_search_sorted_by_distance_from_home():
    """同城最近的排第一 —— 列表第一条会被拿去推荐，也会印在计划书上。"""
    p = MockHospitalProvider()
    hospitals = await p.search("北京", "骨科")
    assert [h["hospital"] for h in hospitals] == ["北京积水潭医院", "北京协和医院"]
    distances = [h["distance_km"] for h in hospitals]
    assert distances == sorted(distances)
    # "离家约 X 公里"是给老人和模型看的那句话，不能是空字符串
    assert all(h["distance_text"] and h["from_home"] for h in hospitals)


async def test_hospital_sort_ignores_fixture_order(monkeypatch):
    """“就近”得是真算出来的：把 fixture 里的医院倒过来，结果顺序必须不变。

    只按列表顺序输出的实现会在这里（正确地）失败 —— 这正是这条断言的意义。
    """
    data = load_fixture("hospitals")
    reversed_data = {**data, "hospitals": list(reversed(data["hospitals"]))}
    monkeypatch.setattr(hospital_mod, "load_fixture", lambda _name: reversed_data)
    hospitals = await MockHospitalProvider().search("北京", "骨科")
    assert [h["hospital"] for h in hospitals] == ["北京积水潭医院", "北京协和医院"]


async def test_hospital_search_never_crosses_city():
    """南京的老人不会拿到北京的医院 —— 异地不是"远一点"，是今天走不到。"""
    p = MockHospitalProvider()
    nj = await p.search("南京", "骨科")
    assert [h["hospital"] for h in nj] == ["南京鼓楼医院"]
    assert all(h["city"] == "南京" for h in nj)
    # 上海两家都在：六院离家 1.7 公里排在华山 2.2 公里前面
    sh_all = await p.search("上海", "")
    assert [h["hospital"] for h in sh_all][0] == "上海市第六人民医院"
    assert [h["hospital"] for h in sh_all][-1] == "复旦大学附属华山医院"


async def test_hospital_search_unknown_city_returns_nothing():
    """认不出的城市宁可不给，也不跨城 —— 上游会如实说"没查到苏州的骨科医院"。"""
    p = MockHospitalProvider()
    assert await p.search("苏州", "骨科") == []
    assert await p.search("杭州市第一人民医院", "骨科") == []


def test_elder_homes_cover_every_city():
    """每座城都得有一个"家"当零点，每家医院都得有坐标，否则"就近"没法算。"""
    data = load_fixture("hospitals")
    assert set(data["elder_homes"]) == set(data["cities"])
    for h in data["hospitals"]:
        assert h["city"] in data["cities"], h["name"]
        assert isinstance(h["location"]["lng"], float), h["name"]
        assert isinstance(h["location"]["lat"], float), h["name"]


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


async def test_resolve_date():
    from datetime import date, timedelta

    assert resolve_date("tomorrow") == (date.today() + timedelta(days=1)).isoformat()
    assert resolve_date("+2") == (date.today() + timedelta(days=2)).isoformat()
    assert resolve_date("2026-10-01") == "2026-10-01"
    assert resolve_date(None) == date.today().isoformat()


# ------------------------------------------------------------ 本地路线：三种走法

# 老人从家去的五家医院（fixture 的城市各一家起步，北京两家可比远近）
_HOME_TO_HOSPITAL = [
    ("家", "南京鼓楼医院"),
    ("家", "北京积水潭医院"),
    ("家", "北京协和医院"),
    ("家", "上海市第六人民医院"),
    ("家", "复旦大学附属华山医院"),
]


async def test_mock_route_supports_bus_metro_walk():
    """公交/地铁/步行三种方式都得能出结果，且每种都有老人照着走的原话。"""
    p = MockMapProvider()
    for origin, destination in _HOME_TO_HOSPITAL:
        for mode in ("", "公交", "地铁", "步行"):
            route = await p.plan_route(origin, destination, mode)
            where = f"{destination}·{mode or '默认'}"
            assert route["matched"] is True, where
            assert route["mode"] in ("公交", "地铁", "步行"), where
            if mode:
                assert route["mode"] == mode, where
            assert route["duration"] and route["steps"], where
            assert route["announce"] and route["polyline"], where
            assert route["distance_km"], where
            # 三种方式一起给出去，老人才能在页面上换
            assert {o["mode"] for o in route["options"]} == {"公交", "地铁", "步行"}, where


async def test_mock_route_has_no_intercity_anything():
    """整份路线库里不许再出现高铁/航班这类词 —— 那是本项目砍掉的方向。"""
    blob = json.dumps(load_fixture("routes")["routes"], ensure_ascii=False)
    for banned in ("高铁", "动车", "车次", "航班", "飞机", "机票", "机场", "12306"):
        assert banned not in blob, banned
    assert not re.search(r"G\d+", blob), "车次号"


async def test_mock_route_refuses_cross_city():
    """跨城不给路线：matched=False、时长留空，并且把话说透（编一个时长最糟）。"""
    route = await MockMapProvider().plan_route("家（南京鼓楼区）", "北京积水潭医院")
    assert route["matched"] is False
    assert route["duration"] == "" and route["steps"] == []
    assert route["out_of_city"] is True
    assert "本市" in route["summary"]


async def test_mock_route_uses_elder_city_when_origin_is_just_home():
    """出发地写"家"时正文里没有城名，得靠老人档案的城市才认得出这是跨城。"""
    route = await MockMapProvider().plan_route("家", "北京积水潭医院", "", "南京")
    assert route["matched"] is False and route["out_of_city"] is True
    # 同一个"家"，老人本来就在北京，那就是一条正常的市内线
    same_city = await MockMapProvider().plan_route("家", "北京积水潭医院", "", "北京")
    assert same_city["matched"] is True and same_city["mode"] == "公交"


def test_plan_route_mode_aliases_are_local_only():
    """模型说的"走路/轨道交通"要归一到三种本地方式；打车、高铁一律不认。"""
    from app.tools.travel_tools import _normalize_mode
    assert _normalize_mode("走路") == "步行"
    assert _normalize_mode("轨道交通") == "地铁"
    assert _normalize_mode("公交车") == "公交"
    assert _normalize_mode("打车") == "" and _normalize_mode("高铁") == ""
    assert _normalize_mode(None) == "" and _normalize_mode("") == ""


def test_routes_fixture_is_local_only():
    """每条路线都是市内线：三种方式齐备、城市在册、点位不跨省。"""
    data = load_fixture("routes")
    for route in data["routes"]:
        modes = [route["mode"]] + [a["mode"] for a in route["alternatives"]]
        assert set(modes) == {"公交", "地铁", "步行"}, route["to"]
        assert route["city"] in data["cities"], route["to"]
        assert not any("济南" in p["location"] for p in route["points"]), route["to"]
