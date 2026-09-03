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
