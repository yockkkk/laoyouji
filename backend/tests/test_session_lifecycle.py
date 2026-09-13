"""会话生命周期的四处硬骨头：hydrate 竞态、轮次串行、断线、内存上界。

这些都不是"理论上可能"：四条里三条先用探针复现过，然后才写的修复。
放在一个文件里是因为它们讲的是同一件事 —— **一个会话在时间上的完整性**：
谁在写它、写的顺序对不对、没人看着的时候会怎样、开久了会不会烂。
"""
from __future__ import annotations

import asyncio

import pytest

from app.core.events import USER_MESSAGE
from app.core.turn_gate import QUEUED_HINT, SessionTurnGate, TurnBusy


# ------------------------------------------------------------------ hydrate 竞态

async def test_two_requests_waking_one_cold_session_do_not_collide(ctx, elder):
    """两个请求同时唤醒同一个冷会话，不许撞 seq、不许丢事件。

    修复前实测（探针原样）::

        _pending: [(2,'来自A'), (2,'来自B')]            两条抢到同一个号
        _events:  [(1,'第一句'), (2,'来自B')]           A 在内存里被 B 顶掉
        库里:      [(1,..), (2,'来自A'), (2,'来自B')]    Postgres 上撞唯一键

    成因是 ``hydrate`` 在 ``await repos.list`` 上让出控制权，两边都读到旧的
    max(seq)。``append`` 自己没有竞态（纯同步、无读改写窗口），窗口只在这儿。
    """
    log = ctx.event_log
    session = await log.create_session(elder["id"], "冷会话")
    sid = session["id"]
    log.append(sid, elder["id"], USER_MESSAGE, {"text": "第一句"})
    await log.flush(sid)

    # 变成真正的"冷会话"：内存态全清，只剩库里那一条
    assert log.release(sid) is True

    # 放大 I/O 窗口，让竞态必然发生而不是偶尔发生
    original_list = ctx.repos.list

    async def slow_list(table, **kwargs):
        rows = await original_list(table, **kwargs)
        await asyncio.sleep(0.05)
        return rows

    ctx.repos.list = slow_list
    try:
        async def wake_and_write(tag: str) -> None:
            await log.hydrate(sid)
            log.append(sid, elder["id"], USER_MESSAGE, {"text": "来自" + tag})

        await asyncio.gather(wake_and_write("A"), wake_and_write("B"))
    finally:
        ctx.repos.list = original_list

    seqs = [e.seq for e in log.events(sid)]
    assert len(seqs) == len(set(seqs)), "seq 撞号了：%s" % seqs
    assert seqs == list(range(1, len(seqs) + 1)), seqs
    texts = [e.payload.get("text") for e in log.events(sid)]
    # A / B 谁先谁后取决于调度，无所谓；三条都在才是要的
    assert sorted(texts) == sorted(["第一句", "来自A", "来自B"]), \
        "有事件被顶掉了：%s" % texts

    await log.flush(sid)
    rows = await ctx.repos.list("session_events", where={"session_id": sid},
                                order="seq")
    db_seqs = [r["seq"] for r in rows]
    assert len(db_seqs) == len(set(db_seqs)), "库里撞唯一键：%s" % db_seqs
    assert len(rows) == 3


async def test_hydrate_during_a_live_turn_does_not_reset_the_log(ctx, elder):
    """已经 hydrate 过的会话再被 hydrate，内存日志不能被重置回库里那份。

    没有双检的话，第二次 hydrate 会把 ``_events`` 换成刚读到的行 ——
    这中间 append 进来的（还在写后缓冲里、库里还没有的）事件当场消失。
    """
    log = ctx.event_log
    session = await log.create_session(elder["id"], "热会话")
    sid = session["id"]
    log.append(sid, elder["id"], USER_MESSAGE, {"text": "落库的"})
    await log.flush(sid)
    log.append(sid, elder["id"], USER_MESSAGE, {"text": "还没落库的"})

    await log.hydrate(sid)                      # 幂等，且不许把第二条弄丢

    assert [e.payload.get("text") for e in log.events(sid)] == [
        "落库的", "还没落库的"]
    assert log.pending_count(sid) == 1


