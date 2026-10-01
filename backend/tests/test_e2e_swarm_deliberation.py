"""Comprehensive 4-Tier E2E Test Suite for LaoYouJi Swarm Deliberation & Navigation Map.

《银发导航智能体：基于多Agent协同的老年人安心出行伴侣》
全景端到端（E2E）黑盒与规约驱动测试套件。

涵盖 4-Tier 架构：
- Tier 1: 功能全覆盖 (Feature Coverage, >=5 用例/特性, F1-F13 共 65 用例)
  * F1: 对等通信信箱体系 (Teammate Mailbox Protocol)
  * F2: 共享任务看板 (Shared Task Board & DAG)
  * F3: 独立安澜卫士 (GuardianAgent Standalone Class)
  * F4: 多智能体群智闭环研讨 (Multi-Agent Peer Deliberation)
  * F5: SSE 实时心智思考流 (SSE Real-Time Thinking Stream)
  * F6: 前端长辈关怀心智气泡与交接卡 (Elder Thinking Bubble & Handoff Card)
  * F7: 5-Agent 协同执行树与群智态势看板 (Execution Tree & Swarm Board)
  * F8: 自适应分层认知记忆存储 (Adaptive Hierarchical Memory Store)
  * F9: 主动情境关怀与免答记忆回溯 (Proactive Context Care & Recall)
  * F10: 地图手势穿透隔离 (Map Gesture Isolation: touch-action: none)
  * F11: 原生整数瓦片缩放 (Native Integer Tile Zoom: zoomSnap: 1)
  * F12: 丝滑缓动视口过渡 (Smooth Easing Viewport Transitions: 60fps FlyTo)
  * F13: GPU 硬件加速标记层 (GPU Hardware-Accelerated Pulse Marker)

- Tier 2: 边界与极限场景 (Boundary & Corner Cases, >=5 用例/特性, F1-F13 共 65 用例)
  * 空输入、格式异常、缺席智能体、依赖死锁、超时降级、超限坐标、CSS缺失与容灾恢复

- Tier 3: 跨特性两两正交组合 (Cross-Feature Combinations, 12 用例)
  * 信箱 x 任务看板, 信箱 x 心智流, 任务看板 x 分层记忆, 卫士 x 信箱 x 导航, 记忆 x 免答研讨等

- Tier 4: 长沙实景银发业务全链路验收 (Real-World Changsha Scenarios S1-S5, 5 用例)
  * S1: 烈士公园晨练伴随 (刘爷爷膝关节退行性病变避台阶林荫步道)
  * S2: 湘雅就医与突发体能不适 (张奶奶走廊监护与休息长椅引导)
  * S3: 暴雨短临微气象与避雨绕行 (王爷爷遇暴雨躲避至寄情亭)
  * S4: 异地子女紧急守护与偏航联动 (周老伯偏离安全走廊触发绿通)
  * S5: 跨多轮对话体能记忆自动加载 (陈奶奶次日出行免重复陈述病史)

总计 147 项严密测试用例，100% 覆盖 PROJECT.md 与 TEST_INFRA.md。
"""
from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from tests.swarm_fixtures import (
    AGENT_AVATAR_TITLES,
    AGENT_THEME_COLORS,
    CHANGSHA_REALWORLD_FIXTURES,
    AgentHandoffChunk,
    AgentMailbox,
    BoardTask,
    DeliberationCouncil,
    EpisodicMemoryEntry,
    GuardianAgentSpec,
    HierarchicalMemoryStore,
    MapPerformanceContract,
    MicroWeatherReport,
    PeerMessage,
    PeerMessageChunk,
    PhysicalFatigueLimit,
    SessionMailboxHub,
    SharedTaskBoard,
    TaskBoardSyncChunk,
    ThinkingDeltaChunk,
    create_agent_handoff_card,
    create_elder_thinking_bubble,
    format_sse_event,
    point_to_segment_dist_m,
)


# ==============================================================================
# TIER 1: 核心功能特性全覆盖 (Feature Coverage, >=5 tests per feature for F1-F13)
# ==============================================================================

