"""Milestone 1 Adversarial Challenge: Guardian Security & Diamond DAG Stress Suite.

Empirical verification for:
1. Guardian Corridor Edge Cases:
   - Null island [0,0] & keyword coords (filtering & calibrating state)
   - Extreme coordinates (longitude > 180 / < -180, latitude > 90 / < -90)
   - Tolerance boundary: exactly 80.0m (safe / NORMAL) vs 80.1m (alert / OFF_ROUTE)
   - Malformed/missing coordinates handling
2. Dwell Detection Edge Cases:
   - Rest bench transition: 1499s (safe / RESTING_AT_BENCH) vs 1500s (alert / ABNORMAL_DWELL)
   - Rest bench distance threshold: 25.0m (is_at_bench=True) vs 25.1m (is_at_bench=False)
   - Non-bench location transition: 899s (safe) vs 900s (alert)
   - Speed boundary: 0.50 km/h (MOVING / safe) vs 0.49 km/h (stationary dwell check)
3. SharedTaskBoard Complex Multi-Root Diamond DAG:
   - 5-task diamond dependency (A -> B, C; B, C -> D; D -> E) resolution
   - Concurrent branch resolution order invariance (B then C, or C then B)
   - Multi-root confluence diamond (Root A & Root E joining downstream)
   - Circular dependency detection across diamond topologies
   - Agent busy contention & crash recovery during concurrent diamond execution
"""
from __future__ import annotations

import asyncio
import math
import pytest

from app.agents.guardian_agent import (
    GuardianAgent,
    KNOWN_REST_BENCHES,
    detect_abnormal_dwell,
    monitor_safety_corridor,
)
from app.core.tasks import (
    BoardTask,
    ClaimTaskReason,
    SharedTaskBoard,
    TaskStatus,
)
from app.providers.external.amap_service import (
    haversine_distance_m,
    min_distance_to_corridor_m,
)


# ==============================================================================
# 1. Guardian Corridor Edge Cases
# ==============================================================================

@pytest.mark.asyncio
async def test_corridor_null_island_filtering():
    """验证硬件初始化/北斗授时阶段 [0,0] 零岛坐标的识别与软性校准放行 (零误报)."""
    # 1. 数组形式 [0, 0]
    res_list = await monitor_safety_corridor(None, {"current_coords": [0.0, 0.0]})
    assert res_list["ok"] is True
    assert res_list["data"]["corridor_status"]["status"] == "CALIBRATING"
    assert res_list["data"]["corridor_status"]["is_safe"] is True
    assert res_list["data"]["corridor_status"]["distance_m"] == 0.0
    assert "北斗卫星授时校准中" in res_list["summary"]

    # 2. 整数零岛 [0, 0]
    res_int = await monitor_safety_corridor(None, {"current_coords": [0, 0]})
    assert res_int["data"]["corridor_status"]["status"] == "CALIBRATING"
    assert res_int["data"]["corridor_status"]["is_safe"] is True

    # 3. 命名参数形式 lng=0, lat=0
    res_named = await monitor_safety_corridor(None, {"lng": 0.0, "lat": 0.0})
    assert res_named["data"]["corridor_status"]["status"] == "CALIBRATING"
    assert res_named["data"]["corridor_status"]["is_safe"] is True


@pytest.mark.asyncio
async def test_corridor_extreme_and_overflow_coordinates():
    """验证极值与越界坐标 (经度 >180 / <-180, 纬度 >90 / <-90) 的鲁棒防崩溃与校准拦截."""
    test_cases = [
        ([180.0001, 28.214], "正经度微小越界"),
        ([-180.0001, 28.214], "负经度微小越界"),
        ([112.986, 90.0001], "正纬度微小越界"),
        ([112.986, -90.0001], "负纬度微小越界"),
        ([999.0, 28.214], "极端大经度"),
        ([-999.0, 28.214], "极端负经度"),
        ([112.986, 999.0], "极端大纬度"),
        ([112.986, -999.0], "极端负纬度"),
    ]
    for coords, desc in test_cases:
        res = await monitor_safety_corridor(None, {"current_coords": coords})
        assert res["ok"] is True, f"Failed on {desc}: {coords}"
        assert res["data"]["corridor_status"]["status"] == "CALIBRATING", f"Expected CALIBRATING for {desc}"
        assert res["data"]["corridor_status"]["is_safe"] is True

    # 合法极值边缘（如正好经度180或纬度90）不属于 CALIBRATING，但远离长沙航迹，应确认为 OFF_ROUTE
    res_valid_extreme = await monitor_safety_corridor(None, {"current_coords": [180.0, 89.999]})
    assert res_valid_extreme["ok"] is True
    assert res_valid_extreme["data"]["corridor_status"]["status"] == "OFF_ROUTE"
    assert res_valid_extreme["data"]["corridor_status"]["is_safe"] is False


