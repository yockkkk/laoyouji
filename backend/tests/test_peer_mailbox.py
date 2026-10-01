"""Milestone 1 Test Suite: Peer Mailbox, Shared Task Board & GuardianAgent.

Tests full peer-to-peer deliberation, broadcast, atomic task claiming,
DAG dependency resolution, safety corridor monitoring, and SOS emergency routing.
"""
from __future__ import annotations

import asyncio
import pytest
from pydantic import ValidationError

from app.agents.guardian_agent import (
    GuardianAgent,
    detect_abnormal_dwell,
    monitor_safety_corridor,
    trigger_sos_reroute,
)
from app.core.bus import EventBus, PRE_STEP
from app.core.context import TurnContext
from app.core.events import PEER_MESSAGE, TASK_BOARD_SYNC, durable_type
from app.core.mailbox import (
    AgentMailbox,
    PeerMessage,
    PeerMessageType,
    SessionMailboxHub,
    clear_session_mailbox_hub,
    get_session_mailbox_hub,
    install_mailbox_hook,
)
from app.core.session import StepRequest
from app.core.tasks import (
    BoardTask,
    ClaimTaskReason,
    SharedTaskBoard,
    TaskStatus,
)
from app.tools.peer_tools import (
    broadcast_teammate_message,
    read_teammate_inbox,
    send_teammate_message,
)


# ==============================================================================
# 1. PeerMessage Envelope & Validation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_peer_message_model_validation():
    """验证 PeerMessage 契约字段生成、序列化与校验规则."""
    msg = PeerMessage(
        from_agent="health",
        to_agent="bds_nav",
        msg_type=PeerMessageType.PROPOSAL.value,
        summary="注入膝关节受力红线",
        content="长辈右膝退变酸软，单程步数严控在500米内，坡度<=3%，禁止规划连续台阶",
        data={"max_slope_percent": 3.0, "avoid_stairs": True, "max_walking_distance_m": 500},
    )
    assert len(msg.id) == 8
    assert msg.from_agent == "health"
    assert msg.to_agent == "bds_nav"
    assert msg.msg_type == "proposal"
    assert msg.read is False
    assert msg.hop_count == 0
    assert "T" in msg.created_at

    payload = msg.to_sse_payload()
    assert payload["from"] == "health"
    assert payload["to"] == "bds_nav"
    assert payload["summary"] == "注入膝关节受力红线"
    assert "500米" in payload["preview"]
    assert payload["data"]["avoid_stairs"] is True

    prompt_ctx = msg.to_prompt_context()
    assert "@health" in prompt_ctx
    assert "max_slope_percent" in prompt_ctx

    # 验证缺失必填字段报错
    with pytest.raises(ValidationError):
        PeerMessage(from_agent="health")  # type: ignore


# ==============================================================================
# 2. AgentMailbox FIFO & State Management Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_agent_mailbox_fifo_and_read_state():
    """验证单个 AgentMailbox 的先进先出、状态标记与清空操作."""
    box = AgentMailbox(agent_name="bds_nav", session_id="sess_fifo_test")
    assert box.unread_count() == 0

    m1 = PeerMessage(from_agent="health", to_agent="bds_nav", summary="msg1", content="第一条")
    m2 = PeerMessage(from_agent="weather", to_agent="bds_nav", summary="msg2", content="第二条")
    m3 = PeerMessage(from_agent="guardian", to_agent="bds_nav", summary="msg3", content="第三条")

    await box.post(m1)
    await box.post(m2)
    await box.post(m3)

    assert box.unread_count() == 3

    # peek 不消耗未读
    peeked = box.peek()
    assert len(peeked) == 3
    assert box.unread_count() == 3
    assert peeked[0].summary == "msg1"

    # drain 排空并标记 read=True
    drained = box.drain()
    assert len(drained) == 3
    assert [d.summary for d in drained] == ["msg1", "msg2", "msg3"]
    assert all(d.read for d in drained)
    assert box.unread_count() == 0

    # 历史记录仍可查
    history = box.get_history()
    assert len(history) == 3

    # 清空
    box.clear()
    assert len(box.get_history()) == 0
    assert box.unread_count() == 0


