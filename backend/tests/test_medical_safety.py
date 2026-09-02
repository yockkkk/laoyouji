"""医疗安全 —— 红线 R1（不做诊断）/ R2（不做处方）/ R4（强制免责声明）的门禁。

提示词里早就写了"绝不诊断"。但提示词是**请求**，不是**保证** —— 模型偶尔会忘，
而这条线不能靠自觉。所以这里验收的是三道各自独立的机制：

- **R1/R2 是出口改写**，不是入口约束：``agent/request`` 瀑布的**最外层**
  （order=-100）看的是所有重试、所有其它中间件之后的**最终**那条应答，谁也绕不过。
- **整句替换，不抠词**：抠词会留下"您这是…（已隐去）"这种更吓人的残句。
  整句换掉之后剩下的话仍然通顺，而且引导就医的那半句还在 —— 宁可少说一句，
  不可错说一句。
- **R4 是后置注入**，落在 ``tools/post-execute``：健康域工具的结论一律带
  免责声明，不问模型愿不愿意。

还有一条**刻意留下的边界**要在这里写明白：流式 ``delta`` 是 provider 内部逐片推的，
比改写更早到前端。那些片段是"打字预览"（``persist=False``，不进事件日志）；
进日志、进模型历史、以及前端最终定稿的那条气泡，都是改写后的那一份。
所以"前端必须用 ``agent_msg`` 覆盖预览"不是建议，是契约 ——
本文件里 ``test_the_streaming_preview_is_not_the_authoritative_text`` 就是它的门禁。

误杀比漏杀更隐蔽：饮食推荐和用药提醒都是本项目**声明过的正常能力**，
被这把筛子顺手杀掉的话，功能会静静地少一半而没人报错。所以两组反面测试
（``_DIET_LINES`` / ``_REMINDER_LINES``）和正面测试一样重要。
"""
from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.core.bus import EventBus, REQUEST
from app.core.context import TurnContext
from app.core.events import ASSISTANT_MESSAGE, MAIN_SCOPE
from app.core.registry import ServiceProvider
from app.core.tool import Tool
from app.providers.llm.base import LLMResponse, ToolCallReq
from app.providers.llm.mock import MockLLMProvider
from app.safety.risk_rules import (
    DIAGNOSIS_REPLACEMENT,
    DISCLAIMER,
    GENERIC_DISCLAIMER,
    HEALTH_TOOLS,
    HIGH_RISK_TOOLS,
    HealthDisclaimerGuard,
    PRESCRIPTION_REPLACEMENT,
    install_medical_safety,
    scrub_medical_text,
)


# ------------------------------------------------------------------------ 素材

# 一句典型的越线输出：前半句是诊断（必须消失），后半句是引导就医（必须留下）。
_DIAGNOSIS_LINE = "您这是骨质疏松症，得赶紧治。要不要我帮您挂个骨科？"

_DIAGNOSIS_SENTENCES = (
    "您这是骨质疏松症。",          # "您这是××症"
    "老人得的是肺炎。",            # "得的是××炎"
    "已经确诊了。",                # 光"确诊"两个字就够
    "诊断为高血压二级。",
    "可以确定是糖尿病。",
    "这属于二型糖尿病。",
)

_PRESCRIPTION_SENTENCES = (
    "每天吃两片阿司匹林。",        # 吃…片
    "每天2片，饭后温水送服。",     # 每天 + 数字 + 片
    "以后停药就行了。",            # 停…药
    "建议您吃点消炎药。",          # 建议…吃…药
    "剂量可以自己加。",            # "剂量"本身就是处方语汇
    "口服两粒就好。",
)

# 饮食推荐是**声明过的能力**（diet_advice 工具）。处方规则刻意要求出现剂量单位
# 或"药"字，就是为了不把这些话误杀掉。
_DIET_LINES = (
    "建议吃点清淡的，少油少盐。",
    "多喝水，多吃青菜，一天三顿别落下。",
    "少吃咸菜，多吃新鲜蔬菜和水果。",
    "今天中午给您订了软食套餐，好嚼。",
)

