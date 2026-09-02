"""内核不变式：seq 全序、写后落库、function-calling 因果链、作用域隔离。

对着三个原型缺陷写的，所以断言的是**承诺**而不是实现细节：

- **#6 seq 竞态**：旧实现"先读 max 再 +1"，两个协程交错就能拿到同一个 seq，
  "append-only 全序"那句话不成立。现在 seq 由内存单调计数器同步分配。
- **#3 因果链断裂**：旧实现把工具结果伪装成 ``role:"assistant"`` 的
  ``"[工具结果] …"`` 文本；跨轮次后模型再也分不清哪个结果对应哪次调用。
  现在派生成 ``role:"tool"`` + ``tool_call_id``，严格配对。
- **#1 上下文污染**：旧实现每个子智能体都拉同一份 ``llm_history(session_id, 20)``，
  出行助理能看到健康助理和老人的往来。现在历史按作用域派生。

还有一条贯穿全文件的不变式："**model-visible means logged**" —— 派生出的每一条
消息都必须能在事件日志里指认出处。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.core.events import (
    AGENT_REPORT,
    ARTIFACT_CARD,
    ASSISTANT_MESSAGE,
    CONFIRM_SUSPENDED,
    InvariantViolation,
    MAIN_SCOPE,
    SessionEventLog,
    STEP_START,
    TODO_WRITE,
    TOOL_CALL,
    TOOL_RESULT,
    TURN_END,
    TURN_START,
    USER_MESSAGE,
    durable_type,
)


@pytest.fixture()
async def sid(ctx, elder):
    session = await ctx.event_log.create_session(elder["id"], "内核")
    return session["id"]


def _declare(log, sid: str, calls: list[dict], *, text: str = "",
             scope: str = MAIN_SCOPE, step_id: str | None = None):
    """记一条带 tool_calls 的 assistant 消息（模型侧的"我要调这些"）。"""
    return log.append(sid, None, ASSISTANT_MESSAGE,
                      {"text": text, "tool_calls": calls},
                      agent_id=scope, step_id=step_id)


def _settle(log, sid: str, call_id: str, content: str = '{"ok": true}', *,
            scope: str = MAIN_SCOPE, step_id: str | None = None):
    return log.append(sid, None, TOOL_RESULT,
                      {"call_id": call_id, "tool": "t", "ok": True,
                       "content": content},
                      agent_id=scope, step_id=step_id)


# ------------------------------------------------------------------ seq 全序


async def test_seq_is_dense_and_strictly_increasing_under_concurrency(ctx, sid):
    """四个协程交错追加 100 条 → seq 恰好是 1..100，一个不重不漏。

    ``append`` 是**同步**的：分配 seq 与落 list 之间没有 await，所以在单线程
    事件循环里天然原子。旧实现在这两步之间等了一次 I/O，那个窗口就是缺陷 #6。
    """
    async def writer(tag: str) -> None:
        for i in range(25):
            ctx.event_log.append(sid, None, "ext/probe", {"tag": tag, "i": i})
            await asyncio.sleep(0)          # 交还事件循环，制造真交错

    await asyncio.gather(*(writer(t) for t in "abcd"))

    seqs = [e.seq for e in ctx.event_log.events(sid)]
    assert seqs == list(range(1, 101))


async def test_append_is_synchronous_and_persistence_is_write_behind(ctx, sid):
    """热路径不等 I/O：追加即可见，落库排到 ``session/flush`` 检查点。"""
    log = ctx.event_log
    event = log.append(sid, None, USER_MESSAGE, {"text": "我想去北京"})

    assert event.seq == 1
    assert log.events(sid)[-1] is event                     # 立刻可见
    assert await ctx.repos.list("session_events",
                               where={"session_id": sid}) == []   # 还没落库

    assert await log.flush(sid) == 1
    rows = await ctx.repos.list("session_events", where={"session_id": sid})
    assert [r["seq"] for r in rows] == [1]
    assert await log.flush(sid) == 0, "缓冲已排空，重复 flush 不该重复写"


async def test_seq_continues_after_a_restart(ctx, sid):
    """换个进程 hydrate 回来，seq 接着最大值走 —— 重启不撞号。"""
    log = ctx.event_log
    log.append(sid, None, USER_MESSAGE, {"text": "一"})
    log.append(sid, None, USER_MESSAGE, {"text": "二"})
    await log.flush(sid)

    fresh = SessionEventLog(ctx.repos)
    await fresh.hydrate(sid)
    assert [e.payload["text"] for e in fresh.events(sid)] == ["一", "二"]
    assert fresh.append(sid, None, USER_MESSAGE, {"text": "三"}).seq == 3


async def test_hydrate_is_idempotent(ctx, sid):
    log = ctx.event_log
    log.append(sid, None, USER_MESSAGE, {"text": "一"})
    await log.flush(sid)
    await log.hydrate(sid)
    await log.hydrate(sid)
    assert len(log.events(sid)) == 1, "已 hydrate 的会话不该被重复灌一遍"


# ------------------------------------------------------- function-calling 因果链


async def test_tool_results_derive_as_role_tool_paired_by_id(ctx, sid):
    """工具结果派生成 ``role:"tool"`` + ``tool_call_id``，与声明严格配对。"""
    log = ctx.event_log
    log.append(sid, None, USER_MESSAGE, {"text": "查一下明天去北京的车"})
    _declare(log, sid, [{"id": "c1", "name": "search_train",
                         "arguments": {"date": "tomorrow"}}],
             text="我先查一下车次。")
    _settle(log, sid, "c1", '{"ok": true, "summary": "查到 G102"}')

    messages = log.derive_messages(sid)

    assert [m["role"] for m in messages] == ["user", "assistant", "tool"]
    call = messages[1]["tool_calls"][0]
    assert call["id"] == "c1" and call["type"] == "function"
    assert call["function"]["name"] == "search_train"
    assert json.loads(call["function"]["arguments"]) == {"date": "tomorrow"}
    assert messages[2] == {"role": "tool", "tool_call_id": "c1",
                           "content": '{"ok": true, "summary": "查到 G102"}'}
    # 旧实现的形态：伪装成 assistant 的一段文本。因果链就断在这儿。
    assert not any("[工具结果]" in (m.get("content") or "") for m in messages)


async def test_unsettled_tool_calls_are_dropped_from_history(ctx, sid):
    """声明了两个、只结算了一个 → 历史里只留有结果的那个。

    留着无主的声明，OpenAI 兼容接口下一轮直接 400；而"少一条声明"是安全的
    —— 模型看到的是一段自洽的历史，不是一段自相矛盾的历史。
    """
    log = ctx.event_log
    _declare(log, sid, [{"id": "c1", "name": "a", "arguments": {}},
                        {"id": "c2", "name": "b", "arguments": {}}])
    _settle(log, sid, "c1")

    messages = log.derive_messages(sid)
    assert [c["id"] for c in messages[0]["tool_calls"]] == ["c1"]
    assert [m.get("tool_call_id") for m in messages if m["role"] == "tool"] == ["c1"]


async def test_orphan_tool_result_never_enters_history(ctx, sid):
    """没有前置声明的结果直接丢掉（防御性：正常流程不该出现）。"""
    log = ctx.event_log
    log.append(sid, None, USER_MESSAGE, {"text": "你好"})
    _settle(log, sid, "从没声明过的 id")

    assert [m["role"] for m in log.derive_messages(sid)] == ["user"]


async def test_only_three_event_types_are_model_visible(ctx, sid):
    """进模型历史的只有 user / assistant / tool_result 三类。

    todo、回报、卡片、挂起、生命周期事件都**只落日志**：它们是给前端和审计看的，
    不占模型上下文。这条界线一松，长会话立刻被过程性噪音挤爆。
    """
    log = ctx.event_log
    log.append(sid, None, USER_MESSAGE, {"text": "你好"})
    for noisy in (TURN_START, STEP_START, TODO_WRITE, AGENT_REPORT,
                  ARTIFACT_CARD, CONFIRM_SUSPENDED, TOOL_CALL, TURN_END):
        log.append(sid, None, noisy, {"text": "噪音", "todos": [],
                                      "call_id": "x", "tool": "t"})

    assert log.derive_messages(sid) == [{"role": "user", "content": "你好"}]


async def test_derive_messages_limit_keeps_the_tail(ctx, sid):
    log = ctx.event_log
    for i in range(5):
        log.append(sid, None, USER_MESSAGE, {"text": f"第{i}句"})
    tail = log.derive_messages(sid, limit=2)
    assert [m["content"] for m in tail] == ["第3句", "第4句"]


# ------------------------------------------------------------------ 作用域隔离


async def test_spawn_scope_cannot_see_the_parents_history(ctx, sid):
    """子作用域只看到自己的指令 —— 缺陷 #1 的正面验收。"""
    log = ctx.event_log
    log.append(sid, None, USER_MESSAGE, {"text": "老人的原话"}, agent_id=MAIN_SCOPE)
    log.append(sid, None, USER_MESSAGE, {"text": "派给出行的指令"},
               agent_id="travel#1")
    log.append(sid, None, USER_MESSAGE, {"text": "派给健康的指令"},
               agent_id="health#1")

    assert [m["content"] for m in log.derive_messages(sid, scopes=["travel#1"])] \
        == ["派给出行的指令"]
    assert [m["content"] for m in log.derive_messages(sid, scopes=["health#1"])] \
        == ["派给健康的指令"]
    assert [m["content"] for m in log.derive_messages(sid, scopes=[MAIN_SCOPE])] \
        == ["老人的原话"]


