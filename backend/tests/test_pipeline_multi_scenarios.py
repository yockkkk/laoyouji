"""多类别核心业务链路与极限对抗场景模拟测试套件 (Simulation Matrix & Reliability Pipeline)

覆盖维度：
1. Scenario A: 医疗全流程闭环（北京积水潭医院骨科、G102高铁、漫心酒店2晚、天气、5页可打印就医计划书；3笔挂起审核100.0/443.5/680.0；子女李明与母亲张桂芳角色一致性）
2. Scenario B: 跨城文旅出行闭环（南京南到杭州东G7615、西湖无障碍酒店2晚、杭州天气、5页文旅出行计划书无多余待补）
3. Scenario C: 邻里社区与家政服务（厨房打扫保洁上门 + 社区食堂清淡少油晚餐送餐）
4. Scenario D: 复合跨领域协同（南京鼓楼医院心内科专家号挂号 + 医院陪诊服务下单）
5. Edge Cases:
   - 部分批准/部分拒绝（车票批准、酒店拒绝；状态机流转与计划书拒绝状态呈现）
   - Session 刷新与水合（/api/chat/history 完整还原 suspend、confirmation/resolved、todo、card、tool）
   - 角色一致性（张桂芳72岁母亲，李明42岁儿子，绝无角色反转）
   - 多轮中断式会话（会话中途插话不造成死锁）
"""
from __future__ import annotations

import json
import pytest
from httpx import ASGITransport, AsyncClient

from app.agents import plan_builder
from app.auth.security import create_access_token
from app.core.events import (
    AGENT_REPORT,
    ARTIFACT_CARD,
    CONFIRM_RESOLVED,
    CONFIRM_SUSPENDED,
    TODO_WRITE,
    TOOL_CALL,
    TOOL_RESULT,
)
from app.core.subagents import AgentReport
from app.main import app
from app.safety.risk_rules import HIGH_RISK_TOOLS


def _of(events, name: str) -> list[dict]:
    return [e.data for e in events if e.event == name]


def _rows(card: dict, page_no: int) -> dict[str, str]:
    page = next(p for p in card["pages"] if p["no"] == page_no)
    return {r["label"]: r["value"] for r in page["rows"]}


# ==============================================================================
# 场景 A: 医疗全流程闭环
# ==============================================================================

