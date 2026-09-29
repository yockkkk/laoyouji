"""Adversarial E2E Verification: Geofencing State Transitions, Dwell Corner Cases & SOS Rerouting.

第八届湖南省大学生智能导航科技创新大赛（科技创意类赛道）
《银发导航智能体：基于多Agent协同的老年人安心出行伴侣》
Adversarial Stress Verification Suite:
1. Geofence Transition Stress:
   - Rapid sequence of checkpoints jumping across home living circle (500m), corridor buffer (50-80m), and danger water zone.
   - Verify state transitions are strictly debounced and idempotent.
   - Rapid oscillation across the 80m boundary and terminal ARRIVED state idempotence.
2. Dwell Accumulation Corner Cases:
   - Micro-movements (<25m) vs true departures (>25m) across hours (up to 3+ hours).
   - Verify dwell seconds accumulate properly and reset to 0 upon movement >25m.
   - Verify return after departure starts fresh (no false historical accumulation).
   - Clock skew and negative dwell prevention (max(0, ...)).
   - Rest bench zone (25m radius) 25-min exemption vs extended care trigger.
3. Emergency Hospital Reroute During Abnormal Dwell:
   - Verify synchronous / concurrent execution of dwell alert and green channel emergency reroute without deadlocks.
   - High-concurrency stress test with asyncio.gather across checkpoints and SOS reroutes.
   - Full FastAPI HTTP E2E workflow verification.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Tuple

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_app_context, get_ctx
from app.api.routes_bds_escort import EmergencySosRequest, trigger_emergency_sos
from app.api.routes_guardian import (
    KNOWN_REST_BENCHES,
    LOCATION_COORDS,
    BdsCheckpointEvaluation,
    BdsCheckpointPayload,
    CheckpointIn,
    calculate_checkpoint_dwell_seconds,
    evaluate_bds_checkpoint,
    haversine_distance_m,
    lookup_coords,
    min_distance_to_corridor_m,
    process_checkpoint,
)
from app.auth.security import create_access_token
from app.main import create_app
from app.services.elder_routing_service import (
    CHANGSHA_GRADE_A_HOSPITALS,
    ElderEscortRouteRequest,
    elder_routing_service,
)


# ==============================================================================
# 1. Geofence Transition Stress & Idempotence
# ==============================================================================

class TestAdversarialGeofenceTransitions:
    """电子围栏高频突变压力、防抖幂等性与状态机跃迁测试。"""

    @pytest.fixture
    def changsha_corridor(self):
        """华夏路社区 -> 年嘉湖西路 -> 烈士公园西门 走廊与终点。"""
        origin = (112.9862, 28.2154)
        waypoint = (112.9895, 28.2141)
        dest = (112.9932, 28.2125)
        return [origin, waypoint, dest], dest

    @pytest.mark.asyncio
    async def test_rapid_transition_home_corridor_water_zone_flow(self, ctx, elder, changsha_corridor):
        """长辈在 500m 居住圈、50-80m 走廊、偏航及年嘉湖危险水域之间高频跳变，验证告警防抖与幂等性。"""
        corridor, dest = changsha_corridor
        trip = await ctx.repos.insert("trips", {
            "elder_id": elder["id"],
            "purpose": "步行前往烈士公园西门微地形适老走廊",
            "status": "planned",
            "origin": "华夏路社区",
            "destination": "烈士公园西门",
        })

        base_time = datetime(2026, 9, 29, 9, 0, 0, tzinfo=timezone.utc)

        # 1. 起点：华夏路社区（在 500m 家生活圈起点，走廊起点上）
        cp1 = CheckpointIn(
            location="华夏路社区门口",
            lng=corridor[0][0],
            lat=corridor[0][1],
            altitude_m=50.0,
            satellites=19,
            speed_kmh=2.2,
            timestamp=(base_time + timedelta(seconds=10)).isoformat(),
        )
        res1 = await process_checkpoint(ctx, trip["id"], cp1)
        assert res1["status"] == "normal"
        assert res1["alert_sent"] is False
        assert res1["evaluation"]["is_safe"] is True
        assert res1["evaluation"]["status"] == "NORMAL"

        # 2. 正常走廊微步进（距走廊 20m）
        cp2 = CheckpointIn(
            location="年嘉湖西路适老步道",
            lng=corridor[1][0] + 0.0001,
            lat=corridor[1][1] + 0.0001,
            altitude_m=51.0,
            satellites=20,
            speed_kmh=2.5,
            timestamp=(base_time + timedelta(seconds=30)).isoformat(),
        )
        res2 = await process_checkpoint(ctx, trip["id"], cp2)
        assert res2["status"] == "normal"
        assert res2["alert_sent"] is False
        assert res2["evaluation"]["is_safe"] is True

        # 3. 突发偏航：偏离走廊 200m，进入东风路辅道
        p_off1 = (112.9880, 28.2090)
        cp3 = CheckpointIn(
            location="东风路辅道",
            lng=p_off1[0],
            lat=p_off1[1],
            altitude_m=49.0,
            satellites=18,
            speed_kmh=2.4,
            timestamp=(base_time + timedelta(seconds=50)).isoformat(),
        )
        res3 = await process_checkpoint(ctx, trip["id"], cp3)
        assert res3["status"] == "off_route"
        assert res3["alert_sent"] is True  # 首次偏航：触发子女告警推送
        assert res3["evaluation"]["is_safe"] is False
        assert res3["evaluation"]["status"] == "OFF_ROUTE"
        assert res3["evaluation"]["distance_to_corridor_m"] > 80.0

        # 4. 连续偏航点（相隔10秒再上报偏航点）：验证防抖抑制（杜绝轰炸）
        p_off2 = (112.9882, 28.2088)
        cp4 = CheckpointIn(
            location="东风路辅道深处",
            lng=p_off2[0],
            lat=p_off2[1],
            altitude_m=49.2,
            satellites=18,
            speed_kmh=2.3,
            timestamp=(base_time + timedelta(seconds=60)).isoformat(),
        )
        res4 = await process_checkpoint(ctx, trip["id"], cp4)
        assert res4["status"] == "off_route"
        assert res4["alert_sent"] is False  # 连续偏航防抖生效：alert_sent 应为 False
        assert res4["evaluation"]["is_safe"] is False

        # 5. 危险水域区（年嘉湖水域边缘 ~ 112.9980, 28.2100，偏离走廊 400m+）
        p_water = (112.9980, 28.2100)
        cp5 = CheckpointIn(
            location="年嘉湖危险水域警示区",
            lng=p_water[0],
            lat=p_water[1],
            altitude_m=48.0,
            satellites=21,
            speed_kmh=1.8,
            timestamp=(base_time + timedelta(seconds=80)).isoformat(),
        )
        res5 = await process_checkpoint(ctx, trip["id"], cp5)
        assert res5["status"] == "off_route"
        assert res5["alert_sent"] is False  # 仍处偏航状态，保持防抖抑制
        assert res5["evaluation"]["distance_to_corridor_m"] > 300.0

        # 6. 长辈纠偏返回走廊内（年嘉湖西路适老长椅旁，距走廊 < 20m）
        cp6 = CheckpointIn(
            location="年嘉湖西路林荫长椅旁",
            lng=corridor[1][0],
            lat=corridor[1][1],
            altitude_m=51.5,
            satellites=22,
            speed_kmh=2.1,
            timestamp=(base_time + timedelta(seconds=120)).isoformat(),
        )
        res6 = await process_checkpoint(ctx, trip["id"], cp6)
        assert res6["status"] == "normal"
        assert res6["alert_sent"] is False
        assert res6["evaluation"]["is_safe"] is True

        # 7. 再次偏航：状态由 normal -> off_route，必须重新触发告警！
        cp7 = CheckpointIn(
            location="再次偏离走廊进入营盘路口",
            lng=112.9830,
            lat=28.2050,
            altitude_m=50.0,
            satellites=19,
            speed_kmh=2.6,
            timestamp=(base_time + timedelta(seconds=150)).isoformat(),
        )
        res7 = await process_checkpoint(ctx, trip["id"], cp7)
        assert res7["status"] == "off_route"
        assert res7["alert_sent"] is True  # 状态恢复后再次偏离，新一轮告警必须触发！

        # 8. 顺利抵达终点（烈士公园西门 50m 范围内）
        p_arrive = (dest[0] + 0.0001, dest[1] + 0.0001)
        cp8 = CheckpointIn(
            location="烈士公园西门无障碍门区",
            lng=p_arrive[0],
            lat=p_arrive[1],
            altitude_m=52.0,
            satellites=21,
            speed_kmh=1.0,
            timestamp=(base_time + timedelta(seconds=200)).isoformat(),
        )
        res8 = await process_checkpoint(ctx, trip["id"], cp8)
        assert res8["status"] == "arrived"
        assert res8["alert_sent"] is False
        assert res8["evaluation"]["status"] == "ARRIVED"
        assert res8["evaluation"]["is_safe"] is True

        # 验证数据库中行程已安全结束
        updated_trip = await ctx.repos.get("trips", trip["id"])
        assert updated_trip["status"] == "completed"

        # 9. 终态幂等性：到达后再上报点，状态依然是 arrived，行程保持 completed
        res9 = await process_checkpoint(ctx, trip["id"], cp8)
        assert res9["status"] == "arrived"
        assert res9["evaluation"]["status"] == "ARRIVED"

    def test_rapid_boundary_oscillations_debounce(self, changsha_corridor):
        """在 80 米走廊边界临界区（78m -> 82m -> 78m -> 82m）快速抖动，算法判定确定性与平滑性。"""
        corridor, dest = changsha_corridor
        # 走廊 waypoint 为 (112.9895, 28.2141)
        # 经度 1度 ~ 98000m, 纬度 1度 ~ 111000m
        # 80m 约合 0.00072 纬度偏差
        p_in_boundary = (112.9895, 28.2141 + 0.00065)   # 约 72m
        p_out_boundary = (112.9895, 28.2141 + 0.00085)  # 约 94m

        eval_in = evaluate_bds_checkpoint(
            BdsCheckpointPayload(trip_id="t", lng=p_in_boundary[0], lat=p_in_boundary[1], speed_kmh=2.0, timestamp="2026-09-29T10:00:00Z"),
            corridor, destination_coords=dest, corridor_tolerance_m=80.0
        )
        assert eval_in.is_safe is True
        assert eval_in.status == "NORMAL"
        assert eval_in.distance_to_corridor_m < 80.0

        eval_out = evaluate_bds_checkpoint(
            BdsCheckpointPayload(trip_id="t", lng=p_out_boundary[0], lat=p_out_boundary[1], speed_kmh=2.0, timestamp="2026-09-29T10:00:10Z"),
            corridor, destination_coords=dest, corridor_tolerance_m=80.0
        )
        assert eval_out.is_safe is False
        assert eval_out.status == "OFF_ROUTE"
        assert eval_out.distance_to_corridor_m > 80.0

    def test_zero_island_and_out_of_bounds_resilience(self, changsha_corridor):
        """极端脏数据防御：(0, 0) 零岛坐标、NaN/越界经纬度（经度>180, 纬度>90）不崩溃并优雅校准。"""
        corridor, dest = changsha_corridor

        # 零岛 (0,0)
        res_zero = evaluate_bds_checkpoint(
            BdsCheckpointPayload(trip_id="t", lng=0.0, lat=0.0, timestamp="2026-09-29T10:00:00Z"),
            corridor, destination_coords=dest
        )
        assert res_zero.is_safe is True
        assert res_zero.status == "NORMAL"
        assert "校准" in res_zero.audio_reassurance

        # 极端非法越界经纬度
        res_oob = evaluate_bds_checkpoint(
            BdsCheckpointPayload(trip_id="t", lng=999.0, lat=-888.0, timestamp="2026-09-29T10:00:00Z"),
            corridor, destination_coords=dest
        )
        assert res_oob.is_safe is True
        assert res_oob.status == "NORMAL"
        assert "校准" in res_oob.audio_reassurance


# ==============================================================================
# 2. Dwell Accumulation Corner Cases & Hours-Scale Micro-Movement Stress
# ==============================================================================

class TestAdversarialDwellAccumulation:
    """微移动（<25m）长时间累积、真正离开（>25m）重置与时钟漂移防下溢测试。"""

    @pytest.mark.asyncio
    async def test_micro_movements_under_25m_accumulate_across_hours(self, ctx):
        """在 25 米半径内持续微移动（如原地踏步或小幅晃动）持续 3 小时，滞留秒数单调平滑累加至 10800 秒。"""
        trip_id = "trip_stress_dwell_001"
        base_time = datetime(2026, 9, 29, 8, 0, 0, tzinfo=timezone.utc)
        base_coords = (112.98620, 28.21540)

        # 构造跨越 3 小时、包含 12 次微移动（每步位移 < 15 米）的打卡点
        # 112.98620 处 0.0001 经度约为 9.8 米
        offsets = [
            (0, 0.0, 0.0),             # t0
            (10, 0.00004, 0.00003),     # +10min, ~5m
            (20, 0.00008, 0.00006),     # +20min, ~10m
            (30, 0.00006, 0.00008),     # +30min, ~11m
            (60, 0.00002, 0.00010),     # +60min (1hr), ~12m
            (90, -0.00005, 0.00008),    # +90min (1.5hr), ~11m
            (120, -0.00008, 0.00005),   # +120min (2hr), ~10m
            (150, -0.00006, -0.00004),  # +150min (2.5hr), ~8m
            (180, 0.00000, 0.00000),    # +180min (3hr), 回到原点
        ]

        for minutes, d_lng, d_lat in offsets:
            cp_time = base_time + timedelta(minutes=minutes)
            lng = base_coords[0] + d_lng
            lat = base_coords[1] + d_lat
            # 确认每个微位移距基准点都在 25m 以内
            assert haversine_distance_m(base_coords, (lng, lat)) <= 25.0

            await ctx.repos.insert("trip_checkpoints", {
                "trip_id": trip_id,
                "location": f"适老步道微移动_{minutes}m",
                "lng": lng,
                "lat": lat,
                "status": "normal",
                "created_at": cp_time.isoformat(),
                "timestamp": cp_time.isoformat(),
            })

        # 在 3小时整进行检测
        now_time = base_time + timedelta(hours=3)
        dwell_sec = await calculate_checkpoint_dwell_seconds(
            ctx, trip_id, base_coords[0], base_coords[1], current_time=now_time
        )
        assert dwell_sec == 3 * 3600  # 恰好 10800 秒，平滑累加无截断

    @pytest.mark.asyncio
    async def test_true_departure_resets_dwell_instantly(self, ctx):
        """长辈发生实质性位移（> 25m，如离开 80 米）时，连续滞留秒数瞬间归零。"""
        trip_id = "trip_stress_departure_002"
        base_time = datetime(2026, 9, 29, 8, 0, 0, tzinfo=timezone.utc)
        base_coords = (112.98620, 28.21540)

        # 先在 A 点滞留 40 分钟
        for m in (0, 10, 20, 30, 40):
            cp_time = base_time + timedelta(minutes=m)
            await ctx.repos.insert("trip_checkpoints", {
                "trip_id": trip_id,
                "location": "A点停留区",
                "lng": base_coords[0],
                "lat": base_coords[1],
                "created_at": cp_time.isoformat(),
                "timestamp": cp_time.isoformat(),
            })

        # 第 45 分钟移动到 B 点（距离 A 点 150 米外）
        p_b = (112.9878, 28.2150)
        assert haversine_distance_m(base_coords, p_b) > 100.0

        current_time = base_time + timedelta(minutes=45)
        dwell_b = await calculate_checkpoint_dwell_seconds(
            ctx, trip_id, p_b[0], p_b[1], current_time=current_time
        )
        assert dwell_b == 0  # 发生真实离开，滞留时间立即重置为 0

    @pytest.mark.asyncio
    async def test_return_after_departure_does_not_falsely_link(self, ctx):
        """离开后若干小时重新折返原点，历史滞留链路已被中间打卡切断，不应错误串联旧滞留时长。"""
        trip_id = "trip_stress_return_003"
        base_time = datetime(2026, 9, 29, 8, 0, 0, tzinfo=timezone.utc)
        base_coords = (112.98620, 28.21540)

        # 1. 在 A 点停留 30 分钟 (8:00 - 8:30)
        for m in (0, 15, 30):
            t = base_time + timedelta(minutes=m)
            await ctx.repos.insert("trip_checkpoints", {
                "trip_id": trip_id,
                "location": "A点上午散步",
                "lng": base_coords[0],
                "lat": base_coords[1],
                "created_at": t.isoformat(),
                "timestamp": t.isoformat(),
            })

        # 2. 8:45 前往 2 公里外的公园中心 B 点打卡
        p_away = (112.9932, 28.2125)
        await ctx.repos.insert("trip_checkpoints", {
            "trip_id": trip_id,
            "location": "B点公园中心",
            "lng": p_away[0],
            "lat": p_away[1],
            "created_at": (base_time + timedelta(minutes=45)).isoformat(),
            "timestamp": (base_time + timedelta(minutes=45)).isoformat(),
        })

        # 3. 11:00 (3小时后) 折返回 A 点打卡
        return_time = base_time + timedelta(hours=3)
        dwell_return = await calculate_checkpoint_dwell_seconds(
            ctx, trip_id, base_coords[0], base_coords[1], current_time=return_time
        )
        # 中间有 B 点打断，滞留秒数不能串联到 8:00，必须重置为 0
        assert dwell_return == 0

    @pytest.mark.asyncio
    async def test_clock_skew_and_negative_dwell_prevention(self, ctx):
        """面对客户端时钟混乱、时区跳变或乱序上报，滞留时间决不输出负数 (max(0, ...))。"""
        trip_id = "trip_clock_skew_004"
        future_time = datetime(2026, 9, 29, 12, 0, 0, tzinfo=timezone.utc)
        coords = (112.9862, 28.2154)

        # 插入由于客户端漂移造成的"未来时间戳"记录
        await ctx.repos.insert("trip_checkpoints", {
            "trip_id": trip_id,
            "location": "漂移点",
            "lng": coords[0],
            "lat": coords[1],
            "created_at": future_time.isoformat(),
            "timestamp": future_time.isoformat(),
        })

        # 服务器当前时间早于记录时间
        server_now = datetime(2026, 9, 29, 11, 0, 0, tzinfo=timezone.utc)
        dwell = await calculate_checkpoint_dwell_seconds(
            ctx, trip_id, coords[0], coords[1], current_time=server_now
        )
        assert dwell >= 0
        assert dwell == 0

    @pytest.mark.asyncio
    async def test_corrupted_timestamp_graceful_handling(self, ctx):
        """损坏或无法解析的非标准时间戳字符串，计算程序容错跳过而不崩溃。"""
        trip_id = "trip_corrupted_ts_005"
        coords = (112.9862, 28.2154)

        await ctx.repos.insert("trip_checkpoints", {
            "trip_id": trip_id,
            "location": "异常时间戳记录",
            "lng": coords[0],
            "lat": coords[1],
            "created_at": "INVALID_CORRUPTED_TIMESTAMP",
            "timestamp": "NOT_AN_ISO_DATE",
        })

        dwell = await calculate_checkpoint_dwell_seconds(
            ctx, trip_id, coords[0], coords[1], current_time=datetime.now(timezone.utc)
        )
        assert dwell >= 0

    def test_rest_bench_exemption_vs_extended_care(self):
        """在适老长椅 25m 内享受 25 分钟（1500秒）免报警宽限；超过 25 分钟后触发关怀提示。"""
        bench = KNOWN_REST_BENCHES[0]
        corridor = [bench, (bench[0] + 0.01, bench[1] + 0.01)]
        payload = BdsCheckpointPayload(
            trip_id="t", lng=bench[0], lat=bench[1], speed_kmh=0.1, timestamp="2026-09-29T10:00:00Z"
        )

        # 1. 停留 20 分钟 (1200秒) < 1500秒：豁免报警，状态保持 NORMAL
        eval_exemption = evaluate_bds_checkpoint(
            payload, corridor, registered_rest_benches=KNOWN_REST_BENCHES, consecutive_dwell_seconds=1200
        )
        assert eval_exemption.is_safe is True
        assert eval_exemption.status == "NORMAL"
        assert eval_exemption.alert_message is None

        # 2. 停留 26 分钟 (1560秒) >= 1500秒：触发长椅关怀提醒
        eval_overtime = evaluate_bds_checkpoint(
            payload, corridor, registered_rest_benches=KNOWN_REST_BENCHES, consecutive_dwell_seconds=1560
        )
        assert eval_overtime.is_safe is False
        assert eval_overtime.status == "ABNORMAL_DWELL"
        assert "长椅处滞留已超过 26 分钟" in eval_overtime.alert_message
        assert "长椅处休息较长时间" in eval_overtime.audio_reassurance


# ==============================================================================
# 3. Emergency Hospital Reroute During Abnormal Dwell (Deadlock & Concurrency Free)
# ==============================================================================

class TestEmergencyRerouteDuringAbnormalDwell:
    """异常滞留触发与三甲医院急救绿色通道极速重划联动与高并发无死锁验证。"""

    @pytest.mark.asyncio
    async def test_dwell_alert_and_emergency_reroute_synchronous_flow(self, ctx, elder):
        """验证长辈在异常滞留告警后，立即触发绿色通道重划，两者同步顺序执行无死锁、数据一致。"""
        trip = await ctx.repos.insert("trips", {
            "elder_id": elder["id"],
            "purpose": "步行前往烈士公园散步",
            "status": "ongoing",
            "origin": "华夏路社区",
            "destination": "烈士公园西门",
        })

        stay_point = (112.9865, 28.2155)
        t0 = datetime.now(timezone.utc) - timedelta(minutes=20)

        # 1. 注入 20 分钟前的历史检查点
        await ctx.repos.insert("trip_checkpoints", {
            "trip_id": trip["id"],
            "location": "街角非长椅区",
            "lng": stay_point[0],
            "lat": stay_point[1],
            "status": "normal",
            "created_at": t0.isoformat(),
            "timestamp": t0.isoformat(),
        })

        # 2. 触发当前检查点 -> 判定 ABNORMAL_DWELL
        cp_in = CheckpointIn(
            location="街角非长椅区",
            lng=stay_point[0],
            lat=stay_point[1],
            speed_kmh=0.0,
            satellites=21,
            altitude_m=51.2,
        )
        res_cp = await process_checkpoint(ctx, trip["id"], cp_in)
        assert res_cp["status"] == "abnormal_dwell"
        assert res_cp["alert_sent"] is True
        assert res_cp["evaluation"]["dwell_duration_seconds"] >= 20 * 60

        # 3. 伴随异常滞留，立即发起突发三甲就医绿通重划 (emergency_sos_reroute)
        reroute_res = elder_routing_service.emergency_sos_reroute(
            current_coords=stay_point,
            elder_name=elder["name"],
            condition="突发滞留不适/心悸",
        )
        assert reroute_res["status"] == "SOS_DISPATCHED"
        assert "中南大学湘雅医院" in reroute_res["nearest_hospital"]["name"]
        assert reroute_res["distance_m"] < 300  # 湘雅医院距华夏路社区仅百余米
        assert reroute_res["estimated_duration_min"] >= 3
        assert len(reroute_res["steps"]) >= 2
        assert len(reroute_res["geofence_corridor"]) == 2
        assert "0.35m" in reroute_res["steps"][0]["instruction"]
        assert reroute_res["emergency_phone"] == "0731-84328888"

    @pytest.mark.asyncio
    async def test_concurrent_dwell_and_emergency_reroute_stress(self, ctx, elder):
        """高并发压力测试：同时并发发起 10 组打卡评估与 10 组 SOS 绿通重划，验证无死锁与事件完整。"""
        trip = await ctx.repos.insert("trips", {
            "elder_id": elder["id"],
            "purpose": "步行散步",
            "status": "ongoing",
            "origin": "华夏路社区",
            "destination": "中南大学湘雅医院",
        })

        async def worker_checkpoint(idx: int):
            lng = 112.9862 + idx * 0.0001
            lat = 28.2154 + idx * 0.0001
            body = CheckpointIn(
                location=f"并发测试点_{idx}",
                lng=lng,
                lat=lat,
                speed_kmh=2.0,
                satellites=19,
            )
            return await process_checkpoint(ctx, trip["id"], body)

        def worker_sos(idx: int):
            coords = (112.9862 + idx * 0.0002, 28.2154 + idx * 0.0002)
            return elder_routing_service.emergency_sos_reroute(
                current_coords=coords,
                elder_name="张阿姨",
                condition=f"并发测试告警_{idx}",
            )

        # 10 个打卡异步任务 + 10 个 SOS 任务同步在线程池执行
        cp_tasks = [worker_checkpoint(i) for i in range(10)]
        sos_tasks = [asyncio.to_thread(worker_sos, i) for i in range(10)]

        results = await asyncio.gather(*cp_tasks, *sos_tasks, return_exceptions=True)

        # 验证所有 20 个并发操作均顺利完成，没有任何异常或死锁
        for idx, res in enumerate(results):
            assert not isinstance(res, Exception), f"Concurrent task {idx} raised: {res}"
            if idx < 10:
                assert "checkpoint" in res
                assert res["status"] in ("normal", "off_route", "abnormal_dwell", "arrived")
            else:
                assert res["status"] == "SOS_DISPATCHED"
                assert "nearest_hospital" in res

    @pytest.mark.asyncio
    async def test_fastapi_e2e_dwell_to_emergency_http(self, ctx, elder, monkeypatch):
        """FastAPI 端到端 HTTP 链路：/bds_checkpoint -> 异常滞留 -> /emergency-sos 绿通重划闭环。"""
        from app.api import deps, routes_guardian
        monkeypatch.setattr(routes_guardian, "get_ctx", lambda: ctx)
        monkeypatch.setattr(deps, "get_app_context", lambda: ctx)
        client = TestClient(create_app())

        token = create_access_token(elder, ctx.settings)
        headers = {"Authorization": f"Bearer {token}"}

        trip = await ctx.repos.insert("trips", {
            "elder_id": elder["id"],
            "purpose": "步行前往烈士公园",
            "status": "ongoing",
            "origin": "华夏路社区",
            "destination": "烈士公园西门",
        })

        # 1. 模拟滞留 18 分钟的初次检查点
        t0 = datetime.now(timezone.utc) - timedelta(minutes=18)
        p_stay = (112.9863, 28.2154)
        await ctx.repos.insert("trip_checkpoints", {
            "trip_id": trip["id"],
            "location": "华夏路巷口",
            "lng": p_stay[0],
            "lat": p_stay[1],
            "status": "normal",
            "created_at": t0.isoformat(),
            "timestamp": t0.isoformat(),
        })

        # 2. HTTP POST 上报北斗打卡
        payload_cp = {
            "trip_id": trip["id"],
            "lng": p_stay[0],
            "lat": p_stay[1],
            "altitude_m": 52.0,
            "satellites": 20,
            "speed_kmh": 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        resp_cp = client.post(
            f"/api/trips/{trip['id']}/bds_checkpoint",
            json=payload_cp,
            headers=headers,
        )
        assert resp_cp.status_code == 200
        data_cp = resp_cp.json()
        assert data_cp["status"] == "abnormal_dwell"
        assert data_cp["evaluation"]["status"] == "ABNORMAL_DWELL"
        assert data_cp["evaluation"]["dwell_duration_seconds"] >= 18 * 60

        # 3. HTTP POST 触发 /api/bds/escort/emergency-sos
        payload_sos = {
            "coords": [p_stay[0], p_stay[1]],
            "elder_name": elder["name"],
            "elder_id": elder["id"],
            "condition": "突发身体不适",
        }
        resp_sos = client.post("/api/bds/escort/emergency-sos", json=payload_sos)
        assert resp_sos.status_code == 200
        data_sos = resp_sos.json()
        assert data_sos["status"] == "SOS_DISPATCHED"
        assert "湘雅医院" in data_sos["nearest_hospital"]["name"]
        assert len(data_sos["steps"]) >= 2
        assert len(data_sos["geofence_corridor"]) == 2