# 用药提醒同理：提醒老人吃**医生已经开好**的药，不是替医生决定吃什么、吃多少。
_REMINDER_LINES = (
    "到点了，该吃药了。",
    "早上八点、晚上八点，我都提醒您。",
    "记好啦，钙片记得饭后吃。",
)


def _tool(name: str) -> Tool:
    """一个只有名字的工具 —— 免责声明守卫只看名字和结果，不会调 handler。"""
    async def handler(turn, args: dict) -> dict:      # pragma: no cover
        return {"ok": True}

    return Tool(name=name, description=f"{name}。测试桩",
                parameters={"type": "object", "properties": {}}, handler=handler)


async def _through(bus: EventBus, response: LLMResponse,
                   *, agent: str = "health") -> LLMResponse:
    """把一条应答送过 ``agent/request`` 瀑布，返回出口那一份。"""
    async def terminal(_request) -> LLMResponse:
        return response

    request = SimpleNamespace(agent=SimpleNamespace(name=agent))
    return await bus.waterfall(REQUEST, request, terminal)


def _of(events, name: str) -> list[dict]:
    return [e.data for e in events if e.event == name]


async def _answer(ctx, elder, content: str, *, title: str = "解读"):
    """让安康助手把 ``content`` 说出口，返回 ``(turn, AgentTurn, SSE 事件列表)``。

    用的是真的安康助手（不是桩）：要验的就是**真实装配**下这条线管不管用。
    """
    ctx.registry.register(ServiceProvider(
        "llm", lambda _c: MockLLMProvider(script=[LLMResponse(content=content)])))
    session = await ctx.event_log.create_session(elder["id"], title)
    turn = TurnContext(ctx=ctx, session_id=session["id"], user=elder)
    agent_turn = await ctx.agents["health"].run_turn(
        turn, "报告上写着骨密度低，我这是咋了？")

    events = []
    while not turn.queue.empty():
        events.append(turn.queue.get_nowait())
    return turn, agent_turn, events


def _assistant_texts(ctx, session_id: str) -> list[str]:
    return [e.payload.get("text") or "" for e in ctx.event_log.events(session_id)
            if e.type == ASSISTANT_MESSAGE]


# -------------------------------------------------------------- 逐句体检（纯函数）


def test_a_diagnosis_sentence_is_replaced_whole_and_the_helpful_half_survives():
    """整句替换而不是抠词，而且**引导就医的那半句留着** —— 这才是有用的输出。

    抠词的后果是留下"您这是…（已隐去）"，比原话更吓人；整句换掉之后，
    "要不要我帮您挂个骨科？"照样在，老人拿到的是下一步动作，不是一句拒绝。
    """
    cleaned, hits = scrub_medical_text(_DIAGNOSIS_LINE)

    assert hits == ["diagnosis"]
    assert cleaned == f"{DIAGNOSIS_REPLACEMENT}要不要我帮您挂个骨科？"
    assert "骨质疏松" not in cleaned, "病名一个字都不该留"
    assert "得赶紧治" not in cleaned, "同一句里的话跟着整句一起走"


@pytest.mark.parametrize("sentence", _DIAGNOSIS_SENTENCES)
def test_every_way_of_saying_a_diagnosis_is_caught(sentence: str):
    """六种说法都算诊断 —— 不能只拦"您这是××病"这一种句式。"""
    cleaned, hits = scrub_medical_text(sentence)
    assert hits == ["diagnosis"], sentence
    assert cleaned == DIAGNOSIS_REPLACEMENT, sentence


@pytest.mark.parametrize("sentence", _PRESCRIPTION_SENTENCES)
def test_every_way_of_prescribing_is_caught(sentence: str):
    """剂量、频次、停药、加量都算处方（R2）—— 这些话只有医生能说。"""
    cleaned, hits = scrub_medical_text(sentence)
    assert hits == ["prescription"], sentence
    assert cleaned == PRESCRIPTION_REPLACEMENT, sentence