async def test_concurrent_flushes_do_not_lose_a_batch(ctx, elder):
    """同一会话两次 flush 同时在飞：两边各摘走一半缓冲，也不能丢。"""
    log = ctx.event_log
    session = await log.create_session(elder["id"], "双 flush")
    sid = session["id"]
    for i in range(6):
        log.append(sid, elder["id"], USER_MESSAGE, {"text": "第%d句" % i})

    written = await asyncio.gather(log.flush(sid), log.flush(sid))
    assert sum(written) == 6, "两次 flush 合计只写了 %d 条" % sum(written)
    assert log.pending_count(sid) == 0
    rows = await ctx.repos.list("session_events", where={"session_id": sid})
    assert len(rows) == 6


# ------------------------------------------------------------------ 轮次闸门

async def test_turns_in_one_session_run_one_after_another():
    """同一会话的两轮必须首尾相接，不能重叠。

    重叠的后果不是"慢"，是模型历史交错成"问A 答A 问B 答B"混在一起的一锅粥：
    模型分不清哪句回答对着哪句提问，下一步的工具参数就可能张冠李戴。
    """
    gate = SessionTurnGate()
    timeline: list[str] = []

    async def turn(tag: str) -> None:
        async with gate.hold("s1"):
            timeline.append(tag + "进")
            await asyncio.sleep(0.02)
            timeline.append(tag + "出")

    await asyncio.gather(turn("A"), turn("B"))
    # 谁先进不重要，"进出进出"这个形状才是要的（"进进出出"就是重叠）
    assert timeline in (["A进", "A出", "B进", "B出"],
                        ["B进", "B出", "A进", "A出"]), timeline


async def test_different_sessions_never_wait_on_each_other():
    """闸门是每会话一把 —— 两个老人同时用，不能互相排队。"""
    gate = SessionTurnGate()
    started = asyncio.Event()

    async def slow() -> None:
        async with gate.hold("s1"):
            started.set()
            await asyncio.sleep(0.3)

    task = asyncio.create_task(slow())
    await started.wait()
    # 另一个会话必须立刻拿到闸门，等不到就是串成一条队了
    await asyncio.wait_for(_enter_and_leave(gate, "s2"), timeout=0.1)
    task.cancel()


async def _enter_and_leave(gate: SessionTurnGate, session_id: str) -> None:
    async with gate.hold(session_id):
        return


async def test_a_queued_turn_says_so_before_it_waits():
    """排队时说一句"我还在办上一件事" —— 界面上要看得见系统在排队。

    只在真需要等的时候说：不用等也弹一句，屏幕上就多一行无谓的闪动。
    """
    gate = SessionTurnGate()
    said: list[str] = []

    async def announce() -> None:
        said.append(QUEUED_HINT)

    async with gate.hold("s1", on_wait=announce):
        assert said == [], "没人占着闸门时不该提示排队"

        async def second() -> None:
            async with gate.hold("s1", on_wait=announce):
                return

        task = asyncio.create_task(second())
        await asyncio.sleep(0.01)               # 让它撞上闸门
        assert said == [QUEUED_HINT], "排队了却没告诉老人"
    await task


async def test_waiting_too_long_is_told_in_plain_words():
    """等不到闸门就说实话，且这句话得是能直接念给老人听的。"""
    gate = SessionTurnGate(max_wait_s=0.05)

    async def hog() -> None:
        async with gate.hold("s1"):
            await asyncio.sleep(0.5)

    task = asyncio.create_task(hog())
    await asyncio.sleep(0.01)
    with pytest.raises(TurnBusy) as caught:
        async with gate.hold("s1"):
            pass
    message = caught.value.message
    assert message
    assert not any(word in message for word in
                   ("锁", "超时", "timeout", "并发", "session", "Error"))
    task.cancel()


async def test_the_gate_is_released_even_when_the_turn_blows_up():
    """一轮抛异常也必须放闸 —— 否则这个会话从此再也发不出话。"""
    gate = SessionTurnGate()
    with pytest.raises(RuntimeError):
        async with gate.hold("s1"):
            raise RuntimeError("智能体崩了")
    assert gate.busy("s1") is False
    async with gate.hold("s1"):                 # 还能再进，说明闸真放开了
        pass


