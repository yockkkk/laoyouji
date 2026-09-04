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
import time

from app.agents.base import BaseAgent
from app.core.bus import TOOLS_RESULT
from app.core.context import TurnContext
from app.core.events import AGENT_REPORT
from app.core.registry import ServiceProvider
from app.core.subagents import FORK, SPAWN, AgentReport, SubagentSpec
from app.providers.llm.base import LLMProvider, LLMResponse, ToolCallReq
from app.providers.llm.mock import MockLLMProvider


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
    """发现接缝：谁在场、各自承诺哪些字段 —— 装配可当场自证，不靠文档。"""
    found = {x["name"]: tuple(x["reports"]) for x in ctx.subagents.available()}
    assert found == {
        "travel": ("ticket", "hotel"),
        "health": ("appointment",),
        "community": ("service_order",),
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
    assert (alias.name, alias.instruction, alias.mode) == ("travel", "查车票", SPAWN)


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
    墙钟仍然留着，但只卡在串行下限（3 × 0.2 = 0.6 秒）上做个兜底。
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
    assert elapsed >= 0.2, "桩没被真正调用，这条断言就是空的"
    assert elapsed < 0.6, f"墙钟到了串行下限：{elapsed:.2f}s"
    assert _collectors(ctx) == [], "采集监听者跑完即卸载"


async def test_one_spec_still_yields_one_report(ctx, elder):
    """只派一支时不走 gather，行为也必须一样（少一个特例就少一处走样）。"""
    _use_llm(ctx, _RecordingLLM())
    turn = await _turn(ctx, elder, "单派")
    reports = await ctx.subagents.run_parallel(
        turn, [SubagentSpec(name="travel", instruction="查车票")])

    assert len(reports) == 1
    assert reports[0].scope == "travel#1"
    assert await ctx.subagents.run_parallel(turn, []) == []


# ------------------------------------------------------------------- 作用域隔离


async def test_spawn_child_sees_only_its_own_instruction(ctx, elder):
    """子作用域里只有派给它的那句话 —— 缺陷 #1 的正面验收。"""
    llm = _use_llm(ctx, _RecordingLLM())
    turn = await _turn(ctx, elder, "隔离")
    # 父作用域先落一句老人的原话。子智能体不该看见它。
    await turn.emit("user_msg", {"text": "我想去北京看腿疼的老毛病"})

    report = await ctx.subagents.spawn(
        turn, SubagentSpec(name="travel", instruction="查明天南京到北京的高铁"))

    assert report.scope == "travel#1"
    assert llm.calls == 1
    assert llm.seen[0][0]["role"] == "system", "第一条永远是自己的提示词"
    assert llm.user_texts(0) == ["查明天南京到北京的高铁"]
    assert "腿疼" not in "".join(llm.user_texts(0)), "父的原话不该漏进来"


async def test_fork_child_sees_the_parent_history_then_its_own(ctx, elder):
    """需要上文时才用 fork：作用域是 ``[父, 己]``，按 seq 织成一段连贯历史。"""
    llm = _use_llm(ctx, _RecordingLLM())
    turn = await _turn(ctx, elder, "承接")
    await turn.emit("user_msg", {"text": "我想去北京看腿疼的老毛病"})

    await ctx.subagents.fork(turn, SubagentSpec(
        name="travel", instruction="接着上面的事，订医院附近的酒店", mode=FORK))

    assert llm.user_texts(0) == ["我想去北京看腿疼的老毛病",
                                 "接着上面的事，订医院附近的酒店"]


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
        SubagentSpec(name="travel", instruction="查车票"),
        SubagentSpec(name="health", instruction="挂号")])
    second = await ctx.subagents.spawn(
        turn, SubagentSpec(name="travel", instruction="再订酒店"))

    assert sorted(r.scope for r in first) == ["health#1", "travel#1"]
    assert second.scope == "travel#2"


# ------------------------------------------------------------------- 结构化回报


async def test_a_successful_tool_lands_under_its_report_key(ctx, elder):
    """成功的工具结果整段进 ``report_key``。字段来自工具，不来自模型措辞。"""
    report = await _scripted(ctx, elder, agent="community", calls=[
        ToolCallReq(id="c1", name="canteen_order",
                    arguments={"menu_item": "软食套餐A", "count": 1,
                               "deliver_time": "11:30"})])

    assert report.ok is True and report.suspended is False
    assert report.tools_used == ["canteen_order"]
    order = report.data["canteen"]["order"]      # canteen_order 的 report_key
    assert order["service_type"] == "canteen"
    assert order["amount"] > 0