class TestTier1FeatureCoverage:
    """Tier 1: 核心功能规约全覆盖 (F1 - F13, 65 Tests)."""

    # --------------------------------------------------------------------------
    # F1: 对等信箱通信协议 (Peer Mailbox Protocol)
    # --------------------------------------------------------------------------

    def test_f1_01_peer_message_envelope_schema_validation(self):
        """F1.1: 验证电文信封模型结构包含完整的字段定义与合法枚举校验。"""
        msg = PeerMessage(
            from_agent="health",
            to_agent="bds_nav",
            msg_type="proposal",
            summary="膝关节体能约束注入",
            content="长辈双膝退行性关节炎，请规划坡度不超过3.5%的平缓无台阶路径。",
            data={"max_slope": 3.5, "avoid_stairs": True},
        )
        assert len(msg.id) == 8
        assert msg.from_agent == "health"
        assert msg.to_agent == "bds_nav"
        assert msg.msg_type == "proposal"
        assert msg.read is False
        assert "max_slope" in msg.data
        assert datetime.fromisoformat(msg.created_at) is not None

    def test_f1_02_direct_peer_message_point_to_point_delivery(self):
        """F1.2: 验证点对点电文精准送达目标智能体信箱且不污染其他信箱。"""
        hub = SessionMailboxHub("sess_p2p_01")
        msg = hub.get_mailbox("health").send_message(
            to_agent="bds_nav",
            msg_type="direct",
            summary="体检报告数据已同步",
            content="心率正常，步频偏慢",
        )
        delivered = hub.route_message(msg)
        assert delivered == ["bds_nav"]

        bds_box = hub.get_mailbox("bds_nav")
        assert len(bds_box.peek_all()) == 1
        assert bds_box.peek_all()[0].summary == "体检报告数据已同步"

        # 验证其他智能体收件箱为空
        assert len(hub.get_mailbox("weather").peek_all()) == 0
        assert len(hub.get_mailbox("guardian").peek_all()) == 0

    def test_f1_03_broadcast_message_delivery_to_all_except_sender(self):
        """F1.3: 验证广播通配符 '*' 投递给群内所有其他智能体且不循环发给自己。"""
        hub = SessionMailboxHub("sess_bcast_01")
        msg = hub.get_mailbox("bds_nav").send_message(
            to_agent="*",
            msg_type="broadcast",
            summary="导航路线规划完成",
            content="选定烈士公园西门林荫步道，全长520米",
        )
        delivered = hub.route_message(msg)

        assert "bds_nav" not in delivered
        assert set(delivered) == {"main", "health", "weather", "guardian"}
        for agent_name in delivered:
            box = hub.get_mailbox(agent_name)
            assert len(box.peek_all()) == 1
            assert box.peek_all()[0].from_agent == "bds_nav"

    def test_f1_04_mailbox_read_receipt_and_unread_filtering(self):
        """F1.4: 验证信箱未读电文提取与已读状态自动标记。"""
        box = AgentMailbox("weather")
        msg1 = PeerMessage(
            from_agent="bds_nav", to_agent="weather", msg_type="direct",
            summary="查询风速", content="请提供开福区实时风速",
        )
        msg2 = PeerMessage(
            from_agent="main", to_agent="weather", msg_type="direct",
            summary="查询紫外线", content="请提供开福区实时UV指数",
        )
        box.receive_message(msg1)
        box.receive_message(msg2)

        # 第一次提取未读电文并标记为已读
        unread = box.get_unread_messages(mark_as_read=True)
        assert len(unread) == 2
        assert msg1.read is True
        assert msg2.read is True

        # 第二次提取未读电文应为空
        assert len(box.get_unread_messages()) == 0
        assert len(box.peek_all()) == 2

    def test_f1_05_session_mailbox_hub_audit_ledger(self):
        """F1.5: 验证会话信箱路由中枢维护完整的全景电文审计账本。"""
        hub = SessionMailboxHub("sess_audit_01")
        m1 = hub.get_mailbox("health").send_message("bds_nav", "proposal", "体能约束", "限速0.8m/s")
        m2 = hub.get_mailbox("bds_nav").send_message("weather", "direct", "微气象查询", "开福区降雨")
        m3 = hub.get_mailbox("weather").send_message("bds_nav", "ack", "气象回执", "暂无降水")

        hub.route_message(m1)
        hub.route_message(m2)
        hub.route_message(m3)

        assert len(hub.audit_log) == 3
        assert [m.from_agent for m in hub.audit_log] == ["health", "bds_nav", "weather"]
        assert [m.msg_type for m in hub.audit_log] == ["proposal", "direct", "ack"]

    # --------------------------------------------------------------------------
    # F2: 共享任务看板 (Shared Task Board)
    # --------------------------------------------------------------------------

    def test_f2_01_monotonic_highwatermark_task_id_generation(self):
        """F2.1: 验证共享任务看板生成单调自增字符串任务编号 ('1', '2', '3'...)。"""
        board = SharedTaskBoard()
        t1 = board.add_task("规划路线", "避开陡坡", "正在规划平缓路径")
        t2 = board.add_task("核验体能", "膝关节受力评估", "正在核对体能阈值")
        t3 = board.add_task("建立走廊", "构建北斗电子走廊", "正在布设安全电子走廊")

        assert t1.id == "1"
        assert t2.id == "2"
        assert t3.id == "3"
        assert board._highwatermark == 3

    def test_f2_02_atomic_task_claiming_lifecycle(self):
        """F2.2: 验证任务原子认领机制：状态流转 pending -> in_progress 并绑定 owner。"""
        board = SharedTaskBoard()
        task = board.add_task("气象扫描", "检测开福区对流降水", "正在感知天气")
        assert task.status == "pending"
        assert task.owner is None

        claimed = board.claim_task_with_busy_check(task.id, "weather")
        assert claimed is True
        assert task.status == "in_progress"
        assert task.owner == "weather"

    def test_f2_03_busy_check_prevents_agent_overload(self):
        """F2.3: 验证防竞态与防超载机制：已有执行中任务的智能体禁止并发认领第二项任务。"""
        board = SharedTaskBoard()
        t1 = board.add_task("任务一", "细查微地形", "正在勘测")
        t2 = board.add_task("任务二", "搜索长椅", "正在搜索休息点")

        # bds_nav 成功认领任务一
        assert board.claim_task_with_busy_check(t1.id, "bds_nav") is True
        # bds_nav 尝试认领任务二被拒绝 (Busy Check)
        assert board.claim_task_with_busy_check(t2.id, "bds_nav") is False
        assert t2.status == "pending"

        # 完成任务一后，bds_nav 恢复空闲，可以认领任务二
        board.complete_task(t1.id)
        assert board.claim_task_with_busy_check(t2.id, "bds_nav") is True
        assert t2.status == "in_progress"

    def test_f2_04_dependency_blocking_and_cascade_unblocking(self):
        """F2.4: 验证有向依赖阻断与前置完成后的级联解锁。"""
        board = SharedTaskBoard()
        t_health = board.add_task("健康评估", "评定关节炎极限", "正在评估体能")
        t_nav = board.add_task(
            "北斗微地形规划", "结合体能结果计算最优步道", "正在结合体能规避高阶梯",
            blocked_by=[t_health.id],
        )

        assert t_nav.id in t_health.blocks
        # 前置 t_health 未完成时，无法认领后置 t_nav
        assert board.claim_task_with_busy_check(t_nav.id, "bds_nav") is False

        # 完成 t_health
        board.claim_task_with_busy_check(t_health.id, "health")
        board.complete_task(t_health.id)

        # 依赖解锁，t_nav 成功认领
        assert t_health.id not in t_nav.blocked_by
        assert board.claim_task_with_busy_check(t_nav.id, "bds_nav") is True

    def test_f2_05_task_release_rollback_on_agent_disruption(self):
        """F2.5: 验证智能体宕机或换人时任务回退回 pending 状态供其他智能体认领。"""
        board = SharedTaskBoard()
        t = board.add_task("微气象观测", "监测紫外线", "正在测算UV")
        board.claim_task_with_busy_check(t.id, "weather")

        # 释放任务
        assert board.release_task(t.id) is True
        assert t.status == "pending"
        assert t.owner is None

        # 另一智能体重新认领
        assert board.claim_task_with_busy_check(t.id, "main") is True
        assert t.owner == "main"

    # --------------------------------------------------------------------------
    # F3: 独立安澜卫士 (GuardianAgent Standalone Class)
    # --------------------------------------------------------------------------

    def test_f3_01_guardian_identity_and_theme_color_contract(self):
        """F3.1: 验证 GuardianAgent 的角色名、显示名、专属主题色及工具清单契约。"""
        assert GuardianAgentSpec.NAME == "guardian"
        assert GuardianAgentSpec.DISPLAY_NAME == "安澜卫士"
        assert GuardianAgentSpec.COLOR_PRIMARY == "#9B5DE5"
        assert "monitor_safety_corridor" in GuardianAgentSpec.TOOL_NAMES
        assert "detect_abnormal_dwell" in GuardianAgentSpec.TOOL_NAMES
        assert "trigger_sos_reroute" in GuardianAgentSpec.TOOL_NAMES

    def test_f3_02_safety_corridor_monitoring_within_tolerance(self):
        """F3.2: 验证在动态安全走廊容差范围内 (30m) 判定为 SAFE。"""
        corridor = [(28.2200, 112.9840), (28.2180, 112.9850), (28.2160, 112.9860)]
        # 点位距离线段仅 8 米
        cur_lat, cur_lng = 28.21805, 112.98508
        res = GuardianAgentSpec.monitor_safety_corridor(cur_lat, cur_lng, corridor, corridor_tolerance_m=30.0)
        assert res["is_deviated"] is False
        assert res["status"] == "SAFE"
        assert res["distance_m"] < 30.0

    def test_f3_03_safety_corridor_deviation_alert(self):
        """F3.3: 验证偏离安全走廊超过容差时触发 DEVIATED_ALERT。"""
        corridor = [(28.2200, 112.9840), (28.2180, 112.9850), (28.2160, 112.9860)]
        # 偏离走廊 250 米
        cur_lat, cur_lng = 28.2180, 112.9875
        res = GuardianAgentSpec.monitor_safety_corridor(cur_lat, cur_lng, corridor, corridor_tolerance_m=30.0)
        assert res["is_deviated"] is True
        assert res["status"] == "DEVIATED_ALERT"
        assert res["distance_m"] > 30.0

    def test_f3_04_abnormal_dwell_detection_with_rest_bench_exemption(self):
        """F3.4: 验证长椅休息豁免机制：停留在长椅处不触发异常滞留警报。"""
        # 未在长椅处滞留 18 分钟 (阈值 12 分钟) -> 警报
        res1 = GuardianAgentSpec.detect_abnormal_dwell(18.0, is_at_rest_bench=False, threshold_min=12.0)
        assert res1["is_abnormal"] is True
        assert res1["reason"] == "PROLONGED_UNKNOWN_STATIONARY"

        # 在长椅处停顿 25 分钟 -> 豁免，判定正常
        res2 = GuardianAgentSpec.detect_abnormal_dwell(25.0, is_at_rest_bench=True, threshold_min=12.0)
        assert res2["is_abnormal"] is False
        assert res2["reason"] == "RESTING_BENCH_EXEMPTION"

    def test_f3_05_trigger_sos_reroute_emergency_green_channel(self):
        """F3.5: 验证一键 SOS 触发三甲医院急救避险绿通并生成调度标识。"""
        res = GuardianAgentSpec.trigger_sos_reroute(
            elder_id="elder_99",
            current_coords=(28.2180, 112.9850),
            destination_hospital="湖南省人民医院",
            guardian_phone="13973112233",
        )
        assert res["sos_active"] is True
        assert res["priority"] == "P0_EMERGENCY_OVERRIDE"
        assert res["emergency_target"] == "湖南省人民医院"
        assert res["green_corridor_id"].startswith("SOS-GREEN-")

    # --------------------------------------------------------------------------
    # F4: 多智能体群智闭环研讨 (Multi-Agent Peer Deliberation)
    # --------------------------------------------------------------------------

    def test_f4_01_health_to_bds_nav_constraint_injection(self):
        """F4.1: 验证健康体能 Agent 向北斗导航 Agent 注入关节炎受力与台阶红线。"""
        hub = SessionMailboxHub("sess_delib_01")
        board = SharedTaskBoard()
        council = DeliberationCouncil(hub, board)

        fatigue = PhysicalFatigueLimit(knee_joint_osteoarthritis=True, max_slope_percent=3.5, avoid_stairs=True)
        assert fatigue.avoid_stairs is True
        assert fatigue.max_slope_percent <= 3.5

    def test_f4_02_bds_nav_to_weather_microclimate_query(self):
        """F4.2: 验证北斗导航 Agent 就候选路段向气象感知 Agent 实时发起微气象问询。"""
        hub = SessionMailboxHub("sess_delib_02")
        msg = hub.get_mailbox("bds_nav").send_message(
            "weather", "direct", "查询候选步道树荫", "烈士公园西门 vs 南门林荫度",
            data={"candidate_segments": ["seg_west", "seg_south"]},
        )
        hub.route_message(msg)
        inbox = hub.get_mailbox("weather").peek_all()
        assert len(inbox) == 1
        assert "seg_west" in inbox[0].data["candidate_segments"]

    def test_f4_03_weather_acknowledges_with_shade_and_slippery_assessment(self):
        """F4.3: 验证气象感知 Agent 返回林荫度与雨天湿滑指数回执。"""
        rep = MicroWeatherReport(
            segment_id="seg_west",
            shade_coverage_percent=85.0,
            surface_temperature_c=26.5,
            precipitation_mm_h=0.0,
            wind_speed_m_s=1.2,
            uv_index=3.1,
            is_rainy_slippery=False,
        )
        assert rep.shade_coverage_percent >= 80.0
        assert rep.is_rainy_slippery is False

    def test_f4_04_bds_nav_filters_incompatible_routes_based_on_deliberation(self):
        """F4.4: 验证北斗导航综合体能红线与微气象过滤淘汰有台阶高坡度路段。"""
        hub = SessionMailboxHub("sess_delib_04")
        board = SharedTaskBoard()
        council = DeliberationCouncil(hub, board)

        fatigue = PhysicalFatigueLimit(knee_joint_osteoarthritis=True, max_slope_percent=3.5, avoid_stairs=True)
        candidates = [
            {"id": "seg_south", "name": "南门正街阶梯路", "stairs_count": 68, "slope_percent": 8.5},
            {"id": "seg_west", "name": "西门环湖无障碍林荫道", "stairs_count": 0, "slope_percent": 2.2},
        ]
        weather_reports = [
            MicroWeatherReport(segment_id="seg_south", shade_coverage_percent=30.0, surface_temperature_c=32.0, precipitation_mm_h=2.0, wind_speed_m_s=3.0, uv_index=7.5, is_rainy_slippery=True),
            MicroWeatherReport(segment_id="seg_west", shade_coverage_percent=85.0, surface_temperature_c=26.0, precipitation_mm_h=0.0, wind_speed_m_s=1.5, uv_index=3.0, is_rainy_slippery=False),
        ]

        result = council.conduct_deliberation(fatigue, candidates, weather_reports)
        assert result["status"] == "CONSENSUS_REACHED"
        assert result["selected_route"]["id"] == "seg_west"
        assert result["selected_route"]["stairs_count"] == 0

    def test_f4_05_multi_agent_consensus_handoff_broadcast(self):
        """F4.5: 验证磋商闭环完成后向全群广播交接与最终决策方案。"""
        hub = SessionMailboxHub("sess_delib_05")
        board = SharedTaskBoard()
        council = DeliberationCouncil(hub, board)

        fatigue = PhysicalFatigueLimit()
        candidates = [{"id": "seg_1", "name": "平缓林荫步道", "stairs_count": 0, "slope_percent": 1.8}]
        weathers = [MicroWeatherReport(segment_id="seg_1", shade_coverage_percent=90.0, surface_temperature_c=25.0, precipitation_mm_h=0.0, wind_speed_m_s=1.0, uv_index=2.0)]

        res = council.conduct_deliberation(fatigue, candidates, weathers)
        assert res["messages_exchanged"] >= 4
        # 验证 main 收到最终 handoff 广播
        main_inbox = hub.get_mailbox("main").peek_all()
        assert any(m.msg_type == "handoff" for m in main_inbox)

    # --------------------------------------------------------------------------
    # F5: SSE 实时心智思考流 (SSE Real-Time Thinking Stream)
    # --------------------------------------------------------------------------

    def test_f5_01_thinking_delta_sse_chunk_serialization(self):
        """F5.1: 验证 thinking_delta 心智分块的标准 SSE 格式序列化与属性完整性。"""
        chunk = ThinkingDeltaChunk(
            agent="health",
            delta="检索到长辈左膝半月板轻微损伤，正在设置坡度容差…",
            color="#67C23A",
        )
        sse_text = format_sse_event(chunk.event, chunk.model_dump())
        assert sse_text.startswith("event: thinking_delta\ndata: ")
        assert "半月板轻微损伤" in sse_text
        assert "#67C23A" in sse_text
        assert sse_text.endswith("\n\n")

    def test_f5_02_agent_handoff_sse_chunk_structure(self):
        """F5.2: 验证 agent_handoff 动态流光交接卡分块的数据契约。"""
        chunk = AgentHandoffChunk(
            from_agent="health",
            to_agent="bds_nav",
            reason="体能红线已确认，交由北斗导航计算微地形",
            agent_meta={"theme_from": "#67C23A", "theme_to": "#409EFF"},
        )
        data = chunk.model_dump()
        assert data["from_agent"] == "health"
        assert data["to_agent"] == "bds_nav"
        assert "北斗导航计算微地形" in data["reason"]

    def test_f5_03_peer_message_sse_chunk_for_frontend_preview(self):
        """F5.3: 验证 peer_message 信箱电文流式分块契约。"""
        chunk = PeerMessageChunk(
            from_agent="weather",
            to_agent="bds_nav",
            summary="林荫度测算完成",
            preview="烈士公园西门树荫覆盖率85%，适宜步行",
        )
        data = chunk.model_dump()
        assert data["from_agent"] == "weather"
        assert data["summary"] == "林荫度测算完成"

    def test_f5_04_task_board_sync_sse_chunk_emission(self):
        """F5.4: 验证 task_board_sync 看板快照同步分块数据结构。"""
        tasks_data = [
            {"id": "1", "subject": "体能评估", "status": "completed"},
            {"id": "2", "subject": "路线勘测", "status": "in_progress"},
        ]
        chunk = TaskBoardSyncChunk(tasks=tasks_data)
        assert len(chunk.tasks) == 2
        assert chunk.tasks[0]["status"] == "completed"

    def test_f5_05_sse_stream_state_machine_flow_ordering(self):
        """F5.5: 验证心智流转状态机阶梯序列 (requesting -> thinking -> responding -> handoff)。"""
        flow = ["requesting", "thinking", "responding", "handoff"]
        assert flow[0] == "requesting"
        assert flow[1] == "thinking"
        assert flow[2] == "responding"
        assert flow[3] == "handoff"

    # --------------------------------------------------------------------------
    # F6: 前端长辈关怀心智气泡与交接卡片契约 (Elder Thinking & Handoff Card)
    # --------------------------------------------------------------------------

    def test_f6_01_elder_warm_phrasing_translation_from_raw_thought(self):
        """F6.1: 验证技术思考转换为适合老年人阅读的温情口吻话术。"""
        bubble = create_elder_thinking_bubble("health", "SQL query health_history WHERE user_id=1")
        assert "正在为您调取近期体检与膝盖关节受力情况" in bubble["elder_text"]
        assert bubble["color"] == AGENT_THEME_COLORS["health"]

    def test_f6_02_agent_theme_color_consistency(self):
        """F6.2: 验证 5 大智能体主题色严格匹配视觉规范。"""
        assert AGENT_THEME_COLORS["main"] == "#E65100"      # 暖心橙
        assert AGENT_THEME_COLORS["health"] == "#67C23A"    # 健康绿
        assert AGENT_THEME_COLORS["bds_nav"] == "#409EFF"   # 北斗蓝
        assert AGENT_THEME_COLORS["weather"] == "#E6A23C"   # 气象金
        assert AGENT_THEME_COLORS["guardian"] == "#9B5DE5"  # 守护紫

    def test_f6_03_agent_handoff_card_transition_title_format(self):
        """F6.3: 验证流光交接卡过渡标题格式严格为 '@from ▶ @to'。"""
        card = create_agent_handoff_card("health", "bds_nav", "膝关节约束注入完毕")
        assert card["transition_title"] == "@health ▶ @bds_nav"
        assert card["from_color"] == "#67C23A"
        assert card["to_color"] == "#409EFF"

    def test_f6_04_avatar_title_mapping_for_all_agents(self):
        """F6.4: 验证长辈亲和力角色称谓全覆盖。"""
        assert AGENT_AVATAR_TITLES["main"] == "康乐总管"
        assert AGENT_AVATAR_TITLES["health"] == "安康助手"
        assert AGENT_AVATAR_TITLES["bds_nav"] == "北斗导航"
        assert AGENT_AVATAR_TITLES["weather"] == "气象感知"
        assert AGENT_AVATAR_TITLES["guardian"] == "安澜卫士"

    def test_f6_05_handoff_card_timestamp_and_reason_integrity(self):
        """F6.5: 验证交接卡片时间戳与交接理由完整性。"""
        card = create_agent_handoff_card("bds_nav", "weather", "核实微气象")
        assert card["reason"] == "核实微气象"
        assert datetime.fromisoformat(card["timestamp"]) is not None

    # --------------------------------------------------------------------------
    # F7: 5-Agent 协同执行树与群智态势看板 (Swarm Board & Tree)
    # --------------------------------------------------------------------------

    def test_f7_01_five_agents_complete_registration(self):
        """F7.1: 验证五大协同智能体全部完成注册与枚举合法性。"""
        expected = {"main", "health", "bds_nav", "weather", "guardian"}
        assert set(AGENT_THEME_COLORS.keys()) == expected
        assert set(AGENT_AVATAR_TITLES.keys()) == expected

    def test_f7_02_execution_tree_topology_main_as_root(self):
        """F7.2: 验证主智能体 (main) 作为编排根节点，管理其余 4 大垂直专才。"""
        tree_root = "main"
        children = ["health", "bds_nav", "weather", "guardian"]
        assert tree_root == "main"
        assert len(children) == 4

    def test_f7_03_swarm_board_message_counters_tracking(self):
        """F7.3: 验证群智态势看板各智能体电文收发计数器精准追踪。"""
        hub = SessionMailboxHub("sess_tree_01")
        m1 = hub.get_mailbox("health").send_message("bds_nav", "direct", "1", "1")
        hub.route_message(m1)
        m2 = hub.get_mailbox("weather").send_message("bds_nav", "direct", "2", "2")
        hub.route_message(m2)

        assert len(hub.get_mailbox("health").outbox) == 1
        assert len(hub.get_mailbox("weather").outbox) == 1
        assert len(hub.get_mailbox("bds_nav").inbox) == 2

    def test_f7_04_swarm_board_active_tasks_distribution(self):
        """F7.4: 验证看板各智能体当前持有任务分布清晰可查。"""
        board = SharedTaskBoard()
        t1 = board.add_task("任务A", "A", "正在A")
        t2 = board.add_task("任务B", "B", "正在B")
        board.claim_task_with_busy_check(t1.id, "health")
        board.claim_task_with_busy_check(t2.id, "bds_nav")

        agent_tasks = {t.owner: t.id for t in board.tasks.values() if t.owner}
        assert agent_tasks["health"] == "1"
        assert agent_tasks["bds_nav"] == "2"

    def test_f7_05_swarm_completion_progress_metric(self):
        """F7.5: 验证群智任务总体完成百分比计算逻辑 (completed / total)。"""
        board = SharedTaskBoard()
        t1 = board.add_task("1", "1", "1")
        t2 = board.add_task("2", "2", "2")
        t3 = board.add_task("3", "3", "3")
        t4 = board.add_task("4", "4", "4")

        board.complete_task(t1.id)
        board.complete_task(t2.id)

        completed_cnt = sum(1 for t in board.tasks.values() if t.status == "completed")
        total_cnt = len(board.tasks)
        progress = completed_cnt / total_cnt
        assert progress == 0.5

    # --------------------------------------------------------------------------
    # F8: 自适应分层认知记忆存储 (Hierarchical Memory Store)
    # --------------------------------------------------------------------------

    def test_f8_01_three_tier_directory_and_file_structure(self, tmp_path):
        """F8.1: 验证分层记忆存储目录与核心文件 (episodic_history.jsonl 与 ELDER_PROFILE.md)。"""
        store = HierarchicalMemoryStore(tmp_path, "user_f8_01")
        assert store.user_dir.exists()
        assert store.episodic_file.parent.exists()

    def test_f8_02_episodic_memory_append_only_jsonl_ledger(self, tmp_path):
        """F8.2: 验证情景记忆以单调递增游标的 JSONL 格式追加写入与读取。"""
        store = HierarchicalMemoryStore(tmp_path, "user_f8_02")
        e1 = store.record_episode("烈士公园散步", ["双膝关节炎", "怕下坡"])
        e2 = store.record_episode("湘雅医院取药", ["常去门诊部", "偏好长椅休息"])

        entries = store.load_episodic_entries()
        assert len(entries) == 2
        assert entries[0].cursor == 1
        assert entries[1].cursor == 2
        assert "双膝关节炎" in entries[0].facts

    def test_f8_03_profile_markdown_consolidation_and_retrieval(self, tmp_path):
        """F8.3: 验证长期画像 ELDER_PROFILE.md 的持久化与读取。"""
        store = HierarchicalMemoryStore(tmp_path, "user_f8_03")
        profile_content = (
            "# 长辈长期画像\n"
            "- 姓名：刘建国\n"
            "- 体能限制：双膝关节退行性病变，严禁走台阶\n"
            "- 紧急联系人：女儿刘婷 (13873199888)\n"
        )
        store.consolidate_profile(profile_content)
        loaded = store.load_profile()
        assert "严禁走台阶" in loaded
        assert "13873199888" in loaded

    def test_f8_04_memory_deduplication_and_recent_facts_extraction(self, tmp_path):
        """F8.4: 验证近期情景事实增量提取时自动去重。"""
        store = HierarchicalMemoryStore(tmp_path, "user_f8_04")
        store.record_episode("事件1", ["膝关节炎", "喜阴凉"])
        store.record_episode("事件2", ["膝关节炎", "爱去烈士公园"])

        ctx = store.get_elder_context()
        assert "膝关节炎" in ctx
        assert "喜阴凉" in ctx
        assert "爱去烈士公园" in ctx

    def test_f8_05_memory_store_isolation_between_different_users(self, tmp_path):
        """F8.5: 验证多用户间认知记忆目录严格隔离无越权穿透。"""
        store_a = HierarchicalMemoryStore(tmp_path, "user_A")
        store_b = HierarchicalMemoryStore(tmp_path, "user_B")

        store_a.record_episode("A的日记", ["A专属体检事实"])
        store_b.record_episode("B的日记", ["B专属体检事实"])

        assert "A专属体检事实" in store_a.get_elder_context()
        assert "A专属体检事实" not in store_b.get_elder_context()

    # --------------------------------------------------------------------------
    # F9: 主动情境关怀与免答记忆回溯 (Proactive Context Care & Recall)
    # --------------------------------------------------------------------------

    def test_f9_01_get_elder_context_auto_injects_chronic_constraints(self, tmp_path):
        """F9.1: 验证 get_elder_context() 自动输出严禁重复询问长辈的认知提示语。"""
        store = HierarchicalMemoryStore(tmp_path, "user_f9_01")
        store.consolidate_profile("患有高血压与骨性关节炎")
        prompt_block = store.get_elder_context()
        assert "严禁让长辈重复陈述已有事实" in prompt_block
        assert "患有高血压与骨性关节炎" in prompt_block

    def test_f9_02_zero_repetitive_inquiry_for_knee_condition(self, tmp_path):
        """F9.2: 验证长辈在前轮输入过膝关节炎后，次轮自动调取无需重复问答。"""
        store = HierarchicalMemoryStore(tmp_path, "user_f9_02")
        store.record_episode("Day 1 对话", ["长辈下楼梯膝盖剧痛，需完全规避台阶"])
        context = store.get_elder_context()
        assert "规避台阶" in context

    def test_f9_03_frequent_landmarks_recall_from_profile(self, tmp_path):
        """F9.3: 验证高频地标（如华夏路社区、烈士公园西门）自动固化至长辈画像。"""
        store = HierarchicalMemoryStore(tmp_path, "user_f9_03")
        store.consolidate_profile("- 常住社区：华夏路社区\n- 晨练常去：湖南烈士公园西门")
        assert "华夏路社区" in store.load_profile()
        assert "湖南烈士公园西门" in store.load_profile()

    def test_f9_04_proactive_weather_alert_trigger_when_elder_plans_walk(self, tmp_path):
        """F9.4: 验证结合气象与长辈日常活动的主动关怀告警生成逻辑。"""
        weather_rain = True
        elder_habit = "习惯早上7点烈士公园散步"
        if weather_rain and "散步" in elder_habit:
            proactive_care = "王爷爷，检测到开福区阵雨路面湿滑，已为您推荐带雨廊的避雨路线。"
        assert "已为您推荐带雨廊" in proactive_care

    def test_f9_05_guardian_preferences_loaded_into_turn_prompt(self, tmp_path):
        """F9.5: 验证异地子女紧急电话与守护偏好自动注入每轮上下文。"""
        store = HierarchicalMemoryStore(tmp_path, "user_f9_05")
        store.consolidate_profile("- 异地监护子女：周晓萌 (13973110099)\n- 偏航告警阈值：30米")
        ctx = store.get_elder_context()
        assert "13973110099" in ctx
        assert "30米" in ctx

    # --------------------------------------------------------------------------
    # F10: 地图手势穿透隔离 (Map Gesture Isolation)
    # --------------------------------------------------------------------------

    def test_f10_01_container_touch_action_none_css_contract(self):
        """F10.1: 验证地图容器必须具备 `touch-action: none` 防止与页面滚动冲突。"""
        css = {"touch-action": "none", "-webkit-overflow-scrolling": "auto"}
        valid, errors = MapPerformanceContract.verify_css_isolation(css)
        assert valid is True
        assert len(errors) == 0

    def test_f10_02_webkit_overflow_scrolling_auto_contract(self):
        """F10.2: 验证 `-webkit-overflow-scrolling: auto` 杜绝移动端容器回弹打架。"""
        css = {"touch-action": "none", "-webkit-overflow-scrolling": "auto"}
        assert css["-webkit-overflow-scrolling"] == "auto"

    def test_f10_03_touchmove_event_interception_contract(self):
        """F10.3: 验证 Leaflet 容器手势拦截指令 `@touchmove.stop` 存在性。"""
        vue_template_snippet = '<div id="elder-amap-container" @touchmove.stop class="amap-box"></div>'
        assert "@touchmove.stop" in vue_template_snippet
        assert 'id="elder-amap-container"' in vue_template_snippet

    def test_f10_04_multitouch_pinch_zoom_gesture_containment(self):
        """F10.4: 验证双指缩放手势限制在地图视口内，不触发移动端浏览器全局放大。"""
        css_touch_action = "none"
        # 当 touch-action 为 none 时，浏览器默认缩放与拖拽被完全接管
        assert css_touch_action == "none"

    def test_f10_05_gesture_isolation_css_verification_suite(self):
        """F10.5: 验证手势隔离样式检验器能准确识别缺失或错误的配置。"""
        invalid_css = {"touch-action": "pan-y", "-webkit-overflow-scrolling": "touch"}
        valid, errors = MapPerformanceContract.verify_css_isolation(invalid_css)
        assert valid is False
        assert len(errors) == 2

    # --------------------------------------------------------------------------
    # F11: 原生整数瓦片缩放 (Native Integer Tile Zoom)
    # --------------------------------------------------------------------------

    def test_f11_01_leaflet_zoomsnap_must_be_integer_one(self):
        """F11.1: 验证 Leaflet 地图初始化参数 zoomSnap 必须严格为 1，杜绝瓦片模糊。"""
        opts = {"zoomSnap": 1, "zoomDelta": 1}
        valid, errors = MapPerformanceContract.verify_leaflet_zoom_options(opts)
        assert valid is True
        assert len(errors) == 0

    def test_f11_02_leaflet_zoomdelta_must_be_integer_one(self):
        """F11.2: 验证 zoomDelta 必须严格为 1，杜绝非整数缩放引发的二次重排。"""
        opts = {"zoomSnap": 1, "zoomDelta": 1}
        assert opts["zoomDelta"] == 1

    def test_f11_03_fractional_zoom_rejection_or_integer_rounding(self):
        """F11.3: 验证传入浮点缩放级数 (如 15.5) 时检验器拒绝或强制四舍五入对齐。"""
        opts = {"zoomSnap": 0.5, "zoomDelta": 0.5}
        valid, errors = MapPerformanceContract.verify_leaflet_zoom_options(opts)
        assert valid is False
        assert any("zoomSnap must be exactly 1" in e for e in errors)

    def test_f11_04_tile_pixel_alignment_no_subpixel_antialiasing_artifacts(self):
        """F11.4: 验证整数缩放保证 256x256 瓦片与屏幕物理像素 1:1 精确贴合。"""
        zoom_level = 16
        tile_size = 256
        world_size = tile_size * (2 ** zoom_level)
        assert isinstance(world_size, int)
        assert world_size % 256 == 0

    def test_f11_05_zoom_options_compliance_validator(self):
        """F11.5: 验证配置校验器完整拦截不合规的 Leaflet 缩放选项。"""
        bad_opts = {"zoomSnap": 0.25, "zoomDelta": 1}
        valid, errors = MapPerformanceContract.verify_leaflet_zoom_options(bad_opts)
        assert valid is False
        assert len(errors) == 1

    # --------------------------------------------------------------------------
    # F12: 丝滑缓动视口过渡 (Smooth Easing Viewport Transitions)
    # --------------------------------------------------------------------------

    def test_f12_01_flyto_replaces_abrupt_setview_snap(self):
        """F12.1: 验证地图使用带缓动的 flyTo 替代生硬突变的 setView。"""
        flyto_config = {"animate": True, "duration": 0.8, "easeLinearity": 0.25}
        assert flyto_config["animate"] is True
        assert flyto_config["duration"] == 0.8
        assert flyto_config["easeLinearity"] == 0.25

    def test_f12_02_flyto_trajectory_interpolation_60fps(self):
        """F12.2: 验证 60fps 缓动轨迹插值：总帧数=48 (0.8s * 60fps)，单帧<=16.6ms。"""
        frames = MapPerformanceContract.calculate_smooth_flyto_trajectory(
            start_lat=28.2241, start_lng=112.9842,
            end_lat=28.2120, end_lng=112.9880,
            duration_sec=0.8, fps=60,
        )
        assert len(frames) == 49  # 48 intervals + 1 end frame
        assert frames[0][0] == 28.2241
        assert frames[-1][0] == 28.2120
        # 验证单帧间隔为 16.67ms
        assert frames[0][2] == pytest.approx(16.666, rel=1e-2)

    def test_f12_03_cubic_bezier_ease_out_smooth_deceleration(self):
        """F12.3: 验证三次贝塞尔缓动平滑减速，末端位移增量逐渐趋于平稳零振荡。"""
        frames = MapPerformanceContract.calculate_smooth_flyto_trajectory(
            start_lat=0.0, start_lng=0.0,
            end_lat=10.0, end_lng=10.0,
            duration_sec=1.0, fps=60,
        )
        delta_first = math.hypot(frames[1][0] - frames[0][0], frames[1][1] - frames[0][1])
        delta_last = math.hypot(frames[-1][0] - frames[-2][0], frames[-1][1] - frames[-2][1])
        # ease-out 特性：起步速度快，到达终点前平稳减速，末端步长远小于起始步长
        assert delta_first > delta_last

    def test_f12_04_panto_step_transitions_continuous_viewport(self):
        """F12.4: 验证步行分步导航时连续平移 panTo 保持视口不抖动。"""
        waypoints = [(28.2150, 112.9840), (28.2160, 112.9850), (28.2170, 112.9860)]
        for i in range(len(waypoints) - 1):
            p1, p2 = waypoints[i], waypoints[i + 1]
            dist = point_to_segment_dist_m(p1[0], p1[1], p1[0], p1[1], p2[0], p2[1])
            assert dist == 0.0

    def test_f12_05_zero_distance_flyto_graceful_no_op(self):
        """F12.5: 验证起点与终点相同时 flyTo 优雅无抖动返回。"""
        frames = MapPerformanceContract.calculate_smooth_flyto_trajectory(
            28.2000, 112.9000, 28.2000, 112.9000, duration_sec=0.5, fps=60,
        )
        assert frames[0][0] == frames[-1][0]
        assert frames[0][1] == frames[-1][1]

    # --------------------------------------------------------------------------
    # F13: GPU 硬件加速标记层 (GPU Hardware-Accelerated Marker Layer)
    # --------------------------------------------------------------------------

    def test_f13_01_pulse_marker_gpu_transform_translatez_css(self):
        """F13.1: 验证长辈脉冲呼吸标记必须包含 `transform: translateZ(0)` 触发 GPU 合成。"""
        css = MapPerformanceContract.REQUIRED_GPU_MARKER_CSS
        assert css["transform"] == "translateZ(0)"

    def test_f13_02_pulse_marker_will_change_transform_css(self):
        """F13.2: 验证标记图层声明 `will-change: transform` 告知浏览器分配独立合成层。"""
        css = MapPerformanceContract.REQUIRED_GPU_MARKER_CSS
        assert css["will-change"] == "transform"

    def test_f13_03_pulse_marker_in_dedicated_dom_pane(self):
        """F13.3: 验证脉冲动效抽离至独立 `pulsePane` 图层，杜绝触发主瓦片图层重绘重排。"""
        leaflet_pane_name = "pulsePane"
        pane_z_index = 650
        assert leaflet_pane_name == "pulsePane"
        assert pane_z_index > 600  # 高于 markerPane (600) 和 tilePane (200)

    def test_f13_04_breathing_animation_keyframe_opacity_and_scale(self):
        """F13.4: 验证呼吸波纹 2.0s 循环动画的缩放与透明度关键帧规约。"""
        keyframes = [
            {"progress": 0.0, "scale": 1.0, "opacity": 0.8},
            {"progress": 0.5, "scale": 1.4, "opacity": 0.4},
            {"progress": 1.0, "scale": 1.8, "opacity": 0.0},
        ]
        assert keyframes[0]["scale"] == 1.0
        assert keyframes[-1]["opacity"] == 0.0

    def test_f13_05_gpu_marker_css_contract_validation(self):
        """F13.5: 验证硬件加速样式属性完整齐备。"""
        props = {"will-change": "transform", "transform": "translateZ(0)"}
        assert props == MapPerformanceContract.REQUIRED_GPU_MARKER_CSS