@pytest.mark.asyncio
async def test_corridor_tolerance_boundary_exact_80m_vs_80_1m():
    """高精数学边界压力测试：验证 tolerance=80.0m 下 80.0m (放行) 与 80.1m (告警) 的绝对刚性判定."""
    # 建立一条水平航线（常数纬度 28.2100）
    base_lat = 28.2100
    base_lng_start = 112.9800
    base_lng_end = 112.9900
    corridor = [(base_lng_start, base_lat), (base_lng_end, base_lat)]

    # 1度纬度对应米数
    m_per_deg_lat = 6371000.0 * math.pi / 180.0

    # 构造距离航线垂直方向 (北向) 恰好 80.0 米与 80.1 米的测试点
    delta_lat_80_0 = 80.0 / m_per_deg_lat
    delta_lat_80_1 = 80.1 / m_per_deg_lat

    mid_lng = (base_lng_start + base_lng_end) / 2.0
    point_80_0 = [mid_lng, base_lat + delta_lat_80_0]
    point_80_1 = [mid_lng, base_lat + delta_lat_80_1]

    # 独立算子核验
    dist_80_0 = min_distance_to_corridor_m(tuple(point_80_0), corridor)
    dist_80_1 = min_distance_to_corridor_m(tuple(point_80_1), corridor)

    assert dist_80_0 <= 80.0
    assert dist_80_1 > 80.0

    # 执行 Guardian 工具调用
    res_80_0 = await monitor_safety_corridor(None, {
        "current_coords": point_80_0,
        "corridor": corridor,
        "tolerance_m": 80.0,
    })
    res_80_1 = await monitor_safety_corridor(None, {
        "current_coords": point_80_1,
        "corridor": corridor,
        "tolerance_m": 80.0,
    })

    # 80.0m -> NORMAL (在廊安全)
    assert res_80_0["ok"] is True
    assert res_80_0["data"]["corridor_status"]["status"] == "NORMAL"
    assert res_80_0["data"]["corridor_status"]["is_safe"] is True
    assert res_80_0["data"]["corridor_status"]["distance_to_corridor_m"] == 80.0

    # 80.1m -> OFF_ROUTE (偏航告警)
    assert res_80_1["ok"] is True
    assert res_80_1["data"]["corridor_status"]["status"] == "OFF_ROUTE"
    assert res_80_1["data"]["corridor_status"]["is_safe"] is False
    assert res_80_1["data"]["corridor_status"]["distance_to_corridor_m"] == 80.1


@pytest.mark.asyncio
async def test_corridor_malformed_inputs_handling():
    """验证走廊监控工具在缺失、畸形入参下的防崩溃兜底."""
    # 缺失坐标
    res_empty = await monitor_safety_corridor(None, {})
    assert res_empty["ok"] is False
    assert "缺少有效坐标" in res_empty["summary"]

    # 格式错误坐标
    res_bad_format = await monitor_safety_corridor(None, {"current_coords": [112.9]})
    assert res_bad_format["ok"] is False


# ==============================================================================
# 2. Dwell Detection Edge Cases
# ==============================================================================

