import pytest
from app.core.context import TurnContext
from app.core.events import USER_MESSAGE, ASSISTANT_MESSAGE, ARTIFACT_CARD, TODO_WRITE, CONFIRM_SUSPENDED
from app.core.bus import SESSION_FLUSH

@pytest.mark.asyncio
async def test_session_events_persistence_and_history(ctx, elder):
    session = await ctx.event_log.create_session(elder["id"], "测试用例会话")
    sid = session["id"]
    
    # 1. 模拟一个 turn 产生一系列事件
    turn = TurnContext(ctx=ctx, session_id=sid, user=elder)
    await turn.emit("user_msg", {"text": "我想去北京"})
    await turn.emit("agent_msg", {"text": "好的，正在帮您查询车票"})
    await turn.emit("todo", {"todos": [{"title": "查票", "state": "done"}], "progress": {"done": 1, "total": 1}})
    await turn.emit("card", {"type": "ticket", "title": "高铁G123"})
    await turn.emit("final", {"text": "查好了，已为您列出方案"})

    # 2. 触发 flush
    written = await ctx.event_log.flush(sid)
    assert written >= 5, f"Expected at least 5 events written, got {written}"

    # 3. 验证 session_events 表中实际落库了事件
    db_events = await ctx.repos.list("session_events", where={"session_id": sid}, order="seq")
    assert len(db_events) >= 5
    types = [e["type"] for e in db_events]
    assert "user/message" in types
    assert "assistant/message" in types

    # 4. 验证 hydrate 重新读回内存
    new_ctx_log = ctx.event_log
    new_ctx_log._events.pop(sid, None)
    new_ctx_log._hydrated.discard(sid)
    await new_ctx_log.hydrate(sid)
    hydrated = new_ctx_log.events(sid)
    assert len(hydrated) >= 5

