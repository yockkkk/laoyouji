"""北斗适老多智能体协同出行护航引擎单元与集成测试 (Test BDS Escort Engine).

涵盖 R1 与 R4 全部技术指标：
1. CGCS2000 / WGS84 / GCJ-02 大地坐标转换精度（亚米/毫米级收敛）
2. 北斗三号 NMEA-0183 $BDGGA 校验和生成与逆向语法解析
3. 北斗亚米级 RTK/PPP 遥测数据模型（0.35m 精度、18+ 颗卫星、HDOP<0.9）
4. 适老微地形代价路由算法（避台阶、避陡坡、优先林荫与长椅）
5. 长沙示范路线实测（湖南省人民医院、中南大学湘雅医院、湖南烈士公园）
6. 涉诈高危目的地主动拦截与安全网关防御
7. 突发急症/跌倒一键 SOS 三甲医院急救绿色通道极速重划
8. 5 页完整版《北斗适老出行护航方案书》装配渲染
9. FastAPI REST 接口全覆盖验证
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents import plan_builder
from app.bootstrap import build_context
from app.core.subagents import AgentReport
from app.main import app
from app.providers.bds_service import (
    bds_service,
    calculate_nmea_checksum,
    cgcs2000_to_gcj02,
    generate_bdgga,
    gcj02_to_cgcs2000,
    gcj02_to_wgs84,
    haversine_distance_m,
    out_of_china,
    parse_bdgga,
    wgs84_to_gcj02,
)
from app.services.elder_routing_service import (
    ElderEscortRouteRequest,
    elder_routing_service,
)


# =====================================================================
# 1. 坐标系转换与几何距离计算测试
# =====================================================================

def test_cgcs2000_wgs84_gcj02_conversion_precision():
    """验证坐标正逆转换与精度收敛。"""
    # 长沙五一广场 / 营盘路坐标
    wgs_lng, wgs_lat = 112.986200, 28.204500

    # 1. 正变换 WGS84 -> GCJ-02
    gcj_lng, gcj_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
    assert gcj_lng != wgs_lng
    assert gcj_lat != wgs_lat
    # 偏移量通常在数百米内
    dist_offset = haversine_distance_m((wgs_lng, wgs_lat), (gcj_lng, gcj_lat))
    assert 200.0 < dist_offset < 1000.0

    # 2. 逆变换 GCJ-02 -> WGS84 (CGCS2000)
    recovered_lng, recovered_lat = gcj02_to_wgs84(gcj_lng, gcj_lat)
    diff_m = haversine_distance_m((wgs_lng, wgs_lat), (recovered_lng, recovered_lat))
    # 迭代算法保证逆变换误差小于 0.05 米
    assert diff_m < 0.05

    # 3. CGCS2000 等价映射
    cgcs_gcj_lng, cgcs_gcj_lat = cgcs2000_to_gcj02(wgs_lng, wgs_lat)
    assert cgcs_gcj_lng == gcj_lng
    assert cgcs_gcj_lat == gcj_lat

    cgcs_back_lng, cgcs_back_lat = gcj02_to_cgcs2000(gcj_lng, gcj_lat)
    assert abs(cgcs_back_lng - wgs_lng) < 1e-5
    assert abs(cgcs_back_lat - wgs_lat) < 1e-5

    # 4. 境外坐标测试 (不偏移)
    us_lng, us_lat = -122.4194, 37.7749
    assert out_of_china(us_lng, us_lat) is True
    out_lng, out_lat = wgs84_to_gcj02(us_lng, us_lat)
    assert (out_lng, out_lat) == (us_lng, us_lat)


# =====================================================================
# 2. NMEA-0183 $BDGGA 报文与遥测数据模型测试
# =====================================================================

def test_bdgga_nmea_generation_and_parsing():
    """验证 $BDGGA 报文生成、校验和计算及逆向语法解析。"""
    lat, lng = 28.204500, 112.986200
    sentence = generate_bdgga(
        lat=lat,
        lng=lng,
        altitude_m=55.4,
        fix_quality=4,
        satellites=22,
        hdop=0.71,
        diff_age=0.9,
    )

    assert sentence.startswith("$BDGGA,")
    assert sentence.endswith("\r\n")

    # 验证校验和
    parsed = parse_bdgga(sentence)
    assert parsed["talker"] == "BD"
    assert parsed["fix_quality"] == "RTK_FIXED"
    assert parsed["fix_quality_code"] == 4
    assert parsed["satellites"] == 22
    assert parsed["hdop"] == 0.71
    assert parsed["altitude_m"] == 55.4
    assert abs(parsed["latitude"] - lat) < 1e-4
    assert abs(parsed["longitude"] - lng) < 1e-4

    # 验证校验和篡改后报错
    corrupted = sentence.replace("*", "A*")
    with pytest.raises(ValueError):
        parse_bdgga(corrupted)


def test_bds_live_telemetry_model():
    """验证北斗实时遥测数据模型符合赛题与 PROJECT.md 契约。"""
    telemetry = bds_service.get_live_telemetry(lat=28.2140, lng=112.9870)
    assert telemetry.satellites_in_view >= 18
    assert telemetry.satellites_used >= 14
    assert telemetry.fix_quality == "RTK_FIXED"
    assert telemetry.horizontal_accuracy_m <= 0.40  # 亚米级 (0.35m 左右)
    assert telemetry.hdop < 0.9                     # 水平精度因子
    assert telemetry.vdop < 1.2                     # 垂直精度因子
    assert telemetry.raw_nmea_sentence.startswith("$BDGGA")
    assert "B1I" in telemetry.bds_bands
    assert "B2a" in telemetry.bds_bands
    assert "B3I" in telemetry.bds_bands
    assert telemetry.coordinate_system == "CGCS2000"


# =====================================================================
# 3. 适老微地形代价路由与长沙示范场景测试
# =====================================================================

def test_elder_micro_terrain_cost_routing_avoid_stairs_and_slopes():
    """验证适老多目标路由算法满足零台阶与坡度限制。"""
    req = ElderEscortRouteRequest(
        elder_id="elder_test_01",
        origin=(112.9862, 28.2045),
        destination_name="湖南省人民医院（天心阁院区）",
        health_conditions=["双膝骨关节炎", "轻度高血压"],
        avoid_stairs=True,
        max_slope_percent=4.0,
        prefer_rest_benches=True,
    )
    res = elder_routing_service.plan_elder_route(req)

    assert res.plan_id.startswith("BDS-ROUTE-")
    assert "湖南省人民医院" in res.route_name
    assert res.stairs_count == 0                     # 零台阶认证
    assert res.max_gradient_percent <= 4.0          # 最大坡度严格受控
    assert res.barrier_free_score >= 0.95           # 无障碍高评分
    assert res.rest_benches_count >= 3              # 沿途长椅不少于3处
    assert len(res.steps) >= 3                      # 关键路口地标步骤
    assert len(res.geofence_corridor) >= 2          # 航迹走廊折线
    assert res.bds_satellite_count >= 18
    assert res.bds_accuracy_m <= 0.40
    assert len(res.emergency_hospitals_nearby) >= 2


def test_changsha_demonstration_scenarios():
    """验证长沙三大示范场景（湘雅医院、省人民医院、烈士公园）。"""
    # 场景 1: 中南大学湘雅医院
    req_xy = ElderEscortRouteRequest(
        elder_id="elder_test_02",
        origin=(112.9862, 28.2045),
        destination_name="中南大学湘雅医院骨科门诊",
        avoid_stairs=True,
    )
    res_xy = elder_routing_service.plan_elder_route(req_xy)
    assert "湘雅" in res_xy.route_name
    assert res_xy.stairs_count == 0
    assert res_xy.max_gradient_percent <= 4.0
    assert res_xy.rest_benches_count >= 3

    # 场景 2: 湖南烈士公园
    req_park = ElderEscortRouteRequest(
        elder_id="elder_test_03",
        origin=(112.9862, 28.2045),
        destination_name="湖南烈士公园南门适老步道",
        avoid_stairs=True,
    )
    res_park = elder_routing_service.plan_elder_route(req_park)
    assert "烈士公园" in res_park.route_name
    assert res_park.stairs_count == 0
    assert res_park.rest_benches_count >= 5
    assert res_park.weather_summary is not None
    assert "林荫" in res_park.weather_summary["advice"] or "树荫" in res_park.voice_announcement


# =====================================================================
# 4. 主动防御（涉诈拦截）与突发急症 SOS 绿通测试
# =====================================================================

def test_scam_destination_interception():
    """验证主动安全防御网关拦截针对老人的涉诈高危行程。"""
    # 涉诈会销与假药
    scam_req = ElderEscortRouteRequest(
        elder_id="elder_scam_test",
        origin=(112.9862, 28.2045),
        destination_name="城郊闭门养生讲座免费领鸡蛋会销点",
    )
    with pytest.raises(ValueError) as exc_info:
        elder_routing_service.plan_elder_route(scam_req)
    assert "拦截" in str(exc_info.value)

    # 审核接口直接调用
    audit_scam = elder_routing_service.audit_destination_safety("远郊神药体验馆")
    assert audit_scam["is_safe"] is False
    assert audit_scam["risk_level"] == "CRITICAL_SCAM"
    assert audit_scam["intercepted"] is True

    # 正规医院放行
    audit_safe = elder_routing_service.audit_destination_safety("湖南省人民医院")
    assert audit_safe["is_safe"] is True
    assert audit_safe["risk_level"] == "LOW"
    assert audit_safe["intercepted"] is False


def test_emergency_sos_green_channel():
    """验证突发身体不适一键 SOS 直连三甲急救绿色通道。"""
    current_pos = (112.9862, 28.2045)  # 营盘路
    sos_res = elder_routing_service.emergency_sos_reroute(
        current_coords=current_pos,
        elder_name="张阿姨",
        condition="突发剧烈心慌胸闷",
    )

    assert sos_res["status"] == "SOS_DISPATCHED"
    assert "急诊" in sos_res["nearest_hospital"]["emergency_dept"]
    assert sos_res["distance_m"] > 0
    assert sos_res["emergency_phone"]
    assert "北斗" in sos_res["voice_broadcast"]
    assert "张阿姨" in sos_res["voice_broadcast"]
    assert sos_res["bds_telemetry"]["fix_quality"] == "RTK_FIXED"
    assert len(sos_res["steps"]) >= 2


# =====================================================================
# 5. 5页《北斗适老出行护航方案书》装配渲染测试
# =====================================================================

def test_5_page_bds_escort_plan_structure():
    """验证五页《北斗适老出行护航方案书》标题、页序与字段确定性。"""
    elder = {"name": "张桂芳", "city": "长沙", "id": "elder_1"}

    # 准备北斗微地形与气象数据
    route_req = ElderEscortRouteRequest(
        elder_id="elder_1",
        origin=(112.9862, 28.2045),
        destination_name="湖南省人民医院（天心阁院区）",
        avoid_stairs=True,
    )
    bds_route = elder_routing_service.plan_elder_route(route_req).model_dump()

    reports = [
        AgentReport(
            agent="health",
            ok=True,
            summary="挂号完成",
            data={
                "appointment": {
                    "hospital": "湖南省人民医院（天心阁院区）",
                    "department": "老年医学科",
                    "doctor": "刘副主任医师",
                    "date": "2026-09-30",
                    "city": "长沙",
                    "fee": 50,
                },
            },
        ),
        AgentReport(
            agent="bds_nav",
            ok=True,
            summary="北斗适老路径规划完成",
            data={"bds_route": bds_route},
        ),
        AgentReport(
            agent="weather",
            ok=True,
            summary="微气候评估完成",
            data={
                "weather_escort": {
                    "city": "长沙",
                    "date": "2026-09-30",
                    "condition": "晴间多云",
                    "temp_range": "24~30 ℃",
                    "uv_index": "中等 (3级)",
                    "shade_coverage_percent": "85%",
                    "umbrella": False,
                    "advice": "适宜出行，林荫覆盖率高，随身带好温水杯。",
                },
            },
        ),
    ]

    card = plan_builder.build("bds_escort_plan", elder, reports, city="长沙")

    assert card["type"] == "bds_escort_plan"
    assert "张桂芳" in card["title"]
    assert "北斗适老出行护航方案书" in card["title"]
    assert card["printable"] is True
    assert len(card["pages"]) == 5

    page_nos = [p["no"] for p in card["pages"]]
    assert page_nos == [1, 2, 3, 4, 5]

    titles = [p["title"] for p in card["pages"]]
    assert titles[0] == "第一页 · 适老目的地与体征适配"
    assert titles[1] == "第二页 · 北斗亚米级无障碍适老路线"
    assert titles[2] == "第三页 · 适老步道微地形与休憩补给点"
    assert "第四页" in titles[3] and "气象环境与遮阳防雨指引" in titles[3]
    assert titles[4] == "第五页 · 北斗安全电子围栏与紧急守护"

    # 验证字段无缺失
    assert card["complete"] is True
    assert card["missing"] == []


# =====================================================================
# 6. 多智能体接缝注册与调度契约测试
# =====================================================================

def test_multi_agent_bds_nav_and_weather_registration():
    """验证 bootstrap 装配上下文时 bds_nav 与 weather 成功注册。"""
    ctx = build_context()
    agent_names = list(ctx.agents.keys())
    assert "bds_nav" in agent_names
    assert "weather" in agent_names
    assert "main" in agent_names
    assert "health" in agent_names
    assert "travel" in agent_names

    subagent_names = ctx.subagents.names()
    assert "bds_nav" in subagent_names
    assert "weather" in subagent_names

    # 验证工具派发器中包含新工具
    assert ctx.tools.get("plan_bds_elder_route") is not None
    assert ctx.tools.get("inspect_micro_terrain") is not None
    assert ctx.tools.get("locate_rest_benches") is not None
    assert ctx.tools.get("get_bds_weather_escort") is not None
    assert ctx.tools.get("get_shade_comfort_index") is not None


# =====================================================================
# 7. FastAPI REST 接口全链路端到端测试
# =====================================================================

@pytest.mark.asyncio
async def test_api_bds_endpoints():
    """验证 /api/bds/ 路由组 5 大端点响应格式符合预期。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 实时北斗遥测
        r_tel = await client.get("/api/bds/telemetry/live?lat=28.2045&lng=112.9862")
        assert r_tel.status_code == 200
        data_tel = r_tel.json()
        assert data_tel["fix_quality"] == "RTK_FIXED"
        assert data_tel["satellites_in_view"] >= 18
        assert data_tel["horizontal_accuracy_m"] <= 0.40
        assert data_tel["raw_nmea_sentence"].startswith("$BDGGA")

        # 2. 适老微地形路线规划
        r_route = await client.post(
            "/api/bds/escort/route",
            json={
                "elder_id": "elder_api_test",
                "origin": [112.9862, 28.2045],
                "destination_name": "湖南省人民医院",
                "health_conditions": ["膝关节退行性病变"],
                "avoid_stairs": True,
                "max_slope_percent": 4.0,
            },
        )
        assert r_route.status_code == 200
        data_route = r_route.json()
        assert data_route["stairs_count"] == 0
        assert data_route["max_gradient_percent"] <= 4.0
        assert data_route["rest_benches_count"] >= 3
        assert len(data_route["steps"]) >= 3

        # 3. 涉诈审核拦截
        r_scam = await client.post(
            "/api/bds/escort/audit-destination",
            json={"destination_name": "闭门养生讲座免费领鸡蛋"},
        )
        assert r_scam.status_code == 200
        assert r_scam.json()["is_safe"] is False
        assert r_scam.json()["risk_level"] == "CRITICAL_SCAM"

        # 4. 突发急症 SOS 绿通
        r_sos = await client.post(
            "/api/bds/escort/emergency-sos",
            json={
                "coords": [112.9862, 28.2045],
                "elder_name": "张阿姨",
                "condition": "突发心绞痛",
            },
        )
        assert r_sos.status_code == 200
        data_sos = r_sos.json()
        assert data_sos["status"] == "SOS_DISPATCHED"
        assert "湘雅" in data_sos["nearest_hospital"]["name"] or "省人民医院" in data_sos["nearest_hospital"]["name"]

        # 5. 5页完整方案书卡片生成
        r_card = await client.post(
            "/api/bds/escort/plan-book",
            json={
                "elder_id": "elder_1",
                "elder_name": "张桂芳",
                "destination_name": "湖南省人民医院（天心阁院区）",
                "city": "长沙",
            },
        )
        assert r_card.status_code == 200
        data_card = r_card.json()
        assert data_card["type"] == "bds_escort_plan"
        assert len(data_card["pages"]) == 5
        assert data_card["complete"] is True