@pytest.mark.asyncio
async def test_dwell_bench_critical_threshold_1499s_vs_1500s():
    """爱心长椅 25 分钟关怀阈值微秒级临界验证：1499s (放行) vs 1500s (告警)."""
    bench_coord = list(KNOWN_REST_BENCHES[0])  # (112.9875, 28.2148)

    # 1499s (24 分 59 秒) -> 处于关怀允许区间
    res_1499 = await detect_abnormal_dwell(None, {
        "current_coords": bench_coord,
        "dwell_seconds": 1499,
        "speed_kmh": 0.0,
    })
    status_1499 = res_1499["data"]["dwell_status"]
    assert status_1499["is_safe"] is True
    assert status_1499["status"] == "RESTING_AT_BENCH"
    assert status_1499["is_at_bench"] is True
    assert status_1499["alert_message"] is None

    # 1500s (正好 25 分 00 秒) -> 触发异常超时滞留
    res_1500 = await detect_abnormal_dwell(None, {
        "current_coords": bench_coord,
        "dwell_seconds": 1500,
        "speed_kmh": 0.0,
    })
    status_1500 = res_1500["data"]["dwell_status"]
    assert status_1500["is_safe"] is False
    assert status_1500["status"] == "ABNORMAL_DWELL"
    assert status_1500["is_at_bench"] is True
    assert status_1500["alert_message"] is not None
    assert "长椅处休整已达 25 分钟" in status_1500["alert_message"]

    # 1501s -> 持续告警
    res_1501 = await detect_abnormal_dwell(None, {
        "current_coords": bench_coord,
        "dwell_seconds": 1501,
        "speed_kmh": 0.0,
    })
    assert res_1501["data"]["dwell_status"]["status"] == "ABNORMAL_DWELL"
    assert res_1501["data"]["dwell_status"]["is_safe"] is False


@pytest.mark.asyncio
async def test_dwell_bench_proximity_boundary_25m_vs_25_1m():
    """验证爱心长椅 25 米辐射圈临界判定：25.0m (长椅豁免) vs 25.1m (常规区域)."""
    bench = KNOWN_REST_BENCHES[1]  # (112.9895, 28.2141)
    m_per_deg_lat = 6371000.0 * math.pi / 180.0

    # 构造距长椅垂直 25.0 米与 25.1 米的位置
    p_25_0 = [bench[0], bench[1] + 25.0 / m_per_deg_lat]
    p_25_1 = [bench[0], bench[1] + 25.1 / m_per_deg_lat]

    # 设停留时间为 1200 秒 (20 分钟):
    # - 若判定为长椅 (25m内)，享受 25min 豁免 -> RESTING_AT_BENCH (safe)
    # - 若判定为非长椅 (>25m)，执行 15min 门限 -> ABNORMAL_DWELL (unsafe)
    res_25_0 = await detect_abnormal_dwell(None, {
        "current_coords": p_25_0,
        "dwell_seconds": 1200,
        "speed_kmh": 0.0,
    })
    res_25_1 = await detect_abnormal_dwell(None, {
        "current_coords": p_25_1,
        "dwell_seconds": 1200,
        "speed_kmh": 0.0,
    })

    assert res_25_0["data"]["dwell_status"]["is_at_bench"] is True
    assert res_25_0["data"]["dwell_status"]["is_safe"] is True
    assert res_25_0["data"]["dwell_status"]["status"] == "RESTING_AT_BENCH"

    assert res_25_1["data"]["dwell_status"]["is_at_bench"] is False
    assert res_25_1["data"]["dwell_status"]["is_safe"] is False
    assert res_25_1["data"]["dwell_status"]["status"] == "ABNORMAL_DWELL"


@pytest.mark.asyncio
async def test_dwell_non_bench_threshold_899s_vs_900s():
    """非休整路段 15 分钟受困预警门限测试：899s (正常短暂停留) vs 900s (异常滞留告警)."""
    off_bench_coord = [112.9500, 28.2000]

    # 899s -> NORMAL_PAUSE
    res_899 = await detect_abnormal_dwell(None, {
        "current_coords": off_bench_coord,
        "dwell_seconds": 899,
        "speed_kmh": 0.0,
    })
    assert res_899["data"]["dwell_status"]["is_safe"] is True
    assert res_899["data"]["dwell_status"]["status"] == "NORMAL_PAUSE"

    # 900s -> ABNORMAL_DWELL
    res_900 = await detect_abnormal_dwell(None, {
        "current_coords": off_bench_coord,
        "dwell_seconds": 900,
        "speed_kmh": 0.0,
    })
    assert res_900["data"]["dwell_status"]["is_safe"] is False
    assert res_900["data"]["dwell_status"]["status"] == "ABNORMAL_DWELL"
    assert "非休整路段连续停留 15 分钟" in res_900["data"]["dwell_status"]["alert_message"]


