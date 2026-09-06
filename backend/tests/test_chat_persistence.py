import asyncio
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


@pytest.mark.asyncio
async def test_chat_history_maps_assistant_final_and_deduplicates(ctx, elder):
    """验证会话历史重放时正确映射 ASSISTANT_FINAL 事件，且完成去重。

    1. 正常轮次中 ASSISTANT_MESSAGE 与 ASSISTANT_FINAL 文本相同时：去重，只保留一条。
    2. 只有 ASSISTANT_FINAL 时（如挂起回复或直接定稿）：正确呈现在历史中，刷新页面不丢失。
    3. 存在中间状态消息与最终答复不同时：两条均按序保留。
    """
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_ctx
    from app.auth.security import create_access_token

    session = await ctx.event_log.create_session(elder["id"], "定稿去重测试")
    sid = session["id"]

    turn = TurnContext(ctx=ctx, session_id=sid, user=elder)
    # 第 1 轮：老人说话 -> 中间助手消息 -> 相同文本的 final 定稿
    await turn.emit("user_msg", {"text": "今天天气怎么样"})
    await turn.emit("agent_msg", {"text": "今天天气晴朗，气温适宜。"})
    await turn.emit("final", {"text": "今天天气晴朗，气温适宜。"})

    # 第 2 轮：老人说话 -> 只有 final 定稿（无 agent_msg）
    await turn.emit("user_msg", {"text": "明天呢"})
    await turn.emit("final", {"text": "明天有小雨，出门记得带伞。"})

    # 第 3 轮：中间消息与 final 文本不同
    await turn.emit("user_msg", {"text": "帮我看看机票"})
    await turn.emit("agent_msg", {"text": "正在为您查询南京到北京的航班…"})
    await turn.emit("final", {"text": "已为您查到3趟航班方案。"})

    await ctx.event_log.flush(sid)

    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        headers = {"Authorization": f"Bearer {create_access_token(elder, ctx.settings)}"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.get(f"/api/chat/history?session_id={sid}", headers=headers)
            assert res.status_code == 200
            data = res.json()
            messages = data["messages"]

            # 验证第 1 轮去重：只有 1 条 "今天天气晴朗，气温适宜。"
            t1_assistant = [m["text"] for m in messages if not m.get("isUser") and "今天天气" in m.get("text", "")]
            assert len(t1_assistant) == 1
            assert t1_assistant[0] == "今天天气晴朗，气温适宜。"

            # 验证第 2 轮仅 final 也成功展示（刷新不丢失）
            t2_assistant = [m["text"] for m in messages if not m.get("isUser") and "明天有小雨" in m.get("text", "")]
            assert len(t2_assistant) == 1
            assert t2_assistant[0] == "明天有小雨，出门记得带伞。"

            # 验证第 3 轮不同文本均保留
            t3_assistant = [m["text"] for m in messages if not m.get("isUser") and ("航班" in m.get("text", "") or "方案" in m.get("text", ""))]
            assert len(t3_assistant) == 2
            assert t3_assistant[0] == "正在为您查询南京到北京的航班…"
            assert t3_assistant[1] == "已为您查到3趟航班方案。"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_history_strict_authentication(ctx, elder, child):
    """验证历史接口严格鉴权：未认证 401、越权 403。"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_ctx
    from app.auth.security import create_access_token

    session = await ctx.event_log.create_session(elder["id"], "鉴权测试")
    sid = session["id"]

    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. 未提供任何认证 Header 或参数 -> 401
            res = await ac.get(f"/api/chat/history?session_id={sid}")
            assert res.status_code == 401

            # 1b. 未提供认证 Header，仅伪造 user_id 参数 -> 必须返回 401，严禁身份绕过
            res = await ac.get(f"/api/chat/history?session_id={sid}&user_id={elder['id']}")
            assert res.status_code == 401

            # 2. Token 与 user_id 不一致 -> 403
            headers_elder = {"Authorization": f"Bearer {create_access_token(elder, ctx.settings)}"}
            res = await ac.get(f"/api/chat/history?session_id={sid}&user_id=wrong-id", headers=headers_elder)
            assert res.status_code == 403

            # 3. 非本会话拥有者访问 -> 403
            headers_child = {"Authorization": f"Bearer {create_access_token(child, ctx.settings)}"}
            res = await ac.get(f"/api/chat/history?session_id={sid}", headers=headers_child)
            assert res.status_code == 403

            # 4. 拥有者正常访问 -> 200
            res = await ac.get(f"/api/chat/history?session_id={sid}", headers=headers_elder)
            assert res.status_code == 200
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_stream_client_disconnect_protection(ctx, elder):
    """测试客户端断开连接时，request.is_disconnected() 触发退出并将后台任务 detach 完整落库。"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_ctx
    from app.auth.security import create_access_token

    session = await ctx.event_log.create_session(elder["id"], "断线测试")
    sid = session["id"]

    agent_finished = asyncio.Event()

    async def slow_agent(turn):
        await asyncio.sleep(0.08)
        agent_finished.set()
        return "断线后仍然顺利完成定稿"

    original = ctx.agents["main"].run
    ctx.agents["main"].run = slow_agent
    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        headers = {"Authorization": f"Bearer {create_access_token(elder, ctx.settings)}"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            async with ac.stream(
                "POST", "/api/chat/stream", headers=headers,
                json={"session_id": sid, "text": "查查降压药"},
            ) as res:
                assert res.status_code == 200
                async for line in res.aiter_lines():
                    if "session" in line:
                        break
                # 读取到 session 事件后立即跳出 context，模拟客户端主动断开连接

        # 客户端连接已关闭，等待后台 detached 任务跑完
        await asyncio.wait_for(agent_finished.wait(), timeout=2.0)
        # 给 flush 让出事件循环
        await asyncio.sleep(0.05)

        # 验证断线后事件依然完整落库
        rows = await ctx.repos.list("session_events", where={"session_id": sid}, order="seq")
        types = [r["type"] for r in rows]
        assert "user/message" in types
        assert "assistant/final" in types

        # 再次通过 /api/chat/history 获取，验证刷新可恢复完整会话
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            h_res = await ac.get(f"/api/chat/history?session_id={sid}", headers=headers)
            assert h_res.status_code == 200
            msgs = h_res.json()["messages"]
            assert any(m.get("text") == "断线后仍然顺利完成定稿" for m in msgs)
    finally:
        ctx.agents["main"].run = original
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_stream_session_cross_user_forbidden(ctx, elder, child):
    """验证流式接口中，跨用户越权向他人 session 注入对话被严格拦截 (403 Forbidden)。"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_ctx
    from app.auth.security import create_access_token

    session = await ctx.event_log.create_session(elder["id"], "老人私密会话")
    sid = session["id"]

    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        # child 尝试向 elder 的 session 发送流式对话消息
        headers_child = {"Authorization": f"Bearer {create_access_token(child, ctx.settings)}"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                "/api/chat/stream",
                headers=headers_child,
                json={"session_id": sid, "text": "尝试越权写入"},
            )
            assert res.status_code == 403
            assert "无权访问该会话" in res.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_chat_stream_unowned_session_forbidden(ctx, elder):
    """验证流式接口中，访问无主或缺失 user_id 的异常会话被严格拦截 (403 Forbidden)。"""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_ctx
    from app.auth.security import create_access_token

    session = await ctx.repos.insert("sessions", {"title": "无主会话", "user_id": None})
    sid = session["id"]

    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        headers = {"Authorization": f"Bearer {create_access_token(elder, ctx.settings)}"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            res = await ac.post(
                "/api/chat/stream",
                headers=headers,
                json={"session_id": sid, "text": "尝试访问无主会话"},
            )
            assert res.status_code == 403
            assert "无权访问该会话" in res.text
    finally:
        app.dependency_overrides.clear()


