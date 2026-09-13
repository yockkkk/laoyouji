"""子智能体接缝：真并发扇出、作用域隔离、结构化回报。

这是"真多智能体"三个字的验收现场。旧实现有两处是布景：

- **缺陷 #1**：每个子智能体都拉同一份 ``llm_history(session_id, 20)``，
  出行助理能读到健康助理和老人的往来 —— 隔离是话术。
- **缺陷 #2**：``route_to_agent`` 在父工具体内 ``await agent.run()``，
  天然串行且嵌套；提示词还写死"一次派一个"。所谓"调度"只是排队。

再加一条更要紧的：父从子那里拿到的是**一段话**，于是《就医出行计划书》只能靠
总智能体照着那段话重编一遍字典（缺陷 #5）。现在拿到的是 ``AgentReport``，
字段由工具结果采集而来 —— 每一行都能指认出处。

所以本文件的断言分四组：**发现**（装配可自证）、**并发**（墙钟）、
**隔离**（模型看到了什么）、**回报**（字段从哪来、缺了怎么办）。
"""
from __future__ import annotations

import asyncio
import json
import re
import time

from app.agents.base import BaseAgent
from app.core.bus import TOOLS_RESULT
from app.core.context import TurnContext
from app.core.events import AGENT_REPORT
from app.core.registry import ServiceProvider
from app.core.subagents import FORK, SPAWN, AgentReport, SubagentSpec
from app.providers.external.base import load_fixture
from app.providers.llm.base import LLMProvider, LLMResponse, ToolCallReq
from app.providers.llm.mock import MockLLMProvider
from app.tools.community_tools import get_recipe, push_activities, walk_estimate


# ---------------------------------------------------------------------- 桩与工具


class _RecordingLLM(LLMProvider):
    """记下每次请求收到的 messages，然后一句话收尾（不调工具）。

    两件事靠它：一是"子智能体到底看到了什么历史"（隔离），
    二是"三支同时跑还是一支接一支"（并发）—— 后者靠 ``delay`` 把差异放大。
    """

    name = "recording"

    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.seen: list[list[dict]] = []
        # 同时在飞的请求数峰值。并发与否**看这个**，不看墙钟：
        # 墙钟在忙机器上会被调度噪声抬高，峰值不会 —— 三支真同时跑，峰值就是 3。
        self._inflight = 0
        self.peak_inflight = 0

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   on_delta=None) -> LLMResponse:
        self.seen.append([dict(m) for m in messages])
        self._inflight += 1
        self.peak_inflight = max(self.peak_inflight, self._inflight)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            return LLMResponse(content="好的，我知道了。")
        finally:
            self._inflight -= 1

    @property
    def calls(self) -> int:
        return len(self.seen)

    def user_texts(self, index: int = 0) -> list[str]:
        return [m["content"] for m in self.seen[index] if m["role"] == "user"]


class _BrokenAgent(BaseAgent):
    """必然出事的子智能体：构造 messages 时就抛。"""

    name = "broken"
    display_name = "会炸的助理"
    tool_names: list[str] = []

    @property
    def system_prompt(self) -> str:            # type: ignore[override]
        raise RuntimeError("提示词模板坏了")


def _use_llm(ctx, llm):
    """换掉 ``llm`` 这个能力的实现：覆盖注册即失效旧实例（注册表的补丁语义）。

    顺手也验证了"换真实 provider = 只改一行注册"不是一句空话 ——
    这里就是那一行，agents / tools / safety 一个字没动。
    """
    ctx.registry.register(ServiceProvider("llm", lambda _ctx: llm))
    assert ctx.resolve("llm") is llm
    return llm


async def _turn(ctx, elder, title: str) -> TurnContext:
    session = await ctx.event_log.create_session(elder["id"], title)
    return TurnContext(ctx=ctx, session_id=session["id"], user=elder)


async def _scripted(ctx, elder, *, agent: str, calls: list[ToolCallReq],
                    instruction: str = "办件事") -> AgentReport:
    """让某个子智能体照剧本调指定工具，然后收尾。返回它的回报。"""
    _use_llm(ctx, MockLLMProvider(script=[
        LLMResponse(content="好的，我来办。", tool_calls=calls),
        LLMResponse(content="办完了。")]))
    turn = await _turn(ctx, elder, "剧本")
    return await ctx.subagents.spawn(
        turn, SubagentSpec(name=agent, instruction=instruction))