# ------------------------------------------------------------------ 断线

async def test_a_detached_turn_is_held_onto_until_it_finishes():
    """断线后仍在跑的轮次，必须有人拿着它的强引用。

    asyncio 只弱引用 task：没人持有的话，事件循环可能在它落库之前就把它回收了
    —— 那正好是"老人锁屏，回来发现计划书没了"的成因。
    所以 ``_detach`` 把 task 记进模块级集合，跑完再摘掉（摘掉是为了不泄漏）。
    这里直接测这个机制：走 HTTP 测不到它，进程内的 ASGI 传输在关闭响应时
    会把生成器抽干，等于那一轮总是先跑完，取消与不取消看不出区别。
    """
    from app.api.routes_chat import _detach, _detached

    done = asyncio.Event()

    async def turn() -> None:
        await asyncio.sleep(0.05)
        done.set()

    task = asyncio.create_task(turn())
    _detach(task, "s1")
    assert task in _detached, "断线后没人拿着这一轮，它可能被提前回收"

    await asyncio.wait_for(done.wait(), timeout=1.0)
    await task
    assert task.cancelled() is False, "断线不该取消这一轮"
    await asyncio.sleep(0)                      # 让 done callback 跑
    assert task not in _detached, "跑完了还留在集合里，长跑进程会一直堆积"


async def test_a_turn_still_lands_when_the_client_stops_reading(ctx, elder):
    """客户端读到一半就走，这一轮的事件仍要完整落库。

    事件都在写后缓冲里，轮次末尾的 flush 才落库 —— 半途丢下就等于把
    这一问一答扔了。他回来一拉 ``/sessions/{id}/events`` 该是完整的。
    """
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_ctx
    from app.auth.security import create_access_token
    from app.main import app

    session = await ctx.event_log.create_session(elder["id"], "断线")
    sid = session["id"]

    # 把一轮拉长，保证客户端断开时它**确实还在跑**。
    # 不这样的话 mock 智能体几毫秒就跑完了，取消与不取消看不出区别 ——
    # 测试会在"断线即取消"的实现下照样通过，等于没测。
    started = asyncio.Event()

    async def slow_turn(turn) -> None:
        await turn.emit("agent_msg", {"text": "开始给您办"})
        started.set()
        await asyncio.sleep(0.3)
        await turn.emit("agent_msg", {"text": "办完了"})   # 断线后才产生的事件
        return "都办好啦"

    original = ctx.agents["main"].run
    ctx.agents["main"].run = slow_turn
    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        headers = {"Authorization":
                   "Bearer " + create_access_token(elder, ctx.settings)}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            async with client.stream(
                "POST", "/api/chat/stream", headers=headers,
                json={"session_id": sid, "text": "我要去北京看病"},
            ) as response:
                assert response.status_code == 200
                async for _line in response.aiter_lines():
                    if started.is_set():
                        break                   # 轮次正在跑 —— 这时候断线
    finally:
        app.dependency_overrides.clear()
        ctx.agents["main"].run = original

    # 给后台那一轮跑完的时间。它带着预算墙钟，不会永远跑
    for _ in range(200):
        if not ctx.turn_gate.busy(sid):
            break
        await asyncio.sleep(0.02)

    rows = await ctx.repos.list("session_events", where={"session_id": sid},
                                order="seq")
    texts = [(r["payload"] or {}).get("text") for r in rows]
    assert "我要去北京看病" in texts, "断线把老人这一句弄丢了"
    assert "办完了" in texts, "轮次在断线时被取消了，后半截活儿丢了：%s" % texts
    assert "都办好啦" in texts, "收尾的 final 没落库：%s" % texts


# ------------------------------------------------------------------ 内存上界

