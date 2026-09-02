"""智能体全链路测试：MockLLM 驱动旗舰场景。

旗舰剧本（"我想去北京看腿疼的老毛病"）的确定性时序，是这套测试的全部依据：

  主 step1  todo_write + delegate([health 查医院挂号, travel 查票订票])   ← 并行
    health  search_hospital → register_appointment（高危，挂起）
    travel  search_train    → book_ticket（高危，挂起）
  主 step2  todo_write + delegate([travel 订医院附近的酒店 + 看天气])
    travel  search_hotel → book_hotel（高危，挂起）→ get_weather
  主 step3  todo_write + compose_deliverable(trip_plan, city=北京)
  主 step4  收尾的一句话

所以三样东西是**可数的**：3 次挂起、3 份 ``agent/report``、五页计划书。
下面每条断言都对着架构里的一条承诺，不是对着实现细节。
"""
from __future__ import annotations

from app.agents import plan_builder
from app.core.context import TurnContext
from app.core.events import AGENT_REPORT, TODO_WRITE
from app.core.subagents import AgentReport
from app.safety.risk_rules import HIGH_RISK_TOOLS


def _of(events, name: str) -> list[dict]:
    return [e.data for e in events if e.event == name]


def _rows(card: dict, page_no: int) -> dict[str, str]:
    page = next(p for p in card["pages"] if p["no"] == page_no)
    return {r["label"]: r["value"] for r in page["rows"]}


def _reports_in(log, session_id: str) -> list[AgentReport]:
    return [AgentReport.from_dict(e.payload)
            for e in log.events(session_id) if e.type == AGENT_REPORT]


# ------------------------------------------------------------------ 旗舰全链路