async def test_fork_scope_sees_parent_then_self_in_seq_order(ctx, sid):
    """fork 的作用域是 ``[父, 己]``，按 seq 交织成一段连贯历史。"""
    log = ctx.event_log
    log.append(sid, None, USER_MESSAGE, {"text": "老人的原话"}, agent_id=MAIN_SCOPE)
    log.append(sid, None, USER_MESSAGE, {"text": "派给出行的指令"},
               agent_id="travel#1")

    forked = log.derive_messages(sid, scopes=[MAIN_SCOPE, "travel#1"])
    assert [m["content"] for m in forked] == ["老人的原话", "派给出行的指令"]


async def test_a_scope_does_not_borrow_a_siblings_tool_results(ctx, sid):
    """兄弟的调用与结果都不进我的历史 —— 并发扇出时不串味。"""
    log = ctx.event_log
    _declare(log, sid, [{"id": "t1", "name": "search_train", "arguments": {}}],
             scope="travel#1")
    _settle(log, sid, "t1", scope="travel#1")
    _declare(log, sid, [{"id": "h1", "name": "search_hospital", "arguments": {}}],
             scope="health#1")
    _settle(log, sid, "h1", scope="health#1")

    travel = log.derive_messages(sid, scopes=["travel#1"])
    assert [c["id"] for c in travel[0]["tool_calls"]] == ["t1"]
    assert [m["tool_call_id"] for m in travel if m["role"] == "tool"] == ["t1"]
    assert log.derive_messages(sid, scopes=[MAIN_SCOPE]) == []
    assert log.derive_messages(sid, scopes=["travel#2"]) == []