async def test_idle_sessions_are_let_go_so_memory_stays_bounded(ctx, elder):
    """内存里的会话数有上界 —— 长跑进程不能把每个开过的会话都留着。"""
    log = ctx.event_log
    log.MAX_LIVE_SESSIONS = 5
    ids = []
    for i in range(12):
        session = await log.create_session(elder["id"], "会话%d" % i)
        log.append(session["id"], elder["id"], USER_MESSAGE,
                   {"text": "第%d句" % i})
        await log.flush(session["id"])           # 落库了才允许被让出去
        ids.append(session["id"])

    assert log.live_count() <= log.MAX_LIVE_SESSIONS + 1, log.live_count()
    # 让出去不等于丢了：一访问就自动读回来，内容照旧
    await log.hydrate(ids[0])
    assert [e.payload["text"] for e in log.events(ids[0])] == ["第0句"]


async def test_a_session_with_unflushed_events_is_never_let_go(ctx, elder):
    """还有事件没落库的会话不许让出 —— 一让就是丢数据，那正是要防的事。"""
    log = ctx.event_log
    log.MAX_LIVE_SESSIONS = 2
    keep = await log.create_session(elder["id"], "没落库的")
    log.append(keep["id"], elder["id"], USER_MESSAGE, {"text": "还在缓冲里"})

    for i in range(8):
        other = await log.create_session(elder["id"], "别的%d" % i)
        log.append(other["id"], elder["id"], USER_MESSAGE, {"text": "x"})
        await log.flush(other["id"])

    assert log.release(keep["id"]) is False, "有未落库事件却答应让出"
    assert [e.payload["text"] for e in log.events(keep["id"])] == ["还在缓冲里"]
    assert log.pending_count(keep["id"]) == 1


# ------------------------------------------------------------------ 历史气泡

async def test_subagent_instructions_never_show_as_the_elders_words(
        ctx, elder, run_turn):
    """子智能体的派工指令不能渲染成老人的气泡。

    子智能体的 user/message 是**派给它的指令**（"…医院、科室、医生、日期、
    时间、挂号费照抄查询结果"），落日志是为了它自己的历史派生。
    当成老人的原话摆回对话里，就是把系统内部指令给老人看。
    """
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_ctx
    from app.auth.security import create_access_token
    from app.main import app

    sid, _events = await run_turn("我要去北京看病")

    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        headers = {"Authorization":
                   "Bearer " + create_access_token(elder, ctx.settings)}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.get("/api/chat/history?session_id=" + sid,
                                   headers=headers)
        assert res.status_code == 200
        messages = res.json()["messages"]
    finally:
        app.dependency_overrides.clear()

    said = [m["text"] for m in messages if m.get("isUser")]
    assert said == ["我要去北京看病"], "老人的气泡里混进了别的：%s" % said
    assert not any("照抄" in text for text in said)


async def test_turn_gate_concurrency_stress_no_deadlock_or_dropped_lock():
    """并发压力测试：验证在快速并行消息到达时无死锁、无掉锁、等待计数严格同步且退出后完全释放。"""
    gate = SessionTurnGate(max_wait_s=5.0)
    session_id = "stress-session-1"

    execution_order = []
    concurrency_count = 0
    max_observed_concurrency = 0

    async def worker(worker_id: int):
        nonlocal concurrency_count, max_observed_concurrency

        async def on_wait():
            pass

        async with gate.hold(session_id, on_wait=on_wait):
            concurrency_count += 1
            if concurrency_count > max_observed_concurrency:
                max_observed_concurrency = concurrency_count
            execution_order.append(f"start_{worker_id}")
            await asyncio.sleep(0.005)
            execution_order.append(f"end_{worker_id}")
            concurrency_count -= 1

    # 启动 20 个高频并行请求冲刷同一个 session
    tasks = [asyncio.create_task(worker(i)) for i in range(20)]
    await asyncio.gather(*tasks)

    # 1. 严格互斥：任何时刻持锁并发度不得超过 1
    assert max_observed_concurrency == 1
    assert len(execution_order) == 40
    # 2. 严格串行：必须是 start_i, end_i 成对出现，绝不能交叉重叠
    for i in range(0, len(execution_order), 2):
        start_tag = execution_order[i]
        end_tag = execution_order[i + 1]
        assert start_tag.startswith("start_")
        assert end_tag.startswith("end_")
        assert start_tag.split("_")[1] == end_tag.split("_")[1]

    # 3. 资源清理：所有任务完成后，waiting count 清零，locks 映射完全释放
    assert gate.waiting(session_id) == 0
    assert gate.busy(session_id) is False
    assert session_id not in gate._locks


