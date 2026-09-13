"""智能体全链路测试：MockLLM 驱动本地就医旗舰场景。

康乐收敛为"本地就近就医"后，旗舰剧本（"我想在南京就近看腿疼的老毛病"）的
确定性时序，是这套测试的全部依据：

  主 wave0  todo_write + delegate([health 挂号, travel 查天气])       ← 并行两支
    health  search_hospital → register_appointment（当场办好，办完知会子女）
    travel  get_weather
  主 wave1  todo_write + delegate([travel 规划从家怎么去医院])
    travel  plan_route（本地公交/打车，routes.json 里命中"家→南京鼓楼医院"）
  主 wave2  todo_write + compose_deliverable(trip_plan, city=南京)
  主 wave3  收尾的一句话

所以这些东西是**可数的**：0 次挂起（就医知会不审批 —— 挂号当场办好、不挂起，
本地就医仅剩的那件"涉钱的事"也已移出高危集）、3 份 ``agent/report``
（health×1 + travel×2）、子女端一条 ``appointment_notice`` 知会、四页计划书。
城际车票/异地酒店整条砍掉，对应的两页（去程车票、酒店）连同
book_ticket/book_hotel 一并不再出现。下面每条断言都对着架构里的一条承诺，
不是对着实现细节。
"""
from __future__ import annotations