@pytest.mark.asyncio
async def test_chat_sessions_and_history_api(ctx, elder):
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.auth.security import create_access_token

    from app.api.deps import get_ctx

    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        token = create_access_token(elder, ctx.settings)
        headers = {"Authorization": f"Bearer {token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. 创建新会话
            res = await ac.post("/api/chat/sessions/new", json={"title": "新会话测试"}, headers=headers)
            assert res.status_code == 200
            sid = res.json()["session_id"]

            # 2. 查询会话列表
            res = await ac.get("/api/chat/sessions", headers=headers)
            assert res.status_code == 200
            data = res.json()
            assert len(data["items"]) >= 1
            assert data["latest_session"]["id"] == sid

            # 3. 查询该会话的历史（初始为空）
            res = await ac.get(f"/api/chat/history?session_id={sid}", headers=headers)
            assert res.status_code == 200
            assert res.json()["messages"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_flush_is_idempotent(ctx, elder):
    """重复 flush 不该重复落库。

    确认重放、断线补写、轮次末尾三个地方都会触发 flush，
    没有去重就会撞 uq_session_events_session_seq。
    """
    session = await ctx.event_log.create_session(elder["id"], "幂等")
    sid = session["id"]
    turn = TurnContext(ctx=ctx, session_id=sid, user=elder)
    await turn.emit("user_msg", {"text": "在吗"})
    await turn.emit("final", {"text": "在的"})

    first = await ctx.event_log.flush(sid)
    second = await ctx.event_log.flush(sid)
    assert first == 2
    assert second == 0, "第二次 flush 不该再写一遍"
    assert ctx.event_log.pending_count(sid) == 0

    rows = await ctx.repos.list("session_events", where={"session_id": sid})
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_flush_retries_failed_events(ctx, elder):
    """落库失败的事件排回缓冲，下个检查点补写 —— 不能只留一行 warning 就丢了。"""
    session = await ctx.event_log.create_session(elder["id"], "重试")
    sid = session["id"]
    turn = TurnContext(ctx=ctx, session_id=sid, user=elder)
    await turn.emit("user_msg", {"text": "订张票"})

    real_many, real_one = ctx.repos.insert_many, ctx.repos.insert
    calls = {"n": 0}

    async def flaky_many(table, rows):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("模拟网络抖动")
        return await real_many(table, rows)

    async def flaky_one(table, data):
        if calls["n"] == 1 and table == "session_events":
            raise RuntimeError("模拟网络抖动")
        return await real_one(table, data)

    ctx.repos.insert_many, ctx.repos.insert = flaky_many, flaky_one
    try:
        assert await ctx.event_log.flush(sid) == 0
        assert ctx.event_log.pending_count(sid) == 1, "失败的事件必须还在缓冲里"
        assert await ctx.event_log.flush(sid) == 1
    finally:
        ctx.repos.insert_many, ctx.repos.insert = real_many, real_one

    assert ctx.event_log.pending_count(sid) == 0
    rows = await ctx.repos.list("session_events", where={"session_id": sid})
    assert [r["type"] for r in rows] == [USER_MESSAGE]


@pytest.mark.asyncio
async def test_flush_gives_up_after_max_attempts(ctx, elder):
    """一条坏事件不能永远重排队把日志刷满。"""
    session = await ctx.event_log.create_session(elder["id"], "放弃")
    sid = session["id"]
    turn = TurnContext(ctx=ctx, session_id=sid, user=elder)
    await turn.emit("user_msg", {"text": "坏事件"})

    async def always_fail(table, rows):
        raise RuntimeError("库一直写不进去")

    ctx.repos.insert_many = always_fail
    ctx.repos.insert = lambda table, data: always_fail(table, [data])
    for _ in range(ctx.event_log.MAX_FLUSH_ATTEMPTS):
        await ctx.event_log.flush(sid)
    assert ctx.event_log.pending_count(sid) == 0, "试满次数后应放弃，不再无限重排队"


@pytest.mark.asyncio
async def test_user_message_persisted_when_agent_fails(ctx, elder):
    """智能体中途抛异常，这一问也必须落库 —— flush 在 finally 里。"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_ctx
    from app.auth.security import create_access_token

    session = await ctx.event_log.create_session(elder["id"], "新对话")
    sid = session["id"]

    async def boom(turn):
        raise RuntimeError("模拟智能体崩了")

    original = ctx.agents["main"].run
    ctx.agents["main"].run = boom
    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        headers = {"Authorization": f"Bearer {create_access_token(elder, ctx.settings)}"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post("/api/chat/stream", headers=headers,
                                json={"session_id": sid, "text": "我要去北京看病"})
            assert res.status_code == 200
            body = res.text
        assert "error" in body
    finally:
        ctx.agents["main"].run = original
        app.dependency_overrides.clear()

    rows = await ctx.repos.list("session_events", where={"session_id": sid}, order="seq")
    assert [r["type"] for r in rows] == [USER_MESSAGE]
    assert rows[0]["payload"]["text"] == "我要去北京看病"

    # 顺带验证标题回填：占位的"新对话"应换成第一句话
    refreshed = await ctx.repos.get("sessions", sid)
    assert refreshed["title"] == "我要去北京看病"


@pytest.mark.asyncio
async def test_bad_session_id_is_404_not_500(ctx, elder):
    """空串 / 非 uuid 会被原样塞进 Postgres 的 uuid 列（22P02 → 500）。

    前端 storage 里的 id 是可能被清成空串的，那是"会话找不到"，不是服务器错误。
    """
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_ctx
    from app.auth.security import create_access_token

    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        headers = {"Authorization": f"Bearer {create_access_token(elder, ctx.settings)}"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            for bad in ("", "abc", "not-a-uuid"):
                res = await ac.get(f"/api/chat/history?session_id={bad}", headers=headers)
                assert res.status_code == 404, f"{bad!r} 应 404，实际 {res.status_code}"
                res = await ac.get(f"/api/sessions/{bad or 'x'}/events", headers=headers)
                assert res.status_code == 404
    finally:
        app.dependency_overrides.clear()