@pytest.mark.parametrize("line", _DIET_LINES)
def test_diet_advice_is_not_a_prescription(line: str):
    """饮食推荐必须原样活着 —— 它是本项目声明过的能力，不是越线。

    这条测试守的是 ``_PRESCRIPTION_PATTERNS`` 里那个刻意的约束：必须出现
    **剂量单位或"药"字**才算命中。放宽一点，"建议吃点清淡的"就会被替换成
    "吃什么药得听医生的" —— 功能静静地少一半，而且没有任何报错。
    """
    assert "diet_advice" in HEALTH_TOOLS, "饮食推荐确实是在册能力，不是假想的"
    assert scrub_medical_text(line) == (line, []), line


@pytest.mark.parametrize("line", _REMINDER_LINES)
def test_a_medication_reminder_is_not_a_prescription(line: str):
    """提醒吃**已经开好**的药 ≠ 决定吃什么药、吃多少。R2 的线画在"决定"上。"""
    assert scrub_medical_text(line) == (line, []), line


def test_the_same_kind_never_repeats_its_replacement():
    """连着两句诊断只留一句替代话 —— 复读三遍"我不能判断"像在推卸责任。"""
    cleaned, hits = scrub_medical_text("您这是高血压。您这是糖尿病。这个我记下了。")

    assert hits == ["diagnosis", "diagnosis"], "两句都要记账"
    assert cleaned.count(DIAGNOSIS_REPLACEMENT) == 1, "但只说一遍"
    assert cleaned == f"{DIAGNOSIS_REPLACEMENT}这个我记下了。"


def test_two_kinds_each_get_their_own_sentence_in_order():
    """两类各有各的替代话，按原文顺序排 —— 剩下的话仍然读得通。"""
    cleaned, hits = scrub_medical_text("您这是骨质疏松。每天2片钙片。回去多晒太阳。")

    assert hits == ["diagnosis", "prescription"]
    assert cleaned == (f"{DIAGNOSIS_REPLACEMENT}{PRESCRIPTION_REPLACEMENT}"
                       "回去多晒太阳。")


def test_a_sentence_that_trips_both_is_charged_to_the_graver_one():
    """一句话里两样都犯 → 按诊断算（更严重的那条），整句一起消失。"""
    cleaned, hits = scrub_medical_text("您这是糖尿病，每天2片降糖药。")

    assert hits == ["diagnosis"], "诊断优先，不重复记两笔"
    assert cleaned == DIAGNOSIS_REPLACEMENT
    assert PRESCRIPTION_REPLACEMENT not in cleaned
    assert "降糖药" not in cleaned


def test_a_clean_answer_comes_back_unchanged():
    """没越线就一个字都不动 —— 筛子不能顺手改写正常回话。"""
    clean = "明天上午九点提醒您去积水潭医院，别忘了带医保卡。"
    assert scrub_medical_text(clean) == (clean, [])
    assert scrub_medical_text("") == ("", [])


def test_the_replacement_sentences_hand_the_question_to_a_doctor():
    """替代话得给出**下一步**（找医生），不是只说"我不能说"。

    而且是给老人听的：一个英文字母都不该出现（同 test_budget 的措辞门禁）。
    """
    assert "大夫" in DIAGNOSIS_REPLACEMENT
    assert "医生" in PRESCRIPTION_REPLACEMENT
    for reply in (DIAGNOSIS_REPLACEMENT, PRESCRIPTION_REPLACEMENT):
        assert not any(c.isascii() and c.isalpha() for c in reply), reply
        assert reply.endswith("。")


# ------------------------------------------------------------------------ 装配


async def test_the_scrubber_is_the_outermost_request_listener(ctx):
    """装配可自证：``agent/request`` 上就这一位，而且是最外层。

    只挂一次也是契约 —— 挂两次会把同一段话记两笔警告日志，审计时对不上账。
    """
    assert ctx.bus.listeners(REQUEST) == ["diagnosis-scrubber"]


async def test_the_scrubber_can_be_taken_off_again():
    """注册是可逆副作用：摘掉之后同一句话原样通过 —— 行为确实来自那位监听者。"""
    bus = EventBus()
    disposers = install_medical_safety(bus)
    assert bus.listeners(REQUEST) == ["diagnosis-scrubber"]

    guarded = await _through(bus, LLMResponse(content=_DIAGNOSIS_LINE))
    assert DIAGNOSIS_REPLACEMENT in guarded.content

    for dispose in disposers:
        dispose()
    assert bus.listeners(REQUEST) == []

    bare = await _through(bus, LLMResponse(content=_DIAGNOSIS_LINE))
    assert bare.content == _DIAGNOSIS_LINE, "没有守卫时原话就会直接出去"


