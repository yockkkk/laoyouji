"""Empirical Concurrency, Deadlock & TOCTOU Stress Test Suite.

Milestone 1 Challenger 1 Verification Suite:
1. High-concurrency broadcast storm (20 concurrent agents broadcasting simultaneously).
   - Verify zero lost messages.
   - Verify deadlock freedom (strict timeout).
   - Verify FIFO ordering per sender-receiver pair.
   - Verify concurrent drain vs post queue integrity.
2. Cyclic deliberation cascade termination (MAX_DELIBERATION_HOPS = 3).
   - Ping-pong cascade (Agent A <-> Agent B).
   - Ring cascade (Agent A -> Agent B -> Agent C -> Agent A).
   - Verification of termination conditions and tool behavior.
3. TOCTOU race on claim_task_with_busy_check:
   - 10 agents simultaneously claiming the same task (exactly 1 winner, 9 rejections).
   - Scaled 50 agents contention on single task.
   - 1 agent claiming 10 different tasks simultaneously (1 winner, 9 AGENT_BUSY).
   - 10 agents claiming 10 distinct tasks concurrently.
   - Concurrent complete_task DAG unblocking vs claim_task_with_busy_check race.
"""
from __future__ import annotations

import asyncio
from typing import List, Dict, Set
import pytest

from app.core.mailbox import (
    AgentMailbox,
    MAX_DELIBERATION_HOPS,
    PeerMessage,
    PeerMessageType,
    SessionMailboxHub,
    clear_session_mailbox_hub,
    get_session_mailbox_hub,
)
from app.core.tasks import (
    BoardTask,
    ClaimTaskReason,
    ClaimTaskResult,
    SharedTaskBoard,
    TaskStatus,
)
from app.tools.peer_tools import send_teammate_message


# ==============================================================================
# Suite 1: High-Concurrency Broadcast Storm (20 Concurrent Agents)
# ==============================================================================

@pytest.mark.asyncio
async def test_broadcast_storm_20_agents_no_loss_and_fifo():
    """20 concurrent agents broadcasting simultaneously.
    
    Invariants:
    1. Zero message loss: 20 agents each broadcast 5 messages = 100 broadcasts.
       Each broadcast is delivered to 19 other agents (20 - 1 = 19).
       Total expected messages received across all inboxes = 100 * 19 = 1900 messages.
    2. Deadlock freedom: completes within 5.0 seconds.
    3. Strict FIFO ordering: for any pair (Sender i, Receiver j), messages from i must
       arrive at j in monotonic sequence 0, 1, 2, 3, 4.
    """
    session_id = "sess_broadcast_storm_20"
    hub = SessionMailboxHub(session_id)
    num_agents = 20
    msgs_per_agent = 5
    agent_names = [f"swarm_agent_{i:02d}" for i in range(num_agents)]
    known_agents = tuple(agent_names)

    # Pre-register / initialize mailboxes for all 20 agents
    for name in agent_names:
        hub.get_mailbox(name)

    # Define broadcasting coroutine for agent i
    async def agent_broadcast_worker(agent_id: str) -> None:
        for seq in range(msgs_per_agent):
            msg = PeerMessage(
                from_agent=agent_id,
                to_agent="*",
                msg_type=PeerMessageType.BROADCAST.value,
                summary=f"Storm-{agent_id}-seq-{seq}",
                content=f"Payload from {agent_id} seq {seq}",
                data={"agent": agent_id, "seq": seq},
            )
            await hub.send(msg, emit_sse=False, known_agents=known_agents)

    # Launch all 20 workers concurrently with a strict 5.0s timeout
    try:
        async with asyncio.timeout(5.0):
            await asyncio.gather(*[agent_broadcast_worker(name) for name in agent_names])
    except TimeoutError:
        pytest.fail("Broadcast storm DEADLOCKED or exceeded 5.0s timeout!")

    # Verify message accounting and FIFO ordering
    total_received = 0
    for receiver in agent_names:
        box = hub.get_mailbox(receiver)
        unread = box.unread_count()
        expected_for_receiver = (num_agents - 1) * msgs_per_agent
        assert unread == expected_for_receiver, (
            f"Receiver {receiver} expected {expected_for_receiver} messages, got {unread}"
        )
        total_received += unread

        # Drain messages and verify FIFO ordering per sender
        drained = box.drain()
        assert len(drained) == expected_for_receiver
        assert all(m.read for m in drained)

        # Group by sender and verify monotonic sequence
        sender_seqs: Dict[str, List[int]] = {other: [] for other in agent_names if other != receiver}
        for m in drained:
            assert m.to_agent == receiver
            sender = m.from_agent
            seq = m.data["seq"]
            sender_seqs[sender].append(seq)

        for sender, seqs in sender_seqs.items():
            assert len(seqs) == msgs_per_agent, (
                f"Receiver {receiver} missed messages from {sender}: got {seqs}"
            )
            assert seqs == list(range(msgs_per_agent)), (
                f"FIFO violation on ({sender} -> {receiver}): expected {list(range(msgs_per_agent))}, got {seqs}"
            )

    expected_total = num_agents * (num_agents - 1) * msgs_per_agent
    assert total_received == expected_total == 1900
    assert len(hub.message_log) == num_agents * msgs_per_agent == 100