from app.agents import plan_builder
from app.core.context import TurnContext
from app.core.events import AGENT_REPORT, TODO_WRITE
from app.core.subagents import AgentReport


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
    _, events = await run_turn("我想在南京就近看腿疼的老毛病")
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
                     "get_weather", "plan_route",                 # 出行（两支）
                     "compose_deliverable"):                      # 交付
        assert expected in tool_calls, f"缺少工具调用 {expected}"
    # 城际那套已砍：这些工具名一个都不该再冒出来
    for gone in ("search_train", "book_ticket", "search_hotel", "book_hotel"):
        assert gone not in tool_calls, f"{gone} 属于已砍的城际出行，不该再调"

    # 3. 就医知会不审批（红线 R5 收敛为只管钱）：旗舰剧本里**一条挂起都没有** ——
    #    挂号当场办好，不再拦下来等家人点同意。
    assert _of(events, "suspended") == []
    # 挂号那一条调用以成功收尾（ok=True、没有被挂起），不是被拦下的
    booking = next(r for r in _of(events, "tool_result")
                   if r["tool"] == "register_appointment")
    assert booking["ok"] is True and not booking.get("suspended")

    # 4. 每次调用都恰好结算一条结果（缺陷 #7）：这里比的是**集合**而不是顺序
    #    —— 子助理的调用是在父的 delegate 执行过程中发生的，所以全局序列里
    #    父的 call 和 result 之间夹着子的一整段。
    results = _of(events, "tool_result")
    assert sorted(r["call_id"] for r in results) == sorted(
        c["call_id"] for c in _of(events, "tool_call"))
    # 挂号与并发的 get_weather 都照常跑完（挂号不再挂起，谁也不等谁）
    assert any(r["tool"] == "get_weather" and r["ok"] for r in results)
    assert booking["ok"] is True

    # 5. 真多智能体：三份结构化回报，两个子助理，各自独立作用域
    reports = _of(events, "report")
    assert len(reports) == 3
    agents = [r["agent"] for r in reports]
    assert agents.count("travel") == 2 and agents.count("health") == 1
    assert len({r["scope"] for r in reports}) == 3, "每次派活都是独立作用域"
    assert all(r["suspended"] or r["ok"] for r in reports)

    # 6. 计划书：四页、页序写死（城际车票页与酒店页随城际出行一起撤掉）
    cards = _of(events, "card")
    assert cards, "应输出《就医出行计划书》卡片"
    card = cards[-1]
    assert card["type"] == "trip_plan"
    assert card["title"] == f"{elder['name']} · 南京就医出行计划书"
    assert card["printable"] is True
    assert [p["no"] for p in card["pages"]] == [1, 2, 3, 4]
    assert [p["title"] for p in card["pages"]] == [
        "第一页 · 挂号信息",
        "第二页 · 怎么去医院",
        "第三页 · 随身清单（出门前一样一样对）",
        "第四页 · 南京天气与穿衣",
    ]
    # 行李清单是政策模板，方案书原文点名的五样必须在（清单现在是第三页）
    checklist = " ".join(_rows(card, 3).values())
    for item in ("身份证", "医保卡", "既往病历", "老花镜", "常备药"):
        assert item in checklist

    # 7. 字段来自子回报，不是模型复述 —— 答辩时逐条指认的就是这几行
    data = plan_builder.merge_reports([AgentReport.from_dict(r) for r in reports])
    page1, page2 = _rows(card, 1), _rows(card, 2)
    assert page1["医院"] == data["appointment"]["hospital"] == "南京鼓楼医院"
    assert page1["科室"] == data["appointment"]["department"] == "骨科"
    assert page1["医生"] == data["appointment"]["doctor"] == "邱勇"
    assert page1["挂号费"] == f"{data['appointment']['fee']} 元" == "70 元"
    # 医院地址不在冻结的挂号参数里，是按医院名从同一批 search_hospital 结果连回来的
    assert page1["医院地址"] and page1["医院地址"] != plan_builder.MISSING
    # 第二页"到哪儿"两条路径（route.destination / appointment.hospital）都指向鼓楼医院
    assert page2["从哪儿出发"] == data["route"]["origin"]
    assert page2["到哪儿"] == "南京鼓楼医院"
    assert page2["怎么走"] == data["route"]["mode"]

    # 8. 相对日期要换成老人看得懂的写法："+1" 印在纸上等于没印
    assert "+" not in page1["就诊时间"] and "（周" in page1["就诊时间"]

    # 9. 挂号当场办好，纸上就照实写"已办好" —— 不再有"等家人点同意"那一格
    assert page1["状态"] == "已办好"

    # 10. 缺字段策略：待补的行与 missing 清单严格一一对应（不多写也不漏报）
    missing_rows = [r for p in card["pages"] for r in p["rows"] if r["missing"]]
    assert all(r["value"] == plan_builder.MISSING for r in missing_rows)
    assert len(missing_rows) == len(card["missing"])
    assert card["complete"] is (not card["missing"])
    # 家→南京鼓楼医院在 routes.json 里是命中的市内线，每个字段都连得上 —— 满页
    assert card["missing"] == []

    # 11. 免责声明与模拟数据披露必须留在交付物上
    assert "不构成诊断" in card["disclaimer"]
    assert "模拟接口" in card["footnote"]

    # 12. 就医知会不审批：**没有**待确认的确认任务 —— 挂号件事当场办完了，
    #     子女端收到的不是"有件事等你办"，而是"知道了一件事"
    assert await ctx.repos.list("confirmation_tasks") == []
    assert await ctx.confirmation.list_for_child(child["id"], status="pending") == []

    # 13. 取而代之的是给子女的那条知会：完整、写给对人、不重复
    notices = await ctx.repos.list(
        "notifications", where={"user_id": child["id"], "type": "appointment_notice"})
    assert len(notices) == 1, "挂号办好了就写一条知会，且不叠第二张"
    notice = notices[0]
    assert notice["elder_id"] == elder["id"], "知会说的是这位老人的事"
    assert "张桂芳" in notice["title"]
    assert notice["is_read"] is False
    # 完整：哪天、哪位医生、多少钱、为什么去，一样不少（子女只能看到这一条）
    assert notice["data"]["hospital"] == "南京鼓楼医院"
    assert notice["data"]["doctor"] == "邱勇"
    assert notice["data"]["registration_no"]
    assert "去的原因" in notice["summary"]

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
    session_id, events = await run_turn("我想在南京就近看腿疼的老毛病")
    card = _of(events, "card")[-1]

    reports = _reports_in(ctx.event_log, session_id)
    assert len(reports) == 3

    again = plan_builder.build("trip_plan", elder, reports,
                               city="南京", today=card["generated_on"])
    assert again == card

    # 进度快照也在日志里 —— 刷新页面能还原，不是前端内存
    assert len([e for e in ctx.event_log.events(session_id)
                if e.type == TODO_WRITE]) == 3