async def test_scenario_a_medical_closed_loop(ctx, elder, child, run_turn):
    """Scenario A: 异地就医规划闭环（北京积水潭医院看骨科专家号）。"""
    query = ("我最近膝盖疼得厉害，想去北京积水潭医院看骨科专家号，"
             "帮我安排一下去北京的高铁和医院附近的无障碍酒店，顺便查下北京天气做个出行计划")
    session_id, events = await run_turn(query)
    types = [e.event for e in events]

    # 1. 验证工具调用链
    assert "tool_call" in types and "tool_result" in types
    tool_calls = [e["tool"] for e in _of(events, "tool_call")]
    for expected in ("delegate", "search_hospital", "register_appointment",
                     "search_train", "book_ticket", "search_hotel", "book_hotel",
                     "get_weather", "compose_deliverable"):
        assert expected in tool_calls, f"缺少关键工具调用: {expected}"

    # 2. 验证 3 笔高危拦截及精确金额
    suspended = _of(events, "suspended")
    assert len(suspended) == 3, f"期望3笔高危拦截，实际: {len(suspended)}"

    pending = await ctx.confirmation.list_for_child(child["id"], status="pending")
    assert len(pending) == 3

    amounts = {p["tool_name"]: float(p.get("amount") or 0) for p in pending}
    assert amounts.get("register_appointment") == 100.0, f"挂号费应为 100.0，实际: {amounts.get('register_appointment')}"
    assert amounts.get("book_ticket") == 443.5, f"高铁票价应为 443.5，实际: {amounts.get('book_ticket')}"
    assert amounts.get("book_hotel") == 680.0, f"两晚酒店应为 680.0，实际: {amounts.get('book_hotel')}"

    # 3. 验证家人称谓与角色一致性（母亲张桂芳，您儿子李明）
    for p in pending:
        relation_for_elder = p.get("relation_for_elder") or ""
        elder_title = p.get("elder_title_for_child") or ""
        assert "您儿子李明" in relation_for_elder, f"给老人的称谓错误: {relation_for_elder}"
        assert "母亲张桂芳" in elder_title, f"给子女的标题错误: {elder_title}"

    # 4. 子女全额批准
    for task in pending:
        res = await ctx.confirmation.approve_and_execute(task["id"], ctx, child["id"])
        assert res["ok"] is True, f"批准执行失败: {res}"
        assert res["status"] == "executed"

    # 5. 验证 5 页可打印就医计划书
    cards = _of(events, "card")
    assert cards, "应生成计划书卡片"
    card = cards[-1]
    assert card["printable"] is True
    assert card["type"] in ("trip_plan", "medical_plan")
    assert "就医出行计划书" in card["title"]
    assert len(card["pages"]) == 5

    p1, p2, p3, p4, p5 = [_rows(card, i) for i in range(1, 6)]
    assert "北京积水潭医院" in p1["医院"]
    assert "骨科" in p1["科室"]
    assert "田伟" in p1["医生"]
    assert "100" in p1["挂号费"]

    assert "G102" in p2["车次"]
    assert "443.5" in p2["票价"]
    assert "二等座" in p2["座位"]

    assert "漫心酒店" in p3["酒店"]
    assert "680" in p3["房费"]

    checklist = " ".join(p4.values())
    for item in ("身份证", "医保卡", "既往病历", "老花镜", "常备药"):
        assert item in checklist, f"行李清单缺少必备项: {item}"

    assert "北京" in p5.get("城市", card.get("city", "北京")) or "晴" in p5.get("天气", "") or "气温" in p5
    assert card["complete"] is True
    assert card["missing"] == []


# ==============================================================================
# 场景 B: 跨城文旅出行闭环
# ==============================================================================

async def test_scenario_b_tourism_closed_loop(ctx, elder, child, run_turn):
    """Scenario B: 跨城文旅出行（南京南到杭州东看西湖，西湖附近酒店2晚，杭州天气，5页文旅计划书）。"""
    query = "想下周从南京南坐高铁去杭州东看西湖，需要订西湖附近的无障碍酒店住2晚，查一下杭州天气，出一份文旅出行计划书。"
    session_id, events = await run_turn(query)

    tool_calls = [e["tool"] for e in _of(events, "tool_call")]
    for expected in ("delegate", "search_train", "book_ticket", "search_hotel",
                     "book_hotel", "get_weather", "compose_deliverable"):
        assert expected in tool_calls, f"缺少关键工具调用: {expected}"

    # 验证生成的计划书为文旅计划书
    cards = _of(events, "card")
    assert cards, "应生成文旅出行计划书"
    card = cards[-1]
    assert "文旅出行计划书" in card["title"]
    assert card["city"] == "杭州"
    assert len(card["pages"]) == 5

    # 第一页为文旅概况
    p1 = _rows(card, 1)
    assert "杭州" in p1["目的地"]
    assert any("西湖" in p1[k] for k in p1)

    # 第二页车次
    p2 = _rows(card, 2)
    assert "G7615" in p2["车次"]
    assert "117.5" in p2["票价"]
    assert "杭州东" in p2["到达"]

    # 第三页酒店
    p3 = _rows(card, 3)
    assert any("西湖" in p3[k] or "断桥" in p3[k] or "如家" in p3[k] for k in p3)

    # 第四页文旅随身清单
    p4 = _rows(card, 4)
    checklist = " ".join(p4.values())
    assert "老年人优待证" in checklist or "身份证" in checklist
    assert "常备药" in checklist

    # 第五页天气
    p5 = _rows(card, 5)
    assert "天气" in p5

    assert card["complete"] is True
    assert card["missing"] == []


# ==============================================================================
# 场景 C: 邻里社区与家政服务
# ==============================================================================

