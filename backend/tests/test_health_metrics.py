"""康乐左翼·身体核心：参考区间/分诊引擎（health_rules）+ 四个新工具 + 人物档案。

分两层测，界线很清楚：

- **纯函数层**（``health_rules``）：不碰库、不碰模型，逐个档位钉死。分诊是这套东西
  敢挂"分诊"两个字的地方，阈值必须能被逐条指认 —— "输 178/105 进去出来是哪一档、
  为什么"，答辩现场要能当场演。
- **工具层**（``log_vital`` / ``get_health_summary`` / ``add_condition`` /
  ``assess_health``）：走**完整 dispatcher**（含 guard 流水线），测"记下来的数 →
  落到库里 → 分诊读得回来"这条链真的通。

两个反复出现的主张，各自有专门的测试守着：
- **保健优先**：138/86 这种老人常态落"保健"，不许撵人去医院；
- **急症有下限**：保健优先不能盖住 180/110、血氧 89、低血糖这些真危险的数。
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from app.core.context import TurnContext
from app.db.repositories import TABLES
from app.db.seed import KANGLE_PERSONA, seed_kangle_persona
from app.safety import health_rules as hr


# ==================================================================== 纯函数层

class TestClassify:
    """单条读数 → 档位。每条断言就是一个阈值边界，改阈值就得改这里。"""

    @pytest.mark.parametrize("systolic,diastolic,expected", [
        (118, 76, "保健"),      # 正常
        (138, 86, "保健"),      # 老人常态 —— **保健优先**的关键一条
        (139, 89, "保健"),      # 贴着线但没越线，仍不抬档
        (140, 90, "观察"),      # 刚越线：观察、复测，不跑医院
        (155, 95, "观察"),
        (160, 100, "建议就医"),  # 中重度：这才值得去一趟
        (178, 105, "建议就医"),  # 演示主线 A 的主角数
        (180, 110, "紧急"),      # 高血压急症：保健优先管不到这儿
        (200, 120, "紧急"),
        (85, 55, "建议就医"),    # 明显偏低
    ])
    def test_bp_bands(self, systolic, diastolic, expected):
        level, reason = hr.classify_reading("bp", systolic=systolic, diastolic=diastolic)
        assert level == expected, f"{systolic}/{diastolic} → {level}（{reason}）"

    @pytest.mark.parametrize("value,context,expected", [
        (5.5, "空腹", "保健"),
        (6.8, "空腹", "保健"),
        (7.1, "空腹", "观察"),
        (9.0, "空腹", "观察"),
        (14.0, "空腹", "建议就医"),
        (9.5, "餐后", "保健"),
        (12.0, "餐后", "观察"),
        (17.0, "餐后", "建议就医"),
        (3.5, "空腹", "建议就医"),   # 低血糖
        (2.8, "空腹", "紧急"),       # 重度低血糖
    ])
    def test_glucose_bands_respect_fasting_context(self, value, context, expected):
        """同一个数，空腹和餐后不是一回事 —— context 丢了就会误判。"""
        level, _ = hr.classify_reading("glucose", value=value, context=context)
        assert level == expected

    def test_glucose_fasting_is_the_default(self):
        """模型没填 context 时按空腹算（更严的那一档），不按餐后放宽。"""
        strict, _ = hr.classify_reading("glucose", value=8.0, context=None)
        assert strict == hr.classify_reading("glucose", value=8.0, context="空腹")[0]
        assert strict == "观察"

    @pytest.mark.parametrize("value,expected", [
        (72, "保健"), (100, "观察"), (45, "观察"), (135, "建议就医"), (35, "建议就医"),
    ])
    def test_heart_rate_bands(self, value, expected):
        assert hr.classify_reading("heart_rate", value=value)[0] == expected

    @pytest.mark.parametrize("value,expected", [
        (98, "保健"), (94, "观察"), (92, "建议就医"), (88, "紧急"),
    ])
    def test_spo2_bands(self, value, expected):
        assert hr.classify_reading("spo2", value=value)[0] == expected

    @pytest.mark.parametrize("value,expected", [
        (36.5, "保健"), (37.5, "观察"), (39.2, "建议就医"), (34.5, "建议就医"),
    ])
    def test_temperature_bands(self, value, expected):
        assert hr.classify_reading("temperature", value=value)[0] == expected

    def test_weight_never_raises_a_level(self):
        """体重没有"超了就得去医院"这回事，只记录、看趋势 —— 不参与抬档。"""
        assert hr.classify_reading("weight", value=95)[0] == "保健"
        assert hr.classify_reading("weight", value=38)[0] == "保健"

    def test_missing_or_junk_values_do_not_invent_a_level(self):
        """没测到就是没测到 —— 不能靠一个空值判出"保健"以外的任何东西。"""
        assert hr.classify_reading("bp")[0] == "保健"
        assert hr.classify_reading("bp", systolic=178)[0] == "保健"      # 缺低压
        assert hr.classify_reading("glucose", value=None)[0] == "保健"
        assert hr.classify_reading("glucose", value="说不清")[0] == "保健"

    def test_reason_is_always_a_plain_language_sentence(self):
        """原因要是能念给老人听的话，不是给工程师看的枚举值。"""
        _, reason = hr.classify_reading("bp", systolic=178, diastolic=105)
        assert "178/105" in reason and "建议就医" not in reason


class TestTriage:
    """合并层：多条读数 + 慢病 + 症状 → 一个行动档位。"""

    def test_all_normal_lands_on_health_care_not_a_doctor_visit(self):
        """**保健优先**的正面主张：指标都好，就明说不用特意往医院跑。"""
        out = hr.triage({"bp": {"metric_type": "bp", "systolic": 128, "diastolic": 80},
                         "glucose": {"metric_type": "glucose", "value": 5.8, "context": "空腹"}})
        assert out["level"] == "保健"
        assert out["drivers"] == []
        assert "不用特意往医院跑" in out["advice"]

    def test_the_worst_driver_decides(self):
        """一好一坏取最重的那档，但两条原因都要留着 —— 老人有权知道全部情况。"""
        out = hr.triage({
            "bp": {"metric_type": "bp", "systolic": 178, "diastolic": 105},
            "glucose": {"metric_type": "glucose", "value": 7.2, "context": "空腹"},
        })
        assert out["level"] == "建议就医"
        assert {d["metric"] for d in out["drivers"]} == {"bp", "glucose"}
        assert out["drivers"][0]["metric"] == "bp", "最重的驱动要排在最前"

    def test_emergency_beats_health_care_bias(self):
        """保健优先是默认倾向，不是挡箭牌：真危险的值必须顶到紧急。"""
        out = hr.triage({"bp": {"metric_type": "bp", "systolic": 190, "diastolic": 115}})
        assert out["level"] == "紧急"
        assert "120" in out["advice"]

    @pytest.mark.parametrize("symptom,expected", [
        ("胸口疼，喘不上气", "紧急"),
        ("头晕好几天了，越来越重", "建议就医"),
        ("就是有点累", "观察"),
    ])
    def test_symptom_alone_can_drive_the_level(self, symptom, expected):
        assert hr.triage({}, symptom=symptom)["level"] == expected

    def test_blank_symptom_is_not_a_symptom(self):
        """空串/空格不算"报了症状"，否则每次分诊都会凭空多一条"观察"。"""
        assert hr.assess_symptom("") is None
        assert hr.assess_symptom("   ") is None
        assert hr.triage({})["level"] == "保健"

    def test_trend_only_changes_the_wording_never_the_level(self):
        """连续走高值得说一句，但档位由数值定 —— 趋势本身不是急症。"""
        latest = {"bp": {"metric_type": "bp", "systolic": 145, "diastolic": 92}}
        flat = hr.triage(latest)
        rising = hr.triage(latest, trends={"bp": "上升"})
        assert flat["level"] == rising["level"] == "观察"
        assert "持续走高" in rising["drivers"][0]["reason"]
        assert "持续走高" not in flat["drivers"][0]["reason"]


class TestTrend:
    @pytest.mark.parametrize("series,expected", [
        ([140, 140, 140, 140], "平稳"),
        ([140, 141, 139, 140], "平稳"),
        ([140, 145, 155, 170, 178], "上升"),
        ([178, 170, 155, 145, 140], "下降"),
        ([140, 140, 140], "平稳"),           # 点太少，不给结论
        ([], "平稳"),
    ])
    def test_trend(self, series, expected):
        assert hr.trend(series) == expected

    def test_noise_is_not_a_trend(self):
        """±2 的日常抖动不能读成"上升" —— 那会让每天都像在恶化。"""
        assert hr.trend([140, 142, 139, 141, 140, 141]) == "平稳"


class TestCoerceReading:
    """模型填参数的几种真实写法都得认下来 —— 丢了数就得让老人重报一遍。"""

    def test_separate_systolic_diastolic(self):
        row = hr.coerce_reading({"metric_type": "bp", "systolic": 178, "diastolic": 105})
        assert (row["systolic"], row["diastolic"]) == (178.0, 105.0)

    @pytest.mark.parametrize("args", [
        {"metric_type": "bp", "value": "178/105"},
        {"metric_type": "bp", "systolic": "178/105"},
    ])
    def test_compound_string_is_split_whichever_field_it_lands_in(self, args):
        row = hr.coerce_reading(args)
        assert (row["systolic"], row["diastolic"]) == (178.0, 105.0)

    def test_numeric_strings_are_accepted(self):
        assert hr.coerce_reading({"metric_type": "glucose", "value": "8.5"})["value"] == 8.5

    def test_junk_becomes_none_not_a_guess(self):
        assert hr.coerce_reading({"metric_type": "glucose", "value": "挺高的"})["value"] is None
        assert hr.coerce_reading({"metric_type": "bp", "systolic": "178"})["diastolic"] is None


class TestFormatReading:
    def test_bp_reads_as_over(self):
        assert hr.format_reading({"metric_type": "bp", "systolic": 178, "diastolic": 105}) == "178/105 mmHg"

    def test_glucose_carries_its_context(self):
        """餐后 10 和空腹 10 不是一回事，念出来必须带着"餐后"。"""
        assert hr.format_reading({"metric_type": "glucose", "value": 10.0,
                                  "context": "餐后"}) == "10 mmol/L（餐后）"

    def test_missing_values_render_as_a_dash_not_a_zero(self):
        assert "—" in hr.format_reading({"metric_type": "bp", "systolic": None, "diastolic": None})


# ==================================================================== 工具层

def _turn(ctx, elder, sid="s-health"):
    return TurnContext(ctx=ctx, session_id=sid, user=elder)


async def test_new_tables_are_registered():
    """新表不在 TABLES 里，``reset()`` 就不会清它 —— 演示复位后残留上一次的数。"""
    assert "health_metrics" in TABLES
    assert "health_conditions" in TABLES


async def test_log_vital_stores_a_bp_reading(ctx, elder):
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "log_vital",
                                    {"metric_type": "bp", "systolic": 138, "diastolic": 86})
    assert r["ok"] is True
    rows = await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]})
    assert len(rows) == 1
    assert rows[0]["metric_type"] == "bp"
    assert rows[0]["systolic"] == 138.0
    assert rows[0]["unit"] == "mmHg"
    assert rows[0]["level"] == "保健"
    assert rows[0]["measured_at"], "没填测量时刻也要落一个，否则排序没有键"


async def test_log_vital_reports_the_level_on_the_spot(ctx, elder):
    """记完当场给档位 —— 记录不该是"存进去就没下文"。"""
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "log_vital",
                                    {"metric_type": "bp", "systolic": 178, "diastolic": 105})
    assert r["ok"] is True
    assert r["data"]["level"] == "建议就医"
    assert "178/105" in r["summary"]
    assert "遵医嘱" in r["summary"], "R4：报档位就是在对老人的身体下判断，必须带声明"


async def test_log_vital_refuses_half_a_blood_pressure(ctx, elder):
    """只有高压没有低压：宁可请他重报，也不许猜一个数记下来。"""
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "log_vital",
                                    {"metric_type": "bp", "systolic": 170})
    assert r["ok"] is False
    assert await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]}) == []


async def test_log_vital_refuses_an_unknown_metric(ctx, elder):
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "log_vital",
                                    {"metric_type": "骨密度", "value": 1})
    assert r["ok"] is False
    assert await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]}) == []


async def test_add_condition_records_without_judging(ctx, elder):
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "add_condition",
                                    {"name": "原发性高血压", "diagnosed_at": "2021-03-18"})
    assert r["ok"] is True
    assert r["data"]["condition"]["active"] is True
    rows = await ctx.repos.list("health_conditions", where={"elder_id": elder["id"]})
    assert [x["name"] for x in rows] == ["原发性高血压"]


async def test_add_condition_attributes_the_diagnosis_to_the_doctor(ctx, elder):
    """红线 R1：说"您有××病"的是医生，不是康乐。措辞里必须带着这层归属。"""
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "add_condition", {"name": "2 型糖尿病"})
    assert "医生确诊的" in r["announce"]


async def test_summary_says_so_when_there_is_nothing_recorded(ctx, elder):
    """一条没记过就说没记过，不要编一份"最近指标"。"""
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "get_health_summary", {})
    assert r["ok"] is True
    assert r["data"]["readings"] == []
    assert "还没记过" in r["summary"]


async def test_summary_reads_back_what_was_logged(ctx, elder):
    turn = _turn(ctx, elder)
    await ctx.dispatcher.execute(turn, "log_vital", {"metric_type": "bp", "systolic": 138, "diastolic": 86})
    await ctx.dispatcher.execute(turn, "log_vital", {"metric_type": "glucose", "value": 6.5, "context": "空腹"})
    r = await ctx.dispatcher.execute(turn, "get_health_summary", {})
    assert r["data"]["count"] == 2
    assert {x["metric_type"] for x in r["data"]["readings"]} == {"bp", "glucose"}
    assert r["data"]["level"] == "保健"
    assert "遵医嘱" in r["summary"], "R4：概览会说出「这个数怎么样」，要带声明"


async def test_summary_keeps_only_the_latest_reading_per_metric(ctx, elder):
    """概览是"现在怎么样"，不是流水账 —— 同一项记了三次只报最后一次。"""
    turn = _turn(ctx, elder)
    for value in (150, 155, 178):
        await ctx.dispatcher.execute(turn, "log_vital",
                                     {"metric_type": "bp", "systolic": value, "diastolic": 100})
    r = await ctx.dispatcher.execute(turn, "get_health_summary", {})
    bp = [x for x in r["data"]["readings"] if x["metric_type"] == "bp"]
    assert len(bp) == 1
    assert "178" in bp[0]["display"]


async def test_assess_refuses_to_guess_with_nothing_to_go_on(ctx, elder):
    """空着库就分诊等于算命。先说"您先量一下"，别给一个假档位。"""
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "assess_health", {})
    assert r["ok"] is False


async def test_assess_works_on_a_symptom_alone(ctx, elder):
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "assess_health",
                                     {"symptom": "胸口疼，喘不上气"})
    assert r["ok"] is True
    assert r["data"]["level"] == "紧急"


async def test_assess_pulls_the_recorded_readings_in(ctx, elder):
    turn = _turn(ctx, elder)
    await ctx.dispatcher.execute(turn, "log_vital", {"metric_type": "bp", "systolic": 168, "diastolic": 98})
    r = await ctx.dispatcher.execute(turn, "assess_health", {})
    assert r["data"]["level"] == "建议就医"
    assert any(d["metric"] == "bp" for d in r["data"]["drivers"])
    assert "遵医嘱" in r["summary"], "R4：分诊结论必须带声明"


async def test_assess_scopes_to_the_elder_who_asked(ctx, elder, child):
    """分诊只看**问的人**自己的数 —— 子女那边记的不能算到老人头上。"""
    await ctx.dispatcher.execute(_turn(ctx, child, "s-child"), "log_vital",
                                 {"metric_type": "bp", "systolic": 190, "diastolic": 115})
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "assess_health", {})
    assert r["ok"] is False, "老人自己没有任何记录，就该说没有"
    assert await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]}) == []


async def test_archival_tools_carry_no_disclaimer(ctx, elder):
    """记账类不挂声明：每句都挂一遍，声明本身就被当噪音跳过去了。"""
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "add_condition", {"name": "原发性高血压"})
    assert "遵医嘱" not in r["summary"]


# ==================================================================== 人物档案

async def test_persona_spike_drives_a_doctor_visit(ctx, elder):
    """主线 A：30 天档案跑到底，最新一条就是 178/105，分诊落"建议就医"。"""
    info = await seed_kangle_persona(ctx.repos, elder)
    assert info["readings"] > 0

    # 取**血压**的最新一条 —— 全局最新那条是早饭后的血糖（07:30），比晨起血压晚 10 分钟
    rows = await ctx.repos.list("health_metrics",
                                where={"elder_id": elder["id"], "metric_type": "bp"},
                                order="-measured_at", limit=1)
    assert (rows[0]["systolic"], rows[0]["diastolic"]) == (178.0, 105.0)

    r = await ctx.dispatcher.execute(_turn(ctx, elder), "assess_health", {})
    assert r["data"]["level"] == "建议就医"
    assert "就近挂个号" in r["data"]["advice"]


async def test_persona_stable_demonstrates_the_health_care_bias(ctx, elder):
    """主线 C：**同一套阈值**，换一份平稳档案就落"保健、不用去医院"。

    这一条和上一条是同一个卖点的两面 —— 分诊是照阈值算出来的，不是写死的剧本。
    """
    await seed_kangle_persona(ctx.repos, elder, scenario="stable")
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "assess_health", {})
    assert r["data"]["level"] == "保健"
    assert "不用特意往医院跑" in r["data"]["advice"]


async def test_persona_trend_shows_up_as_rising(ctx, elder):
    """最近 5 天一路走高，要在概览里被读成"上升" —— 曲线不是摆着好看的。"""
    await seed_kangle_persona(ctx.repos, elder)
    r = await ctx.dispatcher.execute(_turn(ctx, elder), "get_health_summary", {})
    bp = next(x for x in r["data"]["readings"] if x["metric_type"] == "bp")
    assert bp["trend"] == "上升"
    assert bp["level"] == "建议就医"


async def test_persona_is_reproducible_across_resets(ctx, elder):
    """复位重灌必须拿到同一份档案（含随机噪声）。

    种子取的是**稳定身份**（用户名）而不是 uuid：否则每 reset 一次曲线形状一样、
    数却全变，演示就"每次都不是上次那份"了。
    """
    first = await seed_kangle_persona(ctx.repos, elder)
    row1 = await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]}, order="measured_at")

    # 换一个 uuid 完全不同的人，但用户名相同 —— 应当产出逐条相同的读数
    other = {**elder, "id": "00000000-0000-0000-0000-0000000000ff"}
    await seed_kangle_persona(ctx.repos, other)
    row2 = await ctx.repos.list("health_metrics", where={"elder_id": other["id"]}, order="measured_at")

    key = lambda rows: [(r["metric_type"], r.get("value"), r.get("systolic"), r["measured_at"]) for r in rows]
    assert key(row1) == key(row2)
    assert first["readings"] == len(row1)


async def test_persona_plants_conditions_and_doctor_meds(ctx, elder):
    await seed_kangle_persona(ctx.repos, elder)
    conditions = await ctx.repos.list("health_conditions", where={"elder_id": elder["id"]})
    assert {c["name"] for c in conditions} == {"原发性高血压", "2 型糖尿病"}
    meds = await ctx.repos.list("medication_plans", where={"elder_id": elder["id"]})
    names = {m["drug_name"] for m in meds}
    assert {"苯磺酸氨氯地平片", "二甲双胍缓释片"} <= names


async def test_persona_rejects_an_unknown_scenario(ctx, elder):
    with pytest.raises(ValueError):
        await seed_kangle_persona(ctx.repos, elder, scenario="包治百病")


async def test_persona_is_opt_in_and_leaves_the_plain_seed_alone(ctx, elder):
    """``seed_demo`` 不给指标 —— 演示分诊要显式再调一次，测试基线也不受影响。"""
    assert await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]}) == []
    assert await ctx.repos.list("health_conditions", where={"elder_id": elder["id"]}) == []
    assert KANGLE_PERSONA["age"] == 72


async def test_persona_allows_an_explicit_today_for_a_stable_demo(ctx, elder):
    """日期可注入：档案的"最后一天"能钉死，演示脚本不随日历漂。"""
    fixed = date(2026, 3, 10)
    info = await seed_kangle_persona(ctx.repos, elder, today=fixed)
    rows = await ctx.repos.list("health_metrics",
                                where={"elder_id": elder["id"], "metric_type": "bp"},
                                order="-measured_at", limit=1)
    assert rows[0]["measured_at"].startswith(fixed.isoformat())
    assert rows[0]["systolic"] == 178.0
    assert info["latest_bp"] == (178, 105)


async def test_persona_never_invents_a_reading_for_today_evening(ctx, elder):
    """今天只到早上：否则"最新一条"会被今晚那个数（还更低）盖掉。"""
    today = date(2026, 3, 10)
    await seed_kangle_persona(ctx.repos, elder, today=today)
    rows = await ctx.repos.list("health_metrics", where={"elder_id": elder["id"]},
                                order="-measured_at")
    todays = [r for r in rows if r["measured_at"].startswith(today.isoformat())]
    assert todays, "今天早上的读数要有"
    assert all(r["measured_at"] < f"{today.isoformat()}T12:00:00" for r in todays)


# ==================================================================== 端到端

async def test_left_wing_runs_end_to_end_through_the_main_agent(ctx, run_turn):
    """**左翼全链路**：老人说一句"血压 178/105"，一路走到"帮您就近约号"。

    这条测的是"改到位"而不是"能调用"：主智能体认得出这是报指标而不是要挂号，
    派给安康助手，助手记下 → 分诊 → 照档位回话，四个环节缺一个都到不了终点。
    """
    from app.core.events import AGENT_REPORT
    from app.core.subagents import AgentReport

    sid, events = await run_turn("我今天量了血压178/105")
    reports = [AgentReport.from_dict(e.payload) for e in ctx.event_log.events(sid)
               if e.type == AGENT_REPORT]
    health = next(r for r in reports if r.agent == "health")

    assert "vital_logged" in health.data, "要真记下来"
    assert health.data["vital_logged"]["level"] == "建议就医"
    assert health.data["assessment"]["level"] == "建议就医"
    assert health.tools_used[:2] == ["log_vital", "assess_health"], \
        f"先记后诊，顺序不能反：{health.tools_used}"

    rows = await ctx.repos.list("health_metrics", where={"elder_id": ctx.demo["elder"]["id"]})
    assert (rows[0]["systolic"], rows[0]["diastolic"]) == (178.0, 105.0)

    final = [e.data["text"] for e in events if e.event == "final"][-1]
    assert "医生" in final or "号" in final, f"建议就医该引导去看医生：{final}"


async def test_left_wing_does_not_drag_a_normal_reading_to_the_hospital(ctx, run_turn):
    """**保健优先的端到端证据**：血压 138/86 报上去，落点是"不用跑医院"。

    这是整个康乐最想证明的一件事，所以它必须有一条从老人一句话到最终回话的
    完整证据，而不只是单元测试里的一行 assert。
    """
    from app.core.events import AGENT_REPORT
    from app.core.subagents import AgentReport

    sid, events = await run_turn("我今天量了血压138/86")
    reports = [AgentReport.from_dict(e.payload) for e in ctx.event_log.events(sid)
               if e.type == AGENT_REPORT]
    health = next(r for r in reports if r.agent == "health")

    assert health.data["assessment"]["level"] == "保健"
    assert not any(t in health.tools_used for t in ("search_hospital", "register_appointment")), \
        f"保健档不该去查号挂号：{health.tools_used}"

    final = [e.data["text"] for e in events if e.event == "final"][-1]
    assert "医院" not in final or "不用" in final, f"不许撵老人上医院：{final}"


async def test_mock_parses_the_common_ways_elders_report_numbers():
    """离线剧本也得认得出老人的常见说法 —— 拔了网线演示不能掉链子。"""
    from app.providers.llm.mock import _vital_in

    assert _vital_in("我今天量了血压178/105")["systolic"] == 178.0
    assert _vital_in("血糖8.5，刚吃完饭")["context"] == "餐后"
    assert _vital_in("空腹血糖6.4")["context"] == "空腹"
    assert _vital_in("心率88")["metric_type"] == "heart_rate"
    # 认不出就是认不出，不能从寒暄里读出一个读数
    assert _vital_in("我有点头晕") == {}
    assert _vital_in("12/09 去复查") == {}, "日期不是血压"


# ==================================================================== 交付物

async def test_health_card_shows_the_vitals_when_they_exist(ctx, elder):
    """健康卡要把"最近测的 + 分诊结论"贴上去 —— 这张纸是给老人贴在药盒边的。"""
    from app.agents.plan_builder import build_health_card
    from app.core.subagents import AgentReport

    await seed_kangle_persona(ctx.repos, elder)
    turn = _turn(ctx, elder)
    summary = await ctx.dispatcher.execute(turn, "get_health_summary", {})
    assess = await ctx.dispatcher.execute(turn, "assess_health", {})

    card = build_health_card(elder, [
        AgentReport(agent="health", ok=True, summary="", data={"health_summary": summary["data"]}),
        AgentReport(agent="health", ok=True, summary="", data={"assessment": assess["data"]}),
    ])
    labels = [row["label"] for row in card["pages"][0]["rows"]]
    assert any("最近" in x for x in labels)
    assert "分诊结论" in labels
    assert "建议" in labels


async def test_health_card_is_unchanged_without_vitals(ctx, elder):
    """没有指标数据时，这张卡还是原来那张 —— 不许凭空多出几行空行。"""
    from app.agents.plan_builder import build_health_card
    from app.core.subagents import AgentReport

    card = build_health_card(elder, [
        AgentReport(agent="health", ok=True, summary="",
                    data={"medication": {"plan": {"drug_name": "钙片", "dose": "每次1片",
                                                  "times": ["09:00"], "notes": "饭后"}}}),
    ])
    labels = [row["label"] for row in card["pages"][0]["rows"]]
    assert "分诊结论" not in labels
    assert not any("最近" in x for x in labels)


# ============================================================ 档位的可达性（装配）

def _mock_reply(transcript: str) -> str | None:
    """让离线剧本按给定的工具历史说完最后一句（档位就在 transcript 里）。

    ``None`` 不是"没说话"，而是**这一档不由 ``_vital`` 收尾**："建议就医"要接着去
    挂号（挂号当场办好 + 知会子女），话交给后面那条线说 —— 见 ``_vital`` 的 docstring。
    """
    from app.providers.llm.mock import MockLLMProvider

    reply = MockLLMProvider()._vital({"metric_type": "bp"}, transcript)
    return None if reply is None else reply.content


async def test_the_tier_survives_the_trip_to_the_model():
    """分诊档位必须真的**到得了模型眼前** —— 这是"照档位办事"的物理前提。

    这是一个真出过的漏子：工具结果给模型看的那一份（``to_model_content``）
    只保留白名单实体字段，而 ``level`` 不在名单里。于是档位只活在 summary 那句
    中文里，模型读到一句人话、读不出档位。后果是不对称的 —— 认不出"建议就医"
    就按保健处理，等于漏诊；反过来认不出"保健"顶多多问一句。所以这里钉的是
    **档位必须以结构化字段的形式出现在模型看到的内容里**，而不是"文案里提到了"。
    """
    from app.core.tool import ToolCall, ToolOutcome

    for name, level in (("log_vital", "建议就医"), ("assess_health", "紧急")):
        outcome = ToolOutcome(
            call=ToolCall.new(name),
            result={"ok": True, "summary": "已记录。",
                    "data": {"level": level, "display": "178/105 mmHg"}})
        content = outcome.to_model_content()
        assert f'"level": "{level}"' in content, \
            f"{name} 的档位没进模型看到的内容：{content}"


def test_the_mock_reads_the_tier_from_both_sides_of_the_dispatch():
    """离线剧本读档位只认结构化字段，两处来源都要认（不猜中文措辞）。

    - 子助理那一支看得见自己工具结果里的 ``"level": "…"``；
    - 主智能体那一支只看得见回报摘要，档位由 digest 以 ``分诊: …`` 带出来。
    """
    from app.providers.llm.mock import _level_from

    assert _level_from('"level": "建议就医"') == "建议就医"
    assert _level_from("  分诊: 紧急") == "紧急"
    assert _level_from("早上好，今天天气不错") == "", "读不出就是读不出"
    # 几步结果都在时按最重的读：宁可说重了让老人白跑一趟
    assert _level_from('"level": "保健" … "level": "建议就医"') == "建议就医"


def test_the_digest_carries_the_tier_to_the_dispatching_agent():
    """回报摘要里必须带档位 —— 主智能体只有这一份材料，它得照档位办事。

    ``_triage`` 用的是工具自己的 report_key（assessment 优先于 vital_logged）：
    整体分诊才是"现在该怎么办"的结论，单次测量的档位只是其中一项依据。
    """
    from app.agents.main_agent import _triage
    from app.core.subagents import AgentReport

    assert _triage(AgentReport(agent="health", ok=True, summary="",
                               data={"assessment": {"level": "建议就医"}})) == "建议就医"
    # 没做整体分诊时，退回单次测量的档位，别把已有的信息丢掉
    assert _triage(AgentReport(agent="health", ok=True, summary="",
                               data={"vital_logged": {"level": "观察"}})) == "观察"
    assert _triage(AgentReport(agent="travel", ok=True, summary="",
                               data={"route": {"origin": "家"}})) == ""
    assert _triage(AgentReport(agent="health", ok=True, summary="", data={})) == ""


def test_an_unreadable_tier_never_gets_the_reassuring_line():
    """**不许多说一句宽心话**：读不出档位时那条回话必须是中性的。

    这是本次改出来的 fail-open。原先 ``_vital`` 的兜底就是"保健"那一句
    —— 于是模型历史里只要漏了档位，178/105 会得到"这个数挺稳的…不用特意跑医院"。
    兜底的方向不能是"往好里猜"：分诊读不出来就先不下结论，让医生看。
    """
    ran = '"tool": "log_vital" "tool": "assess_health"'
    assert _mock_reply(ran) == "记下了。这个数要不要紧，得让医生看了才算数。", \
        "读不出档位时不许给宽心话"

    # 而且每一档都得各说各的 —— 兜底不许顺手顶掉任何一档
    assert "挺稳" in _mock_reply(ran + ' "level": "保健"')
    assert "少盐少油" in _mock_reply(ran + ' "level": "观察"')
    # "建议就医"现在**不由 _vital 收尾**：它必须把话交给挂号那条线，因为老人真正
    # 需要的是"号挂上了、子女知道了"，不是一句"我帮您约"。原先这里只断言"含'医生'"
    # —— 那句话恰好是本次修掉的病：老人听见"我帮您就近约个号"，而号根本没挂。
    # 所以这里钉的比原来更死：这一档**必须**交出控制权。
    assert _mock_reply(ran + ' "level": "建议就医"') is None, \
        "建议就医必须接着走挂号那条线，不能停在 _vital 里说一句承诺就算完"
    assert "120" in _mock_reply(ran + ' "level": "紧急"')
    assert (_mock_reply(ran + " 分诊: 建议就医")
            == _mock_reply(ran + ' "level": "建议就医"')), \
        "回报摘要那条路和工具结果那条路要给出同一个结果"


# ======================================================== 症状这条线的分岔（离线剧本）

def _dispatch(text: str) -> tuple[str, list[str], bool, bool, bool]:
    """把一句话喂给离线剧本的**总智能体分岔**，返回 (认到哪支, 工具链, …)。

    只看"派给谁、走哪条线"，不跑工具 —— 这里要钉的是**路由**，不是工具本身。
    """
    from app.providers.llm import mock

    if mock._wants_medical_trip(text):
        return "medical_trip", [], False, False, False
    if mock._wants_travel(text):
        return "travel", [], False, False, False
    if mock._wants_community(text):
        return "community", [], False, False, False
    if mock._wants_health(text):
        return "health", [], bool(mock._symptom_in(text)), bool(mock._vital_in(text)), True
    return "none", [], False, False, False


@pytest.mark.parametrize("text", [
    "我有点头晕，心里发慌",
    "我这两天膝盖疼得厉害",
    "我胸口闷得慌",
    "我胃疼反酸",
    "我咳嗽好几天了",
    "我这两天有点乏力",
])
def _branch(text: str) -> str:
    """这句话在离线剧本里会被派给谁 —— 只判路由，不跑工具。

    判据的顺序必须和 ``MockLLMProvider._main`` 里的一致，否则这里测的就是
    另一套路由了。所以下面直接调那几个 ``_wants_*``。
    """
    from app.providers.llm import mock

    if mock._wants_medical_trip(text):
        return "medical_trip"
    if mock._wants_travel(text):
        return "travel"
    if mock._wants_community(text):
        return "community"
    if mock._wants_health(text):
        return "health"
    return "none"


@pytest.mark.parametrize("text", [
    "我有点头晕，心里发慌",
    "我这两天膝盖疼得厉害",
    "我胸口闷得慌",
    "我胃疼反酸",
    "我咳嗽好几天了",
    "我这两天有点乏力",
])
def test_a_symptom_report_goes_to_health_not_straight_to_booking(text: str):
    """**说不舒服 ≠ 要挂号**：症状先落到安康助手那儿过一遍分诊。

    这条钉的是一个真出过的漏子：旧剧本把"膝盖疼""胸口闷"都算成"要挂号"，
    于是老人说一句"有点头晕"，全部分诊被跳过、直接查号源挂号 —— 正是本项目
    定义的最严重错误（见数/见症状就撵老人上医院）。分岔一旦回到 medical_trip，
    这条线就整个绕过去了，所以它必须单独有个门禁。
    """
    from app.providers.llm import mock

    assert _branch(text) == "health", f"「{text}」该走安康助手分诊"
    assert mock._symptom_in(text), f"「{text}」没被认成症状"


@pytest.mark.parametrize("text,branch", [
    ("我心里闷得慌，一个人没意思", "community"),   # 孤独，不是胸闷
    ("我想找老伙计下下棋", "community"),
    ("我想出门散散步", "travel"),
    ("帮我约个明天的骨科号", "medical_trip"),        # 点名科室 = 把事说全了
    ("我想去鼓楼医院看病", "medical_trip"),
])
def test_the_other_lines_still_keep_their_own_words(text: str, branch: str):
    """修"见症状就挂号"不能顺手把别的线也带歪。

    "闷"字是这里的钉子：老人说"心里闷"是没人说话的闷（邻里帮），
    说"胸口闷"才是身体的事（安康助手）。一个字放宽，胸闷就会被送进活动推荐里。
    """
    assert _branch(text) == branch, f"「{text}」该走 {branch}"


def test_the_department_comes_from_the_same_data_as_the_real_path():
    """离线剧本和真模型那条路必须查**同一份**症状→科室映射。

    两边各立一份表的后果是很实在的：同一句"我胃疼"，真模型那条路查消化内科，
    拔了网线演示却查骨科 —— 而科室会一路冻结给家人确认、印到计划书上。
    所以这里拿真 provider 的 ``suggest_department`` 当基准，逐条比对。
    """
    from app.providers.external.hospital import MockHospitalProvider
    from app.providers.llm import mock

    provider = MockHospitalProvider()
    samples = ("我腿疼", "膝盖疼", "关节痛", "风湿", "胸闷", "心慌", "血压高",
               "咳嗽", "气短", "胃疼", "反酸", "眼睛看不清", "头晕", "拉肚子")
    for symptom in samples:
        real = asyncio.run(provider.suggest_department(symptom))
        assert mock._dept_for(symptom) == real, \
            f"「{symptom}」离线剧本给 {mock._dept_for(symptom)}，真路径给 {real}"


def test_a_symptom_that_maps_to_no_department_falls_back_the_same_way():
    """配不出科室的症状按同一个默认走 —— 两边一致，且**不偷偷编一个科室**。"""
    from app.providers.llm import mock

    assert mock._dept_for("我这两天有点乏力") == "骨科", \
        "配不出科室时落默认值，和 search_hospital 的默认一致"


def test_an_elder_saying_it_lasted_days_is_worth_a_doctor():
    """老人说"好几天了"，就是书面语里的"持续" —— 拖久了的症状该去看。

    只认"持续""反复"这种词，最日常的那句主诉就留在"观察"里了。
    """
    assert hr.assess_symptom("我咳嗽好几天了")[0] == "建议就医"
    assert hr.assess_symptom("这个毛病一直没好")[0] == "建议就医"
    # 但别把"这两天"也当成持续：那是描述近况，不是病程
    assert hr.assess_symptom("我这两天有点乏力")[0] == "观察"


# ============================================================ 知会不审批（同源）

async def test_the_booking_notice_reuses_the_triage_brain(ctx, elder):
    """挂号知会里那句"为什么去"，必须与老人端的分诊**是同一段代码**。

    子女是照着这条知会判断"要不要回一趟家"的。如果知会另写一套判断，同一个
    178/105 就可能在子女端是"略高"、在老人端是"建议就医" —— 两条路各说各话，
    比没有知会更糟：家人会以为老人报的数被系统看轻了。
    所以 ``_visit_reason`` 直接复用 ``triage_overview``，这里把"同源"钉死。
    """
    from app.tools import health_tools as ht

    await seed_kangle_persona(ctx.repos, elder)
    turn = _turn(ctx, elder, "s-notice")

    reason = await ht._visit_reason(turn, {})
    grouped = await ht._grouped_history(ctx.repos, elder["id"])
    conditions = await ht._active_conditions(ctx.repos, elder["id"])
    overview = ht.triage_overview(grouped, conditions)

    assert reason["level"] == overview["level"] == "建议就医"
    assert reason["drivers"] == overview["drivers"]
    assert reason["text"] == "；".join(d["reason"] for d in overview["drivers"])
    assert "178/105" in reason["text"], "原因里要带着那个数，家人才看得懂"


async def test_a_reason_is_never_invented_when_there_is_nothing_to_go_on(ctx, elder):
    """库里没指标、也没说症状：知会宁可**不写原因**，也不编一个出来。

    编出来的"原因"会被子女当成事实读 —— 这是 R1 最直接的一种破法。
    """
    from app.tools import health_tools as ht
    from app.core.context import TurnContext

    stranger = {**elder, "id": "00000000-0000-0000-0000-0000000000aa"}
    reason = await ht._visit_reason(
        TurnContext(ctx=ctx, session_id="s-bare", user=stranger), {})
    assert reason == {"level": "", "drivers": [], "readings": [],
                      "symptom": "", "text": ""}


async def test_a_measured_metric_is_not_a_symptom(ctx, elder):
    """**"量了哪一项"不是"哪儿难受"**：报一个数不该在知会里长出半句主诉。

    老人说"血压 178/105"，走的是"报数 → 分诊 → 该就医 → 就近挂号"。挂号要带一句
    "为什么去"，主智能体顺手把科室映射命中的那个词（**"血压"**）传了下来 —— 而科室
    映射里除了"腿疼"确实也收着"血压"。不拦的话，子女收到的知会是这么一句：

        去的原因：提到“血压”，先观察，持续或加重就去看医生；血压 178/105，中重度偏高。
        分诊为「建议就医」。

    前半句让人先观察、后半句说分诊建议就医，家人得自己猜哪句算数 —— 而老人**一个字
    的不舒服都没提**，他只是在念血压计上的数。那条主诉是系统替他编的。
    """
    from app.tools import health_tools as ht

    assert ht._as_symptom("血压") is None, "整句就是一个指标名：那不是主诉"
    assert ht._as_symptom("血糖") is None
    # 老人自己说了哪儿难受就照传 —— 宁可漏，不替他编话
    assert ht._as_symptom("腿疼") == "腿疼"
    assert ht._as_symptom("血压高得头晕") == "血压高得头晕", "这句话里有他自己的说法"
    assert ht._as_symptom("") is None
    assert ht._as_symptom(None) is None

    await seed_kangle_persona(ctx.repos, elder)
    turn = _turn(ctx, elder, "s-not-a-symptom")
    reason = await ht._visit_reason(turn, {"reason": "血压"})
    assert reason["symptom"] == "", "血压不该被当成主诉写进知会"
    assert not any(d["metric"] == "symptom" for d in reason["drivers"])
    assert "先观察" not in reason["text"], \
        f"知会里不能出现与「建议就医」打架的“先观察”：{reason['text']}"
    assert "178/105" in reason["text"], "指标本身还是要说清楚"


# ==================================================================== 收尾对账
#
# 老人**最后听到的那一句**由主智能体说。它是这一轮的落点：手边有什么卡、号挂上没有，
# 全在这一句里。可主智能体那一层的流水里**看不到子助理调的工具** —— delegate 只回一段
# 摘要（见 main_agent.py 的 digest）。所以"照流水自己拼一句"这条路走过一次，四个分支
# 一个都不成立，问菜的人最后听见的是"活动都给您找出来啦"。
#
# 下面这组把新契约钉死：**谁说的事谁收尾**，主智能体转述子助理自己那句话。

def test_the_specialist_line_comes_back_verbatim():
    """从 delegate 摘要里把子助理的原话取回来。"""
    from app.providers.llm.mock import _specialist_line

    summary = ('{"ok": true, "summary": "已协调子助理处理完毕：\\n'
               '✔ 邻里帮：想孩子了，上面那张电话卡点一下就能打；'
               '社区活动都给您找出来啦，约上老伙计一块儿去。", "tool": "delegate"}')
    assert _specialist_line(summary) == \
        "想孩子了，上面那张电话卡点一下就能打；社区活动都给您找出来啦，约上老伙计一块儿去。"

    # 一行摘要后面还缀着分诊那一行（main_agent 的 digest 会 append），不能一起念出来
    with_tier = ('✔ 安康助手：号已经挂好啦，也把您的情况跟家里说了一声。\n'
                 '   分诊: 建议就医；挂号: 南京鼓楼医院 / 心内科')
    assert _specialist_line(with_tier) == "号已经挂好啦，也把您的情况跟家里说了一声。"

    # 一轮派了两支时，按角色名取，别拿到最后那一条
    two = ("✔ 安康助手：号已经挂好啦。\n✔ 银发导航：路线我给您规划好啦。")
    assert _specialist_line(two, "安康助手") == "号已经挂好啦。"
    assert _specialist_line(two, "银发导航") == "路线我给您规划好啦。"


def test_a_failed_or_empty_report_has_no_line_to_relay():
    """``✘``/``⏳`` 下面不是"办成之后说的话"，占位词更不是 —— 都不能念给老人。

    ✘ 那行下面是错误信息，⏳ 那行下面是"等家人确认"。照搬过来，老人会听见
    一句失败宣言或者一句已经作废的等待，而 system 其实什么都没办成。
    """
    from app.providers.llm.mock import _specialist_line

    assert _specialist_line("✘ 邻里帮：社区服务连不上") == ""
    assert _specialist_line("⏳ 安康助手：已选定，等家人确认") == ""
    assert _specialist_line("✔ 邻里帮：已完成") == "", "占位词不是内容"
    assert _specialist_line("") == ""
    assert _specialist_line("（这一层根本没有回报）") == ""


@pytest.mark.parametrize("text,agent,expect_card", [
    ("教我做一道软烂清淡的家常菜", "community", "recipe"),
    ("我心里闷得慌，一个人没意思", "community", "call"),
    ("陪我散散步", "community", "walk_card"),
])
async def test_the_last_line_matches_what_the_specialist_actually_did(
        ctx, run_turn, text, agent, expect_card):
    """老人最后听到的那句，必须就是子助理那句话 —— 不是主智能体另编的一句。

    旧实现里主智能体自己拼收尾，判据是"流水里出现过哪个工具"。那个判据是假的
    （见本组开头），于是它一律说"都给您张罗好啦"，老人要的菜、要的那通电话
    全被一句话盖过去 —— 卡就在屏幕上，可最后听见的那句没提它。
    """
    from app.core.events import AGENT_REPORT
    from app.core.subagents import AgentReport

    sid, events = await run_turn(text)
    reports = [AgentReport.from_dict(e.payload) for e in ctx.event_log.events(sid)
               if e.type == AGENT_REPORT]
    report = next(r for r in reports if r.agent == agent)
    assert report.ok, f"这一轮该真办成事：{report.error}"

    cards = [e.data for e in events
             if e.event in ("card", "agent_msg") and isinstance(e.data, dict)
             and e.data.get("type") == expect_card]
    assert cards, f"「{text}」该出一张 {expect_card} 卡"

    final = [e.data["text"] for e in events if e.event == "final"][-1]
    assert final == report.summary, \
        f"主智能体的收尾该转述子助理那句：\n  主智能体：{final}\n  子助理：{report.summary}"


async def test_a_walk_request_reaches_the_ring_card(ctx, run_turn):
    """**"陪我散散步"要走到右翼那张环线卡**，不能被出行线半路接走。

    这两句话长得像、问的不是一件事：出行线的 ``plan_route`` 要一个**终点**，
    而"陪我散散步"里根本没有终点 —— 它只能给出一条不知通向哪里的路线，
    老人最后听到"出行的事都办好啦"。右翼的环线卡正好反过来：走回出发点，
    不必有终点，还说清多远、走多久、在哪儿歇。
    """
    from app.providers.llm import mock

    assert mock._wants_walk("陪我散散步")
    # 点了"怎么走"的散步仍归出行线 —— 那时候老人要的确实是路线
    assert mock._wants_travel("去公园散步怎么走") and \
        any(k in "去公园散步怎么走" for k in mock._ROUTE_WORDS)

    _sid, events = await run_turn("陪我散散步")
    walk = [e.data for e in events
            if e.event in ("card", "agent_msg") and isinstance(e.data, dict)
            and e.data.get("type") == "walk_card"]
    assert walk, "右翼的散步环线卡一次都没出过 —— 它此前是条走不到的死路"
    final = [e.data["text"] for e in events if e.event == "final"][-1]
    assert "散步" in final or "道儿" in final, f"最后一句要提到那条道儿：{final}"