# ==============================================================================
# 3. SessionMailboxHub P2P Routing Isolation & Broadcast Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_mailbox_hub_p2p_routing_isolation():
    """验证信箱中枢点对点消息的绝对隔离性（零串味）."""
    hub = SessionMailboxHub(session_id="sess_isolation_test")

    # health 向 bds_nav 发送电文
    msg = PeerMessage(
        from_agent="health",
        to_agent="bds_nav",
        summary="关节受力约束",
        content="避开台阶与陡坡",
    )
    await hub.send(msg, emit_sse=False)

    assert hub.get_unread_count("bds_nav") == 1
    assert hub.get_unread_count("health") == 0
    assert hub.get_unread_count("weather") == 0
    assert hub.get_unread_count("guardian") == 0
    assert hub.get_unread_count("main") == 0

    # 作用域后缀自动剥离 (bds_nav#1 路由到 bds_nav)
    msg_sub = PeerMessage(
        from_agent="weather#2",
        to_agent="bds_nav#1",
        summary="微气候提示",
        content="林荫充足",
    )
    await hub.send(msg_sub, emit_sse=False)
    assert hub.get_unread_count("bds_nav") == 2


@pytest.mark.asyncio
async def test_mailbox_hub_broadcast_reach():
    """验证广播消息投递给所有其他已知成员，发送者排除自身."""
    hub = SessionMailboxHub(session_id="sess_broadcast_test")

    # guardian 发起紧急安全预警广播
    alert = PeerMessage(
        from_agent="guardian",
        to_agent="*",
        msg_type=PeerMessageType.BROADCAST.value,
        summary="安全警报",
        content="检测到偏航异常",
    )
    await hub.send(alert, emit_sse=False)

    # 验证团队已知成员全部收件
    assert hub.get_unread_count("guardian") == 0  # 发送者不自收
    assert hub.get_unread_count("main") == 1
    assert hub.get_unread_count("health") == 1
    assert hub.get_unread_count("bds_nav") == 1
    assert hub.get_unread_count("weather") == 1


@pytest.mark.asyncio
async def test_mailbox_deliberation_hop_limit():
    """验证最大跳数限制 (MAX_DELIBERATION_HOPS = 3)，防止死循环中继."""
    hub = SessionMailboxHub(session_id="sess_hop_test")

    msg = PeerMessage(
        from_agent="health",
        to_agent="bds_nav",
        summary="磋商电文",
        content="环路测试",
        hop_count=4,  # 已超过限制
    )
    await hub.send(msg, emit_sse=False)
    # 应被拦截，不进收件箱
    assert hub.get_unread_count("bds_nav") == 0


# ==============================================================================
# 4. Multi-Agent Deliberation Chains
# ==============================================================================

@pytest.mark.asyncio
async def test_deliberation_health_to_bds_nav_constraint_injection(ctx, elder):
    """研讨链 1: HealthAgent 诊断膝关节退行性病变 -> 注入约束 -> BdsNavAgent 规划零台阶低坡路线 -> ACK."""
    session = await ctx.event_log.create_session(elder["id"], "体能导航协同")
    hub = get_session_mailbox_hub(session["id"])

    # 1. HealthAgent 注入慢病体能约束
    proposal = PeerMessage(
        from_agent="health",
        to_agent="bds_nav",
        msg_type=PeerMessageType.PROPOSAL.value,
        summary="注入膝关节受力红线",
        content="长辈右膝退变酸软，单程步数严控在500米内，坡度<=3.5%，严禁规划连续台阶",
        data={
            "constraint_type": "physical_fatigue_limit",
            "condition": "退行性膝关节炎",
            "max_slope_percent": 3.5,
            "avoid_stairs": True,
            "max_walking_distance_m": 500,
        },
    )
    await hub.send(proposal, emit_sse=False)

    # 2. BdsNavAgent 从信箱提取约束
    bds_inbox = hub.drain("bds_nav")
    assert len(bds_inbox) == 1
    received = bds_inbox[0]
    assert received.data["avoid_stairs"] is True
    assert received.data["max_slope_percent"] == 3.5

    # 3. BdsNavAgent 调用北斗适老路线规划工具
    t_bds = TurnContext(ctx=ctx, session_id=session["id"], user=elder, agent_id="bds_nav#1")
    from app.agents.bds_nav_agent import plan_bds_elder_route
    route_res = await plan_bds_elder_route(t_bds, {
        "destination": "烈士公园",
        "avoid_stairs": received.data["avoid_stairs"],
        "max_slope_percent": received.data["max_slope_percent"],
    })
    assert route_res["ok"] is True
    route_data = route_res["data"]["bds_route"]
    assert route_data["stairs_count"] == 0
    assert route_data["max_gradient_percent"] <= 3.5

    # 4. BdsNavAgent 回复 ACK
    ack = PeerMessage(
        from_agent="bds_nav",
        to_agent="health",
        msg_type=PeerMessageType.ACK.value,
        summary="适老路线规划完成并已满足红线",
        content=f"已规划零台阶路线，最大坡度 {route_data['max_gradient_percent']}%，步行距离 {route_data['total_distance_m']} 米",
        data={"ack_status": "accepted", "compliance": True},
        reply_to=received.id,
    )
    await hub.send(ack, emit_sse=False)

    # 5. HealthAgent 收到 ACK
    health_inbox = hub.drain("health")
    assert len(health_inbox) == 1
    assert health_inbox[0].data["ack_status"] == "accepted"
    clear_session_mailbox_hub(session["id"])