async def test_the_scrubber_screens_what_other_middleware_returns():
    """order=-100 不是装饰：**重试中间件第二次拿到的那份**照样过筛子。

    这是"最外层"的实际含金量 —— 如果它挂在里层，重试/降级中间件返回的应答
    就整份绕过去了，而那恰恰是模型状态最不稳、最容易说错话的一次。
    """
    bus = EventBus()
    install_medical_safety(bus)

    async def fake_retry(request, next_):
        await next_()                                  # 第一次的结果丢掉
        return LLMResponse(content=_DIAGNOSIS_LINE)    # 重试后的那一份

    bus.on(REQUEST, fake_retry, order=0, label="fake-retry")
    assert bus.listeners(REQUEST) == ["diagnosis-scrubber", "fake-retry"]

    out = await _through(bus, LLMResponse(content="好的，我先给您查查。"))
    assert DIAGNOSIS_REPLACEMENT in out.content
    assert "骨质疏松" not in out.content


@pytest.mark.parametrize("content", ["", None])
async def test_a_response_without_text_passes_straight_through(content):
    """只带工具调用、没有正文的那一步不该被碰（也不该因此报错）。"""
    bus = EventBus()
    install_medical_safety(bus)
    response = LLMResponse(content=content)            # type: ignore[arg-type]

    out = await _through(bus, response)
    assert out is response and out.content == content


async def test_scrubbing_the_words_does_not_cancel_the_action():
    """改写措辞不许顺手把"帮您挂号"这个动作也撤掉。

    老人真正需要的是那次挂号。把话改干净、把事照办，两件事不能互相牵连。
    """
    bus = EventBus()
    install_medical_safety(bus)
    call = ToolCallReq(id="c1", name="register_appointment",
                       arguments={"department": "骨科"})

    out = await _through(bus, LLMResponse(content=_DIAGNOSIS_LINE,
                                          tool_calls=[call]))

    assert DIAGNOSIS_REPLACEMENT in out.content
    assert out.tool_calls == [call], "调用一个不少，参数一个不改"


# ---------------------------------------------------------------------- 在线路径


async def test_a_diagnosis_never_reaches_the_event_log(ctx, elder):
    """真跑一轮：越线的话在**进事件日志之前**就被换掉了。

    日志是唯一事实源，所以"日志里没有"等于"历史里没有、审计里没有、
    子女端回看也没有"。
    """
    turn, agent_turn, events = await _answer(ctx, elder, _DIAGNOSIS_LINE)
    expected = f"{DIAGNOSIS_REPLACEMENT}要不要我帮您挂个骨科？"

    assert agent_turn.stop_reason == "model/idle"
    assert agent_turn.final_text == expected
    assert _assistant_texts(ctx, turn.session_id) == [expected]
    assert _of(events, "agent_msg")[-1]["text"] == expected


async def test_the_next_step_does_not_inherit_the_diagnosis(ctx, elder):
    """派生出的模型历史里也没有那句话 —— 否则下一步会照着自己上一句继续说。

    改写的是**权威应答对象**，而历史只从事件日志派生，所以这两件事是同一件事。
    """
    turn, _, _ = await _answer(ctx, elder, _DIAGNOSIS_LINE)
    history = ctx.event_log.derive_messages(turn.session_id, scopes=[MAIN_SCOPE])

    assistant = [m["content"] for m in history if m["role"] == "assistant"]
    assert assistant == [f"{DIAGNOSIS_REPLACEMENT}要不要我帮您挂个骨科？"]
    assert "骨质疏松" not in "".join(str(m.get("content") or "") for m in history)


