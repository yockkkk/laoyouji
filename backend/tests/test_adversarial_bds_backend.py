"""Adversarial stress testing suite for BDS backend algorithms, routing, telemetry, and safety defenses.

第八届湖南省大学生智能导航科技创新大赛（科技创意类赛道）
Adversarial Verification Suite:
1. Extreme & boundary geodetic inputs (poles, antimeridian, Null Island (0,0), negative elevations).
2. Micro-terrain cost routing under harsh conditions: extreme slope angles (>15%), routes saturated with 200+ stairs, negative bench counts, severe rainstorm weather penalties.
3. NMEA generator and parser with malformed strings, corrupted checksums, truncated fields, and unexpected talker IDs ($GPGGA vs $BDGGA vs $GLGGA).
4. Scam destination detection with evasive variants (spaces, special symbols, leetspeak, homophones, whitelist cloaking).
5. Emergency SOS reroute with remote coordinates and simultaneous corridor deviation.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Tuple

import pytest

from app.api.routes_guardian import (
    BdsCheckpointEvaluation,
    BdsCheckpointPayload,
    evaluate_bds_checkpoint,
    min_distance_to_corridor_m,
)
from app.providers.bds_service import (
    BdsTelemetry,
    bds_service,
    calculate_nmea_checksum,
    cgcs2000_to_gcj02,
    format_nmea_latitude,
    format_nmea_longitude,
    generate_bdgga,
    gcj02_to_cgcs2000,
    gcj02_to_wgs84,
    haversine_distance_m,
    out_of_china,
    parse_bdgga,
    parse_nmea_latitude,
    parse_nmea_longitude,
    wgs84_to_gcj02,
)
from app.services.elder_routing_service import (
    ElderEscortRouteRequest,
    ElderEscortRouteResponse,
    MicroTerrainEdge,
    elder_routing_service,
)
from tests.bds_fixtures import (
    PathSegment,
    calculate_segment_cost,
    evaluate_route_barrier_free_score,
    evaluate_scam_risk,
    parse_bdgga_sentence,
)


# ==============================================================================
# 1. 极端/边界大地坐标与高程逆变测试 (Adversarial Geodetic & Altitude Tests)
# ==============================================================================

class TestAdversarialGeodeticInputs:
    """测试极地、日界线、零岛 (0,0) 与极限负高程的数值稳定性。"""

    def test_pole_coordinates_and_antimeridian_geodetics(self):
        """用例 1.1: 验证北极点 (lat=90.0)、南极点 (lat=-90.0) 与日界线 (lng=±180.0) 坐标转换无数值发散。"""
        polar_points = [
            (0.0, 90.0),    # 北极
            (0.0, -90.0),   # 南极
            (180.0, 0.0),   # 国际日期变更线（东）
            (-180.0, 0.0),  # 国际日期变更线（西）
            (179.999999, 89.999999),
            (-179.999999, -89.999999),
        ]

        for lng, lat in polar_points:
            # 极地境外断言
            assert out_of_china(lng, lat) is True

            # WGS84 -> GCJ-02 境外保持原值不偏移
            trans_lng, trans_lat = wgs84_to_gcj02(lng, lat)
            assert trans_lng == lng
            assert trans_lat == lat

            # 逆转换保持一致
            rev_lng, rev_lat = gcj02_to_wgs84(trans_lng, trans_lat)
            assert rev_lng == lng
            assert rev_lat == lat

            # CGCS2000 等价映射
            cgcs_lng, cgcs_lat = cgcs2000_to_gcj02(lng, lat)
            assert cgcs_lng == lng
            assert cgcs_lat == lat

    def test_zero_gps_island_and_out_of_bounds_filtering(self):
        """用例 1.2: 验证经纬度 (0,0) 零岛与越界坐标在轨迹评测中触发校准保护而不误报偏航。"""
        corridor = [(112.9862, 28.2045), (112.9855, 28.1882)]
        utc_ts = datetime.now(timezone.utc).isoformat()

        # 1. 硬件未定位 (0.0, 0.0)
        p_zero = BdsCheckpointPayload(trip_id="trip_adv_001", lng=0.0, lat=0.0, timestamp=utc_ts)
        eval_zero = evaluate_bds_checkpoint(p_zero, corridor)
        assert eval_zero.status == "NORMAL"
        assert eval_zero.is_safe is True
        assert "校准" in eval_zero.audio_reassurance

        # 2. 经纬度绝对值越界 (lng > 180 or lat > 90)
        p_out_lng = BdsCheckpointPayload(trip_id="trip_adv_002", lng=185.2, lat=28.2, timestamp=utc_ts)
        eval_out_lng = evaluate_bds_checkpoint(p_out_lng, corridor)
        assert eval_out_lng.status == "NORMAL"
        assert eval_out_lng.is_safe is True

        p_out_lat = BdsCheckpointPayload(trip_id="trip_adv_003", lng=112.9, lat=-95.0, timestamp=utc_ts)
        eval_out_lat = evaluate_bds_checkpoint(p_out_lat, corridor)
        assert eval_out_lat.status == "NORMAL"
        assert eval_out_lat.is_safe is True

        # 3. 路线规划层对 (0,0) 出发地的容错兜底
        req_zero = ElderEscortRouteRequest(
            elder_id="elder_adv_0",
            origin=(0.0, 0.0),
            destination_name="湖南省人民医院",
        )
        res_zero = elder_routing_service.plan_elder_route(req_zero)
        assert res_zero.stairs_count == 0
        assert len(res_zero.steps) >= 3

    def test_negative_elevations_dead_sea_and_trench(self):
        """用例 1.3: 验证负高程场景（如吐鲁番艾丁湖 -154m、死海 -414m、马里亚纳海沟 -10994m）的数据合规性。"""
        negative_altitudes = [-154.0, -414.0, -10994.0, -0.1]

        for alt in negative_altitudes:
            # 1. NMEA 报文生成负高程
            nmea = generate_bdgga(lat=28.2045, lng=112.9862, altitude_m=alt)
            assert f",{alt:.1f},M," in nmea

            # 2. NMEA 报文反解析校验
            parsed = parse_bdgga(nmea)
            assert abs(parsed["altitude_m"] - alt) < 1e-4

            # 3. 实时遥测模型对负高程的承载能力
            tel = BdsTelemetry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                latitude=28.2045,
                longitude=112.9862,
                altitude_m=alt,
            )
            assert tel.altitude_m == alt

    def test_haversine_antipodal_extremes_and_numerical_safety(self):
        """用例 1.4: 验证对跖点 (Antipodal points) 极大距离与重合点零距离的大圆距离计算安全性。"""
        # 对跖点两点（赤道相反经度）
        p1 = (0.0, 0.0)
        p2 = (180.0, 0.0)
        dist_half_sphere = haversine_distance_m(p1, p2)
        # 半球周长约为 20015 km (20015086m)
        assert 20000000.0 < dist_half_sphere < 20050000.0

        # 两极对跖点
        north_pole = (0.0, 90.0)
        south_pole = (0.0, -90.0)
        dist_poles = haversine_distance_m(north_pole, south_pole)
        assert 20000000.0 < dist_poles < 20050000.0

        # 相同点零距离（不得出现 ZeroDivisionError 或浮点下溢）
        assert haversine_distance_m(p1, p1) == 0.0

    def test_cgcs2000_roundtrip_convergence_at_boundaries(self):
        """用例 1.5: 验证中国境内四至边缘坐标的 CGCS2000/GCJ-02 双向收敛精度小于 0.05 米。"""
        boundary_coords = [
            (73.55, 39.25),   # 西端帕米尔高原
            (134.77, 47.74),  # 东端黑瞎子岛
            (122.50, 53.56),  # 北端漠河
            (109.50, 18.25),  # 南端三亚
        ]
        for lng, lat in boundary_coords:
            gcj_lng, gcj_lat = cgcs2000_to_gcj02(lng, lat)
            back_lng, back_lat = gcj02_to_cgcs2000(gcj_lng, gcj_lat)
            error_m = haversine_distance_m((lng, lat), (back_lng, back_lat))
            assert error_m < 0.05, f"边界坐标 ({lng}, {lat}) 收敛误差 {error_m}m 超出 0.05m 阈值"


# ==============================================================================
# 2. 微地形恶劣环境鲁棒性与边界代价测试 (Adversarial Micro-Terrain & Harsh Conditions)
# ==============================================================================

class TestAdversarialMicroTerrainHarshConditions:
    """测试极端坡度 (>15%)、饱和台阶 (200+阶)、负数长椅及暴雨恶劣天气的算法弹性。"""

    def test_extreme_slope_angles_over_15_percent(self):
        """用例 2.1: 验证极端大陡坡 (>15%, 25%, 50%) 代价函数施加极高惩罚但无数值溢出。"""
        # 长度 100m，坡度 18.0% 的极端陡坡
        edge_steep = MicroTerrainEdge(
            from_node="A",
            to_node="B",
            length_m=100.0,
            gradient_percent=18.0,
            stairs_count=0,
            has_ramp=False,
            has_elevator=False,
            bench_count=0,
            shade_percent=0.0,
            coords=[(112.98, 28.20), (112.98, 28.21)],
            description="高耸过街陡坡",
            landmark="陡坡",
        )
        # 正常适老上限 max_slope=4.0
        cost_steep = edge_steep.calculate_cost(avoid_stairs=True, max_slope=4.0)
        # c_slope = 5.0 * (18.0 / 4.0) = 22.5 -> multiplier = 23.5 -> cost = 2350.0
        assert cost_steep == pytest.approx(2350.0, rel=1e-3)
        assert cost_steep > edge_steep.length_m * 20.0

        # 坡度 50% 的极陡阶梯坡
        edge_cliff = MicroTerrainEdge(
            from_node="A",
            to_node="B",
            length_m=100.0,
            gradient_percent=50.0,
            stairs_count=0,
            has_ramp=False,
            has_elevator=False,
            bench_count=0,
            shade_percent=0.0,
            coords=[],
            description="悬崖式阶梯斜坡",
            landmark="悬崖坡",
        )
        cost_cliff = edge_cliff.calculate_cost(avoid_stairs=True, max_slope=4.0)
        # c_slope = 5.0 * (50.0 / 4.0) = 62.5 -> multiplier = 63.5 -> cost = 6350.0
        assert cost_cliff == pytest.approx(6350.0, rel=1e-3)

        # 验证 PathSegment 二次激增惩罚模型
        seg_steep = PathSegment("极端陡坡", (112.98, 28.20), (112.98, 28.21), length_m=100.0, slope_percent=20.0)
        seg_cost = calculate_segment_cost(seg_steep, max_slope_percent=4.0)
        # excess = 16.0 -> (16/4)^2 = 16 -> c_slope = 5.0 * (1 + 16) = 85 -> multiplier = 86 -> cost = 8600.0
        assert seg_cost == pytest.approx(8600.0, rel=1e-3)

    def test_route_saturated_with_200_plus_stairs(self):
        """用例 2.2: 验证路段包含 250 级饱和超长步梯时，代价惩罚达到阻断级别。"""
        edge_stairs = MicroTerrainEdge(
            from_node="A",
            to_node="B",
            length_m=200.0,
            gradient_percent=2.0,
            stairs_count=250,  # 250 级台阶
            has_ramp=False,
            has_elevator=False,
            bench_count=0,
            shade_percent=0.0,
            coords=[],
            description="250级连续超长大步梯",
            landmark="千步梯",
        )
        # 适老规避台阶 (avoid_stairs=True)
        cost_avoid = edge_stairs.calculate_cost(avoid_stairs=True)
        # c_stairs = 100.0 -> multiplier = 101.0 -> cost = 20200.0
        assert cost_avoid == pytest.approx(20200.0, rel=1e-3)

        # 若未开启规避 (avoid_stairs=False)，每级台阶加 2.0 代价
        cost_no_avoid = edge_stairs.calculate_cost(avoid_stairs=False)
        # c_stairs = 250 * 2.0 = 500.0 -> multiplier = 501.0 -> cost = 100200.0
        assert cost_no_avoid == pytest.approx(100200.0, rel=1e-3)

        # 验证路网预言机 PathSegment 的 100x 台阶阻断
        seg_stairs = PathSegment("饱和长梯", (112.98, 28.20), (112.98, 28.21), length_m=100.0, stairs_count=250)
        cost_seg_stairs = calculate_segment_cost(seg_stairs, avoid_stairs=True)
        # c_stairs = 100.0 * 250 = 25000.0 -> cost = 100 * (1 + 25000) = 2500100.0
        assert cost_seg_stairs > 2500000.0

        # 验证路线无障碍评分归零保护
        score = evaluate_route_barrier_free_score([seg_stairs])
        assert score == 0.0

    def test_stair_bypass_with_elevators_and_ramps(self):
        """用例 2.3: 验证虽有 250 级台阶但配备垂直电梯或无障碍缓坡时，台阶惩罚被成功豁免至 0.05。"""
        edge_with_lift = MicroTerrainEdge(
            from_node="A",
            to_node="B",
            length_m=100.0,
            gradient_percent=1.0,
            stairs_count=250,
            has_ramp=False,
            has_elevator=True,  # 配备垂直电梯
            bench_count=1,
            shade_percent=0.5,
            coords=[],
            description="配垂直升降直梯的过街立体连廊",
            landmark="无障碍天桥电梯",
        )
        cost_lift = edge_with_lift.calculate_cost(avoid_stairs=True)
        # c_stairs 豁免为 0.05, b_amenity = 0.15 -> multiplier = 1 + 0.05 - 0.15 = 0.90 -> cost = 90.0
        assert cost_lift == pytest.approx(90.0, rel=1e-3)

    def test_negative_bench_counts_and_clamping(self):
        """用例 2.4: 验证负数长椅 (bench_count < 0) 不会反向增加负面收益或破坏代价下限。"""
        edge_neg_bench = MicroTerrainEdge(
            from_node="A",
            to_node="B",
            length_m=100.0,
            gradient_percent=1.0,
            stairs_count=0,
            has_ramp=True,
            has_elevator=False,
            bench_count=-10,  # 负数长椅脏数据
            shade_percent=0.0,
            coords=[],
            description="异常长椅数据路段",
            landmark="异常段",
        )
        cost = edge_neg_bench.calculate_cost()
        # bench_count <= 0 时 b_amenity=0，multiplier=1.0 -> cost=100.0
        assert cost == pytest.approx(100.0, rel=1e-3)

        # 极限高额奖励不得导致负代价 (受 max(0.2, ...) 保护)
        edge_over_amenity = MicroTerrainEdge(
            from_node="A",
            to_node="B",
            length_m=100.0,
            gradient_percent=0.0,
            stairs_count=0,
            has_ramp=True,
            has_elevator=True,
            bench_count=100,
            shade_percent=1.0,
            coords=[],
            description="超饱和长椅林荫段",
            landmark="林荫道",
        )
        cost_amenity = edge_over_amenity.calculate_cost()
        assert cost_amenity >= edge_over_amenity.length_m * 0.2

    def test_severe_rainstorm_weather_penalties_on_steep_slopes(self):
        """用例 2.5: 验证暴雨恶劣天气惩罚对露天湿滑陡坡施加额外风雨阻断乘数。"""
        # 1. 露天无遮阳/风雨廊
        edge_unsheltered = MicroTerrainEdge(
            from_node="A", to_node="B", length_m=100.0, gradient_percent=1.0,
            stairs_count=0, has_ramp=True, has_elevator=False, bench_count=0,
            shade_percent=0.0, coords=[], description="露天广场", landmark="广场",
        )
        cost_rain_open = edge_unsheltered.calculate_cost(weather_harsh=True)
        # c_weather = (1.0 - 0.0) * 0.5 = 0.5 -> cost = 150.0
        assert cost_rain_open == pytest.approx(150.0, rel=1e-3)

        # 2. 风雨连廊路段 (shade_percent=1.0)
        edge_sheltered = MicroTerrainEdge(
            from_node="A", to_node="B", length_m=100.0, gradient_percent=1.0,
            stairs_count=0, has_ramp=True, has_elevator=False, bench_count=0,
            shade_percent=1.0, coords=[], description="遮雨连廊", landmark="连廊",
        )
        cost_rain_sheltered = edge_sheltered.calculate_cost(weather_harsh=True)
        # c_weather = 0.0, b_amenity = 0.1 -> multiplier = 0.9 -> cost = 90.0
        assert cost_rain_sheltered == pytest.approx(90.0, rel=1e-3)
        assert cost_rain_open > cost_rain_sheltered

        # 3. PathSegment 暴雨+坡度叠加
        seg_wet_slope = PathSegment(
            "暴雨露天坡道", (112.98, 28.20), (112.98, 28.21), length_m=100.0,
            slope_percent=3.5, is_sheltered=False,
        )
        cost_wet_slope = calculate_segment_cost(seg_wet_slope, is_rainy=True)
        # c_weather = 2.0 + 3.0 = 5.0 -> multiplier = 6.0 -> cost = 600.0
        assert cost_wet_slope == pytest.approx(600.0, rel=1e-3)

    def test_zero_slope_limit_algorithmic_boundary(self):
        """用例 2.6: 经验证探查 MicroTerrainEdge.calculate_cost 在非正坡度阈值 (max_slope=0.0) 下的除零边界。"""
        edge = MicroTerrainEdge(
            from_node="A", to_node="B", length_m=100.0, gradient_percent=5.0,
            stairs_count=0, has_ramp=True, has_elevator=False, bench_count=0,
            shade_percent=0.0, coords=[], description="坡道路段", landmark="坡道",
        )
        # 边界验证：当参数为 0.0 时触发 ZeroDivisionError 脆弱性暴露
        with pytest.raises(ZeroDivisionError):
            edge.calculate_cost(max_slope=0.0)

    def test_route_planning_with_extreme_health_morbidity_profile(self):
        """用例 2.7: 验证极端多病共存老人档案（全髋置换+重度骨质疏松+心脏起搏器）规划路线仍保持零台阶。"""
        req_sick = ElderEscortRouteRequest(
            elder_id="elder_critical_morbidity",
            origin=(112.9862, 28.2045),
            destination_name="中南大学湘雅医院骨科门诊",
            health_conditions=[
                "人工全膝关节表面置换术后",
                "双侧全髋关节置换",
                "重度骨质疏松伴病理性骨折史",
                "III度房室传导阻滞植入起搏器",
                "双眼黄斑变性低视力",
            ],
            avoid_stairs=True,
            max_slope_percent=2.0,
            prefer_rest_benches=True,
        )
        res = elder_routing_service.plan_elder_route(req_sick)
        assert res.stairs_count == 0
        assert res.max_gradient_percent <= 2.5
        assert res.rest_benches_count >= 3
        assert res.barrier_free_score >= 0.98


# ==============================================================================
# 3. NMEA-0183 发生器与解析器对抗注入测试 (Adversarial NMEA Stress Tests)
# ==============================================================================

class TestAdversarialNmeaGeneratorAndParser:
    """测试畸变 NMEA 字符串、损坏校验和、截断字段及非标 Talker ID。"""

    def test_corrupted_checksums_and_flipped_bits(self):
        """用例 3.1: 验证 NMEA 校验和单比特翻转、异或错误及被篡改报文被坚决拦截并抛出 ValueError。"""
        valid_sentence = generate_bdgga(lat=28.2045, lng=112.9862, altitude_m=50.0)
        assert valid_sentence.startswith("$BDGGA,")

        # 1. 篡改校验和数值
        body, csum = valid_sentence.strip()[1:].split("*")
        flipped_csum = f"{(int(csum, 16) ^ 0x01):02X}"
        corrupted_sentence = f"${body}*{flipped_csum}\r\n"

        with pytest.raises(ValueError, match="NMEA 校验和不匹配"):
            parse_bdgga(corrupted_sentence)

        # 2. 校验和尾部附带垃圾数据时的差异化表现：
        # bds_fixtures.parse_bdgga_sentence 严格比对全量后缀并拒绝；
        # 而 bds_service.parse_bdgga 取 csum_part[:2] 允许尾部存在换行等杂质。
        trailing_sentence = f"${body}*{csum}EXTRA\r\n"
        with pytest.raises(ValueError, match="Checksum mismatch"):
            parse_bdgga_sentence(trailing_sentence)

        parsed_tolerant = parse_bdgga(trailing_sentence)
        assert parsed_tolerant["talker"] == "BD"

    def test_missing_delimiters_and_invalid_syntax(self):
        """用例 3.2: 验证缺少前导 $ 符号或缺少 * 校验分隔符的畸变字符串。"""
        # 缺少 $
        with pytest.raises(ValueError, match="缺少前导"):
            parse_bdgga("BDGGA,080000.00,2812.27,N,11259.17,E,4,21,0.72,50.0,M,-14.2,M,1.0,0128*5A\r\n")

        # 缺少 *
        with pytest.raises(ValueError, match="缺少校验和分隔符"):
            parse_bdgga("$BDGGA,080000.00,2812.27,N,11259.17,E,4,21,0.72,50.0,M,-14.2,M,1.0,0128\r\n")

        # 空字符串与空白符
        with pytest.raises(ValueError):
            parse_bdgga("")
        with pytest.raises(ValueError):
            parse_bdgga("   \r\n  ")

    def test_unexpected_talker_ids_gpgga_vs_bdgga_vs_glgga(self):
        """用例 3.3: 验证 Talker ID 异构兼容与拒绝规约 ($BDGGA 成功, $GPGGA 兼容 GP, $GLGGA/$GAGGA 拒绝)。"""
        # 1. 北斗原生 $BDGGA
        bd_sentence = generate_bdgga(lat=28.2045, lng=112.9862)
        parsed_bd = parse_bdgga(bd_sentence)
        assert parsed_bd["talker"] == "BD"

        # 2. 兼容 GPS $GPGGA
        gp_body = bd_sentence.strip()[1:].split("*")[0].replace("BDGGA", "GPGGA")
        gp_csum = calculate_nmea_checksum(gp_body)
        gp_sentence = f"${gp_body}*{gp_csum}\r\n"
        parsed_gp = parse_bdgga(gp_sentence)
        assert parsed_gp["talker"] == "GP"

        # 3. 兼容 GNSS 多模 $GNGGA
        gn_body = bd_sentence.strip()[1:].split("*")[0].replace("BDGGA", "GNGGA")
        gn_csum = calculate_nmea_checksum(gn_body)
        gn_sentence = f"${gn_body}*{gn_csum}\r\n"
        parsed_gn = parse_bdgga(gn_sentence)
        assert parsed_gn["talker"] == "GN"

        # 4. 格洛纳斯 $GLGGA 拒绝
        gl_body = bd_sentence.strip()[1:].split("*")[0].replace("BDGGA", "GLGGA")
        gl_csum = calculate_nmea_checksum(gl_body)
        gl_sentence = f"${gl_body}*{gl_csum}\r\n"
        with pytest.raises(ValueError, match="非预期 GGA 语句类型"):
            parse_bdgga(gl_sentence)

        # 5. 伽利略 $GAGGA 拒绝
        ga_body = bd_sentence.strip()[1:].split("*")[0].replace("BDGGA", "GAGGA")
        ga_csum = calculate_nmea_checksum(ga_body)
        ga_sentence = f"${ga_body}*{ga_csum}\r\n"
        with pytest.raises(ValueError, match="非预期 GGA 语句类型"):
            parse_bdgga(ga_sentence)

        # 6. fixtures 校验器严格只放行 BD
        with pytest.raises(ValueError, match="Not a BDS talker"):
            parse_bdgga_sentence(gp_sentence)

    def test_truncated_fields_and_safe_defaults(self):
        """用例 3.4: 验证 NMEA 语句字段被部分截断时，解析器安全赋默认值而不发生 IndexError 崩溃。"""
        # 仅有 talker 与时间的极短合法校验和语句
        minimal_body = "BDGGA,093000.00"
        csum = calculate_nmea_checksum(minimal_body)
        sentence = f"${minimal_body}*{csum}\r\n"

        parsed = parse_bdgga(sentence)
        assert parsed["talker"] == "BD"
        assert parsed["latitude"] == 0.0
        assert parsed["longitude"] == 0.0
        assert parsed["fix_quality_code"] == 0
        assert parsed["fix_quality"] == "INVALID"
        assert parsed["satellites"] == 0

    def test_southern_and_western_hemispheres_nmea_roundtrip(self):
        """用例 3.5: 验证南半球 (S) 与西半球 (W) 负经纬度在 NMEA ddmm.mmmm 格式下的编码与解码双向还原。"""
        test_cases = [
            (-33.8688, 151.2093),   # 悉尼（南半球、东经）
            (40.7128, -74.0060),    # 纽约（北半球、西经）
            (-22.9068, -43.1729),   # 里约热内卢（南半球、西经）
        ]
        for lat, lng in test_cases:
            lat_str, lat_hemi = format_nmea_latitude(lat)
            lng_str, lng_hemi = format_nmea_longitude(lng)

            # 符号方向校验
            assert lat_hemi == ("N" if lat >= 0 else "S")
            assert lng_hemi == ("E" if lng >= 0 else "W")

            # 逆向解析
            recovered_lat = parse_nmea_latitude(lat_str, lat_hemi)
            recovered_lng = parse_nmea_longitude(lng_str, lng_hemi)

            assert abs(recovered_lat - lat) < 1e-4
            assert abs(recovered_lng - lng) < 1e-4

    def test_nmea_parser_non_hex_and_garbage_payload(self):
        """用例 3.6: 验证注入非十六进制校验和（如 *ZZ、*GG）或乱码符号时安全抛出 ValueError。"""
        with pytest.raises(ValueError):
            parse_bdgga("$BDGGA,080000.00,2812.27,N,11259.17,E,4,21*ZZ\r\n")

        with pytest.raises(ValueError):
            parse_bdgga("$#%&^!@*00\r\n")


# ==============================================================================
# 4. 涉诈目的地变种与对抗逃逸挖掘测试 (Adversarial Scam Evasion Mining)
# ==============================================================================

class TestAdversarialScamDestinationDetection:
    """实证检验涉诈高危目的地在空格、特殊符号、拼音混杂、同音字及白名单嵌套下的防御穿透。"""

    def test_canonical_scam_destinations_blocked(self):
        """用例 4.1: 基线对照：标准涉诈目的地被安全网关 100% 拦截并阻断路线规划。"""
        canonical_scams = [
            "远郊神药体验馆",
            "闭门养生讲座免费领鸡蛋",
            "城郊特效降压药体验点",
            "原始股投资养老项目",
            "养老床位返利体验中心",
        ]
        for scam in canonical_scams:
            # 1. 审核接口直接判定
            audit = elder_routing_service.audit_destination_safety(scam)
            assert audit["is_safe"] is False
            assert audit["risk_level"] == "CRITICAL_SCAM"
            assert audit["intercepted"] is True

            # 2. 规划层拦截并抛出 ValueError
            req = ElderEscortRouteRequest(
                elder_id="elder_test_scam",
                origin=(112.9862, 28.2045),
                destination_name=scam,
            )
            with pytest.raises(ValueError, match="拦截"):
                elder_routing_service.plan_elder_route(req)

    def test_scam_evasion_via_whitespace_injection(self):
        """用例 4.2: 经验证探查【字间空格插值】对抗逃逸脆弱性（实证揭示朴素子串匹配被绕过）。"""
        spaced_variants = [
            "免 费 领 鸡 蛋",
            "神 药 体 验 馆",
            "闭 门 养 生 讲 座",
            "原 始 股 投 资",
        ]
        for var in spaced_variants:
            audit = elder_routing_service.audit_destination_safety(var)
            oracle = evaluate_scam_risk(var)

            # 实证发现：空格分隔导致原始子串规则失效 (Bypass Confirmed)
            evasion_succeeded = audit["is_safe"] is True and oracle["is_scam"] is False
            assert evasion_succeeded, f"预期探查到空格逃逸成功，但实际被拦截了: {var}"

            # 归一化防御对比：清洗空白字符后必须 100% 成功拦截
            sanitized = re.sub(r"\s+", "", var)
            audit_sanitized = elder_routing_service.audit_destination_safety(sanitized)
            assert audit_sanitized["is_safe"] is False
            assert audit_sanitized["intercepted"] is True

    def test_scam_evasion_via_special_symbols_and_punctuation(self):
        """用例 4.3: 经验证探查【特殊符号与标点插值】（★、.、-、_、@）逃逸脆弱性。"""
        symbol_variants = [
            "神★药★体★验★馆",
            "闭.门.养.生.讲.座",
            "免-费-领-鸡-蛋",
            "买保健品~送黄金",
        ]
        for var in symbol_variants:
            audit = elder_routing_service.audit_destination_safety(var)
            # 实证发现：特殊符号打断字词连续性，导致 audit_destination_safety 漏判
            assert audit["is_safe"] is True, f"特殊符号样本未穿透: {var}"

            # 归一化防御：剥离非汉字字符后重新核验阻断
            sanitized = re.sub(r"[^\u4e00-\u9fa5]", "", var)
            audit_sanitized = elder_routing_service.audit_destination_safety(sanitized)
            assert audit_sanitized["is_safe"] is False

    def test_scam_evasion_via_leetspeak_and_pinyin_hybrids(self):
        """用例 4.4: 经验证探查【数字代字与拼音混合】（0元领、mianfei领、shenyao）逃逸脆弱性。"""
        pinyin_leetspeak_variants = [
            ("0元领鸡蛋", "免费领鸡蛋"),
            ("mianfei领鸡蛋", "免费领鸡蛋"),
            ("shenyao体验馆", "神药体验馆"),
        ]
        for var, semantic_equivalent in pinyin_leetspeak_variants:
            audit = elder_routing_service.audit_destination_safety(var)
            # 实证发现：拼音混杂在当前纯中文词表中发生逃逸
            assert audit["is_safe"] is True, f"拼音混杂样本未发生逃逸: {var}"

            # 语义等价对照验证
            clean_audit = elder_routing_service.audit_destination_safety(semantic_equivalent)
            assert clean_audit["is_safe"] is False

    def test_scam_evasion_via_homophones(self):
        """用例 4.5: 经验证探查【同音错别字混淆】（免非、神要、避门养声）逃逸脆弱性。"""
        homophone_variants = [
            ("免非领鸡蛋", "免费领鸡蛋"),
            ("神要体验馆", "神药体验馆"),
            ("避门养声讲座", "闭门养生讲座"),
        ]
        for var, orig in homophone_variants:
            audit = elder_routing_service.audit_destination_safety(var)
            # 实证发现：同音字替换绕过严格字面比对
            assert audit["is_safe"] is True, f"同音字样本未发生逃逸: {var}"

            orig_audit = elder_routing_service.audit_destination_safety(orig)
            assert orig_audit["is_safe"] is False

    def test_scam_destination_cloaked_with_legitimate_whitelist_names(self):
        """用例 4.6: 经验证探查【白名单地标伪装嵌套】（如‘湖南省人民医院旁神药体验馆’、‘烈士公园免费体验理疗’）。"""
        # 1. 验证后端 elder_routing_service 安全网关的前置防御性：
        #    即使目的地含有‘省人民医院’或‘烈士公园’，涉诈审核依然前置执行并成功阻断！
        cloaked_dest_1 = "湖南省人民医院旁神药体验馆"
        audit_1 = elder_routing_service.audit_destination_safety(cloaked_dest_1)
        assert audit_1["is_safe"] is False
        assert audit_1["risk_level"] == "CRITICAL_SCAM"

        req_cloaked = ElderEscortRouteRequest(
            elder_id="elder_cloaked_test",
            origin=(112.9862, 28.2045),
            destination_name=cloaked_dest_1,
        )
        with pytest.raises(ValueError, match="拦截"):
            elder_routing_service.plan_elder_route(req_cloaked)

        # 2. 实证揭示测试桩 bds_fixtures.evaluate_scam_risk 的白名单掩盖缺陷：
        #    当含有‘公园’时，evaluate_scam_risk 误判放行了‘烈士公园免费体验理疗’
        cloaked_dest_2 = "烈士公园免费体验理疗"
        oracle_res = evaluate_scam_risk(cloaked_dest_2)
        assert oracle_res["is_scam"] is False, "实证确认 fixture oracle 存在白名单掩蔽漏洞"

    def test_anti_scam_defense_hardening_via_input_sanitization(self):
        """用例 4.7: 构造并验证反逃逸归一化过滤器（Sanitization Pipeline），证明其防御加固可行性。"""
        def normalize_adversarial_text(text: str) -> str:
            # 1. 剥离所有空格、特殊标点、符号
            cleaned = re.sub(r"[\s\*\-\._★@~#%&!?^+=/\\|,，。；：]+", "", text)
            # 2. 基础 Leetspeak / 常见变形映射
            replacements = {
                "0元": "免费",
                "零元": "免费",
                "免非": "免费",
                "神要": "神药",
                "避门": "闭门",
                "养声": "养生",
            }
            for k, v in replacements.items():
                cleaned = cleaned.replace(k, v)
            return cleaned

        adversarial_corpus = [
            "免 费 领 鸡 蛋",
            "神★药★体★验★馆",
            "闭.门.养.生.讲.座",
            "0元领鸡蛋",
            "神要体验馆",
            "免非领鸡蛋",
        ]

        for dirty_dest in adversarial_corpus:
            sanitized = normalize_adversarial_text(dirty_dest)
            audit = elder_routing_service.audit_destination_safety(sanitized)
            assert audit["is_safe"] is False, f"加固过滤器未能阻断归一化后的样本: {dirty_dest} -> {sanitized}"
            assert audit["risk_level"] == "CRITICAL_SCAM"


# ==============================================================================
# 5. 突发应急求助与偏航复合压力测试 (Adversarial Emergency SOS & Deviation)
# ==============================================================================

class TestAdversarialEmergencySosAndDeviation:
    """测试远距离跨省坐标、严重偏航伴随 SOS 以及非数值非法输入的防御表现。"""

    def test_emergency_sos_with_remote_beijing_coordinates(self):
        """用例 5.1: 验证老人在外省（北京 116.3748, 39.9485，距长沙 ~1340km）触发 SOS 时计算安全平稳。"""
        remote_coords = (116.3748, 39.9485)
        sos_res = elder_routing_service.emergency_sos_reroute(
            current_coords=remote_coords,
            elder_name="张阿姨",
            condition="突发剧烈心绞痛",
        )
        assert sos_res["status"] == "SOS_DISPATCHED"
        assert sos_res["distance_m"] > 1300000  # 1300公里
        assert sos_res["estimated_duration_min"] > 10000
        assert sos_res["nearest_hospital"]["name"] in ["中南大学湘雅医院", "湖南省人民医院（天心阁院区）", "中南大学湘雅二医院"]
        assert len(sos_res["geofence_corridor"]) == 2
        assert sos_res["geofence_corridor"][0] == remote_coords
        assert "张阿姨" in sos_res["voice_broadcast"]

    def test_emergency_sos_with_zero_island_coordinates(self):
        """用例 5.2: 验证老人在硬件未定位 (0.0, 0.0) 状态下触发 SOS 不会产生除零或距离越界崩溃。"""
        zero_coords = (0.0, 0.0)
        sos_res = elder_routing_service.emergency_sos_reroute(
            current_coords=zero_coords,
            elder_name="张阿姨",
            condition="突发跌倒无法站立",
        )
        assert sos_res["status"] == "SOS_DISPATCHED"
        assert sos_res["distance_m"] > 10000000  # ~12,245 公里
        assert sos_res["bds_telemetry"]["latitude"] == 0.0
        assert sos_res["bds_telemetry"]["longitude"] == 0.0
        assert sos_res["emergency_phone"] != ""

    def test_simultaneous_corridor_deviation_and_emergency_reroute(self):
        """用例 5.3: 验证【严重偏离走廊 2.3km + 突发呼救 SOS】时，绿通重划后偏航告警安全清除。"""
        corridor_original = [(112.9862, 28.2045), (112.9855, 28.1882)]
        deviated_lng, deviated_lat = 113.0100, 28.2045  # 偏离走廊约 2.3km

        payload = BdsCheckpointPayload(
            trip_id="trip_deviated_sos",
            lng=deviated_lng,
            lat=deviated_lat,
            speed_kmh=1.2,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # 1. 偏航状态确认
        eval_before = evaluate_bds_checkpoint(payload, corridor_original)
        assert eval_before.status == "OFF_ROUTE"
        assert eval_before.is_safe is False
        assert eval_before.distance_to_corridor_m > 2000.0

        # 2. 突发触发应急绿通重划
        sos_res = elder_routing_service.emergency_sos_reroute(
            current_coords=(deviated_lng, deviated_lat),
            elder_name="张阿姨",
            condition="迷路受困伴随心慌",
        )
        assert sos_res["status"] == "SOS_DISPATCHED"
        emergency_corridor = sos_res["geofence_corridor"]

        # 3. 在新生成的应急绿通走廊下复核
        eval_after = evaluate_bds_checkpoint(payload, emergency_corridor)
        assert eval_after.status == "NORMAL"
        assert eval_after.is_safe is True
        assert eval_after.distance_to_corridor_m == 0.0  # 走廊以偏航点为起点，偏航立即解除

    def test_emergency_sos_with_nan_and_inf_coordinates(self):
        """用例 5.4: 验证非法浮点值 (NaN, +Inf, -Inf) 作为 SOS 坐标时抛出清晰 ValueError 而非未捕获异常。"""
        for bad_val in [float("nan"), float("inf"), -float("inf")]:
            with pytest.raises(ValueError):
                elder_routing_service.emergency_sos_reroute((bad_val, 28.2045))

            with pytest.raises(ValueError):
                elder_routing_service.emergency_sos_reroute((112.9862, bad_val))

    def test_emergency_sos_telemetry_validity_under_stress(self):
        """用例 5.5: 验证 SOS 响应中嵌载的北斗高精遥测数据严格符合 PROJECT.md 亚米级契约。"""
        sos_res = elder_routing_service.emergency_sos_reroute(
            current_coords=(112.9862, 28.2045),
            elder_name="张阿姨",
        )
        telemetry = sos_res["bds_telemetry"]
        assert telemetry["fix_quality"] == "RTK_FIXED"
        assert telemetry["satellites_in_view"] >= 18
        assert telemetry["satellites_used"] >= 14
        assert telemetry["horizontal_accuracy_m"] <= 0.40
        assert telemetry["hdop"] < 0.90
        assert telemetry["vdop"] < 1.20
        assert telemetry["raw_nmea_sentence"].startswith("$BDGGA")