async def test_flagship_scenario_full_chain(ctx, elder, child, run_turn):
    _, events = await run_turn("我想去北京看腿疼的老毛病")
    types = [e.event for e in events]

    # 1. 真进度：todo 是整列表覆盖写的快照序列，不是前端内存里的假进度条
    todos = _of(events, "todo")
    assert len(todos) == 3, "每派完一波都该重写一次清单"
    assert any("医院" in t["content"] or "挂号" in t["content"]
               for t in todos[0]["todos"])
    assert all(len(t["todos"]) == len(todos[0]["todos"]) for t in todos), \
        "整张清单一起重写，条数不该变"
    done = [t["progress"]["done"] for t in todos]
    assert done == sorted(done), "进度只增不减"
    assert done[0] == 0 and done[-1] >= 2

    # 2. 工具调用可见，且**父子两层都在**：delegate 是父的，search_* 是子的
    assert "tool_call" in types and "tool_result" in types
    tool_calls = [e["tool"] for e in _of(events, "tool_call")]
    assert tool_calls.count("delegate") == 2          # 两波扇出
    for expected in ("search_hospital", "register_appointment",   # 健康
                     "search_train", "book_ticket",               # 出行①
                     "search_hotel", "book_hotel", "get_weather",  # 出行②
                     "compose_deliverable"):                      # 交付
        assert expected in tool_calls, f"缺少工具调用 {expected}"

    # 3. 高危拦截：三件涉钱的事一件都没漏（红线 R5）
    suspended = _of(events, "suspended")
    assert len(suspended) == 3
    # 拦下来的恰好是"高危集合 ∩ 本轮调用" —— 不多拦一件，也不少拦一件
    assert {s["tool"] for s in suspended} == HIGH_RISK_TOOLS & set(tool_calls)
    assert {s["tool"] for s in suspended} == {
        "register_appointment", "book_ticket", "book_hotel"}

    # 4. 挂起不吞掉同批次的其它调用（缺陷 #7）：每次调用都恰好结算一条结果。
    #    这里比的是**集合**而不是顺序 —— 子助理的调用是在父的 delegate 执行
    #    过程中发生的，所以全局序列里父的 call 和 result 之间夹着子的一整段。
    results = _of(events, "tool_result")
    assert sorted(r["call_id"] for r in results) == sorted(
        c["call_id"] for c in _of(events, "tool_call"))
    # 同一批里 book_hotel 被拦下，紧随其后的 get_weather 照样跑完
    assert any(r["tool"] == "get_weather" and r["ok"] for r in results)

    # 5. 真多智能体：三份结构化回报，两个子助理，各自独立作用域
    reports = _of(events, "report")
    assert len(reports) == 3
    agents = [r["agent"] for r in reports]
    assert agents.count("travel") == 2 and agents.count("health") == 1
    assert len({r["scope"] for r in reports}) == 3, "每次派活都是独立作用域"
    assert all(r["suspended"] or r["ok"] for r in reports)

    # 6. 计划书：五页、页序写死（方案书第三步 20 分的可验收形态）
    cards = _of(events, "card")
    assert cards, "应输出《就医出行计划书》卡片"
    card = cards[-1]
    assert card["type"] == "trip_plan"
    assert card["title"] == f"{elder['name']} · 北京就医出行计划书"
    assert card["printable"] is True
    assert [p["no"] for p in card["pages"]] == [1, 2, 3, 4, 5]
    assert [p["title"] for p in card["pages"]] == [
        "第一页 · 挂号信息",
        "第二页 · 去程车票 + 返程建议",
        "第三页 · 酒店信息",
        "第四页 · 随身清单（出门前一样一样对）",
        "第五页 · 北京天气与穿衣",
    ]
    # 行李清单是政策模板，方案书原文点名的五样必须在
    checklist = " ".join(_rows(card, 4).values())
    for item in ("身份证", "医保卡", "既往病历", "老花镜", "常备药"):
        assert item in checklist

    # 7. 字段来自子回报，不是模型复述 —— 答辩时逐条指认的就是这几行
    data = plan_builder.merge_reports([AgentReport.from_dict(r) for r in reports])
    page1, page2, page3 = _rows(card, 1), _rows(card, 2), _rows(card, 3)
    assert page1["医院"] == data["appointment"]["hospital"]
    assert page1["医生"] == data["appointment"]["doctor"]
    assert page1["挂号费"] == f"{data['appointment']['fee']} 元"
    assert page2["车次"] == data["ticket"]["train_no"]
    assert page2["票价"] == f"{data['ticket']['price']} 元"
    assert page2["座位"] == data["ticket"]["seat_type"]
    assert page3["酒店"] == data["hotel"]["hotel"]
    # 地址/电话/房价都不在冻结参数里，是按酒店名从同一批 search 结果连回来的
    hotel_pick = next(h for h in data["hotel_options"]["hotels"]
                      if h["name"] == data["hotel"]["hotel"])
    assert page3["地址"] == hotel_pick["address"]
    assert page3["电话"] == hotel_pick["phone"]
    assert str(hotel_pick["price"]) in page3["房费"]

    # 8. 相对日期要换成老人看得懂的写法："+3" 印在纸上等于没印
    assert "+" not in page1["就诊时间"] and "（周" in page1["就诊时间"]
    assert page2["乘车日期"] != "tomorrow" and "（周" in page2["乘车日期"]
    assert page3["入住日期"] != "tomorrow"

    # 9. 三件高危项都还挂着，纸上就得照实写"等家人点同意"，不能写"已办好"
    for rows in (page1, page2, page3):
        assert "等家人" in rows["状态"]

    # 10. 缺字段策略：待补的行与 missing 清单严格一一对应（不多写也不漏报）
    missing_rows = [r for p in card["pages"] for r in p["rows"] if r["missing"]]
    assert all(r["value"] == plan_builder.MISSING for r in missing_rows)
    assert len(missing_rows) == len(card["missing"])
    assert card["complete"] is (not card["missing"])
    # 这一版每个字段都连得上，所以旗舰演示是满页的
    assert card["missing"] == []

    # 11. 免责声明与模拟数据披露必须留在交付物上
    assert "不构成诊断" in card["disclaimer"]
    assert "模拟接口" in card["footnote"]

    # 12. 三个确认任务已入库且 pending
    pending = await ctx.confirmation.list_for_child(child["id"], status="pending")
    assert len(pending) == 3

    # 13. 子女批准 → 冻结调用重放执行
    for task in pending:
        result = await ctx.confirmation.approve_and_execute(
            task["id"], ctx, child["id"])
        assert result["ok"] is True, f"{task['tool_name']} 重放失败：{result}"
        assert result["status"] == "executed"
    assert await ctx.confirmation.list_for_child(child["id"], status="pending") == []

    # 14. 计划书已建档为行程（也是行程守护的起点）
    trips = await ctx.repos.list("trips", where={"elder_id": elder["id"]})
    assert len(trips) == 1
    assert trips[0]["plan"]["title"].endswith("计划书")
    assert trips[0]["status"] == "planned"


