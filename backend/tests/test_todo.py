"""todo/write —— "真进度"的验收：整列表覆盖、三态机、清单只活在日志里。

这是缺陷 #4 的后端一半。旧实现的进度是前端启发式：收到任意 ``tool_call`` 就把
第一个待办标成"进行中"，收到 ``tool_result`` 就标"完成"，而计划本身只活在
``chat.vue`` 的组件内存里 —— 刷新即丢，跟真实任务零绑定。

所以这些测试钉的是那件事的反面：**清单是事件**；当前清单是最后一条
``todo/write`` 的投影，不存第二份；换个进程 hydrate 回来还是它。
"""
from __future__ import annotations

from dataclasses import fields

import pytest

from app.core import todo
from app.core.events import InvariantViolation, SessionEventLog, TODO_WRITE
from app.core.todo import COMPLETED, IN_PROGRESS, PENDING, TodoError

# 旗舰剧本里总智能体写的三张快照（三次 delegate/交付各写一次）
FLAGSHIP = [
    [{"content": "选医院、挂骨科专家号", "status": IN_PROGRESS},
     {"content": "查去北京的高铁票", "status": IN_PROGRESS},
     {"content": "订医院附近的酒店", "status": PENDING},
     {"content": "出一份出行计划书", "status": PENDING}],
    [{"content": "选医院、挂骨科专家号", "status": COMPLETED},
     {"content": "查去北京的高铁票", "status": COMPLETED},
     {"content": "订医院附近的酒店", "status": IN_PROGRESS},
     {"content": "出一份出行计划书", "status": PENDING}],
    [{"content": "选医院、挂骨科专家号", "status": COMPLETED},
     {"content": "查去北京的高铁票", "status": COMPLETED},
     {"content": "订医院附近的酒店", "status": COMPLETED},
     {"content": "出一份出行计划书", "status": IN_PROGRESS}],
]


@pytest.fixture()
async def sid(ctx, elder):
    session = await ctx.event_log.create_session(elder["id"], "清单")
    return session["id"]


def _snapshot(log, session_id: str, **kw) -> list[dict]:
    return [item.to_dict() for item in todo.current(log, session_id, **kw)]


# ---------------------------------------------------------------- 形状（刻意的少）


def test_todo_item_is_deliberately_minimal():
    """harness 原样：只有 ``content`` 和三态 ``status``，**没有 id、没有 priority**。

    少这两样不是图省事。整列表覆盖写意味着条目不需要稳定身份；而 priority
    一旦可选，模型就会花步数去给待办排序 —— 那是给自己找活干，不是给老人办事。
    """
    assert [f.name for f in fields(todo.TodoItem)] == ["content", "status"]
    assert todo.STATUSES == (PENDING, IN_PROGRESS, COMPLETED)


def test_bare_strings_become_pending_items():
    """模型经常直接给一串字符串，归一化收下并落到 pending，不报错添乱。"""
    items = todo.normalize(["查医院", "  查车票  "])
    assert [i.to_dict() for i in items] == [
        {"content": "查医院", "status": PENDING},
        {"content": "查车票", "status": PENDING}]


def test_illegal_status_is_loud_not_silently_corrected():
    """状态越界直接报错。静默纠正会让"进度"变成一句没人负责的话。"""
    with pytest.raises(TodoError):
        todo.normalize([{"content": "查医院", "status": "doing"}])


def test_empty_content_and_wrong_shapes_are_loud():
    with pytest.raises(TodoError):
        todo.normalize([{"content": "   "}])
    with pytest.raises(TodoError):
        todo.normalize([123])
    with pytest.raises(TodoError):
        todo.normalize({"content": "查医院"})


# ---------------------------------------------------------------- 整列表覆盖写


async def test_whole_list_is_overwritten_not_merged(ctx, sid):
    """第二次写入整张替换第一次。last-write-wins，没有增量补丁语义。"""
    todo.write(ctx.event_log, sid, ["查医院", "查车票", "订酒店"])
    todo.write(ctx.event_log, sid, [{"content": "出计划书", "status": IN_PROGRESS}])

    assert _snapshot(ctx.event_log, sid) == [
        {"content": "出计划书", "status": IN_PROGRESS}]