def _collectors(ctx) -> list[str]:
    """还挂在 ``tools/result`` 上的采集监听者。跑完必须为空。"""
    return [x for x in ctx.bus.listeners(TOOLS_RESULT) if x.startswith("collect:")]


# ------------------------------------------------------------------------ 发现


async def test_available_declares_what_each_subagent_can_report(ctx):
    """发现接缝：谁在场、各自承诺哪些字段 —— 装配可当场自证，不靠文档。

    邻里帮的承诺从单项 ``activities`` 扩成四项：右翼补齐后它还会出拨号卡
    （``call_action``）、散步环线（``walk_route``）、家常菜谱（``recipe``）。
    """
    found = {x["name"]: tuple(x["reports"]) for x in ctx.subagents.available()}
    assert found == {
        "travel": ("route",),
        "health": ("appointment",),
        "community": ("activities", "call_action", "walk_route", "recipe"),
    }
    assert "main" not in ctx.subagents.names(), "总智能体不能把自己派出去"


async def test_every_subagent_introduces_itself(ctx):
    """display_name / description 是总智能体提示词的原料，空着就会悄悄降级派发。"""
    for entry in ctx.subagents.available():
        assert entry["display_name"] and entry["display_name"] != entry["name"]
        assert len(entry["description"]) > 4, entry


# ------------------------------------------------------------------ 派发规格解析


def test_spec_parse_accepts_the_shapes_a_model_actually_produces():
    """模型给的形状不止一种：裸字符串、agent/instruction、name/task 都收。"""
    assert SubagentSpec.parse("travel") == SubagentSpec(name="travel",
                                                       instruction="")
    parsed = SubagentSpec.parse({"agent": "health", "instruction": "挂个骨科号",
                                 "label": "挂号", "mode": FORK})
    assert (parsed.name, parsed.instruction) == ("health", "挂个骨科号")
    assert (parsed.label, parsed.mode) == ("挂号", FORK)

    alias = SubagentSpec.parse({"name": "travel", "task": "查车票"})
    # 未显式给 mode 时默认 fork：子智能体要看得见父的上下文（"订刚才说的那家"），
    # 需要全新空白作用域的场景必须显式写 "mode": "spawn"。
    assert (alias.name, alias.instruction, alias.mode) == ("travel", "查车票", FORK)
    blank = SubagentSpec.parse({"name": "travel", "task": "查车票", "mode": SPAWN})
    assert blank.mode == SPAWN


def test_spec_parse_refuses_a_dispatch_without_a_target():
    """没写派给谁就是 None —— 交给谁去办这件事不能靠猜。"""
    assert SubagentSpec.parse({}) is None
    assert SubagentSpec.parse({"instruction": "帮我办点事"}) is None
    assert SubagentSpec.parse(123) is None
    assert SubagentSpec.parse(None) is None


# ------------------------------------------------------------------------ 真并发


async def test_parallel_fanout_is_concurrent_not_serial(ctx, elder):
    """三支同时跑：三个模型请求同时在飞，而不是一支接一支（缺陷 #2 的正面验收）。

    每支模型请求固定睡 0.2 秒。判据用"在飞峰值 == 3"而不是墙钟数字：
    墙钟只是间接证据，跑全量套件时 Windows 上的调度开销就能把 0.2 秒的扇出
    抬到 0.5 秒，于是一条测真并发的断言变成了测这台机器忙不忙。
    墙钟仍然留着，但只卡在串行下限（3 × 0.2 = 0.6 秒）上做个兜底 ——
    **只留上限**：下限（"至少睡了 0.2 秒，说明桩真被调了"）看着像个保险，
    实际上 Windows 的时钟粒度能让 asyncio.sleep(0.2) 在 perf_counter 上量出
    0.187 秒，于是保险自己成了闪断源；桩到底调了没有，llm.calls 说得更准。
    """
    llm = _use_llm(ctx, _RecordingLLM(delay=0.2))
    turn = await _turn(ctx, elder, "扇出")
    specs = [SubagentSpec(name=name, instruction=f"{name} 这边办一下")
             for name in ("travel", "health", "community")]

    started = time.perf_counter()
    reports = await ctx.subagents.run_parallel(turn, specs)
    elapsed = time.perf_counter() - started

    assert [r.agent for r in reports] == ["travel", "health", "community"]
    assert llm.calls == 3, "三支各请求一次"
    assert llm.peak_inflight == 3, (
        f"同时在飞的请求峰值只有 {llm.peak_inflight}，扇出退化成串行了")
    assert elapsed < 0.6, f"墙钟到了串行下限：{elapsed:.2f}s"
    assert _collectors(ctx) == [], "采集监听者跑完即卸载"


