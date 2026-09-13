"""高德开放平台路线规划与行程守护闭环测试套件（对抗性与边界覆盖）。

康乐只陪老人在本市走动之后，跨城不再生成任何路线 —— 本套件把"跨城请求得到
``matched=False``、且不含车次/时长"钉死。

**本机没有外网**：高德真接口（transit / walking / driving）一律 SSL 失败，所以
"接口本身通不通"这里验不了。能离线钉死的是：mode 参数分派、跨城拒答、演示库
兜底、换乘/步行的**解析**（喂一份照高德 v5 形状手写的假响应）、以及偏航判定
这些纯函数。
"""

import pytest

from app.api.routes_guardian import CheckpointIn, guard_route, process_checkpoint
from app.providers.external.amap_service import (
    AmapWebClient,
    KNOWN_LANDMARKS,
    haversine_distance_m,
    min_distance_to_corridor_m,
    point_to_segment_distance_m,
)

# 演示里的两个端点（都在南京，走本地演示库兜底）
_HOME = "家（南京鼓楼区）"
_GULOU = "南京鼓楼医院"

# 康乐砍掉的跨城方向：去程与返程都得被拦下
#
# 这里**没有裸"家"**这一档：光秃秃一个"家"认不出是哪座城的家，本就不该由我们
# 拍板说它是跨城（见 test_amap_bare_home_without_city_is_not_a_cross_city_claim）。
# 跨城的判定靠"两头的城名"与"两端直线距离"两条，杭州/苏州两档（不在 routes.json
# 的 cities 里，城名认不出）走的正是距离那一条。
_CROSS_CITY_CASES = [
    (_HOME, "北京积水潭医院"),
    (_HOME, "北京协和医院"),
    (_HOME, "上海市第六人民医院"),
    (_HOME, "杭州市第一人民医院"),      # 杭州不在 routes.json 的 cities 里，靠坐标距离拦
    (_HOME, "苏州大学附属第一医院"),      # 同上
    ("北京积水潭医院", _HOME),            # 返程
]


# ------------------------------------------------------------ 地标与几何（纯函数）


@pytest.mark.asyncio
async def test_amap_web_client_landmarks_and_geocoding():
    """测试地标查表与高德坐标解析准确性，验证长词优先防止截断。"""
    client = AmapWebClient()

    # 1. 积水潭医院
    coords = await client.geocode("北京积水潭医院")
    assert coords is not None
    assert coords == KNOWN_LANDMARKS["北京积水潭医院"]

    # 2. 南京鼓楼医院 绝不能被 "南京" 截断为南京中心 (118.7841, 32.0645)
    gulou_coords = await client.geocode("南京鼓楼医院")
    assert gulou_coords == (118.7838, 32.0569)

    # 3. 家（南京鼓楼区）绝不能被 "南京" 截断为南京市中心（"家"按城市落到 elder_homes）
    home_coords = await client.geocode("家（南京鼓楼区）")
    assert home_coords == (118.7732, 32.0618)

    # 4. 北京协和医院 绝不能被 "北京" 截断为天安门
    xiehe_coords = await client.geocode("北京协和医院")
    assert xiehe_coords == (116.4172, 39.9145)


@pytest.mark.asyncio
async def test_haversine_distance_calculation():
    """测试经纬度距离球面计算精度。"""
    # 南京南站到积水潭医院跨城约 900+ 公里
    p1 = KNOWN_LANDMARKS["南京南站"]
    p2 = KNOWN_LANDMARKS["北京积水潭医院"]
    dist = haversine_distance_m(p1, p2)
    assert 800_000 < dist < 1_100_000


@pytest.mark.asyncio
async def test_point_to_segment_and_corridor_distance():
    """点到折线航迹走廊的最短距离 —— 这是纯几何，与走不走出城无关。

    取南京南站 → 济南西站这段当样本纯粹是为了要一条足够长的线段，
    **不代表**康乐还会规划这条路。
    """
    nan_jing_south = KNOWN_LANDMARKS["南京南站"]
    ji_nan_west = KNOWN_LANDMARKS["济南西站"]

    # 位于线段中点附近的点
    mid_lng = (nan_jing_south[0] + ji_nan_west[0]) / 2.0
    mid_lat = (nan_jing_south[1] + ji_nan_west[1]) / 2.0
    dist_on_line = point_to_segment_distance_m((mid_lng, mid_lat), nan_jing_south, ji_nan_west)
    assert dist_on_line < 100.0  # 在中点上，距离接近 0 米

    # 偏离中点 5 公里的点
    dist_5km = point_to_segment_distance_m((mid_lng + 0.05, mid_lat), nan_jing_south, ji_nan_west)
    assert 3000 < dist_5km < 7000

    # 航迹走廊计算
    corridor = [nan_jing_south, ji_nan_west, KNOWN_LANDMARKS["北京南站"]]
    assert min_distance_to_corridor_m((mid_lng, mid_lat), corridor) < 100.0