async def test_approve_and_execute_gated_with_turn_gate(ctx, elder, child):
    """验证子女批准执行与老人实时对话受 turn_gate 互斥保护，杜绝跨轮次因果错乱。"""
    from app.core.context import TurnContext
    from app.core.guard import GuardResult, GuardVerdict

    # 1. 老人产生一个挂起任务
    session = await ctx.event_log.create_session(elder["id"], "门禁审批并发测试")
    sid = session["id"]
    turn = TurnContext(ctx=ctx, session_id=sid, user=elder)
    tool = ctx.tools.get("register_appointment")
    suspend_res = await ctx.confirmation.suspend(
        turn, tool,
        {"hospital": "南京鼓楼医院", "department": "骨科", "doctor": "邱勇",
         "date": "+1", "time": "上午 08:30", "fee": 70},
        GuardResult(GuardVerdict.INTERCEPT, reason="挂号费 70 元，需要家人确认",
                    risk_level="high", amount=70),
    )
    task_id = suspend_res["confirmation_id"]

    order = []
    # 模拟老人正在占用闸门进行对话
    async def elder_talking():
        async with ctx.turn_gate.hold(sid):
            order.append("elder_chat_start")
            await asyncio.sleep(0.08)
            order.append("elder_chat_end")

    # 模拟子女同时点击批准
    async def child_approving():
        await asyncio.sleep(0.01)  # 确保老人先持锁
        order.append("child_approve_request")
        res = await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])
        order.append("child_approve_done")
        return res

    elder_task = asyncio.create_task(elder_talking())
    child_task = asyncio.create_task(child_approving())

    await asyncio.gather(elder_task, child_task)

    # 验证顺序：老人聊天完成释放闸门后，子女批准才得以执行重放
    assert order == [
        "elder_chat_start",
        "child_approve_request",
        "elder_chat_end",
        "child_approve_done",
    ]
    task = await ctx.repos.get("confirmation_tasks", task_id)
    assert task["status"] == "executed"


async def test_turn_gate_unacquired_lock_cleaned_up_on_timeout():
    """验证等待超时未持锁退出时，waiting 计数归零且 _locks 字典不泄漏锁对象。"""
    gate = SessionTurnGate(max_wait_s=0.02)
    session_id = "timeout-cleanup-session"

    async def slow_holder():
        async with gate.hold(session_id):
            await asyncio.sleep(0.08)

    async def timing_out_waiter():
        await asyncio.sleep(0.005)  # 确保 holder 先持锁
        with pytest.raises(TurnBusy):
            async with gate.hold(session_id, max_wait_s=0.01):
                pass

    t1 = asyncio.create_task(slow_holder())
    t2 = asyncio.create_task(timing_out_waiter())
    await asyncio.gather(t1, t2)

    assert gate.waiting(session_id) == 0
    assert gate.busy(session_id) is False
    assert session_id not in gate._locks


async def test_turn_gate_on_wait_exception_cleans_up_and_releases():
    """验证 on_wait 抛异常时，waiting 计数在 finally 中保证递减，且后续轮次不受阻碍。"""
    gate = SessionTurnGate(max_wait_s=1.0)
    session_id = "on-wait-exc-session"

    async def boom_wait():
        raise ValueError("on_wait 回调崩了")

    async def holder():
        async with gate.hold(session_id):
            await asyncio.sleep(0.05)

    async def faulty_waiter():
        await asyncio.sleep(0.005)
        with pytest.raises(ValueError, match="on_wait 回调崩了"):
            async with gate.hold(session_id, on_wait=boom_wait):
                pass

    t1 = asyncio.create_task(holder())
    t2 = asyncio.create_task(faulty_waiter())
    await asyncio.gather(t1, t2)

    assert gate.waiting(session_id) == 0
    assert gate.busy(session_id) is False
    assert session_id not in gate._locks

    # 验证后续任务仍可正常获取该会话锁
    acquired = False
    async with gate.hold(session_id):
        acquired = True
    assert acquired is True
    assert session_id not in gate._locks