async def test_one_spec_still_yields_one_report(ctx, elder):
    """只派一支时不走 gather，行为也必须一样（少一个特例就少一处走样）。"""
    _use_llm(ctx, _RecordingLLM())
    turn = await _turn(ctx, elder, "单派")
    reports = await ctx.subagents.run_parallel(
        turn, [SubagentSpec(name="travel", instruction="规划去医院的路线")])

    assert len(reports) == 1
    assert reports[0].scope == "travel#1"
    assert await ctx.subagents.run_parallel(turn, []) == []


# ------------------------------------------------------------------- 作用域隔离


async def test_spawn_child_sees_only_its_own_instruction(ctx, elder):
    """子作用域里只有派给它的那句话 —— 缺陷 #1 的正面验收。"""
    llm = _use_llm(ctx, _RecordingLLM())
    turn = await _turn(ctx, elder, "隔离")
    # 父作用域先落一句老人的原话。子智能体不该看见它。
    await turn.emit("user_msg", {"text": "我想在南京就近看腿疼的老毛病"})

    report = await ctx.subagents.spawn(
        turn, SubagentSpec(name="travel", instruction="规划从家到鼓楼医院怎么走"))

    assert report.scope == "travel#1"
    assert llm.calls == 1
    assert llm.seen[0][0]["role"] == "system", "第一条永远是自己的提示词"
    assert llm.user_texts(0) == ["规划从家到鼓楼医院怎么走"]
    assert "腿疼" not in "".join(llm.user_texts(0)), "父的原话不该漏进来"


async def test_fork_child_sees_the_parent_history_then_its_own(ctx, elder):
    """需要上文时才用 fork：作用域是 ``[父, 己]``，按 seq 织成一段连贯历史。"""
    llm = _use_llm(ctx, _RecordingLLM())
    turn = await _turn(ctx, elder, "承接")
    await turn.emit("user_msg", {"text": "我想在南京就近看腿疼的老毛病"})

    await ctx.subagents.fork(turn, SubagentSpec(
        name="travel", instruction="接着上面的事，规划从家到医院的路线", mode=FORK))

    assert llm.user_texts(0) == ["我想在南京就近看腿疼的老毛病",
                                 "接着上面的事，规划从家到医院的路线"]


async def test_concurrent_dispatches_never_share_a_scope(ctx, elder):
    """同时派三支同名子智能体 → 三个不同作用域。

    这条是 ``_reserved`` 那个补丁的门禁。作用域号本来只从事件日志推算，
    但并发起步时谁的 ``turn/start`` 都还没落下，三支都会算出 ``travel#1``
    —— 于是三个采集监听者认领同一批工具结果，回报串味。
    """
    _use_llm(ctx, _RecordingLLM(delay=0.05))
    turn = await _turn(ctx, elder, "撞号")
    reports = await ctx.subagents.run_parallel(turn, [
        SubagentSpec(name="travel", instruction=f"第{i}件事") for i in (1, 2, 3)])

    assert sorted(r.scope for r in reports) == ["travel#1", "travel#2",
                                                "travel#3"]


async def test_scope_numbering_continues_into_the_next_wave(ctx, elder):
    """第二波接着第一波编号：号是从日志推出来的，不另存一份计数器。"""
    _use_llm(ctx, _RecordingLLM())
    turn = await _turn(ctx, elder, "两波")
    first = await ctx.subagents.run_parallel(turn, [
        SubagentSpec(name="travel", instruction="查南京天气"),
        SubagentSpec(name="health", instruction="挂号")])
    second = await ctx.subagents.spawn(
        turn, SubagentSpec(name="travel", instruction="规划去医院的路线"))

    assert sorted(r.scope for r in first) == ["health#1", "travel#1"]
    assert second.scope == "travel#2"


# ------------------------------------------------------------------- 结构化回报


async def test_a_successful_tool_lands_under_its_report_key(ctx, elder):
    """成功的工具结果整段进 ``report_key``。字段来自工具，不来自模型措辞。"""
    report = await _scripted(ctx, elder, agent="community", calls=[
        ToolCallReq(id="c1", name="push_activities", arguments={})])

    assert report.ok is True and report.suspended is False
    assert report.tools_used == ["push_activities"]
    activities = report.data["activities"]["activities"]   # push_activities 的 report_key
    assert activities and activities[0]["title"]
    assert activities[0]["place"]


