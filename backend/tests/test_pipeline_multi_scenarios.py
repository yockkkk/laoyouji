"""康乐核心链路的对抗/边界场景（收敛后精简版）。

老友记时代这里是一张"仿真矩阵"：异地就医、跨城文旅、社区家政、复合协同四大场景，
外加若干极限对抗。康乐收敛为"本地就近就医"后，那四类场景要么与"就近"矛盾
（跨城文旅、异地酒店），要么整条能力已砍（社区付费下单、医院陪诊 order_service、
城际车票 book_ticket/酒店 book_hotel），旗舰主链路本身也已由 test_agents.py 逐条
验收。所以这里只留下 test_agents 覆盖不到的三条**独立接缝**：

1. **Session 水合**：会话刷新后通过 ``/api/chat/history`` 把 tool/todo/card
   完整还原（HTTP 层，不是内存假卡片），且**没有** suspend 拦截卡片 ——
   挂号当场办好，历史里再不该出现"等家人点同意"那一格。
2. **角色与称谓零反转**：通知与卡片里，母亲张桂芳 / 儿子李明 的长幼称谓
   一处都不许错；子女端收到的是"知会"而不是"待办"。
3. **多轮中断式会话**：老人挂号挂到一半突然插话问常识，不死锁、照常应答。

统一用本地就医旗舰查询"我想在南京就近看腿疼的老毛病"起头 —— 与 test_agents 同源，
产出四页计划书、零挂起、子女端一条挂号知会。
"""
from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.auth.security import create_access_token
from app.main import app


_FLAGSHIP_QUERY = "我想在南京就近看腿疼的老毛病"


def _of(events, name: str) -> list[dict]:
    return [e.data for e in events if e.event == name]


# ==============================================================================
# 边界 1: Session 刷新与水合
# ==============================================================================

async def test_edge_case_session_rehydration(ctx, elder, child, run_turn):
    """会话刷新后通过 /api/chat/history 完整水合，不回退为阶段3-4的假卡片。

    就医改成"知会不审批"后，历史里**不该再有 suspend 拦截卡片**：挂号当场办好，
    取消的正是"等家人点同意"那一格。这一条要守的仍是"刷新不丢历史"，所以改验
    tool/todo/card 是否齐全，并确认挂号那条流水水合出来是"办好了"而不是"挂起"。
    """
    session_id, events = await run_turn(_FLAGSHIP_QUERY)

    token = create_access_token(elder, ctx.settings)
    headers = {"Authorization": f"Bearer {token}"}

    from app.api.deps import get_ctx
    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/chat/history?session_id={session_id}", headers=headers)
            assert resp.status_code == 200
            data = resp.json()

            messages = data["messages"]
            kinds = [m["kind"] for m in messages]

            # 必须包含 tool, todo, card 消息；suspend 已经随"知会不审批"一起消失
            assert "tool" in kinds, "水合历史必须包含 tool 类型的流水"
            assert "todo" in kinds, "水合历史必须包含 todo 清单"
            assert "card" in kinds, "水合历史必须包含交付物计划书"
            assert "suspend" not in kinds, "挂号不再挂起，历史里不该再有拦截卡片"

            # 挂号那条流水水合成"办好了"，不是"挂起等确认"
            booking = next(m for m in messages
                           if m.get("kind") == "tool"
                           and m.get("tool") == "register_appointment")
            assert booking["status"] == "completed" and booking["ok"] is True

            # 检查 todo 清单非空且有 progress
            todo_msg = next(m for m in messages if m["kind"] == "todo")
            assert len(todo_msg["todos"]) > 0
            assert "total" in todo_msg["progress"]

            # 挂号当场办好后，历史里有两张卡：先挂号卡、后计划书。计划书照旧是四页
            card_msg = next(m for m in messages
                            if m["kind"] == "card" and m.get("type") == "trip_plan")
            assert len(card_msg.get("pages") or []) == 4
    finally:
        app.dependency_overrides.clear()


# ==============================================================================
# 边界 2: 角色与称谓零反转
# ==============================================================================

async def test_edge_case_persona_and_role_consistency(ctx, elder, child, run_turn):
    """张桂芳为母亲、李明为儿子，通知与卡片上的长幼称谓一处都不许错。

    就医改成"知会不审批"后，子女端收到的不是"待办"而是"知会"：旗舰剧本跑完不该
    留下任何待确认的确认任务，而应有一条 ``appointment_notice``。称谓照样得对 ——
    这条通知写给谁、说谁，一个都不能反。
    """
    assert elder["name"] == "张桂芳" and elder.get("relation_to_child") == "母亲"
    assert child["name"] == "李明" and child.get("relation_to_elder") == "儿子"

    session_id, events = await run_turn(_FLAGSHIP_QUERY)

    # 知会不是审批：旗舰剧本跑完，子女那边**没有**待确认的待办
    assert await ctx.confirmation.list_for_child(child["id"], status="pending") == []

    # 通知库里有一条挂号知会：说的是张桂芳的事、写给李明，称谓不许反转
    notifs = await ctx.repos.list("notifications", where={"user_id": child["id"]})
    notices = [n for n in notifs if n.get("type") == "appointment_notice"]
    assert notices, "挂号办好了必须给子女写一条知会"
    assert all(n.get("elder_id") == elder["id"] for n in notices)
    for n in notifs:
        title = n.get("title", "")
        assert "张桂芳" in title
        assert "儿子张桂芳" not in title and "母亲李明" not in title

    # 老人端称谓也照旧：挂号卡上写的是"已告诉您儿子李明"，不是别的称呼
    card = next(c for c in _of(events, "card") if c.get("type") == "appointment")
    assert "您儿子李明" in card["body"]["家人知会"]


# ==============================================================================
# 边界 3: 多轮中断式会话不卡死
# ==============================================================================

async def test_edge_case_interruptive_turn(ctx, elder, child, run_turn):
    """老人在挂号途中突然插话问常识，系统自如响应且不造成死锁。"""
    session_id, events1 = await run_turn(_FLAGSHIP_QUERY)

    # 中途突然问一句和本轮任务无关的常识
    session_id, events2 = await run_turn("对了，老年人坐高铁二等座可以带保温杯吗？")
    types2 = [e.event for e in events2]
    assert "final" in types2 or "agent_msg" in types2
    assert len(events2) > 0