async def test_turn_gate_waiter_cancelled_cleans_up_and_does_not_deadlock():
    """验证排队任务被外部协程 cancel 时，waiting 计数正确扣减且不造成死锁。"""
    gate = SessionTurnGate(max_wait_s=2.0)
    session_id = "cancelled-waiter-session"

    async def holder():
        async with gate.hold(session_id):
            await asyncio.sleep(0.06)

    async def doomed_waiter():
        await asyncio.sleep(0.005)
        async with gate.hold(session_id):
            pass

    t1 = asyncio.create_task(holder())
    t2 = asyncio.create_task(doomed_waiter())

    await asyncio.sleep(0.02)  # 等 t2 进入 waiting
    assert gate.waiting(session_id) == 1
    t2.cancel()

    with pytest.raises(asyncio.CancelledError):
        await t2
    await t1

    assert gate.waiting(session_id) == 0
    assert gate.busy(session_id) is False
    assert session_id not in gate._locks


async def test_turn_gate_fifo_ordering_during_on_wait():
    """验证当先到达的排队者在执行 on_wait 时，持有者释放锁后，后到达者绝不能插队抢锁（严格 FIFO）。"""
    gate = SessionTurnGate()
    session_id = "fifo-on-wait-session"
    order = []

    async def holder():
        async with gate.hold(session_id):
            order.append("holder_start")
            await asyncio.sleep(0.02)
            order.append("holder_end")

    async def waiter1():
        await asyncio.sleep(0.005)  # 确保 holder 先持锁
        async def slow_on_wait():
            order.append("waiter1_on_wait_start")
            await asyncio.sleep(0.04)  # holder 会在此期间释放锁
            order.append("waiter1_on_wait_end")

        async with gate.hold(session_id, on_wait=slow_on_wait):
            order.append("waiter1_critical")

    async def waiter2():
        # 在 holder 结束之后、但 waiter1 的 on_wait 尚未完成时到达
        await asyncio.sleep(0.03)
        async with gate.hold(session_id):
            order.append("waiter2_critical")

    await asyncio.gather(holder(), waiter1(), waiter2())

    # 验证执行顺序：waiter1 必须严格在 waiter2 之前进入关键区，绝不允许插队
    assert order == [
        "holder_start",
        "waiter1_on_wait_start",
        "holder_end",
        "waiter1_on_wait_end",
        "waiter1_critical",
        "waiter2_critical",
    ]
    assert gate.waiting(session_id) == 0
    assert gate.busy(session_id) is False
    assert session_id not in gate._locks


async def test_turn_gate_cancelled_on_wait_wakes_next_waiter():
    """验证当排队者在 on_wait 期间被取消时，能够安全将锁传递给后续排队者，无死锁无泄漏。"""
    gate = SessionTurnGate()
    session_id = "cancelled-on-wait-wakes-next-session"
    order = []

    async def holder():
        async with gate.hold(session_id):
            order.append("holder_start")
            await asyncio.sleep(0.03)
            order.append("holder_end")

    async def doomed_waiter():
        await asyncio.sleep(0.005)
        async def slow_wait():
            order.append("doomed_on_wait")
            await asyncio.sleep(0.1)
        async with gate.hold(session_id, on_wait=slow_wait):
            order.append("doomed_critical")

    async def next_waiter():
        await asyncio.sleep(0.01)
        async with gate.hold(session_id):
            order.append("next_critical")

    t1 = asyncio.create_task(holder())
    t2 = asyncio.create_task(doomed_waiter())
    t3 = asyncio.create_task(next_waiter())

    await asyncio.sleep(0.02)  # 等待 t2 进入 on_wait 回调
    t2.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t2

    await asyncio.gather(t1, t3)

    assert "holder_start" in order
    assert "holder_end" in order
    assert "next_critical" in order
    assert "doomed_critical" not in order
    assert gate.waiting(session_id) == 0
    assert gate.busy(session_id) is False
    assert session_id not in gate._locks