@pytest.mark.asyncio
async def test_concurrent_post_and_drain_stress():
    """Verify thread/coroutine safety when post and drain happen simultaneously across 20 agents."""
    session_id = "sess_concurrent_drain_post"
    hub = SessionMailboxHub(session_id)
    num_agents = 10
    rounds = 20
    agent_names = [f"worker_{i}" for i in range(num_agents)]
    known_agents = tuple(agent_names)

    for name in agent_names:
        hub.get_mailbox(name)

    consumed_counts: Dict[str, int] = {name: 0 for name in agent_names}
    stop_event = asyncio.Event()

    async def consumer(name: str):
        while not stop_event.is_set():
            messages = hub.drain(name)
            consumed_counts[name] += len(messages)
            await asyncio.sleep(0.001)
        # Final drain
        final_msgs = hub.drain(name)
        consumed_counts[name] += len(final_msgs)

    async def producer(name: str):
        for r in range(rounds):
            # Target another agent
            target = agent_names[(agent_names.index(name) + 1) % num_agents]
            msg = PeerMessage(
                from_agent=name,
                to_agent=target,
                summary=f"P2P {r}",
                content=f"Content {r}",
                data={"round": r},
            )
            await hub.send(msg, emit_sse=False, known_agents=known_agents)
            await asyncio.sleep(0.001)

    consumers = [asyncio.create_task(consumer(name)) for name in agent_names]
    producers = [asyncio.create_task(producer(name)) for name in agent_names]

    await asyncio.gather(*producers)
    await asyncio.sleep(0.05)
    stop_event.set()
    await asyncio.gather(*consumers)

    # Every agent sent 20 messages to exactly 1 target
    # Total messages sent = num_agents * rounds = 200
    # Every agent should have received exactly 20 messages
    total_consumed = sum(consumed_counts.values())
    assert total_consumed == num_agents * rounds == 200
    for name, count in consumed_counts.items():
        assert count == rounds, f"Agent {name} consumed {count}, expected {rounds}"


# ==============================================================================
# Suite 2: Cyclic Deliberation Cascade & Hop Limit Termination
# ==============================================================================