async def test_missing_route_report_renders_placeholder(ctx, elder, run_turn):
    """人为抽掉路线那一项 → 第二页的走法字段写"待补"，绝不编造（缺陷 #5 的反面）。

    收敛后能被抽掉的"选定项"是路线（城际车票/酒店已整条砍掉）。抽掉 route 之后，
    第二页除了兜底还能取到的目的地（挂号医院）之外，"怎么走""大概多久"这些只有
    ``plan_route`` 才产出的字段该落"待补" —— 而挂号页、清单页、天气页不受牵连。
    少一行写"待补"，绝不少一整页。
    """
    session_id, _ = await run_turn("我想在南京就近看腿疼的老毛病")
    reports = _reports_in(ctx.event_log, session_id)
    assert any("route" in r.data for r in reports), "旗舰剧本本来是有路线的"

    # 只摘掉"选定的路线"，天气和挂号都留着：验证缺字段是**局部**的
    stripped = [AgentReport.from_dict(
        {**r.to_dict(), "data": {k: v for k, v in r.data.items() if k != "route"}})
        for r in reports]

    card = plan_builder.build("trip_plan", elder, stripped, city="南京")
    page2 = _rows(card, 2)
    # 目的地还能从挂号医院兜底取到，但走法/时长这种只有 route 才有的字段该"待补"
    for label in ("怎么走", "大概多久"):
        assert page2[label] == plan_builder.MISSING, f"{label} 不该被编出来"
    assert "route.mode" in card["missing"]
    assert card["complete"] is False

    # 页数不因为缺字段而变少：少一页比写"待补"更容易被漏掉
    assert len(card["pages"]) == 4
    # 其余各页不受牵连
    assert _rows(card, 1)["医院"] != plan_builder.MISSING
    assert _rows(card, 4)["天气"] != plan_builder.MISSING


# ------------------------------------------------------------------ 安全中间层


async def test_health_disclaimer_injected(ctx, elder):
    """红线 R4：健康域工具输出强制带免责声明（不依赖 LLM 自觉）。"""
    turn = TurnContext(ctx=ctx, session_id="s-disc", user=elder)
    result = await ctx.dispatcher.execute(turn, "diet_advice", {"preference": "清淡"})
    assert result["ok"] is True
    assert "遵医嘱" in result.get("summary", "") or "不能替代" in result.get("summary", "")


async def test_scam_denied_by_guard(ctx, elder):
    """反诈：疑似诈骗内容的操作被 DENY（红线 R5 的上游）。

    收敛后 canteen_order 已砍，改用仍在册的 add_medication 承载"神药根治"话术 ——
    ScamContentRule 扫的是参数文本，用哪个在册工具触发都一样，重点是 DENY + 给建议。
    """
    turn = TurnContext(ctx=ctx, session_id="s-scam", user=elder)
    result = await ctx.dispatcher.execute(
        turn, "add_medication", {"drug_name": "保健品神药根治骨关节炎"})
    assert result.get("denied") is True
    assert "advice" in result


# ------------------------------------------------------------------ 社区支线


async def test_community_agent_route(ctx, elder, run_turn):
    """社区支线（心理·社交）：一波扇出就够，不出计划书。

    收敛后邻里帮从"付费下单"转成"推线下活动"：push_activities 只把活动列表结构化
    回报上来，既不涉钱（无挂起），也不自动出计划书（compose_deliverable 不调）。
    """
    _, events = await run_turn("帮我找找最近社区有什么活动")
    tool_calls = [e["tool"] for e in _of(events, "tool_call")]
    assert "delegate" in tool_calls
    assert "push_activities" in tool_calls
    assert "compose_deliverable" not in tool_calls

    assert [r["agent"] for r in _of(events, "report")] == ["community"]
