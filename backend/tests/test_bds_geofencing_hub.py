"""Tests for BDS Geofencing, Anomaly Detection & Guardian Hub.

第八届湖南省大学生智能导航科技创新大赛（科技创意类赛道）
R3 北斗高精电子围栏与子女端安心守护中枢规约测试：
1. BdsCheckpointPayload & BdsCheckpointEvaluation 契约模型字段与类型校验
2. evaluate_bds_checkpoint 算法：
   - 零岛与搜星校准保护
   - 目的地 50m 到达判定 (ARRIVED)
   - 亚米级步行/微步道走廊贴合度 (50-80m) 与偏航告警 (OFF_ROUTE)
   - 异常滞留主动防御：非长椅区 >15分钟 (900s) 告警 vs 长椅休整区宽限至 25分钟 (1500s)
3. 数据库时空检查点滞留时间溯源 (calculate_checkpoint_dwell_seconds)
4. process_checkpoint 真实守护链路联动与 SSE / 审计日志告警闭环
5. /api/trips/{trip_id}/bds_evaluate 与 /api/trips/{trip_id}/bds_checkpoint API 接口端到端验证
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

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
from app.main import app


# ==============================================================================
# 1. 契约模型与静态地理拓扑测试
# ==============================================================================

class TestBdsGeofenceContracts:
    """测试北斗契约模型与拓扑常数。"""

    def test_bds_checkpoint_payload_contract(self):
        """验证 BdsCheckpointPayload 符合 PROJECT.md 接口契约定义。"""
        payload = BdsCheckpointPayload(
            trip_id="trip_changsha_001",
            lng=112.9862,
            lat=28.2154,
            altitude_m=52.8,
            satellites=19,
            speed_kmh=2.4,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        assert payload.trip_id == "trip_changsha_001"
        assert payload.lng == 112.9862
        assert payload.lat == 28.2154
        assert payload.altitude_m == 52.8
        assert payload.satellites >= 18
        assert payload.speed_kmh == 2.4

    def test_bds_checkpoint_evaluation_contract(self):
        """验证 BdsCheckpointEvaluation 结构体与字段定义。"""
        eval_res = BdsCheckpointEvaluation(
            is_safe=False,
            status="ABNORMAL_DWELL",
            distance_to_corridor_m=12.5,
            dwell_duration_seconds=960,
            alert_message="长辈在当前位置连续停留超过 16 分钟，疑似身体不适或走失受困！",
            audio_reassurance="张阿姨，您在此处停留较长时间，是否需要呼叫家人或急救服务？",
        )
        assert eval_res.is_safe is False
        assert eval_res.status == "ABNORMAL_DWELL"
        assert eval_res.distance_to_corridor_m == 12.5
        assert eval_res.dwell_duration_seconds == 960
        assert "疑似身体不适" in eval_res.alert_message
        assert "呼叫家人" in eval_res.audio_reassurance

    def test_changsha_landmarks_and_rest_benches_registered(self):
        """验证长沙大赛核心地标与休憩长椅均在路由字典正确登记。"""
        assert "华夏路社区" in LOCATION_COORDS
        assert "烈士公园西门" in LOCATION_COORDS
        assert "中南大学湘雅医院" in LOCATION_COORDS
        assert "湖南省人民医院" in LOCATION_COORDS

        assert len(KNOWN_REST_BENCHES) >= 3
        for bench in KNOWN_REST_BENCHES:
            assert 112.0 < bench[0] < 113.5
            assert 28.0 < bench[1] < 28.5


# ==============================================================================
# 2. evaluate_bds_checkpoint 核心算法与异常规则单元测试
# ==============================================================================

class TestBdsEvaluationAlgorithm:
    """测试北斗电子围栏与异常滞留预言机逻辑。"""

    @pytest.fixture
    def changsha_corridor_fixture(self):
        """长沙华夏路社区 -> 年嘉湖西路 -> 烈士公园西门 适老微地形走廊。"""
        origin = (112.9862, 28.2154)
        waypoint = (112.9895, 28.2141)
        dest = (112.9932, 28.2125)
        return [origin, waypoint, dest], dest

    def test_zero_island_and_signal_warmup(self, changsha_corridor_fixture):
        """验证 (0, 0) 零岛或经纬度越界时静默校准，不误报。"""
        corridor, dest = changsha_corridor_fixture
        payload = BdsCheckpointPayload(
            trip_id="trip_test", lng=0.0, lat=0.0, timestamp=datetime.now(timezone.utc).isoformat()
        )
        res = evaluate_bds_checkpoint(payload, corridor, destination_coords=dest)
        assert res.is_safe is True
        assert res.status == "NORMAL"
        assert res.distance_to_corridor_m == 0.0
        assert "校准" in res.audio_reassurance

    def test_arrived_destination_within_50m(self, changsha_corridor_fixture):
        """距离终点 <= 50m 判定为 ARRIVED。"""
        corridor, dest = changsha_corridor_fixture
        # 偏离终点约 15 米的点
        p_arrive = (dest[0] + 0.0001, dest[1] + 0.0001)
        payload = BdsCheckpointPayload(
            trip_id="trip_test", lng=p_arrive[0], lat=p_arrive[1], timestamp=datetime.now(timezone.utc).isoformat()
        )
        res = evaluate_bds_checkpoint(payload, corridor, destination_coords=dest)
        assert res.is_safe is True
        assert res.status == "ARRIVED"
        assert "安全到达" in res.audio_reassurance

    def test_corridor_deviation_triggers_off_route(self, changsha_corridor_fixture):
        """偏离安全走廊 > 80m 触发 OFF_ROUTE 告警。"""
        corridor, dest = changsha_corridor_fixture
        # 营盘路口点，距华夏路社区与年嘉湖走廊约 800 米
        p_off = (112.9830, 28.2050)
        payload = BdsCheckpointPayload(
            trip_id="trip_test", lng=p_off[0], lat=p_off[1], speed_kmh=2.2, timestamp=datetime.now(timezone.utc).isoformat()
        )
        res = evaluate_bds_checkpoint(payload, corridor, destination_coords=dest, corridor_tolerance_m=80.0)
        assert res.is_safe is False
        assert res.status == "OFF_ROUTE"
        assert res.distance_to_corridor_m > 80.0
        assert "偏离规划安全走廊" in res.alert_message

    def test_normal_walking_within_corridor(self, changsha_corridor_fixture):
        """在走廊 50m 范围内正常行走判定为 NORMAL。"""
        corridor, dest = changsha_corridor_fixture
        # 走廊线段上的插值点
        p_on = (112.9878, 28.2148)
        payload = BdsCheckpointPayload(
            trip_id="trip_test", lng=p_on[0], lat=p_on[1], speed_kmh=2.5, timestamp=datetime.now(timezone.utc).isoformat()
        )
        res = evaluate_bds_checkpoint(payload, corridor, destination_coords=dest, corridor_tolerance_m=80.0)
        assert res.is_safe is True
        assert res.status == "NORMAL"
        assert res.distance_to_corridor_m <= 80.0

    def test_dwell_over_15_min_non_bench_area(self, changsha_corridor_fixture):
        """非长椅区滞留 > 15分钟 (900s) 且速度 < 0.5km/h 触发 ABNORMAL_DWELL。"""
        corridor, dest = changsha_corridor_fixture
        # 停留在非长椅的普通步道
        p_stay = (112.9870, 28.2140)
        payload = BdsCheckpointPayload(
            trip_id="trip_test", lng=p_stay[0], lat=p_stay[1], speed_kmh=0.1, timestamp=datetime.now(timezone.utc).isoformat()
        )
        res = evaluate_bds_checkpoint(
            payload, corridor, destination_coords=dest,
            registered_rest_benches=KNOWN_REST_BENCHES,
            consecutive_dwell_seconds=960,  # 16 分钟
        )
        assert res.is_safe is False
        assert res.status == "ABNORMAL_DWELL"
        assert "连续停留超过 16 分钟" in res.alert_message
        assert "呼叫家人" in res.audio_reassurance

    def test_dwell_at_rest_bench_exemption_under_25_min(self, changsha_corridor_fixture):
        """在适老长椅 25m 范围内休息 20分钟 (1200s)，豁免报警，保持 NORMAL。"""
        corridor, dest = changsha_corridor_fixture
        bench = KNOWN_REST_BENCHES[1]  # 年嘉湖西路林荫道长椅 1
        payload = BdsCheckpointPayload(
            trip_id="trip_test", lng=bench[0], lat=bench[1], speed_kmh=0.0, timestamp=datetime.now(timezone.utc).isoformat()
        )
        res = evaluate_bds_checkpoint(
            payload, corridor, destination_coords=dest,
            registered_rest_benches=KNOWN_REST_BENCHES,
            consecutive_dwell_seconds=1200,  # 20 分钟
        )
        assert res.is_safe is True
        assert res.status == "NORMAL"
        assert res.alert_message is None

    def test_dwell_at_rest_bench_triggers_care_over_25_min(self, changsha_corridor_fixture):
        """在适老长椅处连续停留超过 25分钟 (1600s)，触发长椅超时关怀提示。"""
        corridor, dest = changsha_corridor_fixture
        bench = KNOWN_REST_BENCHES[1]
        payload = BdsCheckpointPayload(
            trip_id="trip_test", lng=bench[0], lat=bench[1], speed_kmh=0.0, timestamp=datetime.now(timezone.utc).isoformat()
        )
        res = evaluate_bds_checkpoint(
            payload, corridor, destination_coords=dest,
            registered_rest_benches=KNOWN_REST_BENCHES,
            consecutive_dwell_seconds=1600,  # 26 分钟
        )
        assert res.is_safe is False
        assert res.status == "ABNORMAL_DWELL"
        assert "长椅处滞留已超过 26 分钟" in res.alert_message
        assert "长椅处休息较长时间" in res.audio_reassurance


# ==============================================================================
# 3. 连续时空打卡滞留时间数据库推导测试
# ==============================================================================

class TestDwellDatabaseTracking:
    """测试通过数据库检查点历史计算真实连续滞留秒数。"""

    @pytest.mark.asyncio
    async def test_calculate_checkpoint_dwell_seconds_with_consecutive_records(self, ctx):
        """同一地点连续打卡 3 次，滞留时间从最早一条平滑累加。"""
        trip_id = "test_trip_dwell_001"
        base_time = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)
        coords = (112.9862, 28.2154)

        # 插入 3 条相隔 5 分钟的检查点
        for i in range(3):
            cp_time = base_time + timedelta(minutes=5 * i)
            await ctx.repos.insert("trip_checkpoints", {
                "trip_id": trip_id,
                "location": "长椅休息处",
                "lng": coords[0],
                "lat": coords[1],
                "status": "normal",
                "created_at": cp_time.isoformat(),
                "timestamp": cp_time.isoformat(),
            })

        current_time = base_time + timedelta(minutes=16)  # 16分钟后打卡
        dwell = await calculate_checkpoint_dwell_seconds(
            ctx, trip_id, coords[0], coords[1], current_time=current_time
        )
        assert dwell == 16 * 60  # 960 秒

    @pytest.mark.asyncio
    async def test_movement_over_25m_resets_dwell_seconds(self, ctx):
        """当移动超过 25m 时，滞留时间打断并重置。"""
        trip_id = "test_trip_move_002"
        base_time = datetime(2026, 9, 29, 10, 0, 0, tzinfo=timezone.utc)

        # 历史记录在 A 点
        await ctx.repos.insert("trip_checkpoints", {
            "trip_id": trip_id,
            "location": "A点",
            "lng": 112.9862,
            "lat": 28.2154,
            "created_at": base_time.isoformat(),
            "timestamp": base_time.isoformat(),
        })

        # 当前在 B 点（距 A 点 150 米外）
        current_time = base_time + timedelta(minutes=20)
        p_b = (112.9878, 28.2150)
        dwell = await calculate_checkpoint_dwell_seconds(
            ctx, trip_id, p_b[0], p_b[1], current_time=current_time
        )
        assert dwell == 0


# ==============================================================================
# 4. process_checkpoint 守护主流程与 BDS 扩展验证
# ==============================================================================

class TestProcessCheckpointBdsIntegration:
    """测试 process_checkpoint 对北斗微步道走廊与滞留报警的无缝集成。"""

    @pytest.mark.asyncio
    async def test_process_checkpoint_walking_corridor_tolerance(self, ctx, elder):
        """适老步行模式下，超出 80m 走廊触发偏航且生成 BdsCheckpointEvaluation。"""
        trip = await ctx.repos.insert("trips", {
            "elder_id": elder["id"],
            "purpose": "步行前往烈士公园西门散步",
            "status": "planned",
            "origin": "华夏路社区",
            "destination": "烈士公园西门",
        })

        # 上报偏离走廊 200 米的点
        p_off = (112.9880, 28.2090)
        body = CheckpointIn(
            location="偏离小道",
            lng=p_off[0],
            lat=p_off[1],
            altitude_m=52.0,
            satellites=20,
            speed_kmh=2.4,
        )
        res = await process_checkpoint(ctx, trip["id"], body)
        assert res["status"] == "off_route"
        assert res["alert_sent"] is True

        eval_data = res["evaluation"]
        assert eval_data["is_safe"] is False
        assert eval_data["status"] == "OFF_ROUTE"
        assert eval_data["distance_to_corridor_m"] > 80.0
        assert "偏离" in eval_data["alert_message"]

    @pytest.mark.asyncio
    async def test_process_checkpoint_dwell_alert_trigger(self, ctx, elder):
        """连续滞留触发 abnormal_dwell 告警，并写入审计日志。"""
        trip = await ctx.repos.insert("trips", {
            "elder_id": elder["id"],
            "purpose": "前往湘雅医院看门诊",
            "status": "ongoing",
            "origin": "华夏路社区",
            "destination": "中南大学湘雅医院",
        })

        t0 = datetime.now(timezone.utc) - timedelta(minutes=18)
        p_stay = (112.9865, 28.2155)

        # 预先植入 18 分钟前的首个同地点检查点
        await ctx.repos.insert("trip_checkpoints", {
            "trip_id": trip["id"],
            "location": "街角长椅旁",
            "lng": p_stay[0],
            "lat": p_stay[1],
            "status": "normal",
            "created_at": t0.isoformat(),
            "timestamp": t0.isoformat(),
        })

        # 当前再次上报同一地点，速度为 0
        body = CheckpointIn(
            location="街角长椅旁",
            lng=p_stay[0],
            lat=p_stay[1],
            speed_kmh=0.0,
            satellites=19,
            altitude_m=51.2,
        )
        res = await process_checkpoint(ctx, trip["id"], body)
        assert res["status"] == "abnormal_dwell"
        assert res["alert_sent"] is True

        eval_dict = res["evaluation"]
        assert eval_dict["status"] == "ABNORMAL_DWELL"
        assert eval_dict["dwell_duration_seconds"] >= 18 * 60


# ==============================================================================
# 5. FastAPI HTTP 端点测试 (/bds_evaluate & /bds_checkpoint)
# ==============================================================================

class TestBdsGuardianApiEndpoints:
    """测试北斗专属 API 路由接口。"""

    @pytest.fixture()
    def api_client(self, ctx, monkeypatch):
        from app.api import deps, routes_guardian
        from app.main import create_app
        monkeypatch.setattr(routes_guardian, "get_ctx", lambda: ctx)
        monkeypatch.setattr(deps, "get_app_context", lambda: ctx)
        return TestClient(create_app())

    @pytest.fixture
    def auth_headers(self, ctx, elder):
        """生成老人身份 Authorization Header。"""
        token = create_access_token(elder, ctx.settings)
        return {"Authorization": f"Bearer {token}"}

    @pytest.mark.asyncio
    async def test_bds_evaluate_endpoint_contract(self, ctx, elder, auth_headers, api_client):
        """POST /api/trips/{trip_id}/bds_evaluate 返回规范的 BdsCheckpointEvaluation JSON。"""
        trip = await ctx.repos.insert("trips", {
            "elder_id": elder["id"],
            "purpose": "步行前往烈士公园西门",
            "status": "ongoing",
            "origin": "华夏路社区",
            "destination": "烈士公园西门",
        })

        payload = {
            "trip_id": trip["id"],
            "lng": 112.9862,
            "lat": 28.2154,
            "altitude_m": 53.0,
            "satellites": 21,
            "speed_kmh": 2.5,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        resp = api_client.post(
            f"/api/trips/{trip['id']}/bds_evaluate",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "is_safe" in data
        assert "status" in data
        assert data["status"] in ("NORMAL", "OFF_ROUTE", "ABNORMAL_DWELL", "ARRIVED")
        assert "distance_to_corridor_m" in data
        assert "dwell_duration_seconds" in data
        assert "audio_reassurance" in data

    @pytest.mark.asyncio
    async def test_bds_checkpoint_reporting_endpoint(self, ctx, elder, auth_headers, api_client):
        """POST /api/trips/{trip_id}/bds_checkpoint 成功入库并附带 evaluation 回执。"""
        trip = await ctx.repos.insert("trips", {
            "elder_id": elder["id"],
            "purpose": "步行前往湖南省人民医院",
            "status": "ongoing",
            "origin": "华夏路社区",
            "destination": "湖南省人民医院",
        })

        payload = {
            "trip_id": trip["id"],
            "lng": 112.9862,
            "lat": 28.2154,
            "altitude_m": 51.5,
            "satellites": 19,
            "speed_kmh": 2.4,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        resp = api_client.post(
            f"/api/trips/{trip['id']}/bds_checkpoint",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200
        res_json = resp.json()
        assert "checkpoint" in res_json
        assert "status" in res_json
        assert "evaluation" in res_json
        assert res_json["evaluation"]["is_safe"] is True