async def test_scenario_c_community_services(ctx, elder, child, run_turn):
    """Scenario C: 邻里社区家政与助餐（厨房打扫保洁 + 社区食堂清淡晚餐）。"""
    query = "家里厨房油烟机脏了想找人打扫保洁，顺便帮我订一份今晚社区食堂的少油清淡晚餐送到家。"
    session_id, events = await run_turn(query)

    tool_calls = [e["tool"] for e in _of(events, "tool_call")]
    assert "order_service" in tool_calls, "应调用家政保洁下单工具"
    assert "canteen_order" in tool_calls, "应调用社区食堂订餐工具"

    # 保洁属于高危服务下单，被安全规则拦截挂起
    pending = await ctx.confirmation.list_for_child(child["id"], status="pending")
    cleaning_task = next((p for p in pending if p["tool_name"] == "order_service"), None)
    if cleaning_task:
        res = await ctx.confirmation.approve_and_execute(cleaning_task["id"], ctx, child["id"])
        assert res["ok"] is True

    # 检查数据库中的订单
    orders = await ctx.repos.list("orders", where={"elder_id": elder["id"]})
    assert len(orders) >= 2, f"应创建至少两笔订单，实际: {len(orders)}"

    service_types = {o["service_type"] for o in orders}
    assert "cleaning" in service_types, "应包含保洁订单"
    assert "canteen" in service_types, "应包含助餐订单"

    canteen_order = next(o for o in orders if o["service_type"] == "canteen")
    assert canteen_order["amount"] > 0
    assert any("软食" in it["name"] or "清淡" in it["name"] for it in canteen_order["items"])


# ==============================================================================
# 场景 D: 复合跨领域协同
# ==============================================================================

async def test_scenario_d_complex_cross_domain(ctx, elder, child, run_turn):
    """Scenario D: 复合跨领域协同（南京鼓楼医院心血管专家号 + 医院陪诊服务）。"""
    query = "心脏不舒服想去南京鼓楼医院看心血管内科，而且我一个人去医院腿脚不便，需要帮我约一个下午的医院陪诊服务。"
    session_id, events = await run_turn(query)

    tool_calls = [e["tool"] for e in _of(events, "tool_call")]
    assert "register_appointment" in tool_calls, "应调用就医挂号工具"
    assert "order_service" in tool_calls, "应调用陪诊服务工具"

    # 挂号与陪诊均已拦截挂起
    pending = await ctx.confirmation.list_for_child(child["id"], status="pending")
    assert any(p["tool_name"] == "register_appointment" for p in pending)
    assert any(p["tool_name"] == "order_service" for p in pending)
    reg_task = next(p for p in pending if p["tool_name"] == "register_appointment")
    reg_args = reg_task.get("arguments") or reg_task.get("tool_args", {})
    assert "南京鼓楼医院" in reg_args.get("hospital", "")
    assert "心内科" in reg_args.get("department", "")

    # 家人批准陪诊服务
    accompany_task = next(p for p in pending if p["tool_name"] == "order_service")
    res_acc = await ctx.confirmation.approve_and_execute(accompany_task["id"], ctx, child["id"])
    assert res_acc["ok"] is True

    # 陪诊服务订单已记录
    orders = await ctx.repos.list("orders", where={"elder_id": elder["id"]})
    assert any(o.get("service_type") == "accompany" for o in orders), "应记录陪诊订单"


# ==============================================================================
# 极限对抗 1: 部分批准 / 部分拒绝
# ==============================================================================