@pytest.mark.asyncio
async def test_deliberation_bds_nav_to_weather_shade_query(ctx, elder):
    """研讨链 2: BdsNavAgent 发起微地形多选段 -> WeatherAgent 测算林荫覆盖度与体感 -> 锁定高荫舒适段."""
    session = await ctx.event_log.create_session(elder["id"], "微气候协同")
    hub = get_session_mailbox_hub(session["id"])

    # 1. BdsNavAgent 向 WeatherAgent 咨询林荫舒适度
    query = PeerMessage(
        from_agent="bds_nav",
        to_agent="weather",
        msg_type=PeerMessageType.PROPOSAL.value,
        summary="微气候林荫度评估",
        content="请评估烈士公园东门林荫绿道与西门主干道的遮阳与热应激指标",
        data={
            "destination": "烈士公园东门",
            "candidate_segments": [
                {"name": "烈士公园东门绿道", "type": "shaded"},
                {"name": "烈士公园西门大道", "type": "exposed"},
            ],
        },
    )
    await hub.send(query, emit_sse=False)

    weather_inbox = hub.drain("weather")
    assert len(weather_inbox) == 1

    # 2. WeatherAgent 执行 shade comfort 评估
    t_weather = TurnContext(ctx=ctx, session_id=session["id"], user=elder, agent_id="weather#1")
    from app.agents.weather_agent import get_shade_comfort_index
    shade_res = await get_shade_comfort_index(t_weather, {"destination": "烈士公园东门"})
    assert shade_res["ok"] is True
    shade_data = shade_res["data"]["shade_comfort"]
    assert shade_data["shade_coverage_percent"] >= 75
    assert shade_data["heat_stress_level"] == "LOW"

    # 3. WeatherAgent 回复建议
    recommendation = PeerMessage(
        from_agent="weather",
        to_agent="bds_nav",
        msg_type=PeerMessageType.ACK.value,
        summary="推荐烈士公园东门林荫道",
        content=f"东门绿道树荫覆盖率 {shade_data['shade_coverage_percent']}%，紫外线弱，体感清凉",
        data={
            "recommended_segment": "烈士公园东门绿道",
            "shade_coverage": shade_data["shade_coverage_percent"],
            "comfort_rating": shade_data["comfort_rating"],
        },
    )
    await hub.send(recommendation, emit_sse=False)

    bds_inbox = hub.drain("bds_nav")
    assert len(bds_inbox) == 1
    assert bds_inbox[0].data["recommended_segment"] == "烈士公园东门绿道"
    clear_session_mailbox_hub(session["id"])


@pytest.mark.asyncio
async def test_deliberation_guardian_to_main_corridor_clearance(ctx, elder):
    """研讨链 3: GuardianAgent 研判规划走廊安全性 -> 发送放行电文给 MainAgent."""
    session = await ctx.event_log.create_session(elder["id"], "安全放行研讨")
    hub = get_session_mailbox_hub(session["id"])

    t_guardian = TurnContext(ctx=ctx, session_id=session["id"], user=elder, agent_id="guardian#1")
    # 正常走廊坐标监控
    corridor_eval = await monitor_safety_corridor(t_guardian, {
        "current_coords": [112.9862, 28.2154],
        "corridor": [(112.9862, 28.2154), (112.9895, 28.2141)],
        "tolerance_m": 80.0,
    })
    assert corridor_eval["ok"] is True
    assert corridor_eval["data"]["corridor_status"]["is_safe"] is True

    # 发送放行电文给 main
    clearance = PeerMessage(
        from_agent="guardian",
        to_agent="main",
        msg_type=PeerMessageType.DIRECT.value,
        summary="北斗安全走廊校验通过",
        content="航迹坡度平缓、休息长椅充足、无盲区与涉诈风险点，准予向老人出具护航方案",
        data={"is_cleared": True, "risk_level": "LOW"},
    )
    await hub.send(clearance, emit_sse=False)

    main_inbox = hub.drain("main")
    assert len(main_inbox) == 1
    assert main_inbox[0].data["is_cleared"] is True
    clear_session_mailbox_hub(session["id"])