@pytest.mark.asyncio
async def test_dwell_speed_threshold_boundary():
    """移动速度判定临界：speed >= 0.5 km/h 判定为行进中，即使 dwell_seconds 极高也豁免."""
    coord = [112.9500, 28.2000]

    # speed = 0.5 km/h -> MOVING
    res_moving = await detect_abnormal_dwell(None, {
        "current_coords": coord,
        "dwell_seconds": 2000,
        "speed_kmh": 0.50,
    })
    assert res_moving["data"]["dwell_status"]["status"] == "MOVING"
    assert res_moving["data"]["dwell_status"]["is_safe"] is True

    # speed = 0.49 km/h -> 判定为静止，应用 dwell_seconds 门限
    res_stopped = await detect_abnormal_dwell(None, {
        "current_coords": coord,
        "dwell_seconds": 2000,
        "speed_kmh": 0.49,
    })
    assert res_stopped["data"]["dwell_status"]["status"] == "ABNORMAL_DWELL"
    assert res_stopped["data"]["dwell_status"]["is_safe"] is False


# ==============================================================================
# 3. Complex Multi-Root DAG & Diamond Dependency Resolution in SharedTaskBoard
# ==============================================================================

@pytest.mark.asyncio
async def test_shared_task_board_5_task_diamond_resolution_forward():
    """5任务菱形依赖图正向解析验证 (A -> B, C; B, C -> D; D -> E).
    
    拓扑结构：
         [Task 1: A (体能红线初筛)]
               /            \\
    [Task 2: B (北斗平缓坡道)]  [Task 3: C (气象林荫舒适度)]
               \\            /
         [Task 4: D (适老双约束航迹合成)]
                     |
         [Task 5: E (全景护航报告向老人交付)]
    """
    board = SharedTaskBoard("diamond_board_fwd")

    t1 = await board.add_task(subject="Task A: 体能红线初筛")
    t2 = await board.add_task(subject="Task B: 北斗平缓坡道初筛", blocked_by=[t1.id])
    t3 = await board.add_task(subject="Task C: 气象林荫舒适度测算", blocked_by=[t1.id])
    t4 = await board.add_task(subject="Task D: 适老双约束航迹合成", blocked_by=[t2.id, t3.id])
    t5 = await board.add_task(subject="Task E: 交付全景护航报告", blocked_by=[t4.id])

    assert t1.id == "1" and t2.id == "2" and t3.id == "3" and t4.id == "4" and t5.id == "5"

    # 1. 初始状态：仅 Task 1 可执行
    ready = [t.id for t in board.get_ready_tasks()]
    assert ready == ["1"]

    # 试图抢跑认领 Task 4 或 Task 5 -> 明确 BLOCKED 拒绝
    claim_d_early = await board.claim_task_with_busy_check("4", "bds_nav")
    assert claim_d_early.success is False
    assert claim_d_early.reason == ClaimTaskReason.BLOCKED.value
    assert set(claim_d_early.blocked_by_tasks) == {"2", "3"}

    claim_e_early = await board.claim_task_with_busy_check("5", "main")
    assert claim_e_early.success is False
    assert claim_e_early.reason == ClaimTaskReason.BLOCKED.value
    assert claim_e_early.blocked_by_tasks == ["4"]

    # 2. Health 认领并完成 Task 1 -> B 和 C 同时解锁
    claim_a = await board.claim_task_with_busy_check("1", "health")
    assert claim_a.success is True
    _, unblocked_after_a = await board.complete_task("1")
    assert {t.id for t in unblocked_after_a} == {"2", "3"}
    assert {t.id for t in board.get_ready_tasks()} == {"2", "3"}

    # 3. 两个并发分支：先由 bds_nav 认领并完成 Task 2 (Task 3 仍待执行)
    claim_b = await board.claim_task_with_busy_check("2", "bds_nav")
    assert claim_b.success is True
    _, unblocked_after_b = await board.complete_task("2")
    # Task 4 仍受 Task 3 阻塞，因此 unblocked_after_b 必须为空！
    assert unblocked_after_b == []
    assert {t.id for t in board.get_ready_tasks()} == {"3"}

    # 此时 Task 4 依然不可认领，但 blocker 仅剩 Task 3
    claim_d_mid = await board.claim_task_with_busy_check("4", "guardian")
    assert claim_d_mid.success is False
    assert claim_d_mid.reason == ClaimTaskReason.BLOCKED.value
    assert claim_d_mid.blocked_by_tasks == ["3"]

    # 4. 由 weather 认领并完成 Task 3 -> Task 4 终于解锁
    claim_c = await board.claim_task_with_busy_check("3", "weather")
    assert claim_c.success is True
    _, unblocked_after_c = await board.complete_task("3")
    assert [t.id for t in unblocked_after_c] == ["4"]
    assert [t.id for t in board.get_ready_tasks()] == ["4"]

    # 5. 认领并完成汇聚节点 Task 4 -> Task 5 解锁
    claim_d = await board.claim_task_with_busy_check("4", "bds_nav")
    assert claim_d.success is True
    _, unblocked_after_d = await board.complete_task("4")
    assert [t.id for t in unblocked_after_d] == ["5"]
    assert [t.id for t in board.get_ready_tasks()] == ["5"]

    # 6. 完成汇聚汇尾 Task 5 -> 全看板闭环
    claim_e = await board.claim_task_with_busy_check("5", "main")
    assert claim_e.success is True
    _, unblocked_after_e = await board.complete_task("5")
    assert unblocked_after_e == []
    assert len(board.get_ready_tasks()) == 0

    # 校验所有 5 个任务状态全为 COMPLETED
    all_tasks = board.list_tasks()
    assert len(all_tasks) == 5
    assert all(t.status == TaskStatus.COMPLETED.value for t in all_tasks)