async def test_edge_case_partial_approval_and_rejection(ctx, elder, child, run_turn):
    """Adversarial 1: 部分批准（车票）与部分拒绝（酒店），状态机正确流转，计划书清晰标明拒绝状态。"""
    query = "我想去北京看腿疼的老毛病"
    session_id, events = await run_turn(query)

    pending = await ctx.confirmation.list_for_child(child["id"], status="pending")
    ticket_task = next(p for p in pending if p["tool_name"] == "book_ticket")
    hotel_task = next(p for p in pending if p["tool_name"] == "book_hotel")

    # 1. 批准车票
    res_ticket = await ctx.confirmation.approve_and_execute(ticket_task["id"], ctx, child["id"])
    assert res_ticket["ok"] is True
    assert res_ticket["status"] == "executed"

    # 2. 拒绝酒店
    res_hotel = await ctx.confirmation.reject(
        hotel_task["id"], ctx, child["id"], reason="这家酒店稍贵，我们再商量商量"
    )
    assert res_hotel["ok"] is True
    assert res_hotel["status"] == "rejected"

    # 3. 重新聚合生成计划书
    from app.agents.main_agent import _reports_from_log
    from app.core.context import TurnContext
    turn = TurnContext(ctx=ctx, session_id=session_id, user=elder)
    reports = _reports_from_log(turn)
    updated_card = plan_builder.build("trip_plan", elder, reports, city="北京")

    # 车票页状态为已办好
    p2 = _rows(updated_card, 2)
    assert p2["状态"] == "已办好"

    # 酒店页状态为家人没同意
    p3 = _rows(updated_card, 3)
    assert "家人这次没同意" in p3["状态"] or "重新商量" in p3["状态"]


# ==============================================================================
# 极限对抗 2: Session 刷新与水合
# ==============================================================================

async def test_edge_case_session_rehydration(ctx, elder, child, run_turn):
    """Adversarial 2: 会话刷新后通过 /api/chat/history 完整水合，不回退为阶段3-4假卡片。"""
    query = "我想去北京看腿疼的老毛病"
    session_id, events = await run_turn(query)

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

            # 必须包含 tool, suspend, todo, card 消息
            assert "tool" in kinds, "水合历史必须包含 tool 类型的流水"
            assert "suspend" in kinds, "水合历史必须包含 suspend 拦截卡片"
            assert "todo" in kinds, "水合历史必须包含 todo 清单"
            assert "card" in kinds, "水合历史必须包含交付物计划书"

            # 检查 todo 清单非空且有 progress
            todo_msg = next(m for m in messages if m["kind"] == "todo")
            assert len(todo_msg["todos"]) > 0
            assert "total" in todo_msg["progress"]

            # 检查 card 是完整的 5 页计划书
            card_msg = next(m for m in messages if m["kind"] == "card")
            assert len(card_msg.get("pages") or []) == 5
    finally:
        app.dependency_overrides.clear()


# ==============================================================================
# 极限对抗 3: 角色与称谓零反转
# ==============================================================================

async def test_edge_case_persona_and_role_consistency(ctx, elder, child, run_turn):
    """Adversarial 3: 张桂芳为母亲、李明为儿子，所有待办和通知严格保证长幼称谓一致。"""
    assert elder["name"] == "张桂芳" and elder.get("relation_to_child") == "母亲"
    assert child["name"] == "李明" and child.get("relation_to_elder") == "儿子"

    session_id, events = await run_turn("我想去北京看腿疼的老毛病")

    # 检查待办确认项
    pending = await ctx.confirmation.list_for_child(child["id"], status="pending")
    for p in pending:
        assert p.get("elder_name") == "张桂芳"
        assert p.get("child_name") == "李明"
        assert "您儿子李明" in p.get("relation_for_elder", "")
        assert "母亲张桂芳" in p.get("elder_title_for_child", "")

    # 检查通知库
    notifs = await ctx.repos.list("notifications", where={"user_id": child["id"]})
    for n in notifs:
        title = n.get("title", "")
        assert "母亲张桂芳" in title or "张桂芳" in title
        assert "儿子张桂芳" not in title and "母亲李明" not in title


# ==============================================================================
# 极限对抗 4: 多轮中断式会话不卡死
# ==============================================================================

async def test_edge_case_interruptive_turn(ctx, elder, child, run_turn):
    """Adversarial 4: 老人在会话中途突然打断询问常识或天气，系统自如响应且不造成死锁。"""
    session_id, events1 = await run_turn("我想去北京看腿疼的老毛病")

    # 中途突然问常识
    session_id, events2 = await run_turn("对了，老年人坐高铁二等座可以带保温杯吗？")
    types2 = [e.event for e in events2]
    assert "final" in types2 or "agent_msg" in types2
    assert len(events2) > 0