# ------------------------------------------------------------ 跨城：如实拒答


@pytest.mark.asyncio
@pytest.mark.parametrize("origin,destination", _CROSS_CITY_CASES)
async def test_amap_refuses_cross_city(origin, destination):
    """跨城不规划：matched=False、时长留空、车次留空；折线只画两头的直线。

    **折线不是空的**：两头坐标认得出时就画一条直连的"大致方向"线（有坐标才画），
    这正是 MockMapProvider._no_route 那份"折线只画两头的直线"的口径 —— 两个
    provider 对同一件事必须给同样形状的返回，见
    ``test_amap_and_mock_say_the_same_thing_about_cross_city``。
    空的是 steps/options/duration 这些"会让人照着出门"的东西。

    回执里出现的"车票、机票"是在说"我不查"，那一句必须留着；这里禁的是
    **报出一个班次/一段时长**——编一个出来，老人会照着出门。
    """
    route = await AmapWebClient().plan_route(origin, destination)

    assert route["ok"] is True
    assert route["matched"] is False
    assert route["out_of_city"] is True
    assert route["mode"] == "" and route["duration"] == ""
    assert route["steps"] == [] and route["options"] == []
    assert route["distance_km"] is None
    assert "本市" in route["summary"]
    # 折线最多两个点（两头各一个），绝无中途"车站/换乘点"这种编出来的节点
    assert len(route["polyline"]) <= 2, route["polyline"]

    blob = route["summary"] + route["mode"] + "".join(route["steps"])
    for banned in ("高铁", "动车", "城际", "航班", "机场", "车次", "12306", "小时", "分钟"):
        assert banned not in blob, banned


@pytest.mark.asyncio
async def test_amap_and_mock_say_the_same_thing_about_cross_city():
    """两个 provider 对同一件事必须说同样的话、给同样形状的返回。

    否则老人从"高德这条路"问来的答案，和从"演示库那条路"问来的答案会对不上。
    """
    from app.providers.external.services import MockMapProvider

    real = await AmapWebClient().plan_route(_HOME, "北京积水潭医院")
    mock = await MockMapProvider().plan_route(_HOME, "北京积水潭医院")

    assert real["summary"] == mock["summary"]
    assert sorted(real.keys()) == sorted(mock.keys())
    assert real["matched"] is False and mock["matched"] is False


# ------------------------------------------------------------ "家"到底在哪座城


# 三座城各有一个家（也是 test 里当坐标用的那个常量：原来借的是 KNOWN_LANDMARKS
# 里一条叫"家（南京鼓楼区）"的抄写，如今"家"不在表里了，改从 elder_homes 这一份来）。
# 坐标**只有一份**，写在 hospitals.json 的 elder_homes 里 —— 医院 provider 算"离家多远"
# 用的是同一份，地图取点也用同一份，不许各说各的。
_HOME_POINT = {
    "北京": (116.3650, 39.9400),
    "上海": (121.4380, 31.1900),
    "南京": (118.7732, 32.0618),
}