async def test_missing_is_a_hint_not_a_verdict(ctx, elder):
    """``report_schema`` 是"能给什么"，不是"每次必须给什么"。

    邻里帮承诺的字段是 ``service_order``，但这次派它去订饭 —— 它当然不产出
    派单，那不叫失败。所以 ``missing`` 非空而 ``ok`` 为真；交付物那边不看
    这个标志，缺字段一律自己渲染成"待补"。
    """
    report = await _scripted(ctx, elder, agent="community", calls=[
        ToolCallReq(id="c1", name="canteen_order",
                    arguments={"menu_item": "软食套餐A", "count": 1})])

    assert report.missing == ["service_order"]
    assert report.ok is True


async def test_a_denied_tool_writes_nothing_into_the_report(ctx, elder):
    """被拦下的调用一个字都不留：宁可留白，绝不编造（红线 R5 的下游后果）。"""
    report = await _scripted(ctx, elder, agent="community", calls=[
        ToolCallReq(id="c1", name="canteen_order",
                    arguments={"menu_item": "神药保健品根治套餐", "count": 1})])

    assert report.tools_used == ["canteen_order"], "被拒也算跑过一次，要留痕"
    assert report.data == {}
    assert report.ok is False
    assert report.missing == ["service_order"]


async def test_a_suspended_call_reports_frozen_args_not_a_finished_booking(
        ctx, elder):
    """挂起时存的是**冻结的调用参数**，不是"已挂号"的回执。

    这是诚实性的核心：演示里挂号一定会被拦下，此时并不存在一个已挂上的号。
    旧实现让模型照着自己的话编一份"挂号成功"，纸上就出现了不存在的事实。
    """
    turn = await _turn(ctx, elder, "挂号")
    report = await ctx.subagents.spawn(turn, SubagentSpec(
        name="health", instruction="老人腿疼，想去北京看骨科，请查号源并挂上。"))

    assert report.agent == "health" and report.scope == "health#1"
    assert report.tools_used == ["search_hospital", "register_appointment"]
    assert report.suspended is True
    assert report.ok is True, "「已挂起待确认」是有效进展，不是失败"
    assert report.missing == []

    options = report.data["hospital_options"]
    assert options["department"] == "骨科"                    # 由症状推断而来
    assert options["hospitals"][0]["hospital"] == "北京积水潭医院"

    appointment = report.data["appointment"]
    assert appointment["status"] == "pending_confirm"
    assert appointment["confirmation_id"]
    assert appointment["hospital"] == "北京积水潭医院"
    assert appointment["doctor"] == "田伟"
    assert appointment["fee"] == 100
    # 回执独有的字段一个都不许出现 —— 出现了就说明写进去的不是冻结参数
    for forged in ("registration_no", "address", "announce", "title"):
        assert forged not in appointment, f"{forged} 是挂号成功才有的，不该在这儿"


async def test_concurrent_siblings_do_not_cross_contaminate(ctx, run_turn):
    """旗舰场景跑完：三份回报各管一段，谁的字段都没落到别人身上。

    采集监听者按 ``call.agent_id`` 认领结果，所以出行助理的两次派活
    （车票那支、酒店那支）互不相认 —— 一支有 ticket 没 hotel，另一支反过来。
    """
    sid, _ = await run_turn("我想去北京看腿疼的老毛病")
    by_scope = {r.scope: r for r in (
        AgentReport.from_dict(e.payload)
        for e in ctx.event_log.events(sid) if e.type == AGENT_REPORT)}

    assert sorted(by_scope) == ["health#1", "travel#1", "travel#2"]
    health, ticket_leg, hotel_leg = (by_scope["health#1"], by_scope["travel#1"],
                                     by_scope["travel#2"])

    assert set(health.data) == {"hospital_options", "appointment"}
    assert set(ticket_leg.data) == {"train_options", "ticket"}
    assert set(hotel_leg.data) == {"hotel_options", "hotel", "weather"}

    # 出行助理承诺 ("ticket", "hotel")：两支各缺对方那一半，但两支都办成了事
    assert ticket_leg.missing == ["hotel"] and ticket_leg.ok is True
    assert hotel_leg.missing == ["ticket"] and hotel_leg.ok is True
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
        SubagentSpec(name="community", instruction="帮我订一份中午的软食套餐")])

    assert broken.agent == "broken" and broken.ok is False
    assert "提示词模板坏了" in broken.error
    assert broken.data == {}

    assert community.ok is True
    assert community.data["canteen"]["order"]["service_type"] == "canteen"

    # 异常路径也走 finally: dispose() —— 注册是可逆副作用，不是只在顺路时可逆
    assert _collectors(ctx) == []
