"""交付物渲染管线：确定性、缺字段不编造、三份交付物共用一份 report 输入。

这些测试不碰模型、不碰数据库、不碰事件总线 —— 全是纯函数。方案书第三步那 20 分
压在这条管线上，所以它必须能在答辩现场当场跑、当场改一个字段看结果变化。

康乐收敛为本地就医后，计划书从旧的五页（城际车票 + 异地酒店）改成四页：
①挂号 ②怎么去（本地公交/步行/打车）③随身清单 ④当地天气。城际、酒店整条砍掉。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.agents import plan_builder
from app.agents.plan_builder import MISSING
from app.core.subagents import AgentReport

TODAY = "2026-03-05"          # 周四，写死好让"（周X）"可断言


def _report(agent: str, data: dict, **kw) -> AgentReport:
    return AgentReport(agent=agent, ok=True, summary="", data=data, **kw)


# 每个用例现做一份 report，避免跨用例共享可变 dict（_enrich 会就地回填）。

def _health_report(**over) -> AgentReport:
    """健康支线的回报：查医院的候选 + 被拦下的挂号（冻结参数，等家人确认）。

    ``**over`` 覆盖挂号（appointment）里的字段，用来构造"名字对不上""被拒"等分支。
    医院地址**不在**冻结参数里 —— 它要靠医院名从同一批 hospital_options 连回来。
    """
    appointment = {"hospital": "南京鼓楼医院", "department": "骨科",
                   "doctor": "邱勇", "date": "+1", "time": "上午 08:30", "fee": 70,
                   "status": "pending_confirm", "confirmation_id": "c-1"}
    appointment.update(over)
    return _report("health", {
        "hospital_options": {"hospitals": [{
            "hospital": "南京鼓楼医院", "city": "南京", "level": "三级甲等",
            "specialty": "本地综合三甲",
            "address": "南京市鼓楼区中山路321号",
            "department": "骨科",
            "doctors": [{"doctor": "邱勇", "title": "主任医师", "fee": 70,
                         "slots": [{"date": "+1", "time": "上午 08:30",
                                    "remaining": 15}]}],
        }], "department": "骨科"},
        "appointment": appointment,
    }, suspended=True)


def _route_report() -> AgentReport:
    """出行支线的回报：本地路线（plan_route 整包吐回，不冻结、不挂起）。"""
    return _report("travel", {
        "route": {"origin": "家", "destination": "南京鼓楼医院",
                  "mode": "市内公交或打车", "duration": "约25分钟",
                  "distance_km": 4,
                  "steps": [
                      "小区门口坐 3 路公交，坐 4 站到鼓楼站下。",
                      "下车过一个红绿灯就是医院南门，走路 5 分钟。",
                      "不想倒车就直接打车，起步价能到，15 分钟。"],
                  "summary": "从家到南京鼓楼医院：市内公交或打车，全程约25分钟。"},
    })


def _weather_report() -> AgentReport:
    """出行支线的回报：目的地天气（get_weather 整包，日期已由 provider 解析成 ISO）。"""
    return _report("travel", {
        "weather": {"city": "南京", "date": "2026-03-06", "condition": "多云",
                    "temp_low": 8, "temp_high": 16, "temp_range": "8~16 ℃",
                    "advice": "早晚凉，外面套件厚衣服", "umbrella": False},
    })


ELDER = {"id": "e-1", "name": "李秀兰", "city": "南京"}


def _plan(reports, **kw) -> dict:
    kw.setdefault("city", "南京")
    kw.setdefault("today", TODAY)
    return plan_builder.build("trip_plan", ELDER, reports, **kw)


def _all() -> list[AgentReport]:
    return [_health_report(), _route_report(), _weather_report()]


# ---------------------------------------------------------------- 页序与形态


def test_four_pages_in_the_order_the_proposal_fixed():
    """页序写死：挂号 → 怎么去 → 随身清单 → 天气。收敛后砍掉车票/酒店两页。"""
    card = _plan(_all())
    assert card["type"] == "trip_plan"
    assert card["printable"] is True
    assert card["generated_on"] == TODAY
    assert [p["no"] for p in card["pages"]] == [1, 2, 3, 4]
    assert [p["title"].split("·")[-1].strip() for p in card["pages"]] == [
        "挂号信息", "怎么去医院",
        "随身清单（出门前一样一样对）", "南京天气与穿衣"]
    assert card["title"] == "李秀兰 · 南京就医出行计划书"
    assert card["subtitle"].startswith("共 4 页")


def test_page_count_never_shrinks_when_fields_are_missing():
    """一页都不能少。少一页没人发现，写"待补"才会被看见。"""
    for reports in ([], [_health_report()], _all()):
        assert len(_plan(reports)["pages"]) == 4


def test_checklist_is_a_policy_template_not_a_query_result():
    """行李清单来自政策模板，所以它永不"待补"，连空 report 都印得出来。"""
    page3 = _plan([])["pages"][2]
    assert page3["complete"] is True
    text = " ".join(r["value"] for r in page3["rows"])
    for item in ("身份证", "医保卡", "既往病历", "老花镜", "常备药"):
        assert item in text


def test_checklist_grows_with_weather():
    """清单会按查到的天气追加条目 —— 追加项也都有出处（温度/是否有雨）。"""
    base = len(_plan([])["pages"][2]["rows"])
    with_all = _plan(_all())["pages"][2]
    text = " ".join(r["value"] for r in with_all["rows"])
    assert len(with_all["rows"]) > base
    assert "厚外套" in text          # weather.temp_low = 8 ≤ 10
    assert "伞" not in text          # umbrella=False，不该无端加一把伞


def test_checklist_adds_umbrella_only_when_it_rains():
    """有雨才加伞：来源是 weather.umbrella 布尔，不是拍脑袋。"""
    rainy = _report("travel", {"weather": {"city": "南京", "date": "2026-03-06",
                    "condition": "小雨", "temp_low": 14, "temp_high": 20,
                    "temp_range": "14~20 ℃", "advice": "带把伞", "umbrella": True}})
    text = " ".join(r["value"] for r in _plan([rainy])["pages"][2]["rows"])
    assert "伞" in text
    assert "厚外套" not in text       # temp_low = 14 > 10


# ---------------------------------------------------------------- 确定性


def test_same_input_same_output():
    """同输入同输出。演示两次不能是两个结果 —— 这是可复现的底线。"""
    first = _plan(_all())
    second = _plan(_all())
    assert first == second


def test_report_order_does_not_change_the_card():
    """并发扇出的回报到达顺序不固定，卡片不能跟着变。"""
    forward = _plan([_health_report(), _route_report(), _weather_report()])
    backward = _plan([_weather_report(), _route_report(), _health_report()])
    assert forward == backward


def test_later_report_does_not_overwrite_an_earlier_value_with_nothing():
    """先到的值不被后到的空值盖掉（merge_reports 的"先到者不被覆盖成空"）。"""
    empty = _report("travel", {"route": {}, "weather": {}})
    merged = plan_builder.merge_reports([_route_report(), empty])
    assert merged["route"]["destination"] == "南京鼓楼医院"


# ---------------------------------------------------------------- 缺字段策略


def test_empty_reports_render_all_placeholders_and_fabricate_nothing():
    """一份回报都没有时，三张查询页全是"待补"，一个字都不许编。"""
    card = _plan([])
    assert card["complete"] is False
    for page_no in (1, 2, 4):          # 第三页是政策模板，永不待补
        page = card["pages"][page_no - 1]
        assert page["complete"] is False
        assert all(r["value"] == MISSING for r in page["rows"])
    # missing 与"待补"的行严格一一对应
    flagged = [r for p in card["pages"] for r in p["rows"] if r["missing"]]
    assert len(flagged) == len(card["missing"])


def test_missing_route_only_affects_the_route_page():
    """抽掉路线，第二页"待补"，其余各页照旧 —— 缺字段是局部的。

    但"到哪儿"要优雅兜底到挂号医院（多路径取值），不能因为没查路线就连去哪都不知道。
    """
    card = _plan([_health_report(), _weather_report()])
    page2 = card["pages"][1]
    assert page2["complete"] is False
    assert "route.origin" in card["missing"]
    assert "route.mode" in card["missing"]
    to = next(r for r in page2["rows"] if r["label"] == "到哪儿")
    assert to["value"] == "南京鼓楼医院" and to["missing"] is False
    # 挂号页和天气页不受牵连
    assert card["pages"][0]["complete"] is True
    assert card["pages"][3]["complete"] is True


def test_placeholder_rows_carry_the_missing_flag_for_the_frontend():
    """前端要靠 ``missing`` 布尔画灰底虚线框，不是靠字符串比对。"""
    card = _plan([])
    for page in card["pages"]:
        for row in page["rows"]:
            assert row["missing"] is (row["value"] == MISSING)


def test_complete_mirrors_the_missing_list():
    assert _plan(_all())["complete"] is True
    assert _plan([])["complete"] is False


# ------------------------------------------------------- 连接（回填）与不编造


def test_frozen_args_are_completed_by_a_strict_identifier_join():
    """挂起时只有冻结参数；医院地址按医院名从同一批查询结果连回来。"""
    card = _plan(_all())
    page1 = {r["label"]: r["value"] for r in card["pages"][0]["rows"]}
    # 医院地址不在冻结参数里，靠医院名 join 回填
    assert page1["医院地址"] == "南京市鼓楼区中山路321号"
    # 挂号费按冻结参数照实印
    assert page1["挂号费"] == "70 元"
    assert page1["医院"] == "南京鼓楼医院"
    assert page1["医生"] == "邱勇"


def test_absent_fee_and_time_are_backfilled_from_the_matched_slot():
    """费用/时段没冻结进来时，从"医生 + 号源日期"都对得上的那条连回来。"""
    appt = _health_report()
    appt.data["appointment"].pop("fee")
    appt.data["appointment"].pop("time")
    card = _plan([appt, _route_report(), _weather_report()])
    page1 = {r["label"]: r["value"] for r in card["pages"][0]["rows"]}
    assert page1["挂号费"] == "70 元"          # 从匹配到的医生连回来
    assert page1["具体时段"] == "上午 08:30"    # 从匹配到的号源时段连回来


def test_join_refuses_when_the_identifier_does_not_match():
    """医院名对不上就一个字都不补。宁可"待补"，不可张冠李戴。"""
    card = _plan([_health_report(hospital="另一家没查过的医院"),
                  _route_report(), _weather_report()])
    page1 = {r["label"]: r["value"] for r in card["pages"][0]["rows"]}
    assert page1["医院"] == "另一家没查过的医院"   # 冻结参数照实印
    assert page1["医院地址"] == MISSING            # 连不上就不补
    assert "appointment.address" in card["missing"]


def test_registered_appointment_prints_the_number_and_says_done():
    """真挂上号了就印挂号单号、状态写"已办好"（不再是"等家人"）。"""
    registered = _report("health", {
        "hospital_options": _health_report().data["hospital_options"],
        "appointment": {"hospital": "南京鼓楼医院", "department": "骨科",
                        "doctor": "邱勇", "date": "+1", "time": "上午 08:30",
                        "fee": 70, "registration_no": "R000123",
                        "address": "南京市鼓楼区中山路321号", "city": "南京"},
    })
    card = _plan([registered, _route_report(), _weather_report()])
    rows = card["pages"][0]["rows"]
    assert rows[0]["label"] == "挂号单号" and rows[0]["value"] == "R000123"
    status = next(r for r in rows if r["label"] == "状态")
    assert status["value"] == "已办好"


def test_suspended_appointment_says_waiting_for_family_not_done():
    """挂号还挂着等确认时，纸上不能写"已办好"（这是诚实性的核心）。"""
    card = _plan(_all())
    status = next(r for r in card["pages"][0]["rows"] if r["label"] == "状态")
    assert "等家人" in status["value"]
    assert "已办好" not in status["value"]


def test_rejected_item_says_so_plainly():
    card = _plan([_health_report(status="rejected"), _route_report(),
                  _weather_report()])
    status = next(r for r in card["pages"][0]["rows"] if r["label"] == "状态")
    assert "没同意" in status["value"]


# ---------------------------------------------------------------- 日期可读性


def test_relative_dates_are_rendered_as_a_date_an_elder_can_act_on():
    """"+1" 印在纸上等于没印。换算是算术，指的还是同一天。"""
    card = _plan(_all())
    page1 = {r["label"]: r["value"] for r in card["pages"][0]["rows"]}
    expect_visit = (date.today() + timedelta(days=1)).isoformat()
    assert page1["就诊时间"].startswith(expect_visit)
    assert "（周" in page1["就诊时间"] and page1["就诊时间"].endswith("）")


def test_unrecognised_date_text_is_left_alone():
    """认不出的写法原样保留，绝不改写成某个"看起来像日期"的东西。"""
    assert plan_builder._human_date("周三上午") == "周三上午"
    assert plan_builder._human_date("") is None
    assert plan_builder._human_date(None) is None
    assert plan_builder._human_date("2026-03-05") == "2026-03-05（周四）"


# ---------------------------------------------------------------- 三份共用一源


def test_three_templates_share_one_report_input():
    """同一批 report，三个模板都能渲染 —— 分叉只在模板，不在数据采集。"""
    reports = _all() + [_report("health", {
        "medication": {"plan": {"drug_name": "钙尔奇", "dose": "1片",
                                "times": ["08:00", "20:00"], "notes": "饭后吃"}},
        "report_reading": {"plain": "血脂有点高，少吃油的"},
    }), _report("community", {
        "activities": {"activities": [
            {"title": "社区棋牌室双周赛", "date": "2026-03-07",
             "place": "鼓楼社区活动中心"},
            {"title": "晨间太极班", "date": "2026-03-08",
             "place": "鼓楼公园东门"}]},
    })]

    trip = plan_builder.build("trip_plan", ELDER, reports, city="南京", today=TODAY)
    health = plan_builder.build("health_card", ELDER, reports, today=TODAY)
    community = plan_builder.build("community_card", ELDER, reports, today=TODAY)

    assert trip["type"] == "trip_plan" and len(trip["pages"]) == 4
    assert health["type"] == "health_card" and len(health["pages"]) == 1
    assert community["type"] == "community_card" and len(community["pages"]) == 1

    hrows = {r["label"]: r["value"] for r in health["pages"][0]["rows"]}
    assert hrows["药名"] == "钙尔奇"
    assert hrows["每次吃"] == "1片"
    # 列表要念成人话，不能印成 ['08:00', '20:00']
    assert hrows["每天时间"] == "08:00、20:00"
    assert "南京鼓楼医院" in hrows["下次复查"]
    assert "血脂" in " ".join(health["pages"][0]["notes"])

    # 社区单：每行以活动日期为标签，值是"活动名（地点）"，来源是 activities.activities
    crows = {r["label"]: r["value"] for r in community["pages"][0]["rows"]}
    assert crows["2026-03-07"] == "社区棋牌室双周赛（鼓楼社区活动中心）"
    assert crows["2026-03-08"] == "晨间太极班（鼓楼公园东门）"

    # 计划书与用药卡带医疗免责声明口径；社区单不涉医疗，不强加
    assert "不构成诊断" in trip["disclaimer"]
    assert "不构成诊断" in health["disclaimer"]
    assert "disclaimer" not in community


def test_light_cards_use_the_same_placeholder_policy():
    """轻量卡片不是"简化版"，缺字段策略与计划书完全一致。"""
    health = plan_builder.build("health_card", ELDER, [], today=TODAY)
    assert health["complete"] is False
    assert all(r["value"] == MISSING for r in health["pages"][0]["rows"])
    assert "medication.plan.drug_name" in health["missing"]

    community = plan_builder.build("community_card", ELDER, [], today=TODAY)
    assert community["complete"] is False
    assert any(r["missing"] for r in community["pages"][0]["rows"])
    assert "activities.activities" in community["missing"]


def test_unknown_kind_is_a_loud_error():
    """没有这种交付物就报错，不要默默给一份别的。"""
    with pytest.raises(KeyError):
        plan_builder.build("poster", ELDER, _all())


# ---------------------------------------------------------------- 兜底扁平视图


def test_flat_body_is_a_fallback_view_of_the_same_rows():
    """``body`` 是给纯文本打印/旧渲染器用的兜底视图，值必须与 rows 一致。"""
    card = _plan(_all())
    for page in card["pages"]:
        section = page["title"].split("·")[-1].strip()
        for row in page["rows"]:
            assert card["body"][f"{section}/{row['label']}"] == row["value"]