@pytest.mark.asyncio
async def test_deliberation_guardian_to_main_emergency_sos(ctx, elder):
    """研讨链 4: GuardianAgent 捕捉突发急症/跌倒求救 -> 广播急救走廊与三甲医院直连."""
    session = await ctx.event_log.create_session(elder["id"], "突发急救响应")
    hub = get_session_mailbox_hub(session["id"])

    t_guardian = TurnContext(ctx=ctx, session_id=session["id"], user=elder, agent_id="guardian#1")
    sos_res = await trigger_sos_reroute(t_guardian, {
        "current_coords": [112.9862, 28.2154],
        "elder_name": elder["name"],
        "condition": "突发胸闷跌倒",
    })
    assert sos_res["ok"] is True
    assert "emergency_sos" in sos_res["data"]
    hosp = sos_res["data"]["emergency_sos"]["nearest_hospital"]
    assert "人民医院" in hosp["name"] or "湘雅" in hosp["name"]

    # 广播紧急救助
    sos_broadcast = PeerMessage(
        from_agent="guardian",
        to_agent="*",
        msg_type=PeerMessageType.EMERGENCY.value,
        summary="突发急救SOS已激活",
        content=f"已锁定{elder['name']}位置并连通{hosp['name']}急救通道",
        data=sos_res["data"]["emergency_sos"],
    )
    await hub.send(sos_broadcast, emit_sse=False)

    # 验证 main 收到最高等级应急通知
    main_inbox = hub.drain("main")
    assert len(main_inbox) == 1
    assert main_inbox[0].msg_type == "emergency"
    assert main_inbox[0].data["nearest_hospital"]["name"] == hosp["name"]
    clear_session_mailbox_hub(session["id"])


# ==============================================================================
# 5. Shared Task Board Tests (Monotonic ID, Atomic Claim, DAG Dependency)
# ==============================================================================

@pytest.mark.asyncio
async def test_shared_task_board_monotonic_id_and_transitions():
    """验证任务看板单调自增 ID 发生器与状态机三态流转."""
    board = SharedTaskBoard("test_board_1")
    assert board.highwatermark == 0

    t1 = await board.add_task(subject="体能初筛", description="评估膝关节耐受")
    t2 = await board.add_task(subject="微气候探查", description="测算遮阳指数")
    t3 = await board.add_task(subject="北斗路径计算", description="规避台阶与陡坡")

    assert t1.id == "1"
    assert t2.id == "2"
    assert t3.id == "3"
    assert board.highwatermark == 3

    assert board.get_task("1") is not None
    assert board.get_task("99") is None

    # 状态转换
    assert t1.status == TaskStatus.PENDING.value
    t1_claimed = await board.claim_task_with_busy_check("1", "health")
    assert t1_claimed.success is True
    assert board.get_task("1").status == TaskStatus.IN_PROGRESS.value

    comp_task, unblocked = await board.complete_task("1", {"result": "体能良好"})
    assert comp_task.status == TaskStatus.COMPLETED.value
    assert comp_task.metadata["result"] == "体能良好"