# 老人在甲城、要去乙城的医院：跨城，走"只有大致方向"那条回执，折线两端由取点定。
# 取哪一组不重要，要的是"出发地只写一个家"这个演示里最常见的形状。
_HOME_TO_OTHER_CITY_HOSPITAL = [
    ("北京", "上海市第六人民医院"),
    ("上海", "北京积水潭医院"),
    ("南京", "北京积水潭医院"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("city,destination", _HOME_TO_OTHER_CITY_HOSPITAL)
async def test_bare_home_pins_the_elder_city_not_nanjing(city, destination):
    """出发地只写"家"时，折线的起点必须是**老人所在城市**的家。

    老人一句"我从家出发"，正文里就没有城名了。按城市解析之前，光秃秃的"家"
    只会落到 landmarks 里那一个（南京）—— 子女端守护地图上于是出现一条从南京
    到外地医院的线，差 900 公里。南京那一档一起钉住：修完仍然要落在南京的家。
    """
    from app.providers.external.services import MockMapProvider

    route = await MockMapProvider().plan_route("家", destination, "", city)

    assert route["matched"] is False, city
    assert route["out_of_city"] is True, city
    assert route["polyline"], city
    start = route["polyline"][0]
    # 先看是哪座城的家（家（北京西城区）），再看坐标量级对不对得上
    assert city in start["location"], start
    expect_lng, expect_lat = _HOME_POINT[city]
    assert abs(start["lng"] - expect_lng) < 0.01, start
    assert abs(start["lat"] - expect_lat) < 0.01, start


def test_bare_home_without_a_city_is_not_nanjing():
    """认不出老人所在城市时，不把"家"钉到任何一座城上 —— 包括南京。

    与"查不到就说查不到"同一条口径：宁可只画得出目的地一个点，也不能默默退回
    南京，让"我从家出发"变成一条从南京出发的线。
    """
    from app.providers.external.base import load_fixture
    from app.providers.external.services import _landmark

    landmarks = load_fixture("routes")["landmarks"]
    assert _landmark(landmarks, "家") is None
    assert _landmark(landmarks, "家", city="") is None
    # 这句话里带着城名（家（北京西城区））时退到那座城的市中心当大致方向，
    # 也不许退到南京去
    fallback = _landmark(landmarks, "家（北京西城区）", city="")
    assert fallback and 116 < fallback["lng"] < 117 and 39 < fallback["lat"] < 40, fallback


def test_home_coordinates_agree_across_fixtures():
    """三处"家"必须是同一个点：elder_homes、各条路线的 points[0]、取点那一层。

    routes.json 里每条线的起点是 elder_homes 的抄写 —— 抄飘了，地图上画的家门口
    和计划书上那句"离家 1.3 公里"就成了两个地方，问起来没法解释。
    """
    from app.providers.external.base import load_fixture
    from app.providers.external.services import _landmark

    homes = load_fixture("hospitals")["elder_homes"]
    landmarks = load_fixture("routes")["landmarks"]
    home_routes = [r for r in load_fixture("routes")["routes"] if r["from"] == "家"]
    assert {r["city"] for r in home_routes} == set(homes), "三座城的家都得有从家出发的线"

    for route in home_routes:
        home = homes[route["city"]]
        head = route["points"][0]
        assert head["location"] == home["name"], route["to"]
        assert (head["lng"], head["lat"]) == (home["lng"], home["lat"]), route["to"]
        # 取点这一层也落到同一个点上 —— "家"按城市解析，不是查表查出来的
        assert _landmark(landmarks, "家", route["city"]) == {
            "location": home["name"], "lng": home["lng"], "lat": home["lat"],
        }, route["to"]


# ------------------------------------------------------------ 真接口那条路也得认同一个"家"


def test_landmark_table_has_no_bare_home():
    """地标表里不许再留着裸"家"（尤其不许留着南京那个）。

    留着它，认不出城市时包含匹配就会退到它身上 —— 北京的行程起点被画到南京，
    差 900 公里。坐标只有一份（elder_homes），"家"一律按城市去取。
    """
    assert "家" not in KNOWN_LANDMARKS
    assert not [k for k in KNOWN_LANDMARKS if k.startswith(("家（", "家("))], \
        "带城市名的'家'也不该钉在表里 —— 它按城市落到 elder_homes"


@pytest.mark.asyncio
async def test_geocode_bare_home_without_a_city_is_not_nanjing():
    """"家"认不出城名时不给坐标 —— 不默默退回南京（真接口这条路同样不许）。

    退回一个坐标的代价：子女端守护地图上，北京那条行程的起点线会被画到南京。
    """
    assert await AmapWebClient().geocode("家") is None
    assert await AmapWebClient().geocode("家（南京某区）", "") is not None  # 城名认得出就照常


@pytest.mark.asyncio
@pytest.mark.parametrize("city", ["北京", "上海", "南京"])
async def test_geocode_home_pins_the_city(city):
    """geocode 也得把"家"落到**那座城市**的 elder_homes 上，真接口这条路不能例外。

    上一轮只修了降级那条路（services.py 的 _landmark），geocode 里还留着南京那个
    裸"家"：老人说"家（北京西城区）"，包含匹配退到较短的"北京"键上，落到天安门，
    离西城区的家差 4.3 公里；上海同理差 5.3 公里。
    """
    from app.providers.external.base import load_fixture

    home = load_fixture("hospitals")["elder_homes"][city]
    client = AmapWebClient()

    # 1. 这句话里带着城名（家（北京西城区））
    named = await client.geocode(home["name"])
    assert named is not None, city
    assert abs(named[0] - home["lng"]) < 0.01, named
    assert abs(named[1] - home["lat"]) < 0.01, named

    # 2. 光秃秃一个"家" + 城市上下文（老人档案里的常住城市）
    bare = await client.geocode("家", city)
    assert bare is not None, city
    assert abs(bare[0] - home["lng"]) < 0.01, bare
    assert abs(bare[1] - home["lat"]) < 0.01, bare


@pytest.mark.asyncio
@pytest.mark.parametrize("city", ["北京", "上海", "南京"])
async def test_home_point_agrees_across_three_sources(city):
    """三处来源对同一座城必须是同一个点：elder_homes / points[0] / geocode。

    前两处由 test_home_coordinates_agree_across_fixtures 守着；这里补上第三条腿
    —— 真接口那条 geocode 走的是同一份数据，不是自己另立的一张表。
    """
    from app.providers.external.base import load_fixture

    homes = load_fixture("hospitals")["elder_homes"]
    home = homes[city]
    head = next(r["points"][0] for r in load_fixture("routes")["routes"]
                if r["from"] == "家" and r["city"] == city)

    assert (head["lng"], head["lat"]) == (home["lng"], home["lat"]), city
    assert await AmapWebClient().geocode("家", city) == (home["lng"], home["lat"]), city


@pytest.mark.asyncio
async def test_amap_bare_home_plus_city_plans_and_detects_cross_city():
    """裸"家" + 城市上下文：同城画得出线，去了外地照样按跨城拦下。"""
    client = AmapWebClient()

    # 老人在北京：从家去积水潭医院是本市的一趟，起点必须是北京的家门口
    local = await client.plan_route("家", "北京积水潭医院", "", "北京")
    assert local["matched"] is True
    head = local["points"][0]
    assert head["location"] == "家（北京西城区）", head
    assert abs(head["lng"] - _HOME_POINT["北京"][0]) < 0.01, head
    assert abs(head["lat"] - _HOME_POINT["北京"][1]) < 0.01, head

    # 同一个"家"，目的地在外地：跨城，照样如实拒答
    cross = await client.plan_route("家", "南京鼓楼医院", "", "北京")
    assert cross["matched"] is False and cross["out_of_city"] is True


@pytest.mark.asyncio
async def test_amap_bare_home_without_city_is_not_a_cross_city_claim():
    """认不出"家"在哪座城时：不给线，但也不谎称"跨城了"。

    认不出城名就说"只有大致方向"（_no_route 那一句）；拿跨城那句话去顶，
    等于对着一趟 1 公里的市内路说"您出城了"，是另一种编造。这里同时钉住
    "不许借目的地的城名把'家'接成那座城的家"——借了，"家 → 外地的医院"
    就会被当成同城线放出去。
    """
    route = await AmapWebClient().plan_route("家", "北京积水潭医院")

    assert route["matched"] is False
    assert route["out_of_city"] is False
    assert route["duration"] == "" and route["steps"] == []
    assert "本市走动" not in route["summary"]
    # 折线里不许出现任何一座城的"家"（尤其北京/南京）——起点本就认不出
    assert not [p for p in route["polyline"] if "家" in str(p.get("location", ""))]


def test_guardian_lookup_coords_resolves_home_by_city():
    """子女端守护地图这一侧：LOCATION_COORDS 里没有"家"，坐标同样按城市取。

    表里钉死一个南京的"家"，北京那条行程上报的"家（北京西城区）"就会被包含匹配
    接成北京中心（天安门），守护地图的起点偏出去 4 公里。
    """
    from app.api.routes_guardian import LOCATION_COORDS, lookup_coords
    from app.providers.external.base import load_fixture

    assert "家" not in LOCATION_COORDS

    for city in ("北京", "上海", "南京"):
        home = load_fixture("hospitals")["elder_homes"][city]
        expect = (home["lng"], home["lat"])
        # 1. 行里带着城名
        assert lookup_coords(home["name"]) == expect, city
        # 2. 光秃秃一个"家" + 老人所在城市
        assert lookup_coords("家", city) == expect, city

    # 认不出城的"家"给不出坐标 —— 不退回任何一座城
    assert lookup_coords("家") == (None, None)
    # 不带"家"的地名照旧查表
    assert lookup_coords("北京积水潭医院") == LOCATION_COORDS["北京积水潭医院"]


# ------------------------------------------------------------ provider 包装层也得透传 city


@pytest.mark.asyncio
async def test_amap_map_provider_forwards_city_to_the_real_client(monkeypatch):
    """``AmapMapProvider``（travel_tools → provider 这条路）要把 ``city`` 透给真接口。

    上一版只看了签名里有没有 ``mode``，``city`` 收下就丢：老人档案里的城市永远到不了
    真高德层，裸"家"在真接口那条路上解析不出坐标，只是碰巧落回演示库才按 city 兜底成
    "家（南京鼓楼区）" —— 表面看着对，实际老人的城从没传下去过。这里用 spy 拦真调用，
    直接看传下去的实参，而不是看最终结果（结果由降级决定，看不出透传对没对）。
    """
    from app.providers.external import amap_service
    from app.providers.external.services import AmapMapProvider

    seen: list[tuple] = []

    async def spy(origin, destination, mode="", city=""):
        seen.append((origin, destination, mode, city))
        # 返"没有可用方案"的诚实回执，逼 provider 走降级那一支 ——
        # 这里验的是**透传**，不是降级结果
        return {"ok": True, "matched": False, "mode": "", "duration": "",
                "polyline": [], "steps": [], "options": [], "summary": ""}

    monkeypatch.setattr(amap_service.amap_client, "plan_route", spy)
    await AmapMapProvider().plan_route("家", "南京鼓楼医院", "公交", "南京")

    assert seen == [("家", "南京鼓楼医院", "公交", "南京")], seen


# ------------------------------------------------------------ 本市：分派与兜底


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected", [
    ("公交", "transit"),
    ("地铁", "transit"),
    ("步行", "walking"),
    ("", "driving"),
    ("打车", "driving"),      # 认不出的方式一律驾车，不在这里现编一个
    ("高铁", "driving"),
])
async def test_amap_dispatch_by_mode(monkeypatch, mode, expected):
    """mode 分派：公交/地铁 → 综合换乘、步行 → 步行、空与认不出的 → 驾车。

    三条真接口都返回 None（等价于断网），所以顺带检查"兜底回演示库"这一段：
    换乘卡片不许留白。
    """
    client = AmapWebClient()
    calls: list[str] = []

    async def fake_driving(origin, destination, *a, **k):
        calls.append("driving")
        return None

    async def fake_transit(origin, destination, city="", *a, **k):
        calls.append("transit")
        return None

    async def fake_walking(origin, destination, *a, **k):
        calls.append("walking")
        return None

    monkeypatch.setattr(client, "plan_driving_2", fake_driving)
    monkeypatch.setattr(client, "plan_transit_2", fake_transit)
    monkeypatch.setattr(client, "plan_walking_2", fake_walking)

    route = await client.plan_route(_HOME, _GULOU, mode)

    assert calls == [expected]
    assert route["matched"] is True
    assert route["mode"] in ("公交", "地铁", "步行")
    assert route["duration"] and route["steps"] and route["points"]