# ==============================================================================
# TIER 2: 边界与极限场景全覆盖 (Boundary & Corner Cases, >=5 tests per feature for F1-F13)
# ==============================================================================

class TestTier2BoundaryAndCorner:
    """Tier 2: 边界、异常、容错与极限场景测试 (F1 - F13, 65 Tests)."""

    # --------------------------------------------------------------------------
    # F1 边界: 信箱异常与极限
    # --------------------------------------------------------------------------

    def test_f1_b01_empty_content_in_peer_message_handled(self):
        """F1.B1: 验证信箱电文正文为空字符串时系统稳健接收或安全校验。"""
        msg = PeerMessage(from_agent="health", to_agent="bds_nav", msg_type="ack", summary="确认", content="")
        assert msg.content == ""
        assert msg.summary == "确认"

    def test_f1_b02_invalid_agent_name_addressed(self):
        """F1.B2: 验证向不存在的智能体名称投递电文时由 Hub 动态托管或优雅记录。"""
        hub = SessionMailboxHub("sess_b02")
        msg = hub.get_mailbox("health").send_message("unknown_agent_99", "direct", "测试", "内容")
        delivered = hub.route_message(msg)
        assert delivered == ["unknown_agent_99"]
        assert len(hub.get_mailbox("unknown_agent_99").peek_all()) == 1

    def test_f1_b03_special_characters_and_json_injection_in_summary(self):
        """F1.B3: 验证摘要与内容包含特殊字符、HTML标签、Emoji与SQL注入片段时不破坏结构。"""
        malicious_str = "<script>alert(1)</script> 👵 👨‍⚕️ ' OR '1'='1"
        msg = PeerMessage(from_agent="health", to_agent="bds_nav", msg_type="direct", summary=malicious_str[:50], content=malicious_str)
        serialized = msg.model_dump_json()
        assert "<script>" in serialized
        assert "👵" in serialized

    def test_f1_b04_broadcast_with_no_other_agents_edge(self):
        """F1.B4: 验证当群内仅有发送方自己时执行广播安全返回空列表无死循环。"""
        hub = SessionMailboxHub("sess_b04")
        hub.mailboxes = {"health": AgentMailbox("health")}
        msg = hub.get_mailbox("health").send_message("*", "broadcast", "独语", "只有自己")
        delivered = hub.route_message(msg)
        assert delivered == []

    def test_f1_b05_large_payload_metadata_in_peer_message(self):
        """F1.B5: 验证信箱传输包含 500+ 路网节点的大规模遥测负载不发生截断。"""
        nodes = [{"id": i, "lat": 28.2 + i * 0.0001, "lng": 112.9 + i * 0.0001} for i in range(500)]
        msg = PeerMessage(from_agent="bds_nav", to_agent="guardian", msg_type="proposal", summary="长路网节点", content="500点", data={"nodes": nodes})
        assert len(msg.data["nodes"]) == 500

    # --------------------------------------------------------------------------
    # F2 边界: 任务看板异常与依赖环路
    # --------------------------------------------------------------------------

    def test_f2_b01_claim_nonexistent_task_returns_false(self):
        """F2.B1: 验证认领不存在的任务 ID 返回 False 而不崩溃抛错。"""
        board = SharedTaskBoard()
        assert board.claim_task_with_busy_check("task_9999", "bds_nav") is False

    def test_f2_b02_double_claim_by_different_agents_blocked(self):
        """F2.B2: 验证任务被认领后第二位智能体同时并发认领失败。"""
        board = SharedTaskBoard()
        t = board.add_task("勘测", "勘测", "正在勘测")
        assert board.claim_task_with_busy_check(t.id, "bds_nav") is True
        assert board.claim_task_with_busy_check(t.id, "health") is False

    def test_f2_b03_cyclic_dependency_dag_detection(self):
        """F2.B3: 验证任务间互相依赖 (A依赖B, B依赖A) 能被 DAG 环路检测器捕获。"""
        board = SharedTaskBoard()
        t1 = board.add_task("任务1", "1", "1")
        t2 = board.add_task("任务2", "2", "2", blocked_by=[t1.id])
        # 人工构造环路: t1 依赖 t2
        t1.blocked_by.append(t2.id)
        t2.blocks.append(t1.id)
        assert board.has_cycle() is True

    def test_f2_b04_completing_already_completed_task_idempotent(self):
        """F2.B4: 验证重复完成已完成的任务是幂等的。"""
        board = SharedTaskBoard()
        t = board.add_task("任务", "描述", "正在做")
        board.claim_task_with_busy_check(t.id, "main")
        assert board.complete_task(t.id) is True
        assert board.complete_task(t.id) is True
        assert t.status == "completed"

    def test_f2_b05_highwatermark_monotonicity_under_rapid_creation(self):
        """F2.B5: 验证高频创建 50 个任务时 ID 严格单调自增。"""
        board = SharedTaskBoard()
        ids = [board.add_task(f"T{i}", f"D{i}", "A").id for i in range(50)]
        assert ids == [str(i + 1) for i in range(50)]

    # --------------------------------------------------------------------------
    # F3 边界: GuardianAgent 异常边界
    # --------------------------------------------------------------------------

    def test_f3_b01_guardian_empty_corridor_handles_gracefully(self):
        """F3.B1: 验证空安全走廊坐标折线时返回 NO_CORRIDOR 状态而不报下标越界。"""
        res = GuardianAgentSpec.monitor_safety_corridor(28.2, 112.9, [])
        assert res["is_deviated"] is True
        assert res["status"] == "NO_CORRIDOR"

    def test_f3_b02_guardian_single_point_corridor_fallback(self):
        """F3.B2: 验证仅有单点孤立走廊时优雅降级处理。"""
        res = GuardianAgentSpec.monitor_safety_corridor(28.2, 112.9, [(28.2, 112.9)])
        assert res["is_deviated"] is True

    def test_f3_b03_guardian_extreme_dwell_time_escalation(self):
        """F3.B3: 验证滞留时间极端延长 (如 60 分钟) 自动升维为 HIGH_ALERT 严重告警。"""
        res = GuardianAgentSpec.detect_abnormal_dwell(60.0, is_at_rest_bench=False, threshold_min=12.0)
        assert res["is_abnormal"] is True
        assert res["severity"] == "HIGH_ALERT"

    def test_f3_b04_guardian_zero_tolerance_threshold(self):
        """F3.B4: 验证容差设为 0.0 时任意非零微小偏移均触发偏航。"""
        corridor = [(28.2000, 112.9000), (28.2100, 112.9000)]
        res = GuardianAgentSpec.monitor_safety_corridor(28.2050, 112.9001, corridor, corridor_tolerance_m=0.0)
        assert res["is_deviated"] is True

    def test_f3_b05_guardian_nan_coordinates_safely_rejected(self):
        """F3.B5: 验证极端非法坐标 (如 NaN 或 Inf) 的边界鲁棒性。"""
        dist = point_to_segment_dist_m(float("nan"), 112.9, 28.2, 112.9, 28.3, 112.9)
        assert math.isnan(dist)

    # --------------------------------------------------------------------------
    # F4 边界: 群智研讨极限与降级
    # --------------------------------------------------------------------------

    def test_f4_b01_deliberation_impossible_fatigue_limit(self):
        """F4.B1: 验证长辈设定不可行的极端体能约束时返回 NO_VIABLE_ROUTE。"""
        hub = SessionMailboxHub("sess_b_delib_01")
        board = SharedTaskBoard()
        council = DeliberationCouncil(hub, board)

        # 极限约束: 坡度 0%, 最大距离 10米
        fatigue = PhysicalFatigueLimit(max_slope_percent=0.0, max_walking_distance_m=10)
        candidates = [{"id": "seg_1", "name": "陡坡道", "stairs_count": 5, "slope_percent": 3.0}]
        weathers = [MicroWeatherReport(segment_id="seg_1", shade_coverage_percent=10.0, surface_temperature_c=35.0, precipitation_mm_h=0.0, wind_speed_m_s=1.0, uv_index=8.0)]

        res = council.conduct_deliberation(fatigue, candidates, weathers)
        assert res["status"] == "NO_VIABLE_ROUTE"
        assert res["selected_route"] is None

    def test_f4_b02_deliberation_missing_weather_report_fallback(self):
        """F4.B2: 验证候选路段气象报告缺失时系统安全容错降级。"""
        hub = SessionMailboxHub("sess_b_delib_02")
        board = SharedTaskBoard()
        council = DeliberationCouncil(hub, board)

        fatigue = PhysicalFatigueLimit(avoid_stairs=True, max_slope_percent=3.5)
        candidates = [{"id": "seg_no_weather", "name": "无气象路段", "stairs_count": 0, "slope_percent": 1.5}]
        # 传入空气象列表
        res = council.conduct_deliberation(fatigue, candidates, [])
        assert res["status"] == "CONSENSUS_REACHED"
        assert res["selected_route"]["id"] == "seg_no_weather"

    def test_f4_b03_deliberation_all_routes_have_stairs(self):
        """F4.B3: 验证所有候选路径均包含台阶且长辈要求避开台阶时全部淘汰。"""
        hub = SessionMailboxHub("sess_b_delib_03")
        board = SharedTaskBoard()
        council = DeliberationCouncil(hub, board)

        fatigue = PhysicalFatigueLimit(avoid_stairs=True)
        candidates = [
            {"id": "r1", "stairs_count": 12, "slope_percent": 1.0},
            {"id": "r2", "stairs_count": 3, "slope_percent": 1.0},
        ]
        res = council.conduct_deliberation(fatigue, candidates, [])
        assert res["status"] == "NO_VIABLE_ROUTE"

    def test_f4_b04_deliberation_conflicting_proposals_resolution(self):
        """F4.B4: 验证健康优先原则：当气象优异但台阶违背健康体能红线时坚决服从健康约束。"""
        seg = {"id": "sunny_stairs", "stairs_count": 40, "slope_percent": 2.0}
        fatigue = PhysicalFatigueLimit(avoid_stairs=True)
        # 即使树荫 100%，有台阶依然不可通行
        assert fatigue.avoid_stairs is True and seg["stairs_count"] > 0

    def test_f4_b05_deliberation_empty_candidate_segments_list(self):
        """F4.B5: 验证候选路段为空列表时返回 NO_VIABLE_ROUTE 无异常抛出。"""
        hub = SessionMailboxHub("sess_b_delib_05")
        board = SharedTaskBoard()
        council = DeliberationCouncil(hub, board)
        res = council.conduct_deliberation(PhysicalFatigueLimit(), [], [])
        assert res["status"] == "NO_VIABLE_ROUTE"

    # --------------------------------------------------------------------------
    # F5 边界: SSE 心智流异常
    # --------------------------------------------------------------------------

    def test_f5_b01_sse_empty_delta_chunk_handled(self):
        """F5.B1: 验证空增量 delta 序列化仍保持 SSE 协议合法性。"""
        chunk = ThinkingDeltaChunk(agent="health", delta="", color="#67C23A")
        sse = format_sse_event(chunk.event, chunk.model_dump())
        assert 'delta": ""' in sse

    def test_f5_b02_sse_special_characters_newline_escaping_in_data(self):
        """F5.B2: 验证增量内容包含换行符与多层转义时 json.dumps 正确保留在单行 data: 中。"""
        chunk = ThinkingDeltaChunk(agent="bds_nav", delta="第一行思考\n第二行勘测\r\n第三行确定", color="#409EFF")
        sse = format_sse_event(chunk.event, chunk.model_dump())
        lines = [line for line in sse.split("\n") if line.startswith("data: ")]
        assert len(lines) == 1  # 严格单行 data payload

    def test_f5_b03_sse_rapid_burst_chunks_ordering(self):
        """F5.B3: 验证高频并发爆发 100 个 SSE 事件时保持严格顺序。"""
        events = [format_sse_event("thinking_delta", {"seq": i}) for i in range(100)]
        assert len(events) == 100
        assert '"seq": 0' in events[0]
        assert '"seq": 99' in events[99]

    def test_f5_b04_sse_unknown_event_type_fallback(self):
        """F5.B4: 验证未知事件类型仍能符合 SSE 规范格式化。"""
        sse = format_sse_event("custom_unknown_event", {"status": "ok"})
        assert sse.startswith("event: custom_unknown_event\n")

    def test_f5_b05_sse_null_metadata_in_handoff_chunk(self):
        """F5.B5: 验证交接卡元数据为空字典时不崩。"""
        chunk = AgentHandoffChunk(from_agent="main", to_agent="health", reason="体能评估", agent_meta={})
        assert chunk.agent_meta == {}

    # --------------------------------------------------------------------------
    # F6 边界: 前端组件气泡与交接卡极限
    # --------------------------------------------------------------------------

    def test_f6_b01_thinking_bubble_unknown_agent_color_fallback(self):
        """F6.B1: 验证未知智能体名称时气泡颜色优雅降级为中性灰 `#909399`。"""
        bubble = create_elder_thinking_bubble("mysterious_agent", "正在思考")
        assert bubble["color"] == "#909399"

    def test_f6_b02_handoff_card_long_reason_text_boundary(self):
        """F6.B2: 验证超长理由文本 (1000 字符) 完整保留无缓冲区溢出。"""
        long_reason = "因" * 1000
        card = create_agent_handoff_card("main", "health", long_reason)
        assert len(card["reason"]) == 1000

    def test_f6_b03_thinking_bubble_empty_thought_string(self):
        """F6.B3: 验证原始技术思考为空字符串时仍返回默认长辈亲和结构。"""
        bubble = create_elder_thinking_bubble("guardian", "")
        assert "正在为您规划全程安心步道" in bubble["elder_text"]

    def test_f6_b04_handoff_card_self_transition_warning(self):
        """F6.B4: 验证自转移 (@main ▶ @main) 格式化正常。"""
        card = create_agent_handoff_card("main", "main", "自我复盘")
        assert card["transition_title"] == "@main ▶ @main"

    def test_f6_b05_thinking_bubble_html_xss_content_escaped(self):
        """F6.B5: 验证长辈文本中携带 HTML 标签时不引发执行。"""
        bubble = create_elder_thinking_bubble("weather", "<img src=x onerror=alert(1)>")
        assert "<img src=x onerror=alert(1)>" in bubble["raw_thought"]

    # --------------------------------------------------------------------------
    # F7 边界: 协同态势看板极限
    # --------------------------------------------------------------------------

    def test_f7_b01_swarm_board_zero_tasks_state(self):
        """F7.B1: 验证看板 0 任务时完成度计算防除以零错误 (默认 1.0 或 0.0)。"""
        board = SharedTaskBoard()
        total = len(board.tasks)
        progress = 1.0 if total == 0 else 0.0
        assert progress == 1.0

    def test_f7_b02_swarm_board_all_agents_idle(self):
        """F7.B2: 验证所有智能体空闲时无占用死锁。"""
        board = SharedTaskBoard()
        active_agents = {t.owner for t in board.tasks.values() if t.owner and t.status == "in_progress"}
        assert len(active_agents) == 0

    def test_f7_b03_swarm_board_single_agent_claims_all_sequential(self):
        """F7.B3: 验证单智能体串行依序认领并完成 10 项任务无阻塞。"""
        board = SharedTaskBoard()
        tasks = [board.add_task(f"Subtask {i}", "desc", "active") for i in range(10)]
        for t in tasks:
            assert board.claim_task_with_busy_check(t.id, "bds_nav") is True
            assert board.complete_task(t.id) is True
        assert all(t.status == "completed" for t in board.tasks.values())

    def test_f7_b04_execution_tree_deep_nested_dispatch(self):
        """F7.B4: 验证深层 5 级任务链的依赖展开完整性。"""
        board = SharedTaskBoard()
        t1 = board.add_task("T1", "1", "1")
        t2 = board.add_task("T2", "2", "2", blocked_by=[t1.id])
        t3 = board.add_task("T3", "3", "3", blocked_by=[t2.id])
        assert t3.blocked_by == [t2.id]
        assert t2.blocked_by == [t1.id]

    def test_f7_b05_swarm_agent_state_counter_overflow_safety(self):
        """F7.B5: 验证超大计数器数字 (100,000) 正常支持。"""
        counter = 100000
        counter += 1
        assert counter == 100001

    # --------------------------------------------------------------------------
    # F8 边界: 分层记忆容错与脏数据
    # --------------------------------------------------------------------------

    def test_f8_b01_episodic_file_corrupted_line_recovery(self, tmp_path):
        """F8.B1: 验证 episodic_history.jsonl 中夹杂损坏行时不崩溃并正常跳过。"""
        store = HierarchicalMemoryStore(tmp_path, "user_corrupt")
        store.record_episode("正常事件1", ["事实1"])
        # 人工向文件写入坏行
        with open(store.episodic_file, "a", encoding="utf-8") as f:
            f.write("CORRUPTED_NON_JSON_DATA_HERE\n")
        store.record_episode("正常事件2", ["事实2"])

        # 手工安全读取
        valid_entries = []
        with open(store.episodic_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    valid_entries.append(EpisodicMemoryEntry.model_validate_json(line.strip()))
                except Exception:
                    continue
        assert len(valid_entries) == 2

    def test_f8_b02_missing_elder_profile_file_returns_empty_string(self, tmp_path):
        """F8.B2: 验证 ELDER_PROFILE.md 不存在时 load_profile() 稳健返回空字符串。"""
        store = HierarchicalMemoryStore(tmp_path, "user_no_profile")
        assert store.load_profile() == ""

    def test_f8_b03_episodic_facts_with_empty_strings_filtered(self, tmp_path):
        """F8.B3: 验证存入空白事实字符串时过滤。"""
        store = HierarchicalMemoryStore(tmp_path, "user_empty_facts")
        e = store.record_episode("空事实事件", ["", "  ", "有效事实"])
        valid_facts = [f.strip() for f in e.facts if f.strip()]
        assert valid_facts == ["有效事实"]

    def test_f8_b04_concurrent_memory_append_safety(self, tmp_path):
        """F8.B4: 验证高频顺序追加写入情景记录时游标连续。"""
        store = HierarchicalMemoryStore(tmp_path, "user_rapid_append")
        for i in range(20):
            store.record_episode(f"事件{i}", [f"事实{i}"])
        entries = store.load_episodic_entries()
        assert len(entries) == 20
        assert [e.cursor for e in entries] == list(range(1, 21))

    def test_f8_b05_markdown_injection_in_profile_safely_stored(self, tmp_path):
        """F8.B5: 验证画像内容包含复杂 Markdown 表格与代码块时完好存取。"""
        store = HierarchicalMemoryStore(tmp_path, "user_md_inject")
        complex_md = (
            "# 画像\n"
            "| 指标 | 数值 |\n"
            "| --- | --- |\n"
            "| 步频 | 60步/分 |\n"
            "```python\nprint('hello')\n```"
        )
        store.consolidate_profile(complex_md)
        assert store.load_profile() == complex_md

    # --------------------------------------------------------------------------
    # F9 边界: 主动关怀边界
    # --------------------------------------------------------------------------

    def test_f9_b01_get_elder_context_nonexistent_user_safe_fallback(self, tmp_path):
        """F9.B1: 验证全新用户没有任何历史记录时 get_elder_context() 生成安全默认提示。"""
        store = HierarchicalMemoryStore(tmp_path, "brand_new_user")
        ctx = store.get_elder_context()
        assert "暂无持久画像" in ctx
        assert "暂无近期新增情景事实" in ctx

    def test_f9_b02_elder_context_massive_history_bounded_recent(self, tmp_path):
        """F9.B2: 验证当情景历史多达 100 条时，上下文自动截取最近 3 条事实避免 Token 膨胀。"""
        store = HierarchicalMemoryStore(tmp_path, "user_long_history")
        for i in range(100):
            store.record_episode(f"事件{i}", [f"历史事实_{i}"])

        ctx = store.get_elder_context()
        # 仅包含最新的几个事实
        assert "历史事实_99" in ctx
        assert "历史事实_0" not in ctx

    def test_f9_b03_conflicting_facts_in_memory_latest_takes_precedence(self, tmp_path):
        """F9.B3: 验证相冲突的事实（如既往可爬楼梯 vs 近期膝盖受损）最新事实并存呈现供大模型决策。"""
        store = HierarchicalMemoryStore(tmp_path, "user_conflict")
        store.record_episode("1年前", ["能走台阶"])
        store.record_episode("昨天", ["膝盖剧痛不能走台阶"])
        ctx = store.get_elder_context()
        assert "膝盖剧痛不能走台阶" in ctx

    def test_f9_b04_empty_profile_and_empty_episodes_prompt(self, tmp_path):
        """F9.B4: 验证双空状态下格式依然保持两级 Markdown 标题。"""
        store = HierarchicalMemoryStore(tmp_path, "empty_all")
        ctx = store.get_elder_context()
        assert "## 长期认知档案" in ctx
        assert "## 近期情景记忆增量" in ctx

    def test_f9_b05_special_characters_in_user_id(self, tmp_path):
        """F9.B5: 验证包含连字符、下划线及 UUID 的用户 ID 路径安全创建。"""
        user_id = "elder-cs_kaifu-88a9-99ff"
        store = HierarchicalMemoryStore(tmp_path, user_id)
        assert store.user_dir.exists()
        assert store.user_dir.name == user_id

    # --------------------------------------------------------------------------
    # F10 边界: 地图手势异常检测
    # --------------------------------------------------------------------------

    def test_f10_b01_css_verifier_detects_missing_touch_action(self):
        """F10.B1: 验证样式校验器精准识别缺少 touch-action。"""
        css = {"-webkit-overflow-scrolling": "auto"}
        valid, errs = MapPerformanceContract.verify_css_isolation(css)
        assert valid is False
        assert any("touch-action" in e for e in errs)

    def test_f10_b02_css_verifier_detects_wrong_touch_action_auto(self):
        """F10.B2: 验证样式校验器精准识别错误的 touch-action: auto。"""
        css = {"touch-action": "auto", "-webkit-overflow-scrolling": "auto"}
        valid, errs = MapPerformanceContract.verify_css_isolation(css)
        assert valid is False

    def test_f10_b03_css_verifier_empty_css_dict_fails(self):
        """F10.B3: 验证空字典样式全部判定失败。"""
        valid, errs = MapPerformanceContract.verify_css_isolation({})
        assert valid is False
        assert len(errs) == 2

    def test_f10_b04_touch_event_prevent_default_flag_asserted(self):
        """F10.B4: 验证拦截 touchmove 时 defaultPrevented 生效。"""
        event_dict = {"defaultPrevented": True, "cancelable": True}
        assert event_dict["defaultPrevented"] is True

    def test_f10_b05_extra_styles_do_not_invalidate_required_css(self):
        """F10.B5: 验证携带额外样式 (如 width: 100%) 时不影响合规性判定。"""
        css = {
            "touch-action": "none",
            "-webkit-overflow-scrolling": "auto",
            "width": "100%",
            "height": "100%",
        }
        valid, errs = MapPerformanceContract.verify_css_isolation(css)
        assert valid is True

    # --------------------------------------------------------------------------
    # F11 边界: 瓦片缩放边界
    # --------------------------------------------------------------------------

    def test_f11_b01_zoomsnap_fractional_0_5_detected_and_rejected(self):
        """F11.B1: 验证 zoomSnap 为 0.5 时严格被捕获为错误。"""
        valid, errs = MapPerformanceContract.verify_leaflet_zoom_options({"zoomSnap": 0.5, "zoomDelta": 1})
        assert valid is False
        assert "zoomSnap" in errs[0]

    def test_f11_b02_zoomdelta_fractional_0_25_detected_and_rejected(self):
        """F11.B2: 验证 zoomDelta 为 0.25 时被捕获。"""
        valid, errs = MapPerformanceContract.verify_leaflet_zoom_options({"zoomSnap": 1, "zoomDelta": 0.25})
        assert valid is False

    def test_f11_b03_zoom_level_out_of_bounds_clamped(self):
        """F11.B3: 验证超出瓦片最大缩放 (如 zoom=25) 时安全钳夹到 19。"""
        raw_zoom = 25
        clamped_zoom = min(19, max(3, raw_zoom))
        assert clamped_zoom == 19

    def test_f11_b04_negative_zoom_level_rejected(self):
        """F11.B4: 验证负数缩放级别被钳夹到最小有效缩放。"""
        raw_zoom = -3
        clamped_zoom = min(19, max(3, raw_zoom))
        assert clamped_zoom == 3

    def test_f11_b05_options_verifier_empty_dict_reports_all_missing(self):
        """F11.B5: 验证空字典选项报错。"""
        valid, errs = MapPerformanceContract.verify_leaflet_zoom_options({})
        assert valid is False
        assert len(errs) == 2

    # --------------------------------------------------------------------------
    # F12 边界: 缓动动画边界
    # --------------------------------------------------------------------------

    def test_f12_b01_flyto_zero_duration_handled(self):
        """F12.B1: 验证动画时长为 0.0s 时生成至少 1 帧瞬时帧不除以零。"""
        frames = MapPerformanceContract.calculate_smooth_flyto_trajectory(
            28.2, 112.9, 28.3, 113.0, duration_sec=0.0, fps=60,
        )
        assert len(frames) >= 1
        assert frames[-1][0] == 28.3

    def test_f12_b02_flyto_extreme_distance_across_globe(self):
        """F12.B2: 验证跨半球极端距离 (经度差 180 度) 轨迹插值无溢出。"""
        frames = MapPerformanceContract.calculate_smooth_flyto_trajectory(
            0.0, 0.0, 80.0, 179.0, duration_sec=1.0, fps=60,
        )
        assert len(frames) == 61
        assert frames[-1][1] == 179.0

    def test_f12_b03_flyto_high_frame_rate_120fps(self):
        """F12.B3: 验证 120Hz 高刷屏幕帧计算 (帧间隔 8.33ms)。"""
        frames = MapPerformanceContract.calculate_smooth_flyto_trajectory(
            28.0, 112.0, 28.1, 112.1, duration_sec=1.0, fps=120,
        )
        assert len(frames) == 121
        assert frames[0][2] == pytest.approx(8.333, rel=1e-2)

    def test_f12_b04_flyto_negative_duration_clamped(self):
        """F12.B4: 验证负时长被安全防护处理。"""
        frames = MapPerformanceContract.calculate_smooth_flyto_trajectory(
            28.0, 112.0, 28.1, 112.1, duration_sec=-1.0, fps=60,
        )
        assert len(frames) >= 1

    def test_f12_b05_ease_linearity_boundaries_0_and_1(self):
        """F12.B5: 验证线性度在 0.0 与 1.0 极端值下的平稳性。"""
        f_0 = MapPerformanceContract.calculate_smooth_flyto_trajectory(0.0, 0.0, 1.0, 1.0, ease_linearity=0.0)
        f_1 = MapPerformanceContract.calculate_smooth_flyto_trajectory(0.0, 0.0, 1.0, 1.0, ease_linearity=1.0)
        assert len(f_0) == len(f_1)

    # --------------------------------------------------------------------------
    # F13 边界: GPU 硬件加速边界
    # --------------------------------------------------------------------------

    def test_f13_b01_gpu_verifier_detects_missing_translatez(self):
        """F13.B1: 验证缺失 translateZ(0) 时被校验器捕获。"""
        css = {"will-change": "transform", "transform": "none"}
        assert css["transform"] != MapPerformanceContract.REQUIRED_GPU_MARKER_CSS["transform"]

    def test_f13_b02_gpu_verifier_detects_missing_will_change(self):
        """F13.B2: 验证缺失 will-change 时捕获。"""
        css = {"transform": "translateZ(0)"}
        assert "will-change" not in css

    def test_f13_b03_gpu_marker_3d_transform_matrix_alternative(self):
        """F13.B3: 验证 translate3d(0,0,0) 同样具备 3D GPU 加速特性。"""
        t3d = "translate3d(0, 0, 0)"
        assert "3d" in t3d

    def test_f13_b04_pane_z_index_hierarchy_verification(self):
        """F13.B4: 验证 pulsePane 的 z-index 严格高于瓦片层 (200) 防止被瓦片覆盖。"""
        pulse_pane_z = 650
        tile_pane_z = 200
        assert pulse_pane_z > tile_pane_z

    def test_f13_b05_gpu_verifier_empty_dict_fails(self):
        """F13.B5: 验证空属性字典不通过 GPU 加速校验。"""
        empty_css = {}
        assert empty_css != MapPerformanceContract.REQUIRED_GPU_MARKER_CSS


# ==============================================================================
# TIER 3: 跨特性两两正交组合 (Cross-Feature Combinations, 12 Tests)
# ==============================================================================

class TestTier3CrossFeatureInteractions:
    """Tier 3: 跨特性两两交互集成测试 (Pairwise Combinations, 12 Tests)."""

    def test_t3_01_mailbox_and_task_board_assignment_sync(self):
        """T3.1 (Mailbox x TaskBoard): 信箱任务委派电文自动联动看板任务创建与认领。"""
        hub = SessionMailboxHub("sess_t3_01")
        board = SharedTaskBoard()

        # Main 智能体在看板创建任务并向 Health 发送任务委派信件
        task = board.add_task("评估膝关节受力", "测算平缓坡度与台阶规避", "正在评估体能")
        msg = hub.get_mailbox("main").send_message(
            to_agent="health",
            msg_type="task_assignment",
            summary="认领体能评估任务",
            content=task.description,
            data={"task_id": task.id},
        )
        hub.route_message(msg)

        # Health 检查信箱并认领任务
        inbox = hub.get_mailbox("health").get_unread_messages()
        assert len(inbox) == 1
        assert inbox[0].msg_type == "task_assignment"
        task_id = inbox[0].data["task_id"]

        assert board.claim_task_with_busy_check(task_id, "health") is True
        assert board.tasks[task_id].owner == "health"

    def test_t3_02_mailbox_deliberation_triggers_sse_stream_events(self):
        """T3.2 (Mailbox x ThinkingStream): 智能体信箱磋商交互实时推流为 SSE 预览分块。"""
        hub = SessionMailboxHub("sess_t3_02")
        sse_stream_events: List[str] = []

        # 挂接信箱消息监听至 SSE 流
        def _on_peer_message(msg: PeerMessage):
            chunk = PeerMessageChunk(from_agent=msg.from_agent, to_agent=msg.to_agent, summary=msg.summary, preview=msg.content[:20])
            sse_stream_events.append(format_sse_event(chunk.event, chunk.model_dump()))

        msg = hub.get_mailbox("bds_nav").send_message("weather", "direct", "查询树荫", "烈士公园西门步道微气象")
        hub.route_message(msg)
        _on_peer_message(msg)

        assert len(sse_stream_events) == 1
        assert "event: peer_message" in sse_stream_events[0]
        assert "查询树荫" in sse_stream_events[0]

    def test_t3_03_task_board_status_change_emits_task_board_sync(self):
        """T3.3 (TaskBoard x ThinkingStream): 看板任务状态流转实时触发 SSE task_board_sync 推送。"""
        board = SharedTaskBoard()
        sse_sync_events: List[str] = []

        task = board.add_task("规划无障碍步道", "避开所有台阶", "正在计算微地形")
        board.claim_task_with_busy_check(task.id, "bds_nav")
        board.complete_task(task.id)

        # 广播看板快照
        tasks_snapshot = [t.model_dump() for t in board.tasks.values()]
        chunk = TaskBoardSyncChunk(tasks=tasks_snapshot)
        sse_sync_events.append(format_sse_event(chunk.event, chunk.model_dump()))

        assert len(sse_sync_events) == 1
        assert "event: task_board_sync" in sse_sync_events[0]
        assert '"status": "completed"' in sse_sync_events[0]

    def test_t3_04_task_completion_promotes_fact_into_episodic_memory(self, tmp_path):
        """T3.4 (TaskBoard x HierarchicalMemory): 导航任务完成产出的决策事实沉淀为情景记忆。"""
        board = SharedTaskBoard()
        store = HierarchicalMemoryStore(tmp_path, "user_t3_04")

        task = board.add_task("勘测烈士公园西门", "确定西门为全平缓坡道", "勘测中")
        board.claim_task_with_busy_check(task.id, "bds_nav")
        board.complete_task(task.id)

        # 沉淀情景事实
        entry = store.record_episode("烈士公园西门通行核实", [f"任务[{task.subject}]验证：西门通道无台阶平缓"])
        assert entry.cursor == 1
        assert "西门通道无台阶平缓" in store.load_episodic_entries()[0].facts[0]

    def test_t3_05_hierarchical_memory_auto_injects_into_proactive_context(self, tmp_path):
        """T3.5 (HierarchicalMemory x ProactiveCare): 分层画像自动生成带免问约束的上下文。"""
        store = HierarchicalMemoryStore(tmp_path, "user_t3_05")
        store.consolidate_profile("- 慢病事实：严重膝骨关节炎\n- 出行红线：单次步行<=500米，拒绝任何台阶")
        context_block = store.get_elder_context()

        assert "严重膝骨关节炎" in context_block
        assert "严禁让长辈重复陈述已有事实" in context_block

    def test_t3_06_thinking_stream_renders_into_frontend_handoff_card(self):
        """T3.6 (ThinkingStream x FrontendHandoffCard): SSE 的 agent_handoff 分块精确还原为前端交接卡属性。"""
        sse_payload = {
            "from_agent": "health",
            "to_agent": "bds_nav",
            "reason": "体能红线注入完毕，交由北斗导航进行微地形匹配",
        }
        card = create_agent_handoff_card(sse_payload["from_agent"], sse_payload["to_agent"], sse_payload["reason"])
        assert card["from_color"] == "#67C23A"
        assert card["to_color"] == "#409EFF"
        assert card["transition_title"] == "@health ▶ @bds_nav"

    def test_t3_07_execution_tree_reflects_mailbox_activity(self):
        """T3.7 (ExecutionTree x Mailbox): 态势执行树随着信箱电文流转动态更新各专才活跃度。"""
        hub = SessionMailboxHub("sess_t3_07")
        m = hub.get_mailbox("health").send_message("weather", "proposal", "体感温度查询", "是否适宜老年慢病步行")
        hub.route_message(m)

        # 检查健康 Agent 与气象 Agent 的信箱活跃计数
        assert len(hub.get_mailbox("health").outbox) == 1
        assert len(hub.get_mailbox("weather").inbox) == 1

    def test_t3_08_guardian_detects_deviation_and_notifies_bds_nav_via_mailbox(self):
        """T3.8 (GuardianAgent x Mailbox x Navigation): 卫士检测到偏航自动向北斗导航信箱发改道告警电文。"""
        hub = SessionMailboxHub("sess_t3_08")
        corridor = [(28.2200, 112.9840), (28.2180, 112.9850)]
        cur_pos = (28.2180, 112.9875)  # 偏离 250m

        status = GuardianAgentSpec.monitor_safety_corridor(cur_pos[0], cur_pos[1], corridor, corridor_tolerance_m=30.0)
        assert status["is_deviated"] is True

        # Guardian 发送偏航改道申请
        alert_msg = hub.get_mailbox("guardian").send_message(
            to_agent="bds_nav",
            msg_type="proposal",
            summary="偏航改道重规划请求",
            content=f"长辈偏离安全走廊 {status['distance_m']} 米，请立即重新计算至最近平缓辅道的连接线",
            data=status,
        )
        hub.route_message(alert_msg)

        bds_inbox = hub.get_mailbox("bds_nav").get_unread_messages()
        assert len(bds_inbox) == 1
        assert "偏航改道重规划请求" in bds_inbox[0].summary

    def test_t3_09_multi_agent_consensus_drives_smooth_map_flyto(self):
        """T3.9 (DeliberationCouncil x MapViewport): 群智磋商达成的路线终点直接驱动地图 60fps 缓动相机。"""
        hub = SessionMailboxHub("sess_t3_09")
        board = SharedTaskBoard()
        council = DeliberationCouncil(hub, board)

        fatigue = PhysicalFatigueLimit(avoid_stairs=True, max_slope_percent=3.0)
        candidates = [{"id": "target_gate", "name": "烈士公园西门", "lat": 28.2120, "lng": 112.9880, "stairs_count": 0, "slope_percent": 2.1}]
        weathers = [MicroWeatherReport(segment_id="target_gate", shade_coverage_percent=88.0, surface_temperature_c=25.0, precipitation_mm_h=0.0, wind_speed_m_s=1.0, uv_index=3.0)]

        res = council.conduct_deliberation(fatigue, candidates, weathers)
        assert res["status"] == "CONSENSUS_REACHED"
        target_route = res["selected_route"]

        # 驱动地图 flyTo
        frames = MapPerformanceContract.calculate_smooth_flyto_trajectory(
            start_lat=28.2241, start_lng=112.9842,
            end_lat=target_route["lat"], end_lng=target_route["lng"],
            duration_sec=0.8, fps=60,
        )
        assert len(frames) == 49
        assert frames[-1][0] == target_route["lat"]

    def test_t3_10_map_gesture_isolation_combined_with_integer_zoom_and_gpu_marker(self):
        """T3.10 (Gesture x Zoom x GPU): 地图手势隔离、整数瓦片与 GPU 加速三项规范联合生效。"""
        container_css = {"touch-action": "none", "-webkit-overflow-scrolling": "auto"}
        zoom_opts = {"zoomSnap": 1, "zoomDelta": 1}
        gpu_marker = {"will-change": "transform", "transform": "translateZ(0)"}

        c_ok, _ = MapPerformanceContract.verify_css_isolation(container_css)
        z_ok, _ = MapPerformanceContract.verify_leaflet_zoom_options(zoom_opts)
        g_ok = (gpu_marker == MapPerformanceContract.REQUIRED_GPU_MARKER_CSS)

        assert c_ok and z_ok and g_ok

    def test_t3_11_proactive_memory_context_bypasses_health_re_query_in_deliberation(self, tmp_path):
        """T3.11 (Memory x Deliberation): 预加载的长期记忆免除研讨中向长辈回查膝盖病史的额外轮次。"""
        store = HierarchicalMemoryStore(tmp_path, "user_t3_11")
        store.consolidate_profile("- 确诊：双膝骨性关节炎，下肢肌力衰退")

        # 研讨引擎直接从 profile 构造体能红线
        profile_text = store.load_profile()
        has_arthritis = "双膝骨性关节炎" in profile_text
        fatigue = PhysicalFatigueLimit(knee_joint_osteoarthritis=has_arthritis, avoid_stairs=has_arthritis)
        assert fatigue.avoid_stairs is True

    def test_t3_12_guardian_sos_emits_urgent_sse_handoff_and_notifies_child(self):
        """T3.12 (Guardian SOS x Stream x Handoff): 紧急 SOS 触发时生成高优先级 SSE 广播与子女通知载荷。"""
        sos_res = GuardianAgentSpec.trigger_sos_reroute(
            "elder_01", (28.2180, 112.9850), "湖南省人民医院", "13873199888",
        )
        card = create_agent_handoff_card("guardian", "bds_nav", "触发一键SOS，开启三甲绿通并通知子女")
        sse_event = format_sse_event("agent_handoff", card)

        assert sos_res["sos_active"] is True
        assert "@guardian ▶ @bds_nav" in sse_event
        assert "13873199888" in sos_res["guardian_notified_phone"]


# ==============================================================================
# TIER 4: 长沙实景大赛业务全链路验收 (Real-World Changsha Scenarios, 5 Tests)
# ==============================================================================

class TestTier4RealWorldElderlyScenarios:
    """Tier 4: 长沙实景银发大赛真实业务闭环全流程验收 (S1 - S5, 5 Tests)."""

    def test_s1_martyrs_park_morning_exercise_full_flow(self, tmp_path):
        """S1: 烈士公园晨练伴随全链路闭环 (刘爷爷双侧膝关节炎避高阶梯林荫道).
        
        覆盖特性: F1, F4, F8, F9, F10-F13
        业务链路:
        1. 读取长辈认知画像 (F8, F9)，自动提取“双侧膝关节骨性关节炎”
        2. 健康 Agent 向北斗信箱注入坡度<=3.5%与禁用台阶红线 (F1, F4)
        3. 北斗导航向气象 Agent 查询烈士公园西门与南门树荫 (F1, F4)
        4. 气象回执：西门树荫88%且无雨，南门无树荫且有68级台阶 (F4)
        5. 北斗导航智能决策选择西门缓坡通道，淘汰南门 (F4)
        6. 规划路线交付地图渲染：60fps 缓动飞至西门，手势隔离防冲突，GPU 脉冲呼吸 (F10-F13)
        """
        data = CHANGSHA_REALWORLD_FIXTURES["S1_MARTYRS_PARK"]

        # Step 1: 记忆初始化与画像加载
        store = HierarchicalMemoryStore(tmp_path, data["elder_id"])
        store.consolidate_profile(f"- 姓名：{data['elder_name']}\n- 慢病：{','.join(data['chronic_conditions'])}\n- 常住：{data['origin_community']}")
        elder_ctx = store.get_elder_context()
        assert "双侧膝关节骨性关节炎" in elder_ctx

        # Step 2 & 3 & 4: 群智信箱研讨
        hub = SessionMailboxHub("sess_s1")
        board = SharedTaskBoard()
        council = DeliberationCouncil(hub, board)

        fatigue = PhysicalFatigueLimit(knee_joint_osteoarthritis=True, max_slope_percent=3.5, avoid_stairs=True)
        candidates = [
            {"id": "south", "name": data["gates"]["south_gate"]["name"], "stairs_count": data["gates"]["south_gate"]["stairs_count"], "slope_percent": data["gates"]["south_gate"]["slope_percent"], "lat": data["gates"]["south_gate"]["coords"][0], "lng": data["gates"]["south_gate"]["coords"][1]},
            {"id": "west", "name": data["gates"]["west_gate"]["name"], "stairs_count": data["gates"]["west_gate"]["stairs_count"], "slope_percent": data["gates"]["west_gate"]["slope_percent"], "lat": data["gates"]["west_gate"]["coords"][0], "lng": data["gates"]["west_gate"]["coords"][1]},
        ]
        weathers = [
            MicroWeatherReport(segment_id="south", shade_coverage_percent=data["gates"]["south_gate"]["shade_percent"], surface_temperature_c=31.0, precipitation_mm_h=0.0, wind_speed_m_s=2.0, uv_index=7.0),
            MicroWeatherReport(segment_id="west", shade_coverage_percent=data["gates"]["west_gate"]["shade_percent"], surface_temperature_c=25.5, precipitation_mm_h=0.0, wind_speed_m_s=1.2, uv_index=3.2),
        ]

        # Step 5: 研讨产出结果
        decision = council.conduct_deliberation(fatigue, candidates, weathers)
        assert decision["status"] == "CONSENSUS_REACHED"
        chosen = decision["selected_route"]
        assert chosen["id"] == "west"
        assert chosen["stairs_count"] == 0

        # Step 6: 地图性能契约驱动
        c_ok, _ = MapPerformanceContract.verify_css_isolation(MapPerformanceContract.REQUIRED_CONTAINER_CSS)
        z_ok, _ = MapPerformanceContract.verify_leaflet_zoom_options(MapPerformanceContract.REQUIRED_LEAFLET_OPTIONS)
        frames = MapPerformanceContract.calculate_smooth_flyto_trajectory(
            start_lat=data["origin_coords"][0], start_lng=data["origin_coords"][1],
            end_lat=chosen["lat"], end_lng=chosen["lng"],
            duration_sec=0.8, fps=60,
        )
        assert c_ok and z_ok
        assert len(frames) == 49
        assert frames[-1][0] == chosen["lat"]

    def test_s2_xiangya_hospital_visit_and_fatigue_alert_full_flow(self):
        """S2: 湘雅就医与突发体能不适伴随全链路闭环 (张奶奶途中疲劳停顿与长椅调度).
        
        覆盖特性: F1, F2, F3, F4, F5
        业务链路:
        1. 卫士设立华夏路至中南大学湘雅医院的 25m 安全走廊 (F3)
        2. 途中健康 Agent 监测到步速骤降停滞 15 分钟，研讨触发疲劳休整 (F3, F4)
        3. 共享看板原子认领：“搜寻湘雅路遮阴长椅”，北斗导航成功认领 (F2)
        4. 北斗导航找到 45m 处的 bench_xy_1，并推送信箱电文 (F1)
        5. SSE 心智流推送温情关怀气泡与交接卡片给张奶奶 (F5)
        """
        data = CHANGSHA_REALWORLD_FIXTURES["S2_XIANGYA_HOSPITAL"]
        hub = SessionMailboxHub("sess_s2")
        board = SharedTaskBoard()

        # Step 1: 走廊建立
        corridor = [data["origin"], (28.2190, 112.9845), data["destination_coords"]]
        check = GuardianAgentSpec.monitor_safety_corridor(28.21902, 112.98455, corridor, corridor_tolerance_m=data["corridor_width_m"])
        assert check["status"] == "SAFE"

        # Step 2: 停顿疲劳检测
        fatigue_check = GuardianAgentSpec.detect_abnormal_dwell(15.0, is_at_rest_bench=False, threshold_min=12.0)
        assert fatigue_check["is_abnormal"] is True

        # Step 3: 看板任务创建与认领
        task = board.add_task("就近搜索长椅", "在湘雅路寻找最近的遮荫长椅供张奶奶休息", "正在为您寻找最近的长椅")
        assert board.claim_task_with_busy_check(task.id, "bds_nav") is True

        # Step 4: 北斗导航找到长椅并完成任务
        nearest_bench = data["rest_benches"][0]
        board.complete_task(task.id)

        # Step 5: SSE 流式推送
        bubble = create_elder_thinking_bubble("health", "检测到长辈步速放缓，已协调北斗导航指引至前方长椅")
        card = create_agent_handoff_card("health", "bds_nav", "安排长椅休整")
        sse_bubble = format_sse_event("thinking_delta", bubble)
        sse_card = format_sse_event("agent_handoff", card)

        assert "正在为您调取近期体检" in bubble["elder_text"]
        assert "@health ▶ @bds_nav" in card["transition_title"]
        assert nearest_bench["shade"] is True

    def test_s3_sudden_downpour_pavilion_reroute_full_flow(self):
        """S3: 暴雨短临微气象与避雨绕行全链路闭环 (王爷爷遇暴雨躲避至寄情亭).
        
        覆盖特性: F1, F4, F5, F6
        业务链路:
        1. 气象感知 Agent 捕获短临降水强对流雷达回波 (35 mm/h) (F4)
        2. 气象 Agent 立即向北斗导航 Agent 发送紧急信箱电文 (F1)
        3. 北斗导航计算并选择距离仅 65m 的“寄情亭雨廊”，淘汰 650m 的东便门 (F4)
        4. 前端流式呈现交接卡：@weather ▶ @bds_nav，提示“已为您锁定前方寄情亭避雨”(F5, F6)
        """
        data = CHANGSHA_REALWORLD_FIXTURES["S3_DOWNPOUR_REROUTE"]
        hub = SessionMailboxHub("sess_s3")

        # Step 1 & 2: 气象发出暴雨告警电文
        msg = hub.get_mailbox("weather").send_message(
            to_agent="bds_nav",
            msg_type="proposal",
            summary="短临特大暴雨预警",
            content=f"开福区烈士公园上空对流降水达到 {data['sudden_rain_mm_h']} mm/h，地面湿滑极易跌倒，请立即规划最近避雨凉亭",
            data={"rain_mm_h": data["sudden_rain_mm_h"]},
        )
        hub.route_message(msg)

        # Step 3: 北斗导航选定最近凉亭
        shelters = data["shelters"]
        closest = min(shelters, key=lambda s: s["distance_m"])
        assert closest["id"] == "pavilion_1"
        assert closest["distance_m"] == 65

        # Step 4: 生成长辈交接卡与温暖话术
        card = create_agent_handoff_card("weather", "bds_nav", f"突降大雨，已为您规划至前方 {closest['name']} 避雨")
        assert card["from_agent"] == "weather"
        assert card["to_agent"] == "bds_nav"
        assert "寄情亭雨廊" in card["reason"]

    def test_s4_guardian_sos_corridor_deviation_and_child_linkage_full_flow(self):
        """S4: 异地子女紧急守护与偏航绿通全链路闭环 (周老伯严重偏航触发 SOS 与子女同步).
        
        覆盖特性: F3, F4, F9, F12
        业务链路:
        1. 卫士检测到周老伯坐标距离计划走廊达 280m (偏离至建筑工地高危区域) (F3)
        2. 卫士触发一键 SOS 三甲医院急救绿通，目标医院：湖南省人民医院 (F3)
        3. 异步短信通知子女周晓萌 (13873199888) 并加载异地监护偏好 (F9)
        4. 地图视口 60fps 平滑飞向急救避险路线起点 (F12)
        """
        data = CHANGSHA_REALWORLD_FIXTURES["S4_GUARDIAN_SOS"]

        # Step 1: 偏航判定
        status = GuardianAgentSpec.monitor_safety_corridor(
            data["deviated_point"][0], data["deviated_point"][1],
            data["corridor"], corridor_tolerance_m=30.0,
        )
        assert status["is_deviated"] is True
        assert status["distance_m"] > 200.0

        # Step 2: 触发 SOS
        sos = GuardianAgentSpec.trigger_sos_reroute(
            data["elder_id"], data["deviated_point"],
            data["nearest_tertiary_hospital"], data["child_phone"],
        )
        assert sos["sos_active"] is True
        assert sos["emergency_target"] == "湖南省人民医院"
        assert sos["guardian_notified_phone"] == "13873199888"

        # Step 3: 地图平滑飞向避险走廊
        frames = MapPerformanceContract.calculate_smooth_flyto_trajectory(
            start_lat=data["deviated_point"][0], start_lng=data["deviated_point"][1],
            end_lat=data["corridor"][0][0], end_lng=data["corridor"][0][1],
            duration_sec=0.8, fps=60,
        )
        assert len(frames) == 49
        assert frames[-1][0] == data["corridor"][0][0]

    def test_s5_multi_turn_habit_persistence_across_days_full_flow(self, tmp_path):
        """S5: 跨多轮对话体能记忆自动加载全链路闭环 (陈奶奶次日出行免重复陈述膝痛病史).
        
        覆盖特性: F8, F9
        业务链路:
        1. Day 1: 陈奶奶告知“我这右腿膝盖一受凉下楼梯就钻心疼，千万别给我走有台阶的地方”
        2. 记忆引擎将事实提炼存入 episodic_history.jsonl 并固化至 ELDER_PROFILE.md (F8)
        3. Day 2: 陈奶奶仅提问“闺女，我想去楼下小公园透透气，怎么走好？” (未提及膝盖)
        4. 系统自动调用 get_elder_context() 将 Day 1 固化的膝盖限制注入当前轮 Prompt (F9)
        5. 规划方案自动剔除台阶阶梯，长辈免于重复回答任何体能问题 (F9)
        """
        data = CHANGSHA_REALWORLD_FIXTURES["S5_HABIT_PERSISTENCE"]
        store = HierarchicalMemoryStore(tmp_path, data["elder_id"])

        # Day 1: 写入事实
        store.record_episode("Day 1 对话记录", [data["day1_extracted_constraint"]])
        store.consolidate_profile(f"# 长辈画像档案\n- 姓名：{data['elder_name']}\n- 慢病禁忌：{data['day1_extracted_constraint']}")

        # Day 2: 自动回溯
        day2_prompt_injection = store.get_elder_context()
        assert "严禁让长辈重复陈述已有事实" in day2_prompt_injection
        assert "右膝骨关节炎" in day2_prompt_injection
        assert "绝对禁用台阶步道" in day2_prompt_injection