# ------------------------------------------------------------------ 伴随不变式


async def test_invariants_catch_a_silently_dropped_tool_call(ctx, sid):
    """已结束的轮次里有声明没结果 = 工具调用被静默丢弃（缺陷 #7 的探测器）。"""
    log = ctx.event_log
    log.append(sid, None, TURN_START, {"agent": "travel"}, turn_id="turn_x")
    log.append(sid, None, ASSISTANT_MESSAGE,
               {"text": "", "tool_calls": [{"id": "c1", "name": "book_ticket",
                                            "arguments": {}},
                                           {"id": "c2", "name": "get_weather",
                                            "arguments": {}}]},
               turn_id="turn_x")
    log.append(sid, None, TOOL_RESULT, {"call_id": "c1", "content": "{}"},
               turn_id="turn_x")
    log.append(sid, None, TURN_END, {"stop_reason": "model/idle"}, turn_id="turn_x")

    problems = log.check_invariants(sid)
    assert any("静默丢弃" in p and "c2" in p for p in problems)
    with pytest.raises(InvariantViolation):
        log.assert_invariants(sid)


async def test_invariants_catch_a_result_landing_in_the_wrong_scope(ctx, sid):
    """调用声明在哪个作用域，结果就得落在哪个作用域 —— 否则采集会认错东家。"""
    log = ctx.event_log
    _declare(log, sid, [{"id": "c1", "name": "book_ticket", "arguments": {}}],
             scope="travel#1")
    _settle(log, sid, "c1", scope="health#1")

    assert any("跨作用域" in p for p in log.check_invariants(sid))