@pytest.mark.asyncio
async def test_cyclic_ping_pong_deliberation_cascade_terminates():
    """Verify Agent A <-> Agent B cyclic deliberation cascade strictly terminates at MAX_DELIBERATION_HOPS = 3.
    
    Flow:
    - Round 0: Agent A sends initial message (hop_count=0) -> B receives with hop_count=1.
    - Round 1: Agent B replies to A with hop_count=1 -> A receives with hop_count=2.
    - Round 2: Agent A replies to B with hop_count=2 -> B receives with hop_count=3.
    - Round 3: Agent B replies to A with hop_count=3 -> A receives with hop_count=4.
    - Round 4: Agent A replies to B with hop_count=4 -> hub.send intercepts (4 > 3), returns without posting.
    - Termination: B receives nothing, inbox is empty, loop terminates cleanly without deadlock.
    """
    session_id = "sess_cyclic_ping_pong"
    hub = SessionMailboxHub(session_id)
    agent_a = "health"
    agent_b = "bds_nav"

    # Start cascade: A sends to B
    initial_msg = PeerMessage(
        from_agent=agent_a,
        to_agent=agent_b,
        msg_type=PeerMessageType.PROPOSAL.value,
        summary="Cascade Start: Knee limit",
        content="Avoid steep slope",
        hop_count=0,
    )
    await hub.send(initial_msg, emit_sse=False)

    delivered_hops: List[int] = []
    iterations = 0
    max_safe_iterations = 20  # Safeguard against true infinite loop

    current_receiver = agent_b
    current_sender = agent_a

    while iterations < max_safe_iterations:
        iterations += 1
        box = hub.get_mailbox(current_receiver)
        messages = box.drain()
        if not messages:
            # No messages arrived — cascade terminated!
            break

        received = messages[0]
        delivered_hops.append(received.hop_count)

        # Flip roles and reply propagating hop_count
        next_sender = current_receiver
        next_receiver = current_sender

        reply = PeerMessage(
            from_agent=next_sender,
            to_agent=next_receiver,
            msg_type=PeerMessageType.ACK.value,
            summary=f"Ping-pong reply at hop {received.hop_count}",
            content=f"Counter proposal from {next_sender}",
            hop_count=received.hop_count,
            reply_to=received.id,
        )
        await hub.send(reply, emit_sse=False)

        current_sender = next_sender
        current_receiver = next_receiver

    # The loop MUST have terminated well before max_safe_iterations
    assert iterations <= 6, f"Cascade failed to terminate within 6 steps, took {iterations} iterations"
    # Delivered hop counts should be [1, 2, 3, 4]
    # (Send 1: hop 0->1 delivered; Send 2: hop 1->2 delivered; Send 3: hop 2->3 delivered; Send 4: hop 3->4 delivered; Send 5: hop 4 intercepted!)
    assert delivered_hops == [1, 2, 3, 4], f"Unexpected hop sequence: {delivered_hops}"
    # Verify both mailboxes are now completely empty
    assert hub.get_mailbox(agent_a).unread_count() == 0
    assert hub.get_mailbox(agent_b).unread_count() == 0


@pytest.mark.asyncio
async def test_cyclic_ring_deliberation_cascade_terminates():
    """Verify 3-agent ring cascade (A -> B -> C -> A) strictly terminates when hop_count exceeds MAX_DELIBERATION_HOPS."""
    session_id = "sess_cyclic_ring"
    hub = SessionMailboxHub(session_id)
    ring = ["main", "health", "weather"]

    # Start ring at ring[0] -> ring[1]
    await hub.send(PeerMessage(
        from_agent=ring[0],
        to_agent=ring[1],
        summary="Ring Start",
        content="Cycle test",
        hop_count=0,
    ), emit_sse=False)

    delivered_hops = []
    curr_idx = 1
    steps = 0

    while steps < 20:
        steps += 1
        receiver = ring[curr_idx]
        msgs = hub.get_mailbox(receiver).drain()
        if not msgs:
            break

        received = msgs[0]
        delivered_hops.append((receiver, received.hop_count))

        next_idx = (curr_idx + 1) % len(ring)
        next_receiver = ring[next_idx]

        forward_msg = PeerMessage(
            from_agent=receiver,
            to_agent=next_receiver,
            summary=f"Forward hop {received.hop_count}",
            content="Ring forwarding",
            hop_count=received.hop_count,
        )
        await hub.send(forward_msg, emit_sse=False)
        curr_idx = next_idx

    assert steps <= 6
    assert [hop for _, hop in delivered_hops] == [1, 2, 3, 4]


# ==============================================================================
# Suite 3: TOCTOU Race on claim_task_with_busy_check
# ==============================================================================

@pytest.mark.asyncio
async def test_toctou_10_agents_claim_same_task_simultaneously():
    """10 concurrent agents attempt to claim the exact same task simultaneously.
    
    Invariants:
    1. Exactly 1 agent succeeds (success=True, reason='success').
    2. Exactly 9 agents are rejected (success=False, reason='already_claimed').
    3. Task owner matches the unique winner.
    4. Task status is IN_PROGRESS.
    """
    board = SharedTaskBoard("board_toctou_10")
    task = await board.add_task(subject="急救通道规划", description="高并发争抢单任务")
    assert task.id == "1"
    assert task.status == TaskStatus.PENDING.value

    num_contestants = 10
    agent_ids = [f"agent_{i:02d}" for i in range(num_contestants)]

    # Fire all 10 claims simultaneously via asyncio.gather
    results: List[ClaimTaskResult] = await asyncio.gather(*[
        board.claim_task_with_busy_check(task.id, claimant_agent_id=aid, check_agent_busy=True)
        for aid in agent_ids
    ])

    winners = [r for r in results if r.success]
    losers = [r for r in results if not r.success]

    assert len(winners) == 1, f"TOCTOU violation: expected 1 winner, got {len(winners)}"
    assert len(losers) == 9, f"Expected 9 rejections, got {len(losers)}"

    winner_agent = winners[0].task.owner
    assert winner_agent in agent_ids
    assert winners[0].reason == ClaimTaskReason.SUCCESS.value

    for loser in losers:
        assert loser.reason == ClaimTaskReason.ALREADY_CLAIMED.value
        assert f"already claimed by {winner_agent}" in loser.message

    final_task = board.get_task(task.id)
    assert final_task.owner == winner_agent
    assert final_task.status == TaskStatus.IN_PROGRESS.value