async def test_missing_is_a_hint_not_a_verdict(ctx, elder):
    """``report_schema`` 是"能给什么"，不是"每次必须给什么"。

    邻里帮承诺的字段是 ``("activities", "call_action", "walk_route", "recipe")``，
    但这次顺手让它查了个天气（get_weather 是公共工具）—— 它当然不产出那四样，
    那不叫失败。所以 ``missing`` 把四项都列上（"能报但没报"的提示），而 ``ok``
    为真；交付物那边不看这个标志，缺字段一律自己渲染成"待补"。
    """
    report = await _scripted(ctx, elder, agent="community", calls=[
        ToolCallReq(id="c1", name="get_weather",
                    arguments={"city": "南京", "date": "tomorrow"})])

    assert report.missing == ["activities", "call_action", "walk_route", "recipe"]
    assert report.ok is True


async def test_a_denied_tool_writes_nothing_into_the_report(ctx, elder):
    """被拦下的调用一个字都不留：宁可留白，绝不编造（红线 R5 的下游后果）。

    被拒这一次没有产出任何字段，所以 ``missing`` 把邻里帮承诺的四项全列上 ——
    这是"能报但没报"的提示，不是判决：``ok`` 才回答"这一支有没有办成事"。
    """
    report = await _scripted(ctx, elder, agent="community", calls=[
        ToolCallReq(id="c1", name="plain_say",
                    arguments={"text": "神药保健品根治骨关节炎，转账就送"})])

    assert report.tools_used == ["plain_say"], "被拒也算跑过一次，要留痕"
    assert report.data == {}
    assert report.ok is False
    assert report.missing == ["activities", "call_action", "walk_route", "recipe"]


async def test_a_finished_booking_reports_a_real_receipt(ctx, elder):
    """挂号当场办好 → 回报里存的是**真回执**，不是冻结的调用参数。

    就医改成"知会不审批"之后，这条线上不再有"挂起"那一格，诚实性的判据也反了过来：
    报告里的 ``appointment`` 必须带着只有真挂上号才有的字段（``registration_no`` /
    ``address`` / ``announce``）—— 缺一个就说明写进去的是模型的话，不是挂号结果。
    反过来，冻结参数那套的记号（``status="pending_confirm"``、``confirmation_id``）
    一个字都不许出现。
    """
    turn = await _turn(ctx, elder, "挂号")
    report = await ctx.subagents.spawn(turn, SubagentSpec(
        name="health", instruction="老人腿疼，想在南京就近看骨科，请查号源并挂上。"))

    assert report.agent == "health" and report.scope == "health#1"
    assert report.tools_used == ["search_hospital", "register_appointment"]
    assert report.suspended is False, "挂号不再挂起，当场办好"
    assert report.ok is True
    assert report.missing == []

    options = report.data["hospital_options"]
    assert options["department"] == "骨科"                    # 由症状推断而来
    assert options["hospitals"][0]["hospital"] == "南京鼓楼医院"

    appointment = report.data["appointment"]
    # 回执独有的字段必须出现 —— 它们只有 provider 真出了号才有
    for real in ("registration_no", "address", "announce"):
        assert appointment.get(real), f"{real} 是挂号成功才有的，缺了说明写进去的是编的"
    assert appointment["hospital"] == "南京鼓楼医院"
    assert appointment["doctor"] == "邱勇"
    assert appointment["fee"] == 70
    # 冻结参数那套的记号一个都不该在：出现了就说明存的是被拦下的调用，不是结果
    assert appointment.get("status") != "pending_confirm"
    assert "confirmation_id" not in appointment