async def test_current_is_a_projection_of_the_last_event(ctx, sid):
    """当前清单**就是**最后一条事件的载荷 —— 不存第二份状态，也不另开表。"""
    todo.write(ctx.event_log, sid, ["查医院"])
    todo.write(ctx.event_log, sid, [{"content": "查医院", "status": COMPLETED}])

    written = [e for e in ctx.event_log.events(sid) if e.type == TODO_WRITE]
    assert len(written) == 2, "两次写入 = 两条事件，历史只追加不就地改写"
    assert _snapshot(ctx.event_log, sid) == written[-1].payload["todos"]


async def test_no_todo_write_means_an_empty_list(ctx, sid):
    """还没写过清单就是空清单，不是 None，也不是编出来的默认三条。"""
    assert todo.current(ctx.event_log, sid) == []
    assert todo.progress([]) == {"total": 0, "done": 0, "doing": 0}


async def test_write_returns_the_normalized_list(ctx, sid):
    items = todo.write(ctx.event_log, sid, ["查医院"])
    assert [i.to_dict() for i in items] == [{"content": "查医院",
                                             "status": PENDING}]


# ---------------------------------------------------------------- 作用域


async def test_each_scope_keeps_its_own_list(ctx, sid):
    """子智能体自己也能记清单，与总智能体的那张互不覆盖。

    投影按 ``agent_id`` 过滤，所以并发的兄弟不会把彼此的进度抹掉。
    """
    todo.write(ctx.event_log, sid, ["总助手：出计划书"])
    todo.write(ctx.event_log, sid, ["出行助理：查车次"], agent_id="travel#1")

    assert _snapshot(ctx.event_log, sid) == [
        {"content": "总助手：出计划书", "status": PENDING}]
    assert _snapshot(ctx.event_log, sid, agent_id="travel#1") == [
        {"content": "出行助理：查车次", "status": PENDING}]


# ---------------------------------------------------------------- 三态推进


async def test_progress_walks_forward_across_the_flagship_snapshots(ctx, sid):
    """旗舰剧本的三张快照：总条数不变，完成数只增不减。

    "总条数不变"是整列表覆盖的可观察后果 —— 每次都重写同样四件事，
    只有状态在动。若条数变了，说明模型在悄悄改计划而不是在推进计划。
    """
    seen = []
    for snapshot in FLAGSHIP:
        todo.write(ctx.event_log, sid, snapshot)
        seen.append(todo.progress(todo.current(ctx.event_log, sid)))

    assert [p["total"] for p in seen] == [4, 4, 4]
    assert [p["done"] for p in seen] == [0, 2, 3]
    assert [p["doing"] for p in seen] == [2, 1, 1]
    assert [p["done"] for p in seen] == sorted(p["done"] for p in seen)


def test_progress_only_counts_completed_as_done():
    """``in_progress`` 不算完成。半件事写成一件事，就是假进度。"""
    items = todo.normalize([{"content": "a", "status": COMPLETED},
                            {"content": "b", "status": IN_PROGRESS},
                            {"content": "c", "status": PENDING}])
    assert todo.progress(items) == {"total": 3, "done": 1, "doing": 1}


# ---------------------------------------------------------------- 不变式与回放


async def test_illegal_status_in_the_log_trips_the_invariant(ctx, sid):
    """绕过 normalize 直接写脏状态，伴随校验必须抓到 —— 内核不靠调用方自觉。"""
    ctx.event_log.append(sid, None, TODO_WRITE,
                         {"todos": [{"content": "查医院", "status": "半拉子"}]})

    problems = ctx.event_log.check_invariants(sid)
    assert any("todo 状态非法" in p for p in problems)
    with pytest.raises(InvariantViolation):
        ctx.event_log.assert_invariants(sid)


async def test_the_list_survives_a_refresh_because_it_lives_in_the_log(ctx, sid):
    """换个进程读回来还是它 —— 这正是旧实现"刷新即丢"的反面。"""
    todo.write(ctx.event_log, sid, FLAGSHIP[-1])
    await ctx.event_log.flush(sid)

    fresh = SessionEventLog(ctx.repos)          # 相当于重启后端 / 前端刷新
    await fresh.hydrate(sid)

    assert _snapshot(fresh, sid) == FLAGSHIP[-1]
    assert todo.progress(todo.current(fresh, sid))["done"] == 3