@pytest.mark.asyncio
async def test_amap_intracity_route_planning():
    """市内就医出行：连不上高德时落回演示路线库，三种走法都不许留白。"""
    client = AmapWebClient()
    for mode in ("", "公交", "地铁", "步行"):
        route = await client.plan_route(_HOME, _GULOU, mode)
        where = f"mode={mode or '默认'}"
        assert route["ok"] is True and route["matched"] is True, where
        assert route["mode"] in ("公交", "地铁", "步行"), where
        if mode:
            assert route["mode"] == mode, where
        assert len(route["points"]) >= 2 and len(route["polyline"]) >= 2, where
        assert len(route["steps"]) >= 2 and route["duration"], where
        # 兜底出来的也必须是本市走法，不许夹带跨城字样
        blob = route["summary"] + route["mode"] + "".join(route["steps"])
        for banned in ("高铁", "动车", "航班", "机场"):
            assert banned not in blob, f"{where}·{banned}"


@pytest.mark.asyncio
async def test_amap_transit_parses_real_shaped_response(monkeypatch):
    """换乘解析：线名带"地铁"就标地铁，步行/乘车段的折线与步骤都要收进来。

    这里喂的是一份**照高德 v5 形状手写的**响应 —— 验的是解析，不是接口能不能通。
    """
    client = AmapWebClient()
    canned = {
        "status": "1",
        "route": {
            "transits": [{
                "distance": "12500",
                "cost": {"duration": "1800"},
                "segments": [
                    {"walking": {"steps": [
                        {"instruction": "从家步行300米到鼓楼公园站",
                         "polyline": "118.7700,32.0600;118.7750,32.0600"}]}},
                    {"bus": {"buslines": [
                        {"name": "地铁4号线(龙江--仙林湖)",
                         "polyline": "118.7750,32.0600;118.7830,32.0570"}]}},
                    {"walking": {"steps": [
                        {"instruction": "出站步行200米到医院",
                         "polyline": "118.7830,32.0570;118.7838,32.0569"}]}},
                ],
            }],
        },
    }
    seen: dict = {}

    def fake_get(path, params, timeout=6.0):
        seen["path"], seen["params"] = path, params
        return canned

    monkeypatch.setattr(client, "_http_get", fake_get)

    plan = await client.plan_transit_2(
        _HOME_POINT["南京"], KNOWN_LANDMARKS["南京鼓楼医院"], "南京"
    )

    assert seen["path"] == "/v5/direction/transit/integrated"
    assert seen["params"]["show_fields"] == "cost,polyline,steps"
    # 同城：city1 == city2 == 老人的城
    assert seen["params"]["city1"] == seen["params"]["city2"] == "南京"

    assert plan["mode"] == "地铁"
    assert plan["duration"] == "约30分钟"
    assert plan["distance_km"] == 12.5
    assert plan["steps"] == [
        "从家步行300米到鼓楼公园站", "乘坐地铁4号线(龙江--仙林湖)", "出站步行200米到医院",
    ]
    assert len(plan["polyline"]) == 6      # 三段折线，每段 2 个点