async def test_concurrent_siblings_do_not_cross_contaminate(ctx, run_turn):
    """本地就医旗舰跑完：三份回报各管一段，谁的字段都没落到别人身上。

    收敛后的扇出是两波：第一波挂号(health) ‖ 天气(travel)，第二波路线(travel)。
    采集监听者按 ``call.agent_id`` 认领结果，所以出行助理的两支
    （天气那支、路线那支）互不相认 —— 一支有 weather 没 route，另一支反过来。
    """
    sid, _ = await run_turn("我腿疼，想在南京就近看看骨科专家号")
    by_scope = {r.scope: r for r in (
        AgentReport.from_dict(e.payload)
        for e in ctx.event_log.events(sid) if e.type == AGENT_REPORT)}

    assert sorted(by_scope) == ["health#1", "travel#1", "travel#2"]
    health, weather_leg, route_leg = (by_scope["health#1"], by_scope["travel#1"],
                                      by_scope["travel#2"])

    assert set(health.data) == {"hospital_options", "appointment"}
    assert set(weather_leg.data) == {"weather"}
    assert set(route_leg.data) == {"route"}

    # 出行助理承诺 ("route",)：天气那支没产出路线（缺），路线那支产出了；两支都办成事
    assert weather_leg.missing == ["route"] and weather_leg.ok is True
    assert route_leg.missing == [] and route_leg.ok is True
    assert health.missing == []
    assert _collectors(ctx) == []


# ------------------------------------------------------------------- 失败路径


async def test_an_unknown_agent_becomes_a_failed_report(ctx, elder):
    """派给不存在的子助理 → 一份失败回报，而不是把整轮炸掉。"""
    turn = await _turn(ctx, elder, "查无此人")
    report = await ctx.subagents.spawn(
        turn, SubagentSpec(name="八卦助理", instruction="随便聊聊"))

    assert report.ok is False
    assert report.error == "unknown_agent"
    assert "没有叫" in report.summary
    assert report.data == {}


async def test_a_child_blowing_up_does_not_take_its_siblings_down(ctx, elder):
    """一支异常 → 它自己变成失败回报，兄弟照常办成，监听者照常卸载。"""
    ctx.agents["broken"] = _BrokenAgent()
    turn = await _turn(ctx, elder, "一支炸了")
    broken, community = await ctx.subagents.run_parallel(turn, [
        SubagentSpec(name="broken", instruction="炸给我看"),
        SubagentSpec(name="community", instruction="帮我找找最近社区有什么活动")])

    assert broken.agent == "broken" and broken.ok is False
    assert "提示词模板坏了" in broken.error
    assert broken.data == {}

    assert community.ok is True
    activities = community.data["activities"]["activities"]
    assert activities and activities[0]["title"]

    # 异常路径也走 finally: dispose() —— 注册是可逆副作用，不是只在顺路时可逆
    assert _collectors(ctx) == []


# ============================================================ 右翼·心理与陪伴
#
# 这一组钉的是康乐右翼的三件交付物：一键拨号、散步环线、家常菜谱。
# 它们的共同点是**必须真的能从库里/数据里取到**，取不到就说没有 ——
# 编一个号码、编一条路、编一道菜，老人都分辨不出来，所以由测试来分辨。


async def _run_community(ctx, who, calls: list[ToolCallReq], *,
                         agent: str = "community") -> tuple[AgentReport, list]:
    """跑一个子智能体剧本，顺手把这一轮的 SSE 事件收回来。

    ``_scripted`` 只回 AgentReport —— 但"工具到底吐没吐卡"要看 ``card`` 事件：
    驱动器认的是工具结果里的 ``card`` 键（core/session.py 的 emit），前端认的是
    事件。回报里有、事件里没有，老人屏幕上就什么都不会出现。
    """
    _use_llm(ctx, MockLLMProvider(script=[
        LLMResponse(content="好的，我来办。", tool_calls=calls),
        LLMResponse(content="办完了。")]))
    turn = await _turn(ctx, who, "右翼剧本")
    report = await ctx.subagents.spawn(
        turn, SubagentSpec(name=agent, instruction="办件事"))
    return report, _drain(turn)


def _drain(turn) -> list:
    events = []
    while not turn.queue.empty():
        events.append(turn.queue.get_nowait())
    return events


def _events(events: list, name: str) -> list[dict]:
    return [e.data for e in events if e.event == name]