@pytest.mark.asyncio
async def test_toctou_scaled_50_agents_claim_same_task():
    """Extreme contention: 50 concurrent agents fighting for 1 task."""
    board = SharedTaskBoard("board_toctou_50")
    task = await board.add_task(subject="高负荷争抢任务")

    agent_ids = [f"contender_{i:03d}" for i in range(50)]
    results: List[ClaimTaskResult] = await asyncio.gather(*[
        board.claim_task_with_busy_check(task.id, aid, check_agent_busy=True)
        for aid in agent_ids
    ])

    winners = [r for r in results if r.success]
    losers = [r for r in results if not r.success]

    assert len(winners) == 1
    assert len(losers) == 49
    assert all(l.reason == ClaimTaskReason.ALREADY_CLAIMED.value for l in losers)


@pytest.mark.asyncio
async def test_toctou_single_agent_claiming_10_tasks_simultaneously():
    """1 single agent attempts to claim 10 distinct tasks at the exact same moment.
    
    Under check_agent_busy=True, the agent can only be busy with 1 active task.
    Invariants:
    1. Exactly 1 task claim succeeds.
    2. Exactly 9 task claims fail with reason='agent_busy'.
    """
    board = SharedTaskBoard("board_single_agent_multi_claim")
    tasks = [await board.add_task(subject=f"并发任务-{i}") for i in range(10)]

    agent_id = "solo_agent"
    results: List[ClaimTaskResult] = await asyncio.gather(*[
        board.claim_task_with_busy_check(t.id, agent_id, check_agent_busy=True)
        for t in tasks
    ])

    winners = [r for r in results if r.success]
    losers = [r for r in results if not r.success]

    assert len(winners) == 1, f"Expected 1 task claimed, got {len(winners)}"
    assert len(losers) == 9
    for loser in losers:
        assert loser.reason == ClaimTaskReason.AGENT_BUSY.value
        assert loser.busy_with_tasks == [winners[0].task.id]

    # Verify state of tasks on board
    claimed_tasks = [t for t in board.list_tasks() if t.owner == agent_id]
    assert len(claimed_tasks) == 1
    assert claimed_tasks[0].id == winners[0].task.id


@pytest.mark.asyncio
async def test_10_agents_claiming_10_distinct_tasks_concurrently():
    """10 agents concurrently claiming 10 distinct tasks (1:1 mapping).
    
    Invariants:
    - All 10 succeed with 0 conflicts.
    - All 10 tasks are assigned to distinct owners.
    """
    board = SharedTaskBoard("board_10_to_10")
    tasks = [await board.add_task(subject=f"专属任务-{i}") for i in range(10)]
    agent_ids = [f"dedicated_agent_{i}" for i in range(10)]

    results: List[ClaimTaskResult] = await asyncio.gather(*[
        board.claim_task_with_busy_check(tasks[i].id, agent_ids[i], check_agent_busy=True)
        for i in range(10)
    ])

    assert all(r.success for r in results)
    assert len({r.task.owner for r in results}) == 10