@pytest.mark.asyncio
async def test_shared_task_board_diamond_resolution_reverse_branch():
    """菱形依赖图分支执行顺序无关性测试：先完成 Task C 再完成 Task B，汇聚节点 D 行为一致."""
    board = SharedTaskBoard("diamond_board_rev")

    t1 = await board.add_task(subject="Task A")
    t2 = await board.add_task(subject="Task B", blocked_by=[t1.id])
    t3 = await board.add_task(subject="Task C", blocked_by=[t1.id])
    t4 = await board.add_task(subject="Task D", blocked_by=[t2.id, t3.id])

    await board.claim_task_with_busy_check(t1.id, "agent_a")
    await board.complete_task(t1.id)

    # 优先完成分支 C
    await board.claim_task_with_busy_check(t3.id, "agent_c")
    _, unb_c = await board.complete_task(t3.id)
    assert unb_c == []  # D 依然被 B 阻断

    # 校验 D 报告被 B 阻断
    check_d = await board.claim_task_with_busy_check(t4.id, "agent_d")
    assert check_d.blocked_by_tasks == [t2.id]

    # 后完成分支 B -> 触发 D 解锁
    await board.claim_task_with_busy_check(t2.id, "agent_b")
    _, unb_b = await board.complete_task(t2.id)
    assert len(unb_b) == 1
    assert unb_b[0].id == t4.id


@pytest.mark.asyncio
async def test_shared_task_board_multi_root_confluence_diamond():
    """复杂多根汇聚菱形图 (Multi-Root Confluence DAG)：2 个独立根任务 + 菱形分支汇聚.
    
    结构：
    [Root 1: Task 1 (健康体能)]             [Root 2: Task 5 (突发气象预警)]
            /            \\                               |
    [Task 2: 坡道初筛]   [Task 3: 绿道初筛]                |
            \\            /                               |
             \\          /                                |
        [Task 4: 紧急综合航迹避险 (依赖 2, 3, 以及 Root 5!)]
    """
    board = SharedTaskBoard("multiroot_diamond")

    t1 = await board.add_task(subject="Root 1: 健康体能红线")
    t2 = await board.add_task(subject="Task 2: 坡道初筛", blocked_by=[t1.id])
    t3 = await board.add_task(subject="Task 3: 绿道初筛", blocked_by=[t1.id])
    t4 = await board.add_task(subject="Task 4: 综合航迹合成", blocked_by=[t2.id, t3.id])
    # Root 2 (Task 5) 也将 Task 4 作为后继阻断对象
    t5 = await board.add_task(subject="Root 2: 突发气象预警", blocks=[t4.id])

    # 1. 验证初始并行的 2 个根节点就绪
    ready_roots = {t.id for t in board.get_ready_tasks()}
    assert ready_roots == {"1", "5"}

    # 2. 推进 Root 1 及其下游 (1 -> 2, 3 完成)
    await board.claim_task_with_busy_check(t1.id, "health")
    await board.complete_task(t1.id)

    await board.claim_task_with_busy_check(t2.id, "bds_1")
    await board.complete_task(t2.id)

    await board.claim_task_with_busy_check(t3.id, "bds_2")
    _, unb_3 = await board.complete_task(t3.id)
    # 即使 1, 2, 3 均已完成，Task 4 依然因 Root 2 (Task 5) 未完成而受阻！
    assert unb_3 == []
    claim_t4_blocked = await board.claim_task_with_busy_check(t4.id, "main")
    assert claim_t4_blocked.success is False
    assert claim_t4_blocked.blocked_by_tasks == ["5"]

    # 3. 推进 Root 2 (Task 5 完成) -> Task 4 最终解锁！
    await board.claim_task_with_busy_check(t5.id, "weather")
    _, unb_5 = await board.complete_task(t5.id)
    assert len(unb_5) == 1
    assert unb_5[0].id == t4.id

    # 4. Task 4 正常认领
    claim_t4_ok = await board.claim_task_with_busy_check(t4.id, "main")
    assert claim_t4_ok.success is True