async def test_the_streaming_preview_is_not_the_authoritative_text(ctx, elder):
    """**刻意留下的边界**：流式片段是原话，定稿那条是改写后的。

    ``delta`` 由 provider 内部逐片推出，比改写更早到前端，而且 ``persist=False``
    —— 不进日志、不进历史、不进审计。所以前端必须用 ``agent_msg`` **覆盖**预览，
    不是往后追加。这条契约写在 docs/DESIGN.md 里，这里是它的门禁。
    """
    turn, _, events = await _answer(ctx, elder, _DIAGNOSIS_LINE)

    preview = "".join(e["text"] for e in _of(events, "delta"))
    assert preview == _DIAGNOSIS_LINE, "预览确实是原话（这就是为什么必须覆盖）"

    final = _of(events, "agent_msg")[-1]["text"]
    assert final != preview and DIAGNOSIS_REPLACEMENT in final
    # 预览没落库，所以事实源那一份是干净的
    assert "骨质疏松" not in "".join(_assistant_texts(ctx, turn.session_id))


async def test_the_rewrite_leaves_a_warning_in_the_log(ctx, elder, caplog):
    """改写不是静默的：哪个智能体、命中哪一类，日志里写着 —— 答辩时能当场调出来。"""
    with caplog.at_level(logging.WARNING, logger="app.safety.risk_rules"):
        await _answer(ctx, elder, _DIAGNOSIS_LINE)

    messages = [r.getMessage() for r in caplog.records]
    hit = [m for m in messages if "R1/R2 改写" in m]
    assert len(hit) == 1, messages
    assert "health" in hit[0] and "diagnosis" in hit[0]


async def test_a_benign_answer_survives_the_round_trip(ctx, elder):
    """正常回话走完整条线一个字不变 —— 守卫不许有"顺手改写"的副作用。"""
    clean = "报告上那几项我给您念一遍大白话，您慢慢听。"
    turn, agent_turn, events = await _answer(ctx, elder, clean, title="正常")

    assert agent_turn.final_text == clean
    assert _assistant_texts(ctx, turn.session_id) == [clean]
    assert "".join(e["text"] for e in _of(events, "delta")) == clean


# ------------------------------------------------------------------ R4 免责声明


def test_health_tools_is_the_set_that_gets_the_disclaimer():
    """哪些工具算"健康域结论"是一份明账，不是散在各处的 if。

    ``add_medication`` 刻意不在里面：它记的是医生已经开好的药，属于提醒，
    句尾挂一句"这不是诊断"只会让老人以为提醒本身也不可信。
    """
    assert HEALTH_TOOLS == {"interpret_report", "diet_advice",
                            "register_appointment", "search_hospital",
                            "check_scam"}
    assert "add_medication" not in HEALTH_TOOLS
    # 挂号同时是高危项：一件事可以同时被两条线管，互不替代
    assert "register_appointment" in HEALTH_TOOLS & HIGH_RISK_TOOLS


def test_the_disclaimer_says_assisted_reading_not_diagnosis():
    """口径按要求收紧：明说"辅助解读、不是诊断结论"，别让人误读成看过病了。"""
    assert "辅助解读" in DISCLAIMER
    assert "不是诊断结论" in DISCLAIMER
    assert "遵医嘱" in DISCLAIMER


def test_both_wordings_carry_the_same_three_promises():
    """两版措辞可以不一样，R4 的实质不许不一样。

    通用版是给反诈、挂号、找医院、饮食建议用的 —— 那些场合面前没有报告。
    但"这是辅助的""不是诊断结论""遵医嘱"三件事，哪个工具都得说到。
    """
    assert GENERIC_DISCLAIMER != DISCLAIMER
    for note in (DISCLAIMER, GENERIC_DISCLAIMER):
        assert "辅助" in note
        assert "不是诊断结论" in note
        assert "遵医嘱" in note
    # 去重判据是"遵医嘱"，两版都含它 —— 换措辞不会换出两遍声明
    assert "报告" not in GENERIC_DISCLAIMER


async def test_only_the_report_reading_talks_about_a_report():
    """措辞要对得上眼前的事。

    这条钉的是一个真出现过的毛病：五个健康域工具共用体检解读那一版措辞，
    于是老人问"有人说我中奖了让我交钱"，反诈判定后面跟着一句
    "以上是把报告上的话换成大白话" —— 没有报告，也没人念过报告。
    对不上号的免责声明会被当噪音跳过去，那 R4 就等于白注入。
    """
    guard = HealthDisclaimerGuard()

    reading = await guard.apply(
        None, _tool("interpret_report"), {"ok": True, "summary": "骨密度偏低。"})
    assert reading["summary"].endswith(DISCLAIMER)

    for name in ("check_scam", "diet_advice", "search_hospital",
                 "register_appointment"):
        out = await guard.apply(None, _tool(name), {"ok": True, "summary": "好了。"})
        assert out["summary"].endswith(GENERIC_DISCLAIMER), name
        assert "报告" not in out["summary"], name


