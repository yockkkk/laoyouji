"""高德开放平台路线规划与行程守护闭环测试套件（对抗性与边界覆盖）。"""
import pytest
from app.providers.external.amap_service import (
    AmapWebClient,
    haversine_distance_m,
    point_to_segment_distance_m,
    min_distance_to_corridor_m,
    KNOWN_LANDMARKS,
)
from app.api.routes_guardian import CheckpointIn, process_checkpoint


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

    # 3. 家（南京鼓楼区）绝不能被 "家" 截断为南京市中心
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
    """测试点到折线航迹走廊的最短距离计算（保障京沪高铁与市内走廊贴合判定）。"""
    # 模拟南京南站到济南西站的线段
    nan_jing_south = KNOWN_LANDMARKS["南京南站"]
    ji_nan_west = KNOWN_LANDMARKS["济南西站"]

    # 位于线段中点附近的某高铁经停点（约徐州/安徽交界附近）
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


@pytest.mark.asyncio
async def test_amap_comprehensive_route_planning():
    """测试跨城就医出行的高德综合路线规划：包含经停站点、步骤与航迹折线。"""
    client = AmapWebClient()
    route = await client.plan_route("家（南京鼓楼区）", "北京积水潭医院")
    assert route["ok"] is True
    assert route["matched"] is True
    assert len(route["points"]) >= 4
    assert len(route["polyline"]) >= 4
    assert len(route["steps"]) >= 2
    assert "高铁" in route["mode"]
    assert "积水潭医院" in route["summary"] or "北京" in route["summary"]


@pytest.mark.asyncio
async def test_amap_intracity_route_planning():
    """测试市内就医出行路线规划与兜底步骤生成。"""
    client = AmapWebClient()
    route = await client.plan_route("家（南京鼓楼区）", "南京鼓楼医院")
    assert route["ok"] is True
    assert len(route["points"]) >= 2
    assert len(route["steps"]) >= 2
    assert route["duration"] != ""


@pytest.mark.asyncio
async def test_guardian_periodic_checkpoint_normal_and_offroute(ctx, elder, child):
    """测试长辈端位置上报、高铁走廊贴合判定、目的地到达与偏航频控防抖闭环。"""
    trip = await ctx.repos.insert("trips", {
        "elder_id": elder["id"],
        "purpose": "去北京积水潭医院看骨科",
        "status": "planned",
    })

    # 1. 正常途经点上报（南京南站）
    res1 = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="南京南站", lng=118.7981, lat=31.9696
    ))
    assert res1["status"] == "normal"
    assert res1["alert_sent"] is False
    assert "一切正常" in res1["checkpoint"]["note"]

    # 确认行程状态自动转为 ongoing
    t1 = await ctx.repos.get("trips", trip["id"])
    assert t1["status"] == "ongoing"

    # 2. 模拟老人在京沪高铁途中行进（线路上坐标，非站点，走廊贴合判定必须为 normal）
    # 南京南站与济南西站之间的线段中点附近
    mid_lng = (118.7981 + 116.8974) / 2.0
    mid_lat = (31.9696 + 36.6669) / 2.0
    res_train = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="京沪高铁高速运行中", lng=mid_lng, lat=mid_lat
    ))
    assert res_train["status"] == "normal"
    assert res_train["alert_sent"] is False

    # 3. 首次偏航点上报（朝阳区三里屯太古里，偏离京沪走廊与积水潭医院）
    res2 = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="北京市朝阳区三里屯太古里", lng=116.455, lat=39.937
    ))
    assert res2["status"] == "off_route"
    assert res2["alert_sent"] is True
    assert "位置偏离规划路线" in res2["checkpoint"]["note"]

    # 4. 频控防抖：10 秒后再次在三里屯上报偏航坐标，不重复发送轰炸通知 (alert_sent 为 False)
    res2_repeat = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="北京市朝阳区三里屯太古里", lng=116.456, lat=39.938
    ))
    assert res2_repeat["status"] == "off_route"
    assert res2_repeat["alert_sent"] is False

    # 5. 到达目的地判定（到达积水潭医院门诊大楼）
    res3 = await process_checkpoint(ctx, trip["id"], CheckpointIn(
        location="北京积水潭医院", lng=116.3748, lat=39.9485
    ))
    assert res3["status"] == "arrived"
    assert "已安全到达目的地" in res3["checkpoint"]["note"]

    # 确认行程已顺利完成
    t2 = await ctx.repos.get("trips", trip["id"])
    assert t2["status"] == "completed"


