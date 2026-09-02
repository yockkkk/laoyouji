"""三级预算与单工具超时 —— "跑不飞、卡不死"的验收。

这是缺陷 #8 的门禁。旧实现的唯一止损是 ``MAX_STEPS = 8``：没有 token 上限、
没有墙钟、没有单工具 deadline。后果很具体 —— 上游 LLM 一挂住，SSE 连接跟着悬着，
老人端界面永远转圈，而后台没有任何一条日志说得清"停在哪一步、为什么停"。

所以这里断言的是**三件事各自可指认**：

- **限额自己报名**：耗尽的是步数、token 还是墙钟，``stop_reason`` 里写得明明白白
  （``budget/steps(2/2)``），日志能对账。
- **单工具有 deadline**：卡住的工具按超时结算，**同批次其余调用照样跑完** ——
  超时是一格的事，不是整轮的事。
- **说给老人的话里没有黑话**：预算耗尽和模型失败都各有一句人话，
  "token""超时""预算"一个字都不许出现在老人看到的文本里。

驱动器只按 ``getattr`` 取智能体的形状，所以这里的 ``_StubAgent`` 不继承任何基类
—— 依赖的是形状，不是继承树。
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from app.core.bus import REQUEST_ERROR
from app.core.context import TurnContext
from app.core.events import STEP_END, TURN_END
from app.core.guards import make_timeout_policy
from app.core.registry import ServiceProvider
from app.core.session import (
    AgentDriver,
    BUDGET_REPLY,
    Budget,
    LLM_FAILED_REPLY,
    _budget_for,
    _tokens_of,
)
from app.core.subagents import SubagentSpec, _child_budget
from app.core.tool import Tool, ToolCall
from app.providers.llm.base import LLMProvider, LLMResponse, ToolCallReq


# ---------------------------------------------------------------------- 桩与工具


class _StubAgent:
    """只有形状、没有身世的智能体。驱动器要的就这几样。"""

    name = "stub"
    display_name = "试桩助理"
    description = "只为验收预算而存在"
    system_prompt = "你是测试桩，照吩咐办事。"
    tool_names: list[str] = []
    max_steps = 8
    report_schema: tuple[str, ...] = ()


class _LoopingLLM(LLMProvider):
    """永远再调一次工具的模型：它自己不会收尾，只有预算能让轮次停下。

    这正是没有预算时的最坏情形 —— 旧实现下它会一直跑到步数用光，
    而如果步数给得大一点（或者模型改成慢回话），SSE 就一起悬着。
    """

    name = "looping"

    def __init__(self, *, tool: str = "probe", delay: float = 0.0,
                 usage: dict | None = None):
        self.tool = tool
        self.delay = delay
        self.usage = usage or {}
        self.calls = 0

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   on_delta=None) -> LLMResponse:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return LLMResponse(
            content=f"我再查一遍（第{self.calls}次）。",
            tool_calls=[ToolCallReq(id=f"call_{self.calls}", name=self.tool,
                                    arguments={"i": self.calls})],
            usage=dict(self.usage))


class _AngryLLM(LLMProvider):
    """每次都抛的模型：模拟上游 502 / 网络断开。"""

    name = "angry"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   on_delta=None) -> LLMResponse:
        self.calls += 1
        raise RuntimeError("上游 502")


def _use_llm(ctx, llm):
    """覆盖注册即失效旧实例 —— 换 provider 就这一行（同 test_subagents.py）。"""
    ctx.registry.register(ServiceProvider("llm", lambda _ctx: llm))
    return llm


async def _turn(ctx, elder, title: str) -> TurnContext:
    session = await ctx.event_log.create_session(elder["id"], title)
    return TurnContext(ctx=ctx, session_id=session["id"], user=elder)


def _probe(ctx, name: str, *, delay: float = 0.0,
           timeout_s: float | None = None) -> list[dict]:
    """注册一个测试桩工具，返回"它被调用时收到的参数"这个账本。"""
    seen: list[dict] = []

    async def handler(turn, args: dict) -> dict:
        seen.append(dict(args))
        if delay:
            await asyncio.sleep(delay)
        return {"ok": True, "summary": f"{name} 跑完了", "data": {"i": len(seen)}}

    ctx.tools.register(Tool(
        name=name, description=f"{name}。测试桩工具",
        parameters={"type": "object", "properties": {}},
        handler=handler, timeout_s=timeout_s))
    return seen


async def _drive(ctx, elder, llm, budget: Budget, *, title: str = "预算"):
    """按给定预算跑一轮，返回 ``(TurnContext, AgentTurn)``。"""
    _use_llm(ctx, llm)
    turn = await _turn(ctx, elder, title)
    return turn, await AgentDriver(_StubAgent(), turn, budget=budget).run("办件事")


def _turn_end(ctx, session_id: str) -> dict:
    return [e.payload for e in ctx.event_log.events(session_id)
            if e.type == TURN_END][-1]


# ------------------------------------------------------------------ 限额自己报名


def test_a_fresh_budget_is_not_exhausted():
    assert Budget().exhausted() is None
    assert Budget().elapsed_s == 0.0


def test_each_limit_names_itself_when_it_runs_out():
    """三个理由三种形状，且都带"用了多少/上限多少" —— 日志里能直接对账。"""
    steps = Budget(max_steps=3)
    steps.charge(steps=3)
    assert steps.exhausted() == "budget/steps(3/3)"

    tokens = Budget(max_steps=99, max_tokens=500)
    tokens.charge(tokens=500)
    assert tokens.exhausted() == "budget/tokens(500/500)"

    clock = Budget(max_steps=99, max_tokens=10 ** 9, wall_clock_s=0.0)
    clock.start()
    assert clock.exhausted().startswith("budget/wall_clock(")
    assert clock.exhausted().endswith("s/0.0s)")


def test_the_wall_clock_only_runs_after_start():
    """没 start 过的预算不凭空判超时 —— 否则"构造即耗尽"，轮次一步都跑不了。"""
    idle = Budget(wall_clock_s=0.0)
    assert idle.exhausted() is None
    idle.start()
    assert idle.exhausted() is not None


def test_steps_are_reported_before_tokens_before_the_clock():
    """三项同时见底时报最靠前的那一项：理由稳定，才谈得上对账。"""
    all_out = Budget(max_steps=1, max_tokens=1, wall_clock_s=0.0)
    all_out.start()
    all_out.charge(steps=1, tokens=1)
    assert all_out.exhausted() == "budget/steps(1/1)"


def test_snapshot_is_the_shape_the_turn_end_event_carries():
    budget = Budget()
    budget.start()
    budget.charge(steps=2, tokens=321)

    snap = budget.snapshot()
    assert set(snap) == {"steps_used", "tokens_used", "elapsed_s"}
    assert (snap["steps_used"], snap["tokens_used"]) == (2, 321)
    assert snap["elapsed_s"] == round(snap["elapsed_s"], 2)


# -------------------------------------------------------------------- token 计量


def test_tokens_come_from_the_provider_when_it_reports_them():
    """DeepSeek 会报 usage，报了就用它 —— 估算只是退路。"""
    reported = LLMResponse(content="好", usage={"total_tokens": 1234})
    assert _tokens_of([{"role": "user", "content": "查明天去北京的高铁"}],
                      reported) == 1234


def test_tokens_are_estimated_when_the_provider_is_silent():
    """Mock 不报用量 → 按字符粗估，且下限是 1：守卫宁可估多不可估少。

    估成 0 的后果不是"少算一点"，而是**这一步白跑**：预算永远不见底，
    跑飞的循环就没人拦得住。
    """
    messages = [{"role": "system", "content": "一二三四"},
                {"role": "user", "content": "五六"}]
    assert _tokens_of(messages, LLMResponse(content="七八")) == 4     # 8 // 2
    assert _tokens_of([], None) == 1
    assert _tokens_of([{"role": "user", "content": None}], None) == 1


# ------------------------------------------------------------------ 三级耗尽（整轮）


async def test_the_step_budget_stops_a_model_that_never_stops(ctx, elder):
    """模型每步都再调一次工具 → 步数一到就收尾，理由与账目都落进 turn/end。"""
    seen = _probe(ctx, "probe")
    llm = _LoopingLLM()
    turn, agent_turn = await _drive(ctx, elder, llm, Budget(max_steps=2))

    assert agent_turn.stop_reason == "budget/steps(2/2)"
    assert agent_turn.final_text == BUDGET_REPLY
    assert len(agent_turn.steps) == 2 and llm.calls == 2
    assert len(seen) == 2, "两步各调一次工具，都真跑了"

    ended = _turn_end(ctx, turn.session_id)
    assert ended["stop_reason"] == "budget/steps(2/2)"
    assert set(ended["budget"]) == {"steps_used", "tokens_used", "elapsed_s"}
    assert ended["budget"]["steps_used"] == 2


async def test_the_token_budget_stops_a_turn_that_still_has_steps_left(ctx, elder):
    """步数还剩八成，token 先见底 → 报的是 token，不是步数。"""
    _probe(ctx, "probe")
    budget = Budget(max_steps=9, max_tokens=400)
    _, agent_turn = await _drive(
        ctx, elder, _LoopingLLM(usage={"total_tokens": 500}), budget)

    assert agent_turn.stop_reason == "budget/tokens(500/400)"
    assert agent_turn.final_text == BUDGET_REPLY
    assert budget.steps_used == 1 < budget.max_steps, "不是步数拦下的"


async def test_the_wall_clock_stops_a_turn_that_is_merely_slow(ctx, elder):
    """既没超步数也没超 token，就是慢 —— 墙钟照样能收尾。

    这是旧实现最要命的缺口：模型慢到什么程度都没人管，SSE 一直悬着，
    老人端界面转圈转到自己放弃。
    """
    _probe(ctx, "probe")
    budget = Budget(max_steps=9, max_tokens=10 ** 7, wall_clock_s=0.15)
    started = time.perf_counter()
    _, agent_turn = await _drive(ctx, elder, _LoopingLLM(delay=0.1), budget)
    elapsed = time.perf_counter() - started

    assert agent_turn.stop_reason.startswith("budget/wall_clock(")
    assert agent_turn.final_text == BUDGET_REPLY
    assert 0 < budget.steps_used < budget.max_steps, "不是步数拦下的"
    assert budget.tokens_used < budget.max_tokens, "也不是 token 拦下的"
    assert elapsed < 2.0, f"墙钟没起作用，跑了 {elapsed:.2f}s"


async def test_a_runaway_child_is_stopped_by_its_own_budget(ctx, elder):
    """子智能体跑飞时被自己的预算截住，父照常拿到一份可用的回报。

    "一支跑飞不该拖垮整轮"落到实处：父不需要知道子为什么停，
    它只需要拿到 ``AgentReport``，缺什么写"待补"。
    """
    seen = _probe(ctx, "probe")
    _use_llm(ctx, _LoopingLLM())
    turn = await _turn(ctx, elder, "跑飞")

    report = await ctx.subagents.spawn(
        turn, SubagentSpec(name="community", instruction="一直查下去"))

    steps = ctx.agents["community"].max_steps
    assert len(seen) == steps, "每步调一次，正好被步数预算截住"
    assert report.tools_used == ["probe"] * steps
    assert report.summary == BUDGET_REPLY, "模型没交代，就用那句人话交代"
    assert report.ok is True, "桩工具确实办成了事，预算耗尽不等于失败"
    # 无 report_key 的工具走兜底归档（按工具名），同名只留第一次
    assert report.data == {"probe": {"i": 1}}
    assert report.missing == ["service_order"]


# ------------------------------------------------------------------ 单工具超时


async def test_a_hung_tool_settles_as_timed_out_instead_of_hanging(ctx, elder):
    """卡住的工具按超时**结算**，而不是让协程悬着。这一格必须有结果。"""
    _probe(ctx, "hang_probe", delay=5.0, timeout_s=0.05)
    turn = await _turn(ctx, elder, "超时")

    started = time.perf_counter()
    outcomes = await ctx.dispatcher.execute_batch(
        turn, [ToolCall.new("hang_probe")])
    elapsed = time.perf_counter() - started

    outcome = outcomes[0]
    assert outcome.timed_out is True
    assert outcome.ok is False
    assert outcome.result["tool"] == "hang_probe"      # _finalize 盖的章
    assert elapsed < 1.0, f"等的是工具自己的 5 秒，超时策略没生效（{elapsed:.2f}s）"


async def test_a_hung_tool_does_not_take_its_batch_down(ctx, elder):
    """同批次里一个卡住、一个正常 → 两个都结算，正常那个照样办成。

    墙钟顺带钉住批处理那半个承诺：**并发 execute**。两个各要 0.4 秒，串行下限
    0.8 秒，并发约 0.4 秒 —— 这是全套测试里唯一一处对"工具批次真并发"的计时验收
    （子智能体扇出那一处在 test_subagents.py）。
    """
    _probe(ctx, "hang_two", delay=5.0, timeout_s=0.4)
    fast = _probe(ctx, "fast_two", delay=0.4)
    turn = await _turn(ctx, elder, "同批")

    started = time.perf_counter()
    outcomes = await ctx.dispatcher.execute_batch(
        turn, [ToolCall.new("hang_two"), ToolCall.new("fast_two")])
    elapsed = time.perf_counter() - started

    assert [o.call.name for o in outcomes] == ["hang_two", "fast_two"]
    assert outcomes[0].timed_out is True
    assert outcomes[1].ok is True
    assert fast == [{}], "快的那个真跑了"
    assert elapsed >= 0.4, "桩根本没被等，这条计时断言就是空的"
    assert elapsed < 0.65, f"批处理退化成串行了：{elapsed:.2f}s（串行下限 0.8s）"


async def test_the_timeout_message_says_it_in_plain_words():
    """没声明 ``timeout_s`` 的工具走全局默认；那句话是给老人看的，不是给日志看的。"""
    policy = make_timeout_policy(1.0)
    pctx = SimpleNamespace(tool=SimpleNamespace(timeout_s=None),
                           call=SimpleNamespace(name="查号源", args={}))

    async def hang():
        await asyncio.sleep(30)

    assert await policy(pctx, hang) == {
        "ok": False, "timed_out": True,
        "summary": "查号源 等了 1 秒还没回话，这次先不等了，稍后我再试。"}


# ------------------------------------------------------------------ 模型失败


async def test_a_model_failure_ends_the_turn_with_a_human_sentence(ctx, elder):
    """上游挂了 → 一步就收尾，理由是 ``llm/failed``，老人听到的是一句人话。"""
    llm = _AngryLLM()
    turn, agent_turn = await _drive(ctx, elder, llm, Budget(max_steps=5))

    assert agent_turn.stop_reason == "llm/failed"
    assert agent_turn.final_text == LLM_FAILED_REPLY
    assert llm.calls == 1, "没人处理这个错就别硬撑着重试"
    assert len(agent_turn.steps) == 1

    step_ends = [e.payload for e in ctx.event_log.events(turn.session_id)
                 if e.type == STEP_END]
    assert step_ends == [{"index": 0, "error": "llm_failed"}]


async def test_a_request_error_listener_can_rescue_the_turn(ctx, elder):
    """重试/降级策略挂 ``agent/request-error`` 钩子即可，驱动器一个字不用改。

    这条同时是"注册是可逆副作用"的复验：摘掉监听者后，同样的模型又变回失败。
    """
    rescued = LLMResponse(content="这边先给您记下了，我一会儿再试。")
    tried: list[str] = []

    async def fallback(payload: dict, next_) -> LLMResponse:
        tried.append(str(payload["error"]))
        return rescued                       # 不调 next_ 即短路，返回值就是裁决

    dispose = ctx.bus.on(REQUEST_ERROR, fallback, label="test-fallback")
    try:
        _, agent_turn = await _drive(ctx, elder, _AngryLLM(), Budget(max_steps=5))
    finally:
        dispose()

    assert tried == ["上游 502"]
    assert agent_turn.stop_reason == "model/idle", "救回来了就正常收尾"
    assert agent_turn.final_text == rescued.content
    assert "test-fallback" not in ctx.bus.listeners(REQUEST_ERROR)

    # 摘掉之后同一个模型又变回失败 —— 行为确实来自那个监听者
    _, again = await _drive(ctx, elder, _AngryLLM(), Budget(max_steps=5),
                            title="摘掉之后")
    assert again.stop_reason == "llm/failed"


# ------------------------------------------------------------------ 子预算与措辞


async def test_a_child_gets_a_tighter_budget_than_its_parent(ctx, elder):
    """子智能体的 token 与墙钟各按 0.6 折算；步数沿用它自己声明的上限。

    收紧的是"能烧多少"和"能拖多久"，不是"能想几步" —— 一支子智能体本来就只
    负责一件事，把它的步数再砍一刀只会让它半途而废。
    """
    turn = await _turn(ctx, elder, "子预算")
    agent = ctx.agents["travel"]
    parent, child = _budget_for(agent, turn), _child_budget(agent, turn)

    assert parent.max_tokens == ctx.settings.budget_max_tokens
    assert parent.wall_clock_s == ctx.settings.budget_wall_clock_s
    assert child.max_tokens == int(parent.max_tokens * 0.6) < parent.max_tokens
    assert child.wall_clock_s == parent.wall_clock_s * 0.6 < parent.wall_clock_s
    assert child.max_steps == parent.max_steps == agent.max_steps
    assert child.tool_timeout_s == parent.tool_timeout_s == ctx.settings.tool_timeout_s


def test_the_words_the_elder_hears_carry_no_jargon():
    """预算耗尽和模型失败都得说人话 —— 一个英文字母都不该出现在老人眼前。"""
    for reply in (BUDGET_REPLY, LLM_FAILED_REPLY):
        assert len(reply) > 10
        assert not any(c.isascii() and c.isalpha() for c in reply), reply
        for jargon in ("超时", "预算", "步数", "失败", "错误", "上限"):
            assert jargon not in reply, f"{jargon} 是黑话：{reply}"