@pytest.mark.asyncio
async def test_amap_transit_labels_bus_when_no_metro(monkeypatch):
    """线名里没有"地铁"就是公交 —— 不能把公交线说成地铁；没给城市就不硬塞 city1。"""
    client = AmapWebClient()
    canned = {
        "status": "1",
        "route": {"transits": [{
            "distance": "1100",
            "cost": {"duration": "900"},
            "segments": [{"bus": {"buslines": [
                {"name": "3路(鼓楼公园--新街口)", "polyline": "118.7732,32.0618;118.7801,32.0588"}]}}],
        }]},
    }
    seen: dict = {}

    def fake_get(path, params, timeout=6.0):
        seen["params"] = params
        return canned

    monkeypatch.setattr(client, "_http_get", fake_get)

    plan = await client.plan_transit_2(
        _HOME_POINT["南京"], KNOWN_LANDMARKS["南京鼓楼医院"]
    )

    assert plan["mode"] == "公交"
    assert plan["steps"] == ["乘坐3路(鼓楼公园--新街口)"]
    assert "city1" not in seen["params"] and "city2" not in seen["params"]


@pytest.mark.asyncio
async def test_amap_walking_parses_real_shaped_response(monkeypatch):
    """步行解析：走的是 /v5/direction/walking，时长取自 cost.duration。"""
    client = AmapWebClient()
    canned = {
        "status": "1",
        "route": {"paths": [{
            "distance": "1100",
            "cost": {"duration": "1080"},
            "steps": [{"instruction": "沿中山路往南走",
                       "polyline": "118.7732,32.0618;118.7838,32.0569"}],
        }]},
    }
    seen: dict = {}

    def fake_get(path, params, timeout=6.0):
        seen["path"], seen["params"] = path, params
        return canned

    monkeypatch.setattr(client, "_http_get", fake_get)

    plan = await client.plan_walking_2(
        _HOME_POINT["南京"], KNOWN_LANDMARKS["南京鼓楼医院"]
    )

    assert seen["path"] == "/v5/direction/walking"
    assert seen["params"]["show_fields"] == "cost,polyline,steps"
    assert "city1" not in seen["params"]      # 步行不需要城市码，不许硬塞

    assert plan["mode"] == "步行"
    assert plan["duration"] == "约18分钟"
    assert plan["distance_km"] == 1.1
    assert plan["steps"] == ["沿中山路往南走"]
    assert len(plan["polyline"]) == 2


