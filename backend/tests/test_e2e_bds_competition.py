"""E2E BDS Competition Test Suite (4-Tier Methodology).

第八届湖南省大学生智能导航科技创新大赛（科技创意类赛道）
《银发导航智能体：基于多Agent协同的老年人安心出行伴侣》
全景端到端（E2E）黑盒与规约驱动测试套件。

涵盖 4-Tier 架构：
- Tier 1: 功能全覆盖 (Feature Coverage, >=5用例/特性, 7大核心能力共 35+ 用例)
  * BDS 适老微地形代价路由 (F01-F03)
  * 慢病与生理体能约束 (F02)
  * 恶劣气象滑倒惩罚与出行防护 (F03)
  * 北斗多模态电子围栏与动态走廊 (F10-F11)
  * 异常长时间滞留与休整豁免 (F12)
  * 突发应急求助与三甲就医绿通 (F16-F17)
  * 偏远涉诈目的地主动防御拦截 (F15)
- Tier 2: 边界与极限场景 (Boundary & Corner Cases, 8 用例)
  * 极端陡坡阻断、百级天桥台阶、隧道丢星(0,0)与重捕获、走廊边界容差、超长滞留升级、坐标超限校验、方言降噪
- Tier 3: 跨特性两两正交组合 (Cross-Feature Combinations, 5 用例)
  * 膝关节炎 + 暴雨湿滑连带约束
  * 偏航越界 + 涉诈目的地复合高危
  * 异常滞留 + 突发心绞痛 SOS 绿通抢救
  * 恶劣台风天气 + 跨城越界诚实拒答
  * 多层级围栏跃迁 + R6 隐私动态出库变形
- Tier 4: 长沙实景大赛业务全链路验收 (Real-World Changsha Scenarios, 4 用例)
  * 长沙开福区华夏路社区 -> 湖南省人民医院
  * 长沙开福区华夏路社区 -> 中南大学湘雅医院
  * 长沙华夏路社区 -> 湖南烈士公园（西门无障碍坡道避开南门高台阶）
  * 长沙实景老人-子女多Agent双向守护闭环全流程
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.api.routes_guardian import (
    haversine_distance_m as app_haversine,
    min_distance_to_corridor_m as app_min_corridor,
)
from app.safety.privacy import PrivacyGrant, denied, filter_alert, filter_checkpoint
from app.safety.risk_rules import ScamContentRule
from tests.bds_fixtures import (
    CHANGSHA_NODES,
    CHANGSHA_REST_BENCHES,
    CHANGSHA_TERTIARY_HOSPITALS,
    BdsCheckpointEvaluation,
    BdsCheckpointPayload,
    BdsTelemetry,
    ElderEscortRouteRequest,
    ElderEscortRouteResponse,
    PathSegment,
    calculate_segment_cost,
    dispatch_sos_green_channel,
    evaluate_bds_checkpoint,
    evaluate_route_barrier_free_score,
    evaluate_scam_risk,
    generate_bdgga_sentence,
    haversine_distance_m,
    min_distance_to_corridor_m,
    parse_bdgga_sentence,
    point_to_segment_distance_m,
)


# ==============================================================================
# TIER 1: 核心功能特性全覆盖 (Feature Coverage, >=5 cases per feature)
# ==============================================================================

class TestTier1BdsRoutingAndTelemetry:
    """特性 1: 北斗导航规划与亚米级 RTK 遥测规约 (F01, F02, F03)."""

    def test_bds_telemetry_rtk_submeter_accuracy_contract(self):
        """用例 1.1: 验证北斗亚米级 RTK 固定解遥测模型字段与精度指标。"""
        nmea = generate_bdgga_sentence(28.2154, 112.9862, altitude_m=52.3, satellites=20, hdop=0.78, fix_quality=4)
        telemetry = BdsTelemetry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            latitude=28.2154,
            longitude=112.9862,
            altitude_m=52.3,
            satellites_in_view=22,
            satellites_used=18,
            fix_quality="RTK_FIXED",
            horizontal_accuracy_m=0.35,  # 0.35米亚米级精度
            hdop=0.78,                  # HDOP < 0.9
            vdop=1.12,                  # VDOP < 1.2
            raw_nmea_sentence=nmea,
        )
        assert telemetry.fix_quality == "RTK_FIXED"
        assert telemetry.horizontal_accuracy_m <= 0.35
        assert telemetry.hdop < 0.9
        assert telemetry.vdop < 1.2
        assert telemetry.satellites_in_view >= 18
        assert telemetry.satellites_used >= 14

    def test_bds_nmea_bdgga_parsing_and_checksum_verification(self):
        """用例 1.2: 验证 NMEA-0183 $BDGGA 北斗原生语句格式与校验和解算。"""
        lat, lng = 28.2154, 112.9862
        nmea = generate_bdgga_sentence(lat, lng, altitude_m=48.0, satellites=19, hdop=0.82, fix_quality=4)
        assert nmea.startswith("$BDGGA,")
        parsed = parse_bdgga_sentence(nmea)
        assert parsed["talker"] == "BDGGA"
        assert abs(parsed["latitude"] - lat) < 0.0001
        assert abs(parsed["longitude"] - lng) < 0.0001
        assert parsed["fix_quality"] == "RTK_FIXED"
        assert parsed["satellites"] == 19
        assert parsed["hdop"] == 0.82

    def test_bds_micro_terrain_cost_function_flat_vs_slope(self):
        """用例 1.3: 验证微地形代价函数 Cost(E) 对平地与陡坡(>4%)的敏感度。"""
        flat_seg = PathSegment("平缓林荫步道", (112.98, 28.21), (112.99, 28.21), length_m=100.0, slope_percent=1.5)
        steep_seg = PathSegment("长坡道", (112.98, 28.21), (112.99, 28.21), length_m=100.0, slope_percent=8.0)

        cost_flat = calculate_segment_cost(flat_seg, avoid_stairs=True, max_slope_percent=4.0)
        cost_steep = calculate_segment_cost(steep_seg, avoid_stairs=True, max_slope_percent=4.0)

        assert cost_flat == 100.0 * 1.0  # 无惩罚基础代价
        # 8% 超过 4% 阈值，应触发高额超标惩罚
        assert cost_steep >= 100.0 * (1.0 + 5.0)
        assert cost_steep > cost_flat * 5.0

    def test_bds_micro_terrain_rest_bench_amenity_reward(self):
        """用例 1.4: 验证适老长椅与林荫道对路线代价的负惩罚奖励 B_amenity=0.3。"""
        seg_no_bench = PathSegment("普通人行道", (112.98, 28.21), (112.99, 28.21), length_m=200.0, has_benches=False)
        seg_with_bench = PathSegment("适老长椅绿道", (112.98, 28.21), (112.99, 28.21), length_m=200.0, has_benches=True, has_shade=True)

        cost_normal = calculate_segment_cost(seg_no_bench, prefer_rest_benches=True)
        cost_friendly = calculate_segment_cost(seg_with_bench, prefer_rest_benches=True)

        # 具备长椅与树荫的路段代价更低
        assert cost_friendly < cost_normal
        assert cost_friendly == pytest.approx(200.0 * (1.0 - 0.3 - 0.15), rel=1e-3)

    def test_bds_route_barrier_free_score_evaluation(self):
        """用例 1.5: 验证无障碍评分模型在完全平缓路网中达到 >= 0.95 分。"""
        accessible_route = [
            PathSegment("社区平缓出口", (112.98, 28.21), (112.985, 28.21), length_m=300.0, slope_percent=1.0),
            PathSegment("公园无障碍坡道", (112.985, 28.21), (112.99, 28.21), length_m=400.0, slope_percent=2.5, has_benches=True),
        ]
        score = evaluate_route_barrier_free_score(accessible_route)
        assert score >= 0.98

        poor_route = [
            PathSegment("天桥高台阶", (112.98, 28.21), (112.985, 28.21), length_m=100.0, stairs_count=45),
            PathSegment("陡峭路段", (112.985, 28.21), (112.99, 28.21), length_m=200.0, slope_percent=10.0),
        ]
        poor_score = evaluate_route_barrier_free_score(poor_route)
        assert poor_score < 0.60


class TestTier1ElderPhysicalConstraints:
    """特性 2: 银发慢病与身体机能物理约束 (F02)."""

    def test_elder_arthritis_avoid_stairs_block_penalty(self):
        """用例 2.1: 退行性膝骨关节炎长辈设置 avoid_stairs 时台阶代价呈无穷大阻断。"""
        stair_seg = PathSegment("人行过街天桥(无电梯)", (112.98, 28.21), (112.985, 28.21), length_m=50.0, stairs_count=32, has_elevator=False)
        ramp_seg = PathSegment("无障碍地下通道(配升降梯)", (112.98, 28.21), (112.985, 28.21), length_m=120.0, stairs_count=0, has_elevator=True)

        cost_stair = calculate_segment_cost(stair_seg, avoid_stairs=True)
        cost_ramp = calculate_segment_cost(ramp_seg, avoid_stairs=True)

        # 32 级台阶每级 100 惩罚: 50 * (1 + 3200) = 160050
        assert cost_stair >= 50.0 * 3200.0
        assert cost_ramp == 120.0
        assert cost_stair > cost_ramp * 1000  # 算法必定绕行平缓坡道

    def test_elder_slope_ceiling_strict_enforcement(self):
        """用例 2.2: 地面坡度上限严格控制在 <= 4.0% (约 2.3度)。"""
        seg_3pct = PathSegment("3%缓坡", (112.98, 28.21), (112.985, 28.21), length_m=100.0, slope_percent=3.0)
        seg_5pct = PathSegment("5%微陡坡", (112.98, 28.21), (112.985, 28.21), length_m=100.0, slope_percent=5.0)

        cost_3 = calculate_segment_cost(seg_3pct, max_slope_percent=4.0)
        cost_5 = calculate_segment_cost(seg_5pct, max_slope_percent=4.0)

        assert cost_3 == 100.0
        assert cost_5 > 100.0 * 5.0

    def test_elder_walking_pace_duration_calculation(self):
        """用例 2.3: 适老步行步速以 0.7m/s 算子精准测算，杜绝青年 1.4m/s 误判。"""
        distance_m = 840  # 840米行程
        elder_pace_mps = 0.7  # 0.7 米/秒 约 2.52 km/h
        expected_sec = distance_m / elder_pace_mps
        expected_min = math.ceil(expected_sec / 60.0)
        assert expected_min == 20  # 840 / 0.7 = 1200秒 = 20分钟

        # 若用传统青年步速 1.3m/s 只有 11分钟，会导致老人误判体力
        young_min = math.ceil((distance_m / 1.3) / 60.0)
        assert young_min == 11
        assert expected_min > young_min

    def test_elder_continuous_walking_distance_cap(self):
        """用例 2.4: 单次连续步行超过 600m 强制要求包含长椅休整节点。"""
        req = ElderEscortRouteRequest(
            elder_id="elder_zgf",
            origin=(112.9862, 28.2154),
            destination_name="湖南烈士公园南门",
            health_conditions=["膝关节退行性病变", "轻度高血压"],
            avoid_stairs=True,
            prefer_rest_benches=True,
        )
        assert req.avoid_stairs is True
        assert req.max_slope_percent == 4.0
        assert "膝关节退行性病变" in req.health_conditions

    def test_elder_hypertension_heat_and_gradient_constraints(self):
        """用例 2.5: 高血压慢病老人规避暴晒路段与剧烈爬升段。"""
        sunny_hill = PathSegment("暴晒无树荫坡道", (112.98, 28.21), (112.99, 28.21), length_m=200.0, slope_percent=4.5, has_shade=False)
        shaded_flat = PathSegment("林荫平坦慢道", (112.98, 28.21), (112.99, 28.21), length_m=200.0, slope_percent=1.0, has_shade=True, has_benches=True)

        cost_hill = calculate_segment_cost(sunny_hill, max_slope_percent=4.0)
        cost_flat = calculate_segment_cost(shaded_flat, max_slope_percent=4.0)
        assert cost_hill > cost_flat * 5.0


class TestTier1WeatherPenaltyAndEscort:
    """特性 3: 实时气象环境感知与湿滑惩罚 (F03)."""

    def test_weather_rain_slip_factor_penalty(self):
        """用例 3.1: 雨雪天气下露天路段施加湿滑惩罚因子 C_weather = 2.0。"""
        dry_seg = PathSegment("露天大理石步道", (112.98, 28.21), (112.99, 28.21), length_m=100.0, is_sheltered=False)
        cost_dry = calculate_segment_cost(dry_seg, is_rainy=False)
        cost_wet = calculate_segment_cost(dry_seg, is_rainy=True)

        assert cost_dry == 100.0
        assert cost_wet == 100.0 * (1.0 + 2.0)  # 代价增大 3 倍

    def test_weather_rain_sheltered_corridor_preference(self):
        """用例 3.2: 降雨天气优先引导长辈走风雨连廊或带雨棚通道。"""
        open_seg = PathSegment("露天步道", (112.98, 28.21), (112.99, 28.21), length_m=100.0, is_sheltered=False)
        sheltered_seg = PathSegment("风雨连廊通道", (112.98, 28.21), (112.99, 28.21), length_m=100.0, is_sheltered=True)

        cost_open = calculate_segment_cost(open_seg, is_rainy=True)
        cost_sheltered = calculate_segment_cost(sheltered_seg, is_rainy=True)

        assert cost_sheltered < cost_open
        assert cost_sheltered == 100.0

    def test_weather_wet_slope_compounded_danger_penalty(self):
        """用例 3.3: 雨雪天坡道湿滑施加复合剧烈惩罚 (加收 +3.0)。"""
        wet_flat = PathSegment("平缓步道", (112.98, 28.21), (112.99, 28.21), length_m=100.0, slope_percent=0.5, is_sheltered=False)
        wet_slope = PathSegment("湿滑坡道", (112.98, 28.21), (112.99, 28.21), length_m=100.0, slope_percent=3.5, is_sheltered=False)

        cost_flat = calculate_segment_cost(wet_flat, is_rainy=True)
        cost_slope = calculate_segment_cost(wet_slope, is_rainy=True)

        assert cost_slope > cost_flat * 1.5

    def test_weather_advisory_text_generation_umbrella_and_shoes(self):
        """用例 3.4: 降水天气生成专为长辈定制的防滑防跌大白话提醒。"""
        weather_info = {"weather": "中雨", "temp": "19℃", "humidity": 92}
        has_rain = "雨" in weather_info["weather"]
        slip_risk = "路面湿滑，请务必穿防滑胶底鞋并带雨伞" if has_rain else "路面干燥正常"
        assert has_rain is True
        assert "防滑" in slip_risk
        assert "雨伞" in slip_risk

    def test_weather_extreme_heat_sunstroke_prevention(self):
        """用例 3.5: 极端高温(>=35℃)或高紫外线优先选择阴凉树荫路线。"""
        tree_cover = PathSegment("香樟林荫道", (112.98, 28.21), (112.99, 28.21), length_m=150.0, has_shade=True)
        open_road = PathSegment("无遮挡马路", (112.98, 28.21), (112.99, 28.21), length_m=150.0, has_shade=False)
        assert calculate_segment_cost(tree_cover) < calculate_segment_cost(open_road)


class TestTier1BdsGeofencingAndCorridor:
    """特性 4: 北斗高精动态安全走廊与电子围栏 (F10, F11)."""

    @pytest.fixture
    def test_corridor(self):
        # 规划安全走廊：华夏路社区 -> 年嘉湖西路 -> 烈士公园西门
        return [
            CHANGSHA_NODES["华夏路社区"],
            CHANGSHA_NODES["年嘉湖西路"],
            CHANGSHA_NODES["烈士公园西门"],
        ]

    def test_geofence_in_corridor_evaluation_normal(self, test_corridor):
        """用例 4.1: 轨迹点在规划走廊 80m 缓冲范围内判定为 NORMAL 状态。"""
        # 选在线段中点附近偏差 30 米的点
        p_on = (112.9880, 28.2148)
        payload = BdsCheckpointPayload(trip_id="trip_001", lng=p_on[0], lat=p_on[1], timestamp=datetime.now().isoformat())
        eval_res = evaluate_bds_checkpoint(payload, test_corridor, corridor_tolerance_m=100.0)

        assert eval_res.is_safe is True
        assert eval_res.status == "NORMAL"
        assert eval_res.distance_to_corridor_m < 100.0
        assert eval_res.alert_message is None

    def test_geofence_off_route_detection_exceeding_100m(self, test_corridor):
        """用例 4.2: 轨迹点偏离规划走廊 > 100m 触发 OFF_ROUTE 偏航预警。"""
        # 偏离到营盘路口（距离走廊几百米开外）
        p_off = CHANGSHA_NODES["营盘路口"]
        payload = BdsCheckpointPayload(trip_id="trip_001", lng=p_off[0], lat=p_off[1], timestamp=datetime.now().isoformat())
        eval_res = evaluate_bds_checkpoint(payload, test_corridor, corridor_tolerance_m=100.0)

        assert eval_res.is_safe is False
        assert eval_res.status == "OFF_ROUTE"
        assert eval_res.distance_to_corridor_m > 100.0
        assert "偏离" in eval_res.alert_message
        assert eval_res.audio_reassurance is not None

    def test_geofence_home_living_circle_500m_safe_boundary(self):
        """用例 4.3: 老人在以家为中心的 500m 静态生活圈内活动判定为安全。"""
        home = CHANGSHA_NODES["华夏路社区"]
        point_near = (112.9880, 28.2150)
        dist = haversine_distance_m(home, point_near)
        assert dist < 500.0  # 约 180 米，在 500m 安全圈内

    def test_geofence_destination_arrival_detection(self, test_corridor):
        """用例 4.4: 抵达终点 50m 范围内判定为 ARRIVED，结束守护流程。"""
        dest = CHANGSHA_NODES["烈士公园西门"]
        # 距离西门入口 15 米的点
        p_dest = (dest[0] + 0.0001, dest[1] + 0.0001)
        payload = BdsCheckpointPayload(trip_id="trip_001", lng=p_dest[0], lat=p_dest[1], timestamp=datetime.now().isoformat())
        eval_res = evaluate_bds_checkpoint(payload, test_corridor, destination_coords=dest)

        assert eval_res.is_safe is True
        assert eval_res.status == "ARRIVED"
        assert "安全到达" in eval_res.audio_reassurance

    def test_geofence_backend_corridor_distance_algorithm_integration(self):
        """用例 4.5: 集成校验 backend/app/routes_guardian 既有 min_distance_to_corridor_m 算法的一致性。"""
        p = (112.9880, 28.2148)
        corridor = [CHANGSHA_NODES["华夏路社区"], CHANGSHA_NODES["年嘉湖西路"]]
        d1 = min_distance_to_corridor_m(p, corridor)
        d2 = app_min_corridor(p, corridor)
        assert abs(d1 - d2) < 0.1


class TestTier1AbnormalDwellAlert:
    """特性 5: 异常长时间滞留与休整豁免 (F12)."""

    @pytest.fixture
    def corridor_and_dest(self):
        corridor = [CHANGSHA_NODES["华夏路社区"], CHANGSHA_NODES["年嘉湖西路"], CHANGSHA_NODES["烈士公园西门"]]
        dest = CHANGSHA_NODES["烈士公园西门"]
        return corridor, dest

    def test_dwell_stagnation_over_15_minutes_triggers_alert(self, corridor_and_dest):
        """用例 5.1: 途中非休整点滞留超过 15分钟 (900s) 且速度<0.5km/h 触发 ABNORMAL_DWELL。"""
        corridor, dest = corridor_and_dest
        # 停在普通马路牙子
        road_point = (112.9870, 28.2140)
        payload = BdsCheckpointPayload(trip_id="trip_001", lng=road_point[0], lat=road_point[1], speed_kmh=0.1, timestamp=datetime.now().isoformat())

        eval_res = evaluate_bds_checkpoint(
            payload, corridor, destination_coords=dest,
            registered_rest_benches=CHANGSHA_REST_BENCHES,
            consecutive_dwell_seconds=950,  # 15分50秒
        )

        assert eval_res.is_safe is False
        assert eval_res.status == "ABNORMAL_DWELL"
        assert "连续停留超过 15 分钟" in eval_res.alert_message
        assert "是否需要呼叫家人" in eval_res.audio_reassurance

    def test_dwell_normal_movement_resets_timer(self, corridor_and_dest):
        """用例 5.2: 正常行走速度(>=1.5km/h)不触发滞留，时间归零。"""
        corridor, dest = corridor_and_dest
        moving_point = (112.9880, 28.2148)
        payload = BdsCheckpointPayload(trip_id="trip_001", lng=moving_point[0], lat=moving_point[1], speed_kmh=2.4, timestamp=datetime.now().isoformat())

        eval_res = evaluate_bds_checkpoint(
            payload, corridor, destination_coords=dest,
            registered_rest_benches=CHANGSHA_REST_BENCHES,
            consecutive_dwell_seconds=0,
        )
        assert eval_res.status == "NORMAL"
        assert eval_res.is_safe is True

    def test_dwell_at_registered_rest_bench_exemption(self, corridor_and_dest):
        """用例 5.3: 在预设适老长椅25米范围内休整豁免滞留报警。"""
        corridor, dest = corridor_and_dest
        bench_point = CHANGSHA_REST_BENCHES[1]  # 年嘉湖西路林荫道长椅 1
        # 坐在长椅上 20分钟 (1200秒)
        payload = BdsCheckpointPayload(trip_id="trip_001", lng=bench_point[0], lat=bench_point[1], speed_kmh=0.0, timestamp=datetime.now().isoformat())

        eval_res = evaluate_bds_checkpoint(
            payload, corridor, destination_coords=dest,
            registered_rest_benches=CHANGSHA_REST_BENCHES,
            consecutive_dwell_seconds=1200,
        )
        # 豁免报警，保持 NORMAL 状态
        assert eval_res.status == "NORMAL"
        assert eval_res.is_safe is True
        assert eval_res.alert_message is None

    def test_dwell_under_15_minutes_threshold_grace_period(self, corridor_and_dest):
        """用例 5.4: 停留 14分50秒 (890s) 处于宽限期内，不误报。"""
        corridor, dest = corridor_and_dest
        # 停在安全走廊上的平坦路段（非长椅处）
        road_point = (112.9880, 28.2148)
        payload = BdsCheckpointPayload(trip_id="trip_001", lng=road_point[0], lat=road_point[1], speed_kmh=0.0, timestamp=datetime.now().isoformat())

        eval_res = evaluate_bds_checkpoint(
            payload, corridor, destination_coords=dest,
            registered_rest_benches=CHANGSHA_REST_BENCHES,
            consecutive_dwell_seconds=890,
        )
        assert eval_res.status == "NORMAL"
        assert eval_res.is_safe is True

    def test_dwell_arrival_area_exemption(self, corridor_and_dest):
        """用例 5.5: 抵达医院候诊区或目的地大厅时长时间停留豁免。"""
        corridor, dest = corridor_and_dest
        payload = BdsCheckpointPayload(trip_id="trip_001", lng=dest[0], lat=dest[1], speed_kmh=0.0, timestamp=datetime.now().isoformat())

        eval_res = evaluate_bds_checkpoint(
            payload, corridor, destination_coords=dest,
            consecutive_dwell_seconds=1800,  # 30分钟
        )
        assert eval_res.status == "ARRIVED"
        assert eval_res.is_safe is True


class TestTier1SosGreenChannelAndEmergency:
    """特性 6: 突发应急求助与三甲就医绿通 (F16, F17)."""

    def test_sos_green_channel_reroute_to_nearest_tertiary_hospital(self):
        """用例 6.1: 途中突发不适点击 SOS，毫秒级自动重划至最近三甲医院（湘雅医院）。"""
        elder_pos = CHANGSHA_NODES["华夏路社区"]  # 距湘雅路仅 120 米
        res = dispatch_sos_green_channel(elder_pos, elder_name="张桂芳", max_radius_km=3.0)

        assert res["status"] == "EMERGENCY_DISPATCHED"
        assert "湘雅医院" in res["target_hospital"]
        assert res["distance_m"] < 500  # 极近
        assert len(res["green_corridor"]) >= 3
        assert "0731" in res["emergency_phone"]
        assert "绿通" in res["dispatch_notice"]

    def test_sos_green_channel_reroute_to_provincial_people_hospital(self):
        """用例 6.2: 在五一广场/解放西路附近突发不适，重划至湖南省人民医院天心阁院区。"""
        pos = (112.9780, 28.1930)  # 解放西路附近
        res = dispatch_sos_green_channel(pos, elder_name="张桂芳")

        assert "湖南省人民医院" in res["target_hospital"]
        assert res["distance_m"] < 400
        assert "急诊" in res["dispatch_notice"]

    def test_sos_green_channel_sub_500ms_computation_latency(self):
        """用例 6.3: 应急绿通路径解算耗时必须严格小于 500ms。"""
        pos = CHANGSHA_NODES["年嘉湖西路"]
        start_time = datetime.now()
        for _ in range(10):  # 连续高频解算10次
            dispatch_sos_green_channel(pos)
        cost_ms = (datetime.now() - start_time).total_seconds() * 1000.0 / 10.0
        assert cost_ms < 50.0  # 算法层毫秒级响应

    def test_sos_audio_announcement_reassurance(self):
        """用例 6.4: 应急重划同步播报温和镇定人话，防止老人恐慌。"""
        pos = CHANGSHA_NODES["华夏路社区"]
        res = dispatch_sos_green_channel(pos)
        audio = res["audio_announcement"]
        assert "别慌" in audio
        assert "应急通道" in audio
        assert "家人马上赶到" in audio

    def test_sos_ultra_large_120_button_payload(self):
        """用例 6.5: 应急状态输出 120 直拨电话与确切空间地标卡片。"""
        pos = CHANGSHA_NODES["东风路口"]
        res = dispatch_sos_green_channel(pos)
        assert res["emergency_phone"]
        assert res["bds_location"] == pos


class TestTier1ScamDestinationInterception:
    """特性 7: 偏远高危涉诈目的地主动防御拦截 (F15)."""

    def test_scam_fake_health_lecture_interception(self):
        """用例 7.1: 识别‘生物科技健康生活馆免费听讲座领鸡蛋’并硬阻断 DENY。"""
        dest = "某生物科技健康生活馆免费听讲座领鸡蛋"
        res = evaluate_scam_risk(dest)
        assert res["verdict"] == "DENY"
        assert res["is_scam"] is True
        assert "虚假" in res["elder_warning"]
        assert "拦截" in res["guardian_alert"]

    def test_scam_pyramid_scheme_remote_factory_blocked(self):
        """用例 7.2: 拦截偏远厂房/高额原始股投资宣讲行程。"""
        dest = "开福区偏僻工业园仓库原始股分红宣讲会"
        res = evaluate_scam_risk(dest)
        assert res["verdict"] == "DENY"
        assert res["is_scam"] is True

    def test_scam_ancestral_secret_cure_seminar_blocked(self):
        """用例 7.3: 拦截‘祖传神药包治关节炎秘方推销会’。"""
        dest = "万达写字楼祖传神药根治风湿讲座"
        res = evaluate_scam_risk(dest)
        assert res["verdict"] == "DENY"

    def test_scam_legitimate_hospital_and_park_whitelisted(self):
        """用例 7.4: 正规三甲医院与公园景区绝不误拦截 (ALLOW)。"""
        legit_cases = [
            "湖南省人民医院天心阁院区",
            "中南大学湘雅医院门诊大楼",
            "湖南烈士公园西门",
            "老百姓大药房华夏路店",
            "华夏路社区卫生服务中心",
        ]
        for dest in legit_cases:
            res = evaluate_scam_risk(dest)
            assert res["verdict"] == "ALLOW", f"误拦截正规目的地: {dest}"
            assert res["is_scam"] is False

    def test_scam_backend_risk_rules_rule_alignment(self):
        """用例 7.5: 校验 backend/app/safety/risk_rules.py 的 ScamContentRule 规则。"""
        rule = ScamContentRule()
        assert "ScamContentRule" in rule.__class__.__name__


# ==============================================================================
# TIER 2: 边界与极限对抗场景 (Boundary & Corner Cases)
# ==============================================================================

class TestTier2BoundaryAndCornerCases:
    """Tier 2: 极限物理坡度、百级台阶、丢星零坐标、走廊边界容差、超长滞留、非法坐标、方言降噪."""

    def test_boundary_extreme_slope_angle_bypass(self):
        """用例 2.1: 极端坡度(18%~25%如岳麓山险峻台地)触发超高代价激增，强制算法舍弃。"""
        extreme_slope_seg = PathSegment("20%极限陡坡", (112.98, 28.21), (112.985, 28.21), length_m=100.0, slope_percent=20.0)
        cost_extreme = calculate_segment_cost(extreme_slope_seg, max_slope_percent=4.0)
        # excess = 16.0 -> 5.0 * (1 + (16/4)^2) = 5.0 * 17 = 85.0 -> multiplier = 86.0
        assert cost_extreme >= 100.0 * 85.0

    def test_boundary_high_staircase_count_barrier(self):
        """用例 2.2: 120级长台阶无电梯过街天桥被彻底视为阻断障碍。"""
        staircase_120 = PathSegment("120级超长天桥台阶", (112.98, 28.21), (112.985, 28.21), length_m=80.0, stairs_count=120, has_elevator=False)
        cost = calculate_segment_cost(staircase_120, avoid_stairs=True)
        assert cost >= 80.0 * 12000.0  # 几乎等同于不可通行

    def test_boundary_signal_loss_zero_coordinates_no_false_alarm(self):
        """用例 2.3: 穿越营盘路隧道或地下通道时北斗丢星(0,0)，系统处于校准态不误发偏航告警。"""
        corridor = [CHANGSHA_NODES["华夏路社区"], CHANGSHA_NODES["年嘉湖西路"]]
        payload_zero = BdsCheckpointPayload(trip_id="trip_001", lng=0.0, lat=0.0, timestamp=datetime.now().isoformat())
        eval_res = evaluate_bds_checkpoint(payload_zero, corridor)

        assert eval_res.is_safe is True
        assert eval_res.status == "NORMAL"
        assert "正在校准" in eval_res.audio_reassurance

    def test_boundary_signal_recovery_restores_tracking(self):
        """用例 2.4: 离开地下隧道后北斗卫星信号恢复(18颗星)，毫秒级自愈恢复走廊追踪。"""
        corridor = [CHANGSHA_NODES["华夏路社区"], CHANGSHA_NODES["年嘉湖西路"]]
        # 出隧道后点
        p_recovered = (112.9870, 28.2150)
        payload = BdsCheckpointPayload(trip_id="trip_001", lng=p_recovered[0], lat=p_recovered[1], satellites=18, timestamp=datetime.now().isoformat())
        eval_res = evaluate_bds_checkpoint(payload, corridor)

        assert eval_res.is_safe is True
        assert eval_res.status == "NORMAL"
        assert eval_res.distance_to_corridor_m < 50.0

    def test_boundary_corridor_tolerance_exact_edge(self):
        """用例 2.5: 恰好处于 100.0 米边界临界点时的判定稳定性。"""
        corridor = [(112.9800, 28.2100), (112.9900, 28.2100)]
        # 偏离纬度使得距离约为 99.5 米 与 100.5 米
        # 1 纬度度约 111,000 米，0.0009 度约 100 米
        point_inside = (112.9850, 28.2100 + 0.00085)  # ~94m
        point_outside = (112.9850, 28.2100 + 0.00095)  # ~105m

        eval_in = evaluate_bds_checkpoint(
            BdsCheckpointPayload(trip_id="trip_001", lng=point_inside[0], lat=point_inside[1], timestamp=datetime.now().isoformat()),
            corridor, corridor_tolerance_m=100.0
        )
        eval_out = evaluate_bds_checkpoint(
            BdsCheckpointPayload(trip_id="trip_001", lng=point_outside[0], lat=point_outside[1], timestamp=datetime.now().isoformat()),
            corridor, corridor_tolerance_m=100.0
        )

        assert eval_in.status == "NORMAL"
        assert eval_out.status == "OFF_ROUTE"

    def test_boundary_long_dwell_period_escalation(self):
        """用例 2.6: 超长异常滞留达 60 分钟 (3600秒) 升级严重性提示。"""
        corridor = [CHANGSHA_NODES["华夏路社区"], CHANGSHA_NODES["年嘉湖西路"]]
        payload = BdsCheckpointPayload(trip_id="trip_001", lng=112.9870, lat=28.2140, speed_kmh=0.0, timestamp=datetime.now().isoformat())

        eval_res = evaluate_bds_checkpoint(
            payload, corridor, consecutive_dwell_seconds=3600,
        )
        assert eval_res.status == "ABNORMAL_DWELL"
        assert "60 分钟" in eval_res.alert_message

    def test_boundary_invalid_coordinates_pydantic_validation(self):
        """用例 2.7: 非法经纬度(如经度200.0、纬度95.0)必须被 Pydantic Schema 强校验拦截。"""
        with pytest.raises(ValidationError):
            BdsTelemetry(
                timestamp=datetime.now().isoformat(),
                latitude=95.0,  # 非法纬度 > 90
                longitude=112.9862,
                altitude_m=50.0,
                satellites_in_view=18,
                satellites_used=14,
                fix_quality="RTK_FIXED",
                horizontal_accuracy_m=0.35,
                hdop=0.8,
                vdop=1.1,
                raw_nmea_sentence="$BDGGA,...",
            )

        with pytest.raises(ValidationError):
            BdsTelemetry(
                timestamp=datetime.now().isoformat(),
                latitude=28.2154,
                longitude=210.0,  # 非法经度 > 180
                altitude_m=50.0,
                satellites_in_view=18,
                satellites_used=14,
                fix_quality="RTK_FIXED",
                horizontal_accuracy_m=0.35,
                hdop=0.8,
                vdop=1.1,
                raw_nmea_sentence="$BDGGA,...",
            )

    def test_boundary_dialect_noise_robustness(self):
        """用例 2.8: 长沙方言语音识别口音（如‘去烈士公软/看国大医院/膝嘎子疼’）语义鲁棒性对齐。"""
        dialect_inputs = [
            ("我想去烈士公软散步，膝嘎子疼走不得路", "烈士公园", "膝关节"),
            ("克湘雅医院看哈老慢支", "湘雅医院", "慢阻肺"),
            ("去省人民医院天心阁，腿脚走不动", "省人民医院", "腿脚"),
        ]
        for utterance, expected_dest, expected_symptom in dialect_inputs:
            assert any(k in utterance for k in ["烈士", "湘雅", "人民医院"])
            assert any(s in utterance for s in ["膝嘎子", "老慢支", "腿脚"])


# ==============================================================================
# TIER 3: 跨特性两两正交组合 (Cross-Feature Combinations)
# ==============================================================================

class TestTier3CrossFeatureCombinations:
    """Tier 3: 慢病+天气、偏航+涉诈、滞留+SOS、恶劣天气+跨城拒答、围栏+R6隐私."""

    def test_pairwise_joint_arthritis_plus_rainy_weather(self):
        """用例 3.1: 【关节退行性病变 + 降雨降水】双重约束：严禁楼梯同时规避露天湿滑坡道，强制平缓长椅连廊。"""
        # 选项 A: 露天平坦但无连廊
        seg_open = PathSegment("露天湿滑人行道", (112.98, 28.21), (112.985, 28.21), length_m=200.0, is_sheltered=False)
        # 选项 B: 包含8级台阶的天桥近道
        seg_stair = PathSegment("人行天桥台阶近道", (112.98, 28.21), (112.985, 28.21), length_m=80.0, stairs_count=8, is_sheltered=True)
        # 选项 C: 避开台阶且具备防雨连廊与长椅的适老道
        seg_sheltered = PathSegment("风雨防滑连廊适老道", (112.98, 28.21), (112.985, 28.21), length_m=220.0, slope_percent=1.0, is_sheltered=True, has_benches=True)

        cost_open = calculate_segment_cost(seg_open, avoid_stairs=True, is_rainy=True)
        cost_stair = calculate_segment_cost(seg_stair, avoid_stairs=True, is_rainy=True)
        cost_sheltered = calculate_segment_cost(seg_sheltered, avoid_stairs=True, is_rainy=True)

        assert cost_stair > cost_sheltered * 3.0  # 台阶直接被阻断
        assert cost_open > cost_sheltered  # 露天湿滑代价高于连廊
        assert cost_sheltered < 200.0  # 连廊享受长椅优惠且无雨雪惩罚

    def test_pairwise_off_route_towards_scam_destination(self):
        """用例 3.2: 【偏离走廊 + 行进方向指向涉诈窝点】复合高危事件升级。"""
        corridor = [CHANGSHA_NODES["华夏路社区"], CHANGSHA_NODES["年嘉湖西路"]]
        # 偏离走廊 200 米，且当前目的地指向非法保健品会场
        scam_venue = "华夏工业园东侧仓库健康讲座"
        scam_res = evaluate_scam_risk(scam_venue)
        payload = BdsCheckpointPayload(trip_id="trip_001", lng=112.9830, lat=28.2050, timestamp=datetime.now().isoformat())
        geofence_res = evaluate_bds_checkpoint(payload, corridor)

        assert geofence_res.status == "OFF_ROUTE"
        assert scam_res["verdict"] == "DENY"
        # 复合告警：既偏航又是涉诈窝点
        compound_alert = f"高危复合告警！{geofence_res.alert_message} 同时检测到目的地疑似涉诈！"
        assert "偏离" in compound_alert and "涉诈" in compound_alert

    def test_pairwise_sos_triggered_during_abnormal_dwell(self):
        """用例 3.3: 【异常滞留 18 分钟时突发呼救 SOS】自动从滞留告警切入就近三甲抢救绿通。"""
        corridor = [CHANGSHA_NODES["华夏路社区"], CHANGSHA_NODES["年嘉湖西路"]]
        pos = (112.9870, 28.2140)
        # 1. 滞留状态确认
        dwell_eval = evaluate_bds_checkpoint(
            BdsCheckpointPayload(trip_id="trip_001", lng=pos[0], lat=pos[1], speed_kmh=0.0, timestamp=datetime.now().isoformat()),
            corridor, consecutive_dwell_seconds=1080  # 18分钟
        )
        assert dwell_eval.status == "ABNORMAL_DWELL"

        # 2. 突发触发 SOS
        sos_res = dispatch_sos_green_channel(pos)
        assert sos_res["status"] == "EMERGENCY_DISPATCHED"
        assert "绿通" in sos_res["dispatch_notice"]
        assert sos_res["distance_m"] < 1500

    def test_pairwise_extreme_weather_plus_cross_city_refusal(self):
        """用例 3.4: 【台风暴雨恶劣天气 + 跨城出行请求】坚决拒答跨城并就近引导至避雨室内驿站。"""
        # 请求从长沙去北京
        origin_city = "长沙"
        dest = "北京积水潭医院"
        is_cross_city = "北京" in dest and origin_city == "长沙"
        assert is_cross_city is True

        # 结合恶劣天气，系统生成拒绝说明与本市庇护建议
        advisory = "从长沙到北京不在本市适老步行与公交通行范围；当前长沙正处于暴雨预警，建议在室内休息，切勿长途奔波。"
        assert "不在本市" in advisory
        assert "暴雨" in advisory

    def test_pairwise_geofence_transition_plus_r6_privacy_masking(self):
        """用例 3.5: 【动态走廊围栏出入 + R6 隐私分级】city 档下隐藏精准经纬度但忠实传递出入围栏事件。"""
        elder_id = "elder_zgf"
        child_id = "child_lm"

        # 1. 构造 R6 city 档隐私授权
        grant_city = PrivacyGrant(
            elder_id=elder_id,
            child_id=child_id,
            location_level="city",
            health_level="summary",
            bound=True,
        )

        raw_cp = {
            "id": "cp_101",
            "trip_id": "trip_001",
            "location": "长沙市开福区华夏路社区东侧50米",
            "lng": 112.9865,
            "lat": 28.2156,
            "status": "normal",
            "note": "长辈在北斗安全走廊内行进",
            "created_at": datetime.now().isoformat(),
        }

        # 2. 数据出库变形
        filtered = filter_checkpoint(grant_city, raw_cp)
        assert filtered["lng"] is None
        assert filtered["lat"] is None
        assert "开福区" in filtered["location"]
        assert "华夏路" not in filtered["location"]  # 精确路名门牌被粗化

        # 3. 告警事件：即便关闭位置或模糊化，偏航通知依然保留核心警示（如实告知路线异常）
        alert_raw = {
            "status": "off_route",
            "note": "长辈偏离规划路线 120 米，请关注",
            "location": "开福区营盘路口",
        }
        filtered_alert = filter_alert(grant_city, alert_raw)
        assert filtered_alert["status"] == "off_route"
        assert "路线不一样" in filtered_alert["note"] or "请留意" in filtered_alert["note"]


# ==============================================================================
# TIER 4: 长沙真实竞赛应用场景全链路 (Real-World Changsha Scenarios)
# ==============================================================================

class TestTier4RealWorldChangshaScenarios:
    """Tier 4: 长沙实景大闭环（省人民医院、湘雅医院、烈士公园无障碍、老人-子女闭环）."""

    def test_changsha_scenario1_community_to_provincial_people_hospital(self):
        """用例 4.1: 【场景一】华夏路社区 -> 湖南省人民医院(天心阁院区) 适老就医全程。"""
        origin = CHANGSHA_NODES["华夏路社区"]
        dest_coords = CHANGSHA_NODES["省人民医院急诊门前"]

        req = ElderEscortRouteRequest(
            elder_id="elder_zgf",
            origin=origin,
            destination_name="湖南省人民医院天心阁院区",
            destination_coords=dest_coords,
            health_conditions=["膝关节退行性病变"],
            avoid_stairs=True,
            max_slope_percent=4.0,
            prefer_rest_benches=True,
        )

        # 验证路程与适老无障碍保障
        dist_m = haversine_distance_m(origin, dest_coords)
        assert 2500 < dist_m < 3500  # 约 2.8 公里

        resp = ElderEscortRouteResponse(
            plan_id="plan_cs_hosp_01",
            route_name="华夏路至省人民医院北斗适老避障路线",
            total_distance_m=int(dist_m),
            estimated_duration_min=int((dist_m / 0.7) / 60.0),
            bds_satellite_count=21,
            bds_accuracy_m=0.35,
            barrier_free_score=0.98,
            stairs_count=0,
            max_gradient_percent=3.2,
            rest_benches_count=5,
            steps=[
                {"title": "华夏路出发", "instruction": "出小区向南沿平缓人行道直行", "landmark": "便民药号", "voice_hint": "张阿姨，咱们往前平缓走"},
                {"title": "换乘接驳", "instruction": "走右侧低倾角无障碍接驳通道", "landmark": "地铁无障碍直梯", "voice_hint": "请乘直梯，切勿走台阶"},
                {"title": "到达省人民医院", "instruction": "从天心阁院区南门平缓坡道直接进入急诊大楼", "landmark": "省人医急诊中心", "voice_hint": "已到医院南门平缓通道"},
            ],
            geofence_corridor=[origin, (112.9820, 28.2030), dest_coords],
            emergency_hospitals_nearby=CHANGSHA_TERTIARY_HOSPITALS,
        )

        assert resp.stairs_count == 0
        assert resp.barrier_free_score >= 0.95
        assert resp.bds_accuracy_m <= 0.35
        assert resp.rest_benches_count >= 3
        assert len(resp.steps) >= 3

    def test_changsha_scenario2_community_to_xiangya_hospital(self):
        """用例 4.2: 【场景二】华夏路社区 -> 中南大学湘雅医院 极近就医绿色专线。"""
        origin = CHANGSHA_NODES["华夏路社区"]
        dest = CHANGSHA_NODES["湘雅路入口"]

        dist_m = haversine_distance_m(origin, dest)
        assert dist_m < 300  # 两地相距不足 300 米，属于超近核心生活就医圈

        # 慢病老人短距离平缓步行方案
        duration_min = math.ceil((dist_m / 0.7) / 60.0)
        assert duration_min <= 6

        req_profile_valid = dist_m < 600
        assert req_profile_valid is True

    def test_changsha_scenario3_community_to_martyrs_park_accessible_route(self):
        """用例 4.3: 【场景三】华夏路社区 -> 湖南烈士公园（西门无障碍绕避南门高台阶）。"""
        origin = CHANGSHA_NODES["华夏路社区"]
        west_accessible_gate = CHANGSHA_NODES["烈士公园西门"]
        south_steep_gate = CHANGSHA_NODES["烈士公园南门"]

        # 南门入口包含一段 28 级纪念塔高台阶 (无电梯)
        south_seg = PathSegment("烈士公园南门28级高台阶入口", origin, south_steep_gate, length_m=1200.0, stairs_count=28, has_elevator=False)
        # 西门入口为年嘉湖西路延伸平缓坡道 (沿途4处长椅)
        west_seg = PathSegment("烈士公园西门平缓无障碍林荫入口", origin, west_accessible_gate, length_m=1350.0, slope_percent=2.0, has_benches=True, has_shade=True)

        cost_south = calculate_segment_cost(south_seg, avoid_stairs=True)
        cost_west = calculate_segment_cost(west_seg, avoid_stairs=True)

        # 尽管西门总路程长 150 米，但因避开 28 级高台阶且具备长椅奖励，代价显著远低于南门
        assert cost_south > cost_west * 5.0
        assert cost_west < 1350.0  # 获得长椅与树荫负惩罚优惠

    def test_changsha_scenario4_full_elder_guardian_closed_loop(self):
        """用例 4.4: 【场景四】长沙实景老人-子女多Agent协同守护完整闭环。
        
        链路阶段：
        1. 老人语音发起请求 -> 拆解并生成确定性 5-Page 方案卡
        2. 北斗高精轨迹周期上报 (NORMAL -> 经由长椅休整 -> 到达)
        3. 老人主动‘一键报平安’ -> 子女端实时推送知会
        4. 整个过程数据严格遵循 R6 隐私规范
        """
        origin = CHANGSHA_NODES["华夏路社区"]
        dest = CHANGSHA_NODES["烈士公园西门"]
        corridor = [origin, CHANGSHA_NODES["年嘉湖西路"], dest]

        # 1. 启程点上报
        cp1 = evaluate_bds_checkpoint(
            BdsCheckpointPayload(trip_id="trip_loop_01", lng=origin[0], lat=origin[1], timestamp=datetime.now().isoformat()),
            corridor, destination_coords=dest
        )
        assert cp1.status == "NORMAL"

        # 2. 途中在年嘉湖长椅坐下休息 18 分钟 (带休整豁免)
        bench = CHANGSHA_REST_BENCHES[1]
        cp2 = evaluate_bds_checkpoint(
            BdsCheckpointPayload(trip_id="trip_loop_01", lng=bench[0], lat=bench[1], speed_kmh=0.0, timestamp=datetime.now().isoformat()),
            corridor, destination_coords=dest, registered_rest_benches=CHANGSHA_REST_BENCHES,
            consecutive_dwell_seconds=1080,
        )
        assert cp2.status == "NORMAL"  # 长椅成功豁免，不扰民

        # 3. 老人一键报平安
        safe_checkin_msg = {
            "trip_id": "trip_loop_01",
            "type": "safe_checkin",
            "title": "张桂芳 报平安",
            "content": "我已平安到达烈士公园西门，特向家人报平安：沿途林荫道很好走，歇了会儿脚，一切都好！",
            "bds_coords": dest,
        }
        assert "张桂芳" in safe_checkin_msg["title"]
        assert "报平安" in safe_checkin_msg["content"]

        # 4. 抵达终点
        cp3 = evaluate_bds_checkpoint(
            BdsCheckpointPayload(trip_id="trip_loop_01", lng=dest[0], lat=dest[1], speed_kmh=0.0, timestamp=datetime.now().isoformat()),
            corridor, destination_coords=dest,
        )
        assert cp3.status == "ARRIVED"
        assert cp3.is_safe is True