async def test_suggest_call_prefills_the_bound_child_number(ctx, elder, child):
    """拨号卡的号码来自 ``family_bindings`` → ``users.phone``，不是任何一处常量。

    证明方式不是"等于 13900000002"（那本身就是写死），而是**把库里的号改掉，
    卡跟着改**。硬编码的实现在这一步必然露馅。
    """
    report, events = await _run_community(ctx, elder, [
        ToolCallReq(id="c1", name="suggest_call",
                    arguments={"relation": "儿子",
                               "reason": "我心里闷得慌，一个人没意思"})])

    call = report.data["call_action"]["call"]
    assert call["phone"] == child["phone"]
    assert call["relation"] == "儿子" and call["name"] == child["name"]
    assert report.data["call_action"]["contacts"][0]["phone"] == child["phone"]

    cards = _events(events, "card")
    assert cards and cards[0]["type"] == "call", "卡没发出去，前端就画不出那个大按钮"
    assert cards[0]["phone"] == child["phone"]

    # 换掉孩子的号码：卡必须跟着换。写死的号在这一步会打给一个错的人。
    await ctx.repos.update("users", child["id"], {"phone": "13900001234"})
    report2, _ = await _run_community(ctx, elder, [
        ToolCallReq(id="c1", name="suggest_call", arguments={"relation": "儿子"})])
    assert report2.data["call_action"]["call"]["phone"] == "13900001234"
    assert report2.data["call_action"]["call"]["phone"] != elder["phone"], \
        "拨号卡不能拨给老人自己"


async def test_suggest_call_without_a_binding_offers_no_number(ctx):
    """没绑定家人 → 不给卡、不编号码，只请他报个号让系统记上。

    给一个点了没反应的按钮，比不给按钮更伤：老人会以为是自己按错了。
    """
    lonely = await ctx.repos.insert("users", {
        "role": "elder", "name": "周素英", "phone": "13700000003", "city": "南京"})
    report, events = await _run_community(ctx, lonely, [
        ToolCallReq(id="c1", name="suggest_call", arguments={})])

    assert report.ok is True
    assert report.data["call_action"]["contacts"] == []
    assert "call" not in report.data["call_action"]
    assert _events(events, "card") == [], "没有号码就不该有卡"


def test_walk_estimate_is_slow_paced():
    """时长只有一个出处，而且那个出处按慢走算、往上取整。

    ``1.8 / 3 * 60 = 36`` → 取整到 40：老人要的是"大概多久"，报 36 分钟反而
    逼着他去算；报少了会让人以为来得及。
    """
    est = walk_estimate(1.8, 2)
    assert (est["walking_min"], est["rest_min"], est["total_min"]) == (40, 10, 50)
    assert "慢走" in est["pace"], "口径要说出来，不然时长会被当成承诺"
    assert walk_estimate(3.6, 0)["total_min"] > walk_estimate(1.8, 0)["total_min"]
    assert walk_estimate(0, 0)["total_min"] == 0


async def test_suggest_walk_gives_a_ring_and_says_how_long(ctx, elder):
    """散步卡只说现成的环线；**没有这条线的城市就实话说没有**。

    最后那半句是这条链路里最要紧的：老人照着一条不存在的路走，比"我这儿没有"
    糟糕得多 —— 前者他会真出门。
    """
    report, events = await _run_community(ctx, elder, [
        ToolCallReq(id="c1", name="suggest_walk", arguments={"city": "南京"})])

    est = report.data["walk_route"]["estimate"]
    card = _events(events, "card")[0]
    assert card["type"] == "walk_card"
    assert est["total_min"] == est["walking_min"] + est["rest_min"] > 0
    assert f"{est['total_min']} 分钟" in card["body"]["用时"], "卡上的时长必须来自估算"
    assert card["body"]["在哪儿歇"] and card["body"]["怎么走"]
    assert "演示数据" in card["footnote"], "合成数据得自己说清楚"

    missing, events = await _run_community(ctx, elder, [
        ToolCallReq(id="c1", name="suggest_walk", arguments={"city": "杭州"})])
    assert missing.ok is False
    assert _events(events, "card") == []
    # report.summary 是模型自己收尾那句话，查不到线要说的话在**工具结果**里
    assert "没有" in _events(events, "tool_result")[0]["summary"]


def test_walk_loops_are_real_rings():
    """数据护栏：写出去的就必须是**环线**（走回出发点），不是一条越走越远的路。"""
    loops = load_fixture("activities")["walk_loops"]
    assert loops, "环线数据不能是空的"
    for loop in loops:
        pts = loop["points"]
        assert len(pts) >= 4, f"{loop['name']} 的点太少，画不出环"
        assert pts[0]["location"] == pts[-1]["location"], f"{loop['name']} 不是环线"
        assert (pts[0]["lng"], pts[0]["lat"]) == (pts[-1]["lng"], pts[-1]["lat"])
        assert loop["rest_stops"], f"{loop['name']} 没写歇脚的地方"
        assert 1 <= loop["distance_km"] <= 3, f"{loop['name']} 的距离不是老人腿脚的量级"
        assert loop["surface"] and loop["best_time"] and loop["steps"]
    assert "南京" in {x["city"] for x in loops}, "演示城市南京得有环线"