@pytest.mark.asyncio
async def test_amap_transit_and_walking_return_none_on_failure(monkeypatch):
    """接口失败/超时/无数据就是 None —— 绝不吞掉异常再编一份假数据出来。"""
    client = AmapWebClient()
    origin, destination = _HOME_POINT["南京"], KNOWN_LANDMARKS["南京鼓楼医院"]

    # 1. 网络失败（本机的真实处境）
    monkeypatch.setattr(client, "_http_get", lambda *a, **k: None)
    assert await client.plan_transit_2(origin, destination, "南京") is None
    assert await client.plan_walking_2(origin, destination) is None

    # 2. 高德回了一个"查不到 / 超配额"的状态码
    monkeypatch.setattr(client, "_http_get",
                        lambda *a, **k: {"status": "0", "info": "DAILY_QUERY_OVER_LIMIT"})
    assert await client.plan_transit_2(origin, destination, "南京") is None
    assert await client.plan_walking_2(origin, destination) is None

    # 3. 状态码正常但没有可用方案
    monkeypatch.setattr(client, "_http_get",
                        lambda *a, **k: {"status": "1", "route": {"transits": [], "paths": []}})
    assert await client.plan_transit_2(origin, destination, "南京") is None
    assert await client.plan_walking_2(origin, destination) is None


# ------------------------------------------------------------ 守护地图：只画本市