@pytest.mark.asyncio
async def test_amap_shanghai_and_return_trip_routes():
    """测试上海专线、返程路线反转与北京协和到院规划准确性。"""
    client = AmapWebClient()

    # 1. 上海专线（南京 -> 上海市第六人民医院）
    sh_route = await client.plan_route("家（南京鼓楼区）", "上海市第六人民医院")
    assert sh_route["ok"] is True
    assert "高铁" in sh_route["mode"]
    sh_pts = [p["location"] for p in sh_route["points"]]
    assert "上海虹桥站" in sh_pts
    assert "济南西站" not in sh_pts  # 绝不能穿过济南西站去上海
    assert "北京南站" not in sh_pts  # 绝不能穿过北京南站去上海
    assert "上海市第六人民医院" in sh_route["summary"]

    # 2. 北京协和医院专线
    xh_route = await client.plan_route("家（南京鼓楼区）", "北京协和医院")
    assert xh_route["ok"] is True
    assert "北京协和医院" in [p["location"] for p in xh_route["points"]]
    assert "北京协和医院" in xh_route["summary"]
    assert "到达积水潭医院" not in xh_route["summary"]

    # 3. 返程路线测试（北京积水潭医院 -> 家）
    return_route = await client.plan_route("北京积水潭医院", "家（南京鼓楼区）")
    assert return_route["ok"] is True
    assert "返程" in return_route["mode"]
    ret_pts = [p["location"] for p in return_route["points"]]
    # 返程起点为北京，终点为南京家
    assert ret_pts[0] == "北京积水潭医院"
    assert ret_pts[-1] == "家（南京鼓楼区）"
    assert "返程" in return_route["summary"]


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
async def test_guardian_direct_and_quick_endpoints(ctx, elder):
    """测试直接路线规划与无 trip_id 时的快速建程联动。"""
    from app.api.routes_guardian import direct_route, create_quick_trip, QuickTripIn

    # 1. 直接路线规划
    res_direct = await direct_route("家（南京鼓楼区）", "南京鼓楼医院")
    assert res_direct["ok"] is True
    assert "约约" not in res_direct["route"]["summary"]  # 杜绝约约字样
    assert "打车" in res_direct["route"]["summary"]

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


@pytest.mark.asyncio
async def test_amap_hangzhou_and_suzhou_and_general_intercity():
    """测试杭州、苏州专线及通用城际规划，杜绝非北京目的地被北京南站/济南西站劫持。"""
    client = AmapWebClient()

    # 1. 杭州专线
    hz_route = await client.plan_route("家（南京鼓楼区）", "杭州市第一人民医院")
    assert hz_route["ok"] is True
    hz_pts = [p["location"] for p in hz_route["points"]]
    assert "杭州东站" in hz_pts
    assert "北京南站" not in hz_pts
    assert "济南西站" not in hz_pts
    assert "杭州" in hz_route["summary"]

    # 2. 苏州专线
    sz_route = await client.plan_route("家（南京鼓楼区）", "苏州大学附属第一医院")
    assert sz_route["ok"] is True
    sz_pts = [p["location"] for p in sz_route["points"]]
    assert "苏州站" in sz_pts
    assert "北京南站" not in sz_pts
    assert "济南西站" not in sz_pts
    assert "苏州" in sz_route["summary"]

    # 3. 通用城际行程（如合肥），绝不被北京南站劫持
    hf_route = await client.plan_route("家（南京鼓楼区）", "合肥市第一人民医院")
    assert hf_route["ok"] is True
    hf_pts = [p["location"] for p in hf_route["points"]]
    assert "北京南站" not in hf_pts
    assert "济南西站" not in hf_pts


@pytest.mark.asyncio
async def test_guardian_json_string_plan_and_station_waypoints(ctx, elder):
    """测试数据库中 JSON 字符串格式 plan 字段的容错解析，及上海/杭州站点正常通行判定。"""
    import json
    from app.api.routes_guardian import resolve_trip_origin, resolve_trip_destination

    # 1. 测试 plan 字段为 JSON 序列化字符串时的解析稳定性，杜绝 AttributeError
    serialized_plan = json.dumps({
        "title": "杭州就医出行计划书",
        "pages": [{
            "rows": [
                {"label": "出发", "value": "家（南京鼓楼区）"},
                {"label": "医院", "value": "杭州市第一人民医院"},
                {"label": "到达", "value": "杭州东站"},
            ]
        }]
    })
    trip_record = {
        "purpose": None,
        "plan": serialized_plan,
    }
    origin = resolve_trip_origin(trip_record)
    dest = resolve_trip_destination(trip_record)
    assert origin == "家（南京鼓楼区）"
    assert dest == "杭州市第一人民医院"

    # 2. 测试上海行程中途径“上海虹桥站”上报不误报偏航
    sh_trip = await ctx.repos.insert("trips", {
        "elder_id": elder["id"],
        "purpose": "前往上海市第六人民医院骨科看诊",
        "status": "ongoing",
        "origin": "家（南京鼓楼区）",
        "destination": "上海市第六人民医院",
    })
    res_sh_station = await process_checkpoint(ctx, sh_trip["id"], CheckpointIn(
        location="上海虹桥站候车中", lng=121.3201, lat=31.1942
    ))
    assert res_sh_station["status"] == "normal"
    assert res_sh_station["alert_sent"] is False
    assert "一切正常" in res_sh_station["checkpoint"]["note"]