async def test_get_recipe_card_carries_steps_and_the_disclaimer(ctx, elder):
    """菜谱卡必须带步骤，且**两处**出口（summary / announce）都带免责声明。

    卡上的 ``note`` 是给眼睛看的，summary 是给模型转述的 —— 模型转述完要是没有
    声明，老人听到的就是一句没有边界的话（红线 R4）。

    分两步各验一件事：工具体给的是 summary/announce/card 三件套（announce 只走
    老人的耳朵，不进事件流），而卡能不能真到屏幕上要看 ``card`` 事件 ——
    那个事件是 AgentSession 从结果的 ``card`` 键发出去的，不走 dispatcher。
    """
    turn = await _turn(ctx, elder, "教做菜")
    raw = await get_recipe(turn, {})
    assert raw["ok"] is True
    assert raw["card"]["type"] == "recipe"
    assert raw["card"]["steps"], "没步骤的菜谱卡是张空卡"
    for key in ("summary", "announce"):
        assert "遵医嘱" in raw[key], f"{key} 少了免责声明"

    _, events = await _run_community(ctx, elder, [
        ToolCallReq(id="c1", name="get_recipe", arguments={})])
    cards = _events(events, "card")
    assert cards and cards[0]["type"] == "recipe"
    assert cards[0]["steps"] and cards[0]["note"]


def test_recipe_fixture_makes_no_medical_claim():
    """红线 R1/R2 的**数据层**把关。菜谱极容易滑进"降血压、软化血管"那类话术，

    靠自觉不如靠断言。这里就是把那份滑法钉死：疗效词、保健品、药，一个都不许出现。
    """
    raw = json.dumps(load_fixture("recipes"), ensure_ascii=False)
    for banned in ("治", "功效", "保健品", "药"):
        assert banned not in raw, f"菜谱里出现了「{banned}」——那是疗效话术，不是家常做法"
    assert not re.search(r"降(血压|血糖)", raw)

    recipes = load_fixture("recipes")["recipes"]
    assert len(recipes) >= 5
    for r in recipes:
        assert 3 <= len(r["steps"]) <= 6, f"{r['name']} 的步骤数不像上手就做的家常菜"
        for step in r["steps"]:
            assert len(step) <= 30, f"{r['name']} 有一步太长：{step}"
        assert len(r["ingredients"]) >= 3, f"{r['name']} 的食材列不全"
        assert {"少盐", "软烂"} & set(r["tags"]), f"{r['name']} 没标口感取向"
        assert r["minutes"] > 0 and r["suitable_for"]


def test_activities_look_like_a_community_notice():
    """活动得像一张**能照着出门**的社区公告：时间、地点、收不收费、怎么走，缺一不可。"""
    acts = load_fixture("activities")["activities"]
    assert len(acts) >= 5
    kinds = {"棋牌室", "养老院", "社区活动", "公园", "义诊"}
    for a in acts:
        assert a["title"] and a["date"] and a["place"]
        assert a["kind"] in kinds, f"{a['title']} 的类型不在白名单里：{a.get('kind')}"
        assert a["how_to"], f"{a['title']} 没写怎么走 —— 老人出不了这个门"
        assert a["free"] is True
    assert kinds & {a["kind"] for a in acts} >= {"棋牌室", "养老院", "公园"}, \
        "线下的去处要摊开，别只剩一种"


async def test_asking_for_activities_does_not_emit_a_second_card(ctx, elder):
    """``push_activities`` 不许自己吐卡：活动单由 plan_builder 出。

    工具再吐一张，老人屏幕上就是两张内容一样的活动卡 —— 而且顺序还不确定。
    所以断言必须落在**事件**上：只看结果的键，走的是 dispatcher，那条路上本来
    就发不出 card 事件，这条测试会永远绿。
    """
    turn = await _turn(ctx, elder, "找活动")
    assert "card" not in await push_activities(turn, {})

    report, events = await _run_community(ctx, elder, [
        ToolCallReq(id="c1", name="push_activities", arguments={})])
    assert _events(events, "card") == []
    activities = report.data["activities"]["activities"]
    assert activities and activities[0]["title"] and activities[0]["place"]