def test_every_health_tool_has_a_wording_that_fits():
    """新增健康域工具时忘了登记措辞，兜底也必须是一句说得通的话。

    默认走通用版，不是"随便挑一版" —— 所以这里只要求每个工具都能取到一版，
    且体检解读取到的是报告那一版。
    """
    from app.safety.risk_rules import _DISCLAIMER_BY_TOOL, GENERIC_DISCLAIMER as G

    for name in HEALTH_TOOLS:
        assert _DISCLAIMER_BY_TOOL.get(name, G)
    assert _DISCLAIMER_BY_TOOL["interpret_report"] is DISCLAIMER
    assert set(_DISCLAIMER_BY_TOOL) <= HEALTH_TOOLS


async def test_a_report_reading_carries_the_disclaimer_on_both_channels(ctx, elder):
    """体检解读的**两条出口**（屏幕的 summary、朗读的 announce）都得带上。

    只加在 summary 上，TTS 念出来的那一版就成了没有免责声明的版本 ——
    而老人主要靠听。（大白话正文由 Mock 生成，内容不是这里的重点。）
    """
    turn = TurnContext(ctx=ctx, session_id="s-r4", user=elder)
    result = await ctx.dispatcher.execute(
        turn, "interpret_report", {"report_text": "骨密度 T 值 -2.8"})

    assert result["ok"] is True
    assert result["summary"].endswith(DISCLAIMER)
    assert result["announce"].endswith(DISCLAIMER)


async def test_the_disclaimer_is_never_appended_twice():
    """已经说过"遵医嘱"就不再补一句 —— 连着两遍免责声明像法务文本，没人看。"""
    guard = HealthDisclaimerGuard()
    tool = _tool("interpret_report")

    once = await guard.apply(None, tool, {"ok": True, "summary": "血脂略高一点。"})
    twice = await guard.apply(None, tool, dict(once))

    assert once["summary"].count(DISCLAIMER) == 1
    assert twice["summary"] == once["summary"]


async def test_a_non_health_tool_is_left_alone():
    """订票回执后面挂一句"不是诊断结论"是荒谬的。域外一个字不加。"""
    guard = HealthDisclaimerGuard()
    result = {"ok": True, "summary": "G102 已订好。", "announce": "票订上了。"}

    out = await guard.apply(None, _tool("book_ticket"), dict(result))
    assert out == result


async def test_a_failed_health_result_is_left_alone():
    """免责声明是给**结论**加的，不是给报错加的 —— 没给出解读就没有需要免责的东西。"""
    guard = HealthDisclaimerGuard()
    failed = {"ok": False, "summary": "请把体检报告上的文字念给我或发给我"}

    out = await guard.apply(None, _tool("interpret_report"), dict(failed))
    assert out == failed
    assert DISCLAIMER not in out["summary"]


async def test_a_suspended_appointment_is_not_dressed_up_with_a_disclaimer(
        ctx, elder):
    """挂号被拦下时说的是"等家人确认"，不是一句结论 —— 别给流程状态贴免责声明。

    ``register_appointment`` 同时在健康域和高危集里，所以这一条同时确认了两件事：
    R5 照常拦（``suspended``），R4 照常不掺和（``ok`` 为假就不注入）。
    """
    turn = TurnContext(ctx=ctx, session_id="s-suspend", user=elder)
    result = await ctx.dispatcher.execute(turn, "register_appointment", {
        "hospital": "北京积水潭医院", "department": "骨科",
        "doctor": "田伟", "fee": 100})

    assert result["suspended"] is True and result["ok"] is False
    assert DISCLAIMER not in result["summary"]
    assert GENERIC_DISCLAIMER not in result["summary"]
    assert "确认" in result["summary"]