async def test_flagship_deliverable_is_replayable_from_log(ctx, elder, run_turn):
    """交付物的输入只有事件日志一个来源，所以可以脱离本次运行重放出同一份。

    这是"可逐条指认"的实际含金量：把日志里的 ``agent/report`` 读回来重渲染，
    得到的是同一份卡片 —— 而不是"模型第二次又编了一版"。
    """
    session_id, events = await run_turn("我想去北京看腿疼的老毛病")
    card = _of(events, "card")[-1]

    reports = _reports_in(ctx.event_log, session_id)
    assert len(reports) == 3

    again = plan_builder.build("trip_plan", elder, reports,
                               city="北京", today=card["generated_on"])
    assert again == card

    # 进度快照也在日志里 —— 刷新页面能还原，不是前端内存
    assert len([e for e in ctx.event_log.events(session_id)
                if e.type == TODO_WRITE]) == 3


async def test_missing_hotel_report_renders_placeholder(ctx, elder, run_turn):
    """人为抽掉酒店那一项 → 第三页写"待补"，绝不编造（缺陷 #5 的反面验收）。"""
    session_id, _ = await run_turn("我想去北京看腿疼的老毛病")
    reports = _reports_in(ctx.event_log, session_id)
    assert any("hotel" in r.data for r in reports), "旗舰剧本本来是有酒店的"

    # 只摘掉"选定的酒店"，天气和候选列表都留着：验证缺字段是**局部**的
    stripped = [AgentReport.from_dict(
        {**r.to_dict(), "data": {k: v for k, v in r.data.items() if k != "hotel"}})
        for r in reports]

    card = plan_builder.build("trip_plan", elder, stripped, city="北京")
    page3 = _rows(card, 3)
    for label in ("酒店", "地址", "电话", "入住日期", "房费"):
        assert page3[label] == plan_builder.MISSING, f"{label} 不该被编出来"
    assert "hotel.hotel" in card["missing"] and "hotel.total" in card["missing"]
    assert card["complete"] is False

    # 页数不因为缺字段而变少：少一页比写"待补"更容易被漏掉
    assert len(card["pages"]) == 5
    # 其余各页不受牵连
    assert _rows(card, 1)["医院"] != plan_builder.MISSING
    assert _rows(card, 2)["车次"] != plan_builder.MISSING
    assert _rows(card, 5)["天气"] != plan_builder.MISSING
    # 第四页那条"带上酒店订单"是有酒店才加的，现在就该不在
    assert "酒店订单" not in " ".join(_rows(card, 4).values())


# ------------------------------------------------------------------ 安全中间层


async def test_health_disclaimer_injected(ctx, elder):
    """红线 R4：健康域工具输出强制带免责声明（不依赖 LLM 自觉）。"""
    turn = TurnContext(ctx=ctx, session_id="s-disc", user=elder)
    result = await ctx.dispatcher.execute(turn, "diet_advice", {"preference": "清淡"})
    assert result["ok"] is True
    assert "遵医嘱" in result.get("summary", "") or "不能替代" in result.get("summary", "")


async def test_scam_denied_by_guard(ctx, elder):
    """反诈：疑似诈骗内容的操作被 DENY。"""
    turn = TurnContext(ctx=ctx, session_id="s-scam", user=elder)
    result = await ctx.dispatcher.execute(
        turn, "canteen_order", {"menu_item": "神药保健品根治套餐"})
    assert result.get("denied") is True
    assert "advice" in result


async def test_canteen_small_order_auto_allowed(ctx, elder):
    """小额订餐（<阈值）不拦截，直接下单 —— 展示分级管控。"""
    turn = TurnContext(ctx=ctx, session_id="s-canteen", user=elder)
    result = await ctx.dispatcher.execute(
        turn, "canteen_order", {"menu_item": "软食套餐A", "count": 1})
    assert result["ok"] is True
    assert result.get("suspended") is None


# ------------------------------------------------------------------ 社区支线


async def test_community_agent_route(ctx, elder, run_turn):
    """社区支线：一波扇出就够，不出计划书（卡片来自 canteen_order 工具本身）。"""
    _, events = await run_turn("帮我订一份中午的软食套餐")
    tool_calls = [e["tool"] for e in _of(events, "tool_call")]
    assert "delegate" in tool_calls
    assert "canteen_order" in tool_calls
    assert "compose_deliverable" not in tool_calls

    assert [r["agent"] for r in _of(events, "report")] == ["community"]

    cards = _of(events, "card")
    assert cards and cards[-1]["type"] == "canteen_order"
