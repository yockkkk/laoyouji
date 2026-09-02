"""交付物渲染管线：确定性、缺字段不编造、三份交付物共用一份 report 输入。

这些测试不碰模型、不碰数据库、不碰事件总线 —— 全是纯函数。方案书第三步那 20 分
压在这条管线上，所以它必须能在答辩现场当场跑、当场改一个字段看结果变化。
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


def _health_report(**over) -> AgentReport:
    """健康支线的回报：查医院的候选 + 被拦下的挂号（冻结参数）。"""
    appointment = {"hospital": "北京积水潭医院", "department": "骨科",
                   "doctor": "田伟", "date": "+3", "time": "上午", "fee": 100,
                   "status": "pending_confirm", "confirmation_id": "c-1"}
    appointment.update(over)
    return _report("health", {
        "hospital_options": {"hospitals": [{
            "hospital": "北京积水潭医院", "city": "北京", "level": "三级甲等",
            "specialty": "骨科全国闻名",
            "address": "北京市西城区新街口东街31号",
            "department": "骨科",
            "doctors": [{"doctor": "田伟", "title": "主任医师·教授", "fee": 100,
                         "slots": [{"date": "2026-03-08", "time": "周日上午 08:30"}]}],
        }]},
        "appointment": appointment,
    }, suspended=True)


def _ticket_report() -> AgentReport:
    return _report("travel", {
        "train_options": {"trains": [{
            "train_no": "G102", "depart": "08:00", "arrive": "12:18",
            "duration": "4小时18分",
            "from_station": "南京南", "to_station": "北京南"}]},
        "ticket": {"train_no": "G102", "date": "tomorrow",
                   "from_station": "南京南", "to_station": "北京南",
                   "depart": "08:00", "arrive": "12:18",
                   "seat_type": "二等座", "price": 553.5,
                   "status": "pending_confirm", "confirmation_id": "c-2"},
    }, suspended=True)


def _hotel_report(*, booked: bool = False) -> AgentReport:
    hotels = [{"name": "汉庭酒店（积水潭店）", "city": "北京",
               "address": "北京市西城区德胜门内大街 85 号",
               "near_hospital": "北京积水潭医院",
               "distance_m": 600, "walk_min": 9, "price": 329,
               "accessible_note": "一层客房，电梯直达", "phone": "010-83221111"}]
    hotel = ({"hotel": "汉庭酒店（积水潭店）", "checkin": "tomorrow", "nights": 2,
              "total": 658, "order_no": "H000123456"} if booked
             else {"hotel": "汉庭酒店（积水潭店）", "checkin": "tomorrow", "nights": 2,
                   "status": "pending_confirm", "confirmation_id": "c-3"})
    return _report("travel", {
        "hotel_options": {"hotels": hotels, "city": "北京"},
        "hotel": hotel,
        "weather": {"city": "北京", "date": "2026-03-06", "condition": "多云",
                    "temp_low": 4, "temp_high": 13, "temp_range": "4~13 ℃",
                    "advice": "早晚凉，外面套件厚衣服", "umbrella": False},
    }, suspended=not booked)


ELDER = {"id": "e-1", "name": "李秀兰", "city": "南京"}


def _plan(reports, **kw) -> dict:
    kw.setdefault("city", "北京")
    kw.setdefault("today", TODAY)
    return plan_builder.build("trip_plan", ELDER, reports, **kw)


ALL_REPORTS_NOTE = "每个用例现做一份 report，避免跨用例共享可变 dict"


def _all() -> list[AgentReport]:
    return [_health_report(), _ticket_report(), _hotel_report()]


# ---------------------------------------------------------------- 页序与形态


def test_five_pages_in_the_order_the_proposal_fixed():
    """页序是方案书原文写死的：挂号 → 车票 → 酒店 → 行李 → 天气。"""
    card = _plan(_all())
    assert card["type"] == "trip_plan"
    assert card["printable"] is True
    assert card["generated_on"] == TODAY
    assert [p["no"] for p in card["pages"]] == [1, 2, 3, 4, 5]
    assert [p["title"].split("·")[-1].strip() for p in card["pages"]] == [
        "挂号信息", "去程车票 + 返程建议", "酒店信息",
        "随身清单（出门前一样一样对）", "北京天气与穿衣"]
    assert card["title"] == "李秀兰 · 北京就医出行计划书"
    assert card["subtitle"].startswith("共 5 页")


def test_page_count_never_shrinks_when_fields_are_missing():
    """一页都不能少。少一页没人发现，写"待补"才会被看见。"""
    for reports in ([], [_health_report()], _all()):
        assert len(_plan(reports)["pages"]) == 5


def test_checklist_is_a_policy_template_not_a_query_result():
    """行李清单来自政策模板，所以它永不"待补"，连空 report 都印得出来。"""
    page4 = _plan([])["pages"][3]
    assert page4["complete"] is True
    text = " ".join(r["value"] for r in page4["rows"])
    for item in ("身份证", "医保卡", "既往病历", "老花镜", "常备药"):
        assert item in text


def test_checklist_grows_with_weather_and_hotel():
    """清单会按查到的天气/酒店追加条目 —— 追加项也都有出处。"""
    base = len(_plan([])["pages"][3]["rows"])
    with_all = _plan(_all())["pages"][3]
    text = " ".join(r["value"] for r in with_all["rows"])
    assert len(with_all["rows"]) > base
    assert "厚外套" in text          # weather.temp_low = 4 ≤ 10
    assert "酒店订单" in text        # 有选定的酒店
    assert "伞" not in text          # umbrella=False，不该无端加一把伞


# ---------------------------------------------------------------- 确定性


def test_same_input_same_output():
    """同输入同输出。演示两次不能是两个结果 —— 这是可复现的底线。"""
    first = _plan(_all())
    second = _plan(_all())
    assert first == second


def test_report_order_does_not_change_the_card():
    """并发扇出的回报到达顺序不固定，卡片不能跟着变。"""
    forward = _plan([_health_report(), _ticket_report(), _hotel_report()])
    backward = _plan([_hotel_report(), _ticket_report(), _health_report()])
    assert forward == backward


def test_later_report_does_not_overwrite_an_earlier_value_with_nothing():
    """先到的值不被后到的空值盖掉（merge_reports 的"先到者不被覆盖成空"）。"""
    empty_hotel = _report("travel", {"hotel": {}, "weather": {}})
    merged = plan_builder.merge_reports([_hotel_report(), empty_hotel])
    assert merged["hotel"]["hotel"] == "汉庭酒店（积水潭店）"


# ---------------------------------------------------------------- 缺字段策略


def test_empty_reports_render_all_placeholders_and_fabricate_nothing():
    """一份回报都没有时，四页查询页全是"待补"，一个字都不许编。"""
    card = _plan([])
    assert card["complete"] is False
    for page_no in (1, 2, 3, 5):
        page = card["pages"][page_no - 1]
        assert page["complete"] is False
        assert all(r["value"] == MISSING for r in page["rows"])
    # missing 与"待补"的行严格一一对应
    flagged = [r for p in card["pages"] for r in p["rows"] if r["missing"]]
    assert len(flagged) == len(card["missing"])


def test_missing_hotel_only_affects_the_hotel_page():
    """抽掉酒店，第三页"待补"，其余各页照旧 —— 缺字段是局部的。"""
    card = _plan([_health_report(), _ticket_report()])
    page3 = {r["label"]: r["value"] for r in card["pages"][2]["rows"]}
    assert set(page3.values()) == {MISSING}
    assert "hotel.hotel" in card["missing"]
    assert "hotel.total" in card["missing"]
    # 挂号和车票不受牵连
    assert card["pages"][0]["complete"] is True
    assert card["pages"][1]["complete"] is True


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
    """挂起时只有冻结参数；地址/电话/房价按标识符从同一批查询结果连回来。"""
    card = _plan(_all())
    page3 = {r["label"]: r["value"] for r in card["pages"][2]["rows"]}
    assert page3["地址"] == "北京市西城区德胜门内大街 85 号"
    assert page3["电话"] == "010-83221111"
    assert page3["到医院"] == "步行约 9 分钟（600 米）"
    # 房费是"单价×晚数"的算术，不是编的总价，所以带 ≈
    assert page3["房费"] == "每晚 329 元 × 2 晚 ≈ 658 元"

    page1 = {r["label"]: r["value"] for r in card["pages"][0]["rows"]}
    assert page1["医院地址"] == "北京市西城区新街口东街31号"


def test_join_refuses_when_the_identifier_does_not_match():
    """名字对不上就一个字都不补。宁可"待补"，不可张冠李戴。"""
    wrong = _hotel_report()
    wrong.data["hotel"]["hotel"] = "另一家没查过的酒店"
    card = _plan([_health_report(), _ticket_report(), wrong])
    page3 = {r["label"]: r["value"] for r in card["pages"][2]["rows"]}
    assert page3["酒店"] == "另一家没查过的酒店"   # 冻结参数照实印
    assert page3["地址"] == MISSING                # 连不上就不补
    assert page3["电话"] == MISSING
    assert page3["房费"] == MISSING


def test_booked_hotel_prints_the_locked_total_not_an_estimate():
    """真订成了就印总价（无"≈"），状态也从"等家人"变成"已办好"。"""
    card = _plan([_health_report(), _ticket_report(), _hotel_report(booked=True)])
    page3 = {r["label"]: r["value"] for r in card["pages"][2]["rows"]}
    assert page3["房费"] == "共 658 元"
    assert "≈" not in page3["房费"]
    assert page3["状态"] == "已办好"


def test_suspended_items_say_waiting_for_family_not_done():
    """三件高危项还挂着的时候，纸上不能写"已办好"（这是诚实性的核心）。"""
    card = _plan(_all())
    for page_no in (1, 2, 3):
        status = next(r for r in card["pages"][page_no - 1]["rows"]
                      if r["label"] == "状态")
        assert "等家人" in status["value"]
        assert "已办好" not in status["value"]


def test_rejected_item_says_so_plainly():
    card = _plan([_health_report(status="rejected"), _ticket_report(),
                  _hotel_report()])
    status = next(r for r in card["pages"][0]["rows"] if r["label"] == "状态")
    assert "没同意" in status["value"]


# ---------------------------------------------------------------- 日期可读性


def test_relative_dates_are_rendered_as_a_date_an_elder_can_act_on():
    """"+3" / "tomorrow" 印在纸上等于没印。换算是算术，指的还是同一天。"""
    card = _plan(_all())
    page1 = {r["label"]: r["value"] for r in card["pages"][0]["rows"]}
    page2 = {r["label"]: r["value"] for r in card["pages"][1]["rows"]}

    expect_visit = (date.today() + timedelta(days=3)).isoformat()
    expect_depart = (date.today() + timedelta(days=1)).isoformat()
    assert page1["就诊时间"].startswith(expect_visit)
    assert page2["乘车日期"].startswith(expect_depart)
    assert "（周" in page1["就诊时间"] and page1["就诊时间"].endswith("）")
    # 返程建议里的日期也得是人话
    notes = " ".join(card["pages"][1]["notes"])
    assert "+3" not in notes and expect_visit in notes


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
        "service_order": {"order": {"service_type": "cleaning",
                                    "provider_name": "邻里帮保洁队",
                                    "amount": 80},
                          "date": "2026-03-07"},
    })]

    trip = plan_builder.build("trip_plan", ELDER, reports, city="北京", today=TODAY)
    health = plan_builder.build("health_card", ELDER, reports, today=TODAY)
    community = plan_builder.build("community_card", ELDER, reports, today=TODAY)

    assert trip["type"] == "trip_plan" and len(trip["pages"]) == 5
    assert health["type"] == "health_card" and len(health["pages"]) == 1
    assert community["type"] == "community_card" and len(community["pages"]) == 1

    hrows = {r["label"]: r["value"] for r in health["pages"][0]["rows"]}
    assert hrows["药名"] == "钙尔奇"
    assert hrows["每次吃"] == "1片"
    # 列表要念成人话，不能印成 ['08:00', '20:00']
    assert hrows["每天时间"] == "08:00、20:00"
    assert "北京积水潭医院" in hrows["下次复查"]
    assert "血脂" in " ".join(health["pages"][0]["notes"])

    crows = {r["label"]: r["value"] for r in community["pages"][0]["rows"]}
    assert crows["服务"] == "保洁上门"          # cleaning → 中文，只换词不换来源
    assert crows["金额"] == "80 元"
    assert crows["状态"] == "已办好"

    # 三份都带免责声明口径（社区单不涉医疗，所以只有前两份有）
    assert "不构成诊断" in trip["disclaimer"]
    assert "不构成诊断" in health["disclaimer"]


def test_light_cards_use_the_same_placeholder_policy():
    """轻量卡片不是"简化版"，缺字段策略与计划书完全一致。"""
    health = plan_builder.build("health_card", ELDER, [], today=TODAY)
    assert health["complete"] is False
    assert all(r["value"] == MISSING for r in health["pages"][0]["rows"])
    assert "medication.plan.drug_name" in health["missing"]

    community = plan_builder.build("community_card", ELDER, [], today=TODAY)
    assert community["complete"] is False
    assert any(r["missing"] for r in community["pages"][0]["rows"])


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