@pytest.mark.asyncio
async def test_guard_route_never_draws_cross_city():
    """守护地图的取路线入口：跨城不画 —— 空航迹、空时长，且不提车次。"""
    route = await guard_route(_HOME, "北京积水潭医院")

    assert route["matched"] is False
    assert route["polyline"] == [] and route["points"] == [] and route["steps"] == []
    assert route["mode"] == "" and route["duration"] == ""

    blob = route["summary"] + route["mode"]
    for banned in ("高铁", "动车", "城际", "航班", "机场", "车次"):
        assert banned not in blob, banned


@pytest.mark.asyncio
async def test_guard_route_draws_local_route():
    """同城：画得出来，而且一定是老人端认的三种走法之一。"""
    route = await guard_route(_HOME, _GULOU)

    assert route["matched"] is True
    assert route["mode"] in ("公交", "地铁", "步行")
    assert len(route["polyline"]) >= 2
    assert route["points"], "站点标记不能空 —— 前端 points 画的就是它"


def _stub_route(payload: dict):
    async def _call(*a, **k):
        return dict(payload)
    return _call


@pytest.mark.asyncio
async def test_guard_route_blocks_non_local_modes(monkeypatch):
    """规划结果里带高铁/航班字样，或压根不是本市走法的，一律换成空航迹。

    这是"再挡一道"：amap_service 已经不再产跨城线了，但守护地图是子女端
    看的那张图 —— 出现一条跨省航迹比"没有路线"更容易让人误会。
    """
    import app.api.routes_guardian as guardian

    for bad in (
        {"ok": True, "matched": True, "mode": "高铁 + 市内接驳", "duration": "约2小时",
         "polyline": [{"lng": 118.8, "lat": 32.0}], "steps": ["坐高铁去北京"]},
        {"ok": True, "matched": True, "mode": "市内打车/自驾", "duration": "约15分钟",
         "polyline": [{"lng": 118.8, "lat": 32.0}], "steps": ["打车过去"]},
        {"ok": True, "matched": False, "mode": "", "duration": "", "polyline": [], "steps": []},
    ):
        monkeypatch.setattr(guardian.amap_client, "plan_route", _stub_route(bad))
        route = await guardian.guard_route(_HOME, _GULOU)
        assert route["matched"] is False, bad["mode"]
        assert route["polyline"] == [], bad["mode"]


# ------------------------------------------------------------ 守护闭环：位置上报


@pytest.mark.asyncio
async def test_guardian_periodic_checkpoint_same_city_closure(ctx, elder):
    """本市行程的位置上报闭环：途经点放行、走廊内放行、偏离告警、重复不轰炸、到达收尾。

    用北京那条 5.3 公里的同城线当样本：南京演示那条只有 1.1 公里，整段都落在
    "已到达"的 1 公里半径里，判不出"在走廊上"这个中间态。
    """
    origin = "家（北京西城区）"
    destination = "北京协和医院"
    trip = await ctx.repos.insert("trips", {
        "elder_id": elder["id"],
        "purpose": "去北京协和医院看门诊",
        "status": "planned",
        "origin": origin,
        "destination": destination,
    })

    # 1. 正常途经点上报（出发地，也是规划航迹上的点）
    res1 = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location=origin, lng=116.365, lat=39.94
    ))
    assert res1["status"] == "normal"
    assert res1["alert_sent"] is False
    assert "一切正常" in res1["checkpoint"]["note"]

    # 确认行程状态自动转为 ongoing
    t1 = await ctx.repos.get("trips", trip["id"])
    assert t1["status"] == "ongoing"

    # 2. 走廊上的行进点（家 → 东单路口北站 这一段的中点，非站点）：不能误报偏航
    res_on = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="西二环上的路口", lng=116.39, lat=39.9265
    ))
    assert res_on["status"] == "normal"
    assert res_on["alert_sent"] is False

    # 3. 首次偏离（三里屯太古里，离这条走廊四公里开外）
    res2 = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="北京市朝阳区三里屯太古里", lng=116.455, lat=39.937
    ))
    assert res2["status"] == "off_route"
    assert res2["alert_sent"] is True
    assert "位置偏离规划路线" in res2["checkpoint"]["note"]

    # 4. 频控防抖：同一片区域再报，不重复轰炸子女端
    res2_repeat = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="北京市朝阳区三里屯太古里", lng=116.456, lat=39.938
    ))
    assert res2_repeat["status"] == "off_route"
    assert res2_repeat["alert_sent"] is False

    # 5. 到达目的地判定（到达北京协和医院）
    res3 = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location=destination, lng=116.4172, lat=39.9145
    ))
    assert res3["status"] == "arrived"
    assert "已安全到达目的地" in res3["checkpoint"]["note"]

    t2 = await ctx.repos.get("trips", trip["id"])
    assert t2["status"] == "completed"