@pytest.mark.asyncio
async def test_shared_task_board_diamond_cycle_rejections():
    """菱形图跨层回环依赖检测与防御."""
    board = SharedTaskBoard("diamond_cycle_test")

    t1 = await board.add_task(subject="Task A")
    t2 = await board.add_task(subject="Task B", blocked_by=[t1.id])
    t3 = await board.add_task(subject="Task C", blocked_by=[t1.id])
    t4 = await board.add_task(subject="Task D", blocked_by=[t2.id, t3.id])

    # 1. 尝试自环 (blocked_by 与 blocks 包含同一任务)
    with pytest.raises(ValueError, match="Circular dependency"):
        await board.add_task(subject="Self Loop", blocked_by=[t4.id], blocks=[t4.id])

    # 2. 尝试从汇聚节点 D 回环到根节点 A (D -> X -> A)
    with pytest.raises(ValueError, match="Circular dependency"):
        await board.add_task(subject="Cycle D to A", blocked_by=[t4.id], blocks=[t1.id])

    # 3. 尝试从汇聚节点 D 回环到单侧分支 B (D -> Y -> B)
    with pytest.raises(ValueError, match="Circular dependency"):
        await board.add_task(subject="Cycle D to B", blocked_by=[t4.id], blocks=[t2.id])

    # 4. 尝试从单侧分支 C 回环到根节点 A (C -> Z -> A)
    with pytest.raises(ValueError, match="Circular dependency"):
        await board.add_task(subject="Cycle C to A", blocked_by=[t3.id], blocks=[t1.id])


@pytest.mark.asyncio
async def test_shared_task_board_concurrent_agent_contention_and_recovery():
    """并发认领互斥与智能体崩溃自动解绑恢复 (防死锁)."""
    board = SharedTaskBoard("diamond_contention")

    t1 = await board.add_task(subject="Task A")
    t2 = await board.add_task(subject="Task B", blocked_by=[t1.id])
    t3 = await board.add_task(subject="Task C", blocked_by=[t1.id])

    # 解锁 B 和 C
    await board.claim_task_with_busy_check(t1.id, "health")
    await board.complete_task(t1.id)

    # 智能体 "bds_nav" 认领了 Task B
    res_b = await board.claim_task_with_busy_check(t2.id, "bds_nav")
    assert res_b.success is True

    # 同一智能体 "bds_nav" 试图并发抢占 Task C -> AGENT_BUSY 互斥
    res_c_busy = await board.claim_task_with_busy_check(t3.id, "bds_nav", check_agent_busy=True)
    assert res_c_busy.success is False
    assert res_c_busy.reason == ClaimTaskReason.AGENT_BUSY.value

    # 另一智能体 "weather" 认领 Task C -> 成功
    res_c_ok = await board.claim_task_with_busy_check(t3.id, "weather")
    assert res_c_ok.success is True

    # 此时 "bds_nav" 进程崩溃，触发解绑
    recovery_info = await board.unassign_teammate_tasks("bds_nav", reason="heartbeat_timeout")
    assert recovery_info["count"] == 1
    assert recovery_info["unassigned_tasks"] == [t2.id]

    # Task B 自动回退为 PENDING，且 owner 为 None
    task_b_recovered = board.get_task(t2.id)
    assert task_b_recovered.status == TaskStatus.PENDING.value
    assert task_b_recovered.owner is None

    # 新接入的替补智能体 "bds_backup" 成功接管 Task B
    res_takeover = await board.claim_task_with_busy_check(t2.id, "bds_backup")
    assert res_takeover.success is True
    assert task_b_recovered.owner == "bds_backup"