@pytest.mark.asyncio
async def test_shared_task_board_atomic_claiming_with_busy_check():
    """验证原子抢占与繁忙互斥 (Claude Code claimTaskWithBusyCheck 对齐)."""
    board = SharedTaskBoard("test_board_2")

    t1 = await board.add_task(subject="任务1")
    t2 = await board.add_task(subject="任务2")

    # 1. agent_a 认领任务 1
    res1 = await board.claim_task_with_busy_check(t1.id, claimant_agent_id="health")
    assert res1.success is True
    assert res1.reason == ClaimTaskReason.SUCCESS.value

    # 2. agent_b 尝试重复认领任务 1 -> ALREADY_CLAIMED
    res2 = await board.claim_task_with_busy_check(t1.id, claimant_agent_id="bds_nav")
    assert res2.success is False
    assert res2.reason == ClaimTaskReason.ALREADY_CLAIMED.value

    # 3. agent_a 试图在持有任务 1 时继续认领任务 2 -> AGENT_BUSY
    res3 = await board.claim_task_with_busy_check(t2.id, claimant_agent_id="health", check_agent_busy=True)
    assert res3.success is False
    assert res3.reason == ClaimTaskReason.AGENT_BUSY.value
    assert res3.busy_with_tasks == [t1.id]

    # 4. agent_a 完成任务 1 后，再次认领任务 2 -> 成功
    await board.complete_task(t1.id)
    res4 = await board.claim_task_with_busy_check(t2.id, claimant_agent_id="health", check_agent_busy=True)
    assert res4.success is True
    assert res4.reason == ClaimTaskReason.SUCCESS.value


@pytest.mark.asyncio
async def test_shared_task_board_dependency_blocking():
    """验证 DAG 依赖阻断与前置完成后的级联解锁."""
    board = SharedTaskBoard("test_board_3")

    # t1: 体能红线; t2: 遮阳指数; t3: 航迹规划 (依赖 t1 与 t2)
    t1 = await board.add_task(subject="体能红线")
    t2 = await board.add_task(subject="遮阳指数")
    t3 = await board.add_task(subject="综合航迹规划", blocked_by=[t1.id, t2.id])

    # 双向索引验证
    assert board.get_task(t1.id).blocks == [t3.id]
    assert board.get_task(t2.id).blocks == [t3.id]
    assert set(board.get_task(t3.id).blocked_by) == {t1.id, t2.id}

    # t3 当前不可认领 (BLOCKED)
    claim_blocked = await board.claim_task_with_busy_check(t3.id, "bds_nav")
    assert claim_blocked.success is False
    assert claim_blocked.reason == ClaimTaskReason.BLOCKED.value
    assert set(claim_blocked.blocked_by_tasks) == {t1.id, t2.id}

    # 完成 t1，t3 依然受 t2 阻塞
    _, unblocked_1 = await board.complete_task(t1.id)
    assert unblocked_1 == []

    # 完成 t2，t3 级联解锁并在 newly_unblocked 中产出
    _, unblocked_2 = await board.complete_task(t2.id)
    assert len(unblocked_2) == 1
    assert unblocked_2[0].id == t3.id

    # 此时 t3 可成功认领
    claim_ok = await board.claim_task_with_busy_check(t3.id, "bds_nav")
    assert claim_ok.success is True


@pytest.mark.asyncio
async def test_shared_task_board_circular_dependency_rejection():
    """验证环路依赖检测与防范."""
    board = SharedTaskBoard("test_board_4")

    t1 = await board.add_task(subject="任务1")
    t2 = await board.add_task(subject="任务2", blocked_by=[t1.id])

    # 尝试创建指向自己的环或互相阻断的环
    with pytest.raises(ValueError, match="Circular dependency"):
        await board.add_task(subject="任务3", blocks=[t1.id], blocked_by=[t2.id])


@pytest.mark.asyncio
async def test_shared_task_board_unassign_teammate_tasks():
    """验证智能体离线/崩溃时未闭环任务释放 (unassignTeammateTasks)."""
    board = SharedTaskBoard("test_board_5")

    t1 = await board.add_task(subject="任务1")
    t2 = await board.add_task(subject="任务2")

    await board.claim_task_with_busy_check(t1.id, "bds_nav")
    await board.complete_task(t1.id)  # 已完成

    # 认领任务 2
    await board.claim_task_with_busy_check(t2.id, "bds_nav")
    assert board.get_task(t2.id).status == TaskStatus.IN_PROGRESS.value

    # bds_nav 异常离线
    unassign_res = await board.unassign_teammate_tasks("bds_nav", reason="process_crash")
    assert unassign_res["count"] == 1
    assert unassign_res["unassigned_tasks"] == [t2.id]

    # t2 回退为 pending，可被其他智能体认领
    assert board.get_task(t2.id).status == TaskStatus.PENDING.value
    assert board.get_task(t2.id).owner is None