@pytest.mark.asyncio
async def test_race_complete_task_unblocking_vs_claim():
    """Concurrent race: Agent A completes upstream Task 1 while Agent B concurrently attempts
    to claim downstream Task 2 (blocked by Task 1).
    
    Verifies that Task 2 cannot be claimed prematurely before Task 1 completion completes,
    and once Task 1 is complete, Task 2 is claimable without inconsistency.
    """
    board = SharedTaskBoard("board_race_complete_claim")
    t1 = await board.add_task(subject="前置任务")
    t2 = await board.add_task(subject="后置任务", blocked_by=[t1.id])

    # First verify t2 cannot be claimed yet
    claim_early = await board.claim_task_with_busy_check(t2.id, "bds_nav")
    assert claim_early.success is False
    assert claim_early.reason == ClaimTaskReason.BLOCKED.value

    # Run completion of t1 and claiming of t2 concurrently
    async def completer():
        await asyncio.sleep(0.005)
        return await board.complete_task(t1.id)

    async def claimer():
        for _ in range(50):
            res = await board.claim_task_with_busy_check(t2.id, "bds_nav")
            if res.success:
                return res
            await asyncio.sleep(0.001)
        return res

    comp_res, claim_res = await asyncio.gather(completer(), claimer())
    assert comp_res[0].status == TaskStatus.COMPLETED.value
    assert claim_res.success is True
    assert board.get_task(t2.id).owner == "bds_nav"
    assert board.get_task(t2.id).status == TaskStatus.IN_PROGRESS.value


# ==============================================================================
# Suite 4: Adversarial Edge Cases & Boundary Conditions
# ==============================================================================

@pytest.mark.asyncio
async def test_adversarial_tool_level_deliberation_hop_behavior():
    """Empirical analysis of tool-level deliberation (send_teammate_message):
    
    Verifies that while SessionMailboxHub.send correctly enforces MAX_DELIBERATION_HOPS = 3
    when hop_count is present on PeerMessage, the tool `send_teammate_message` constructs
    PeerMessage without propagating hop_count or inspecting reply_to.
    This test verifies that:
    1. Direct hub calls enforce the termination boundary.
    2. Tool calls reset hop_count to 0 on outgoing creation, resulting in hop_count=1 on delivery.
    """
    session_id = "sess_tool_hop_behavior"
    hub = get_session_mailbox_hub(session_id)

    class MockTurn:
        def __init__(self, sess_id: str, aid: str):
            self.session_id = sess_id
            self.agent_id = aid
        async def emit(self, *args, **kwargs):
            pass

    t_health = MockTurn(session_id, "health")
    t_bds = MockTurn(session_id, "bds_nav")

    # Step 1: health sends proposal
    res1 = await send_teammate_message(t_health, {
        "to_agent": "bds_nav",
        "summary": "Step 1",
        "content": "Knee constraint",
    })
    assert res1["ok"] is True
    m1_id = res1["data"]["message_id"]

    # Step 2: bds_nav receives hop_count=1
    inbox_bds = hub.drain("bds_nav")
    assert len(inbox_bds) == 1
    assert inbox_bds[0].hop_count == 1

    # Step 3: bds_nav replies referencing reply_to
    res2 = await send_teammate_message(t_bds, {
        "to_agent": "health",
        "summary": "Step 2 Reply",
        "content": "Route planned",
        "reply_to": m1_id,
    })
    assert res2["ok"] is True

    # Step 4: health receives reply, hop_count is 1 (tool resets to 0, hub routes to 1)
    inbox_health = hub.drain("health")
    assert len(inbox_health) == 1
    assert inbox_health[0].hop_count == 1

    clear_session_mailbox_hub(session_id)


@pytest.mark.asyncio
async def test_adversarial_add_task_with_initial_owner_and_unresolved_dependencies():
    """Verify behavior when add_task is invoked with an initial owner but has unresolved blocked_by.
    
    Findings:
    - add_task sets status=IN_PROGRESS if owner is provided at creation time.
    - claim_task_with_busy_check strictly prevents claiming when blocked_by is unresolved.
    - Therefore, dynamic swarm tasks should be added as PENDING (owner=None) and claimed
      via claim_task_with_busy_check to enforce DAG dependency invariants.
    """
    board = SharedTaskBoard("board_adv_add_task")
    t1 = await board.add_task(subject="前置依赖任务")
    
    # Adding task with initial owner while t1 is incomplete
    t2 = await board.add_task(subject="后置任务", owner="bds_nav", blocked_by=[t1.id])
    assert t2.status == TaskStatus.IN_PROGRESS.value
    assert t2.owner == "bds_nav"

    # But if added cleanly with owner=None, claiming is strictly blocked by DAG
    t3 = await board.add_task(subject="规范后置任务", blocked_by=[t1.id])
    claim_res = await board.claim_task_with_busy_check(t3.id, "bds_nav")
    assert claim_res.success is False
    assert claim_res.reason == ClaimTaskReason.BLOCKED.value