async def test_invariants_catch_a_result_without_a_declaration(ctx, sid):
    log = ctx.event_log
    _settle(log, sid, "凭空出现的 id")
    assert any("没有对应的调用声明" in p for p in log.check_invariants(sid))


def test_sse_names_translate_to_durable_types_in_one_place():
    """前端线格式与内核词表由 ``durable_type`` 单点翻译，没登记的进 ext/。"""
    assert durable_type("tool_result") == TOOL_RESULT
    assert durable_type("report") == AGENT_REPORT
    assert durable_type("todo") == TODO_WRITE
    assert durable_type("delta") == "ext/delta"      # 过程性事件，本来不落库


# ------------------------------------------------------------ 旗舰运行后的全局校验


async def test_flagship_run_leaves_no_invariant_violation(ctx, run_turn):
    """真跑一遍旗舰场景，全套不变式必须干净。这是最有说服力的一条。"""
    sid, _ = await run_turn("我想去北京看腿疼的老毛病")
    assert ctx.event_log.check_invariants(sid) == []


async def test_every_derived_message_traces_back_to_an_event(ctx, run_turn):
    """"model-visible means logged" 的逐条落实。

    对每个作用域各派生一遍，每条消息都要能在日志里找到出处 ——
    模型看到过的东西，一定有一条事件为它负责。
    """
    sid, _ = await run_turn("我想去北京看腿疼的老毛病")
    log = ctx.event_log
    events = log.events(sid)

    logged_user = {e.payload.get("text") for e in events if e.type == USER_MESSAGE}
    logged_assistant = {e.payload.get("text") or ""
                        for e in events if e.type == ASSISTANT_MESSAGE}
    logged_results = {e.payload.get("call_id"): e.payload.get("content")
                      for e in events if e.type == TOOL_RESULT}
    scopes = sorted({e.agent_id for e in events})
    assert MAIN_SCOPE in scopes and len(scopes) >= 4, "主 + 三次派发的独立作用域"

    checked = 0
    for scope in scopes:
        for message in log.derive_messages(sid, scopes=[scope]):
            checked += 1
            if message["role"] == "user":
                assert message["content"] in logged_user
            elif message["role"] == "assistant":
                assert (message["content"] or "") in logged_assistant
                for call in message.get("tool_calls") or []:
                    # 出现在历史里 ⇒ 已结算。无主声明会让下一轮请求直接失败。
                    assert call["id"] in logged_results
            else:
                cid = message["tool_call_id"]
                assert message["content"] == logged_results[cid]
    assert checked > 10, "旗舰场景的历史不该只有零星几条"


async def test_calls_and_results_pair_one_to_one_within_a_step(ctx, run_turn):
    """全局序列里父子交错，但**同一个 step 内**调用与结果一一对应且同序。

    批处理的承诺是"有序 pre → 并发 execute → 有序 post"，所以结算顺序就是模型
    给出的顺序。挂起也算一种结算 —— 这正是缺陷 #7 的反面：旧实现在挂起处
    ``break``，同批次剩下的调用连结果都没有。
    """
    sid, _ = await run_turn("我想去北京看腿疼的老毛病")
    events = ctx.event_log.events(sid)

    declared: dict[str, list[str]] = {}
    for event in events:
        if event.type == ASSISTANT_MESSAGE and event.payload.get("tool_calls"):
            declared[event.step_id] = [c["id"]
                                       for c in event.payload["tool_calls"]]

    announced: dict[str, list[str]] = {}
    settled: dict[str, list[str]] = {}
    for event in events:
        if event.type == TOOL_CALL:
            announced.setdefault(event.step_id, []).append(
                event.payload["call_id"])
        elif event.type == TOOL_RESULT:
            settled.setdefault(event.step_id, []).append(
                event.payload["call_id"])

    assert declared, "旗舰剧本本来就有工具调用"
    assert announced == declared, "推给前端的调用与写进历史的声明必须同源同序"
    assert settled == declared, "每一格都结算，一个不落、不改序"