# ==============================================================================
# 6. Peer Tools End-to-End Execution Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_peer_tools_execution_via_turn_context(ctx, elder):
    """验证 send_teammate_message, broadcast_teammate_message, read_teammate_inbox 工具调用."""
    session = await ctx.event_log.create_session(elder["id"], "工具执行端到端")

    t_health = TurnContext(ctx=ctx, session_id=session["id"], user=elder, agent_id="health#1")
    # 1. health 发送给 bds_nav
    res_send = await send_teammate_message(t_health, {
        "to_agent": "bds_nav",
        "summary": "微地形限制",
        "content": "避开陡坡",
        "data": {"max_slope": 3.0},
    })
    assert res_send["ok"] is True
    assert "已成功向 @bds_nav 发送" in res_send["summary"]

    # 2. bds_nav 查收信箱
    t_bds = TurnContext(ctx=ctx, session_id=session["id"], user=elder, agent_id="bds_nav#1")
    res_read = await read_teammate_inbox(t_bds, {"clear_read": True})
    assert res_read["ok"] is True
    assert res_read["data"]["count"] == 1
    assert res_read["data"]["messages"][0]["from_agent"] == "health"

    # 3. 再次查收已为空
    res_empty = await read_teammate_inbox(t_bds, {"clear_read": True})
    assert res_empty["ok"] is True
    assert res_empty["data"]["count"] == 0

    # 4. weather 发起广播
    t_weather = TurnContext(ctx=ctx, session_id=session["id"], user=elder, agent_id="weather#1")
    res_bc = await broadcast_teammate_message(t_weather, {
        "summary": "天气预警",
        "content": "未来两小时有雷雨",
    })
    assert res_bc["ok"] is True
    assert "已向团队全体成员广播" in res_bc["summary"]

    # health 查收广播
    res_health_read = await read_teammate_inbox(t_health, {"clear_read": True})
    assert res_health_read["ok"] is True
    assert res_health_read["data"]["count"] == 1
    assert res_health_read["data"]["messages"][0]["summary"] == "天气预警"

    clear_session_mailbox_hub(session["id"])


# ==============================================================================
# 7. Mailbox PRE_STEP Passive Injection Hook Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_mailbox_pre_step_hook_prompt_injection(elder):
    """验证 install_mailbox_hook 在 PRE_STEP 瀑布中自动将被动未读电文注入大模型推理上下文."""
    bus = EventBus()
    disposer = install_mailbox_hook(bus)

    session_id = "sess_hook_test"
    hub = get_session_mailbox_hub(session_id)

    # 提前向 bds_nav 投递一条慢病约束电文
    await hub.send(PeerMessage(
        from_agent="health",
        to_agent="bds_nav",
        summary="关节极限",
        content="避开所有楼梯与超过3%的坡度",
        data={"avoid_stairs": True},
    ), emit_sse=False)

    class DummyAgent:
        name = "bds_nav"
        display_name = "北斗导航"
        system_prompt = "你是北斗导航智能体。"

    class DummyTurn:
        def __init__(self, sess_id):
            self.session_id = sess_id

    turn = DummyTurn(session_id)
    agent = DummyAgent()

    # 模拟 terminal/build 函数生成初始 messages
    async def mock_build(req: StepRequest) -> StepRequest:
        req.messages = [{"role": "system", "content": agent.system_prompt}]
        return req

    request = StepRequest(turn=turn, agent=agent, step=None, agent_turn=None)
    result = await bus.waterfall(PRE_STEP, request, mock_build)

    assert result.messages is not None
    sys_content = result.messages[0]["content"]
    assert "【来自队友智能体的协同信箱来信】" in sys_content
    assert "@health" in sys_content
    assert "避开所有楼梯与超过3%的坡度" in sys_content

    # 验证信箱已被自动排空，后续 step 不重复注入
    assert hub.get_unread_count("bds_nav") == 0

    disposer()
    clear_session_mailbox_hub(session_id)