@pytest.mark.asyncio
async def test_guardian_gps_warmup_and_zero_coords(ctx, elder):
    """测试长辈端 GPS 未就绪、搜星连接中及零坐标兜底，杜绝虚假偏航报警。"""
    trip = await ctx.repos.insert("trips", {
        "elder_id": elder["id"],
        "purpose": "前往南京鼓楼医院看门诊",
        "status": "planned",
    })

    # 1. 刚打开页面，定位尚在搜星
    res_warm = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="实时定位中", lng=None, lat=None
    ))
    assert res_warm["status"] == "normal"
    assert res_warm["alert_sent"] is False
    assert "等待长辈设备卫星定位信号" in res_warm["checkpoint"]["note"]

    # 2. 硬件上报未初始化零岛坐标 (0, 0)
    res_zero = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="GPS校准中", lng=0.0, lat=0.0
    ))
    assert res_zero["status"] == "normal"
    assert res_zero["alert_sent"] is False


@pytest.mark.asyncio
async def test_guardian_json_string_plan_and_local_waypoint(ctx, elder):
    """plan 字段是 JSON 字符串时的容错解析，以及本市途经点正常通行判定。"""
    import json

    from app.api.routes_guardian import resolve_trip_destination, resolve_trip_origin

    # 1. plan 字段为 JSON 序列化字符串时解析要稳，杜绝 AttributeError
    serialized_plan = json.dumps({
        "title": "就医出行计划书",
        "pages": [{
            "rows": [
                {"label": "出发", "value": "家（南京鼓楼区）"},
                {"label": "医院", "value": "南京鼓楼医院"},
                {"label": "到达", "value": "鼓楼公园站"},
            ]
        }]
    })
    trip_record = {"purpose": None, "plan": serialized_plan}
    assert resolve_trip_origin(trip_record) == "家（南京鼓楼区）"
    assert resolve_trip_destination(trip_record) == "南京鼓楼医院"

    # 2. 本市航迹上的点（出发地）上报：判"一切正常"，不误报偏航。
    #    注意鼓楼公园站离南京鼓楼医院只有 400 米，先撞上"已到达"的 1 公里半径，
    #    要拿走廊上另一个端点才验得到"在走廊上"这一支。
    trip = await ctx.repos.insert("trips", {
        "elder_id": elder["id"],
        "purpose": "前往南京鼓楼医院看门诊",
        "status": "ongoing",
        "origin": _HOME,
        "destination": _GULOU,
    })
    res_waypoint = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location=_HOME, lng=118.7732, lat=32.0618
    ))
    assert res_waypoint["status"] == "normal"
    assert res_waypoint["alert_sent"] is False
    assert "一切正常" in res_waypoint["checkpoint"]["note"]

    # 3. 跨城的火车站不再是"预期途经点"：报在济南西站就是偏航，不能报"一切正常"
    res_cross = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="济南西站", lng=116.8974, lat=36.6669
    ))
    assert res_cross["status"] == "off_route"
    assert res_cross["alert_sent"] is True


@pytest.mark.asyncio
async def test_guardian_direct_and_quick_endpoints(ctx, elder):
    """测试直接路线规划与无 trip_id 时的快速建程联动。

    第 2 段走 ``create_quick_trip`` → ``get_ctx()`` → 真实 MariaDB（SSH 隧道），
    本机没网会 EOFError —— 那不是本工作流要修的东西，如实留着。
    """
    from app.api.routes_guardian import QuickTripIn, create_quick_trip, direct_route

    # 1. 直接路线规划（本市）
    res_direct = await direct_route("家（南京鼓楼区）", "南京鼓楼医院")
    assert res_direct["ok"] is True
    route = res_direct["route"]
    assert route["matched"] is True
    assert route["mode"] == "公交"
    assert "约约" not in route["summary"]  # 杜绝约约字样
    assert "公交" in route["summary"]

    # 2. 快速建立行程
    res_quick = await create_quick_trip(QuickTripIn(
        origin="家（南京鼓楼区）",
        destination="南京鼓楼医院",
        elder_id=elder["id"],
        purpose="前往南京鼓楼医院",
    ))
    assert res_quick["ok"] is True
    assert res_quick["trip"]["status"] == "ongoing"
    assert res_quick["trip"]["origin"] == "家（南京鼓楼区）"
    assert res_quick["trip"]["destination"] == "南京鼓楼医院"