# ==============================================================================
# 8. GuardianAgent Standalone Class & Safety Tools Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_guardian_agent_class_and_tools(ctx, elder):
    """验证 GuardianAgent 属性、专属工具与防偏航/长椅宽限研判."""
    guardian = GuardianAgent()
    assert guardian.name == "guardian"
    assert guardian.display_name == "亲情守护"
    assert guardian.color == "#9B5DE5"
    assert guardian.avatar == "🛡️"
    assert "monitor_safety_corridor" in guardian.tool_names
    assert "detect_abnormal_dwell" in guardian.tool_names
    assert "trigger_sos_reroute" in guardian.tool_names

    session = await ctx.event_log.create_session(elder["id"], "守护测试")
    t = TurnContext(ctx=ctx, session_id=session["id"], user=elder, agent_id="guardian#1")

    # 1. 走廊监控 - 正常在廊
    res_corridor_ok = await monitor_safety_corridor(t, {
        "current_coords": [112.9862, 28.2154],
        "corridor": [(112.9862, 28.2154), (112.9895, 28.2141)],
        "tolerance_m": 80.0,
    })
    assert res_corridor_ok["ok"] is True
    assert res_corridor_ok["data"]["corridor_status"]["status"] == "NORMAL"

    # 走廊监控 - 严重偏航 (>80m)
    res_corridor_off = await monitor_safety_corridor(t, {
        "current_coords": [112.9700, 28.2000],
        "corridor": [(112.9862, 28.2154), (112.9895, 28.2141)],
        "tolerance_m": 80.0,
    })
    assert res_corridor_off["ok"] is True
    assert res_corridor_off["data"]["corridor_status"]["status"] == "OFF_ROUTE"
    assert res_corridor_off["data"]["corridor_status"]["is_safe"] is False

    # 2. 滞留监控 - 运动状态
    res_moving = await detect_abnormal_dwell(t, {"speed_kmh": 2.5, "dwell_seconds": 600})
    assert res_moving["data"]["dwell_status"]["status"] == "MOVING"

    # 滞留监控 - 爱心长椅休整 20 分钟 (允许区间)
    # 使用已知长椅坐标 (112.9875, 28.2148)
    res_bench_safe = await detect_abnormal_dwell(t, {
        "current_coords": [112.9875, 28.2148],
        "dwell_seconds": 1200,  # 20 min < 25 min
        "speed_kmh": 0.0,
    })
    assert res_bench_safe["data"]["dwell_status"]["status"] == "RESTING_AT_BENCH"
    assert res_bench_safe["data"]["dwell_status"]["is_safe"] is True

    # 滞留监控 - 爱心长椅超长 30 分钟 (报警)
    res_bench_alert = await detect_abnormal_dwell(t, {
        "current_coords": [112.9875, 28.2148],
        "dwell_seconds": 1800,  # 30 min >= 25 min
        "speed_kmh": 0.0,
    })
    assert res_bench_alert["data"]["dwell_status"]["status"] == "ABNORMAL_DWELL"
    assert res_bench_alert["data"]["dwell_status"]["is_safe"] is False

    # 滞留监控 - 普通路段 16 分钟 (报警)
    res_non_bench_alert = await detect_abnormal_dwell(t, {
        "current_coords": [112.9500, 28.2000],
        "dwell_seconds": 960,  # 16 min >= 15 min
        "speed_kmh": 0.0,
    })
    assert res_non_bench_alert["data"]["dwell_status"]["status"] == "ABNORMAL_DWELL"
    assert res_non_bench_alert["data"]["dwell_status"]["is_safe"] is False


# ==============================================================================
# 9. Durable Event Logging & SSE Type Mapping Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_mailbox_write_behind_event_log_and_persistence(ctx, elder):
    """验证 peer_message 与 task_board_sync 持久化事件类型转换与 write-behind 日志."""
    assert durable_type("peer_message") == PEER_MESSAGE
    assert durable_type("task_board_sync") == TASK_BOARD_SYNC

    session = await ctx.event_log.create_session(elder["id"], "持久化测试")
    turn = TurnContext(ctx=ctx, session_id=session["id"], user=elder, agent_id="health#1")

    # emit peer_message
    msg = PeerMessage(
        from_agent="health",
        to_agent="bds_nav",
        summary="测试持久化",
        content="内容",
    )
    await turn.emit("peer_message", msg.to_sse_payload(), persist=True)

    # 轮次落库
    written = await ctx.event_log.flush(session["id"])
    assert written >= 1

    # 检验数据库/存储层事实日志
    rows = await ctx.repos.list("session_events", where={"session_id": session["id"]})
    peer_events = [r for r in rows if r["type"] == PEER_MESSAGE]
    assert len(peer_events) >= 1
    assert peer_events[0]["payload"]["summary"] == "测试持久化"
