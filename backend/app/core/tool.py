"""Tool / ToolRegistry / ToolDispatcher —— 工具注册表与执行流水线。

流水线顺序照抄 deepseek-harness 的 ``tool-execution-pipeline``：

```
tools/pre-execute(waterfall)      钩子 / 权限 / 沙箱
      ↓ allow
单调 guards(deny 或弃权)           拦截身份受保护，不可被重排
      ↓ allow
确认询问(fail-closed)              没有应答者 = 拒绝，不是放行
      ↓ allow
tools/execute(waterfall)          环绕派发：超时 / 重试 / 指标
      ↓
工具体 execute()
      ↓
tools/post-execute(waterfall)     接受 / 阻断 / 改写 / 追加上下文
      ↓
finalize                          最后一道 content-only 不变式
      ↓
tools/result(emit)                冻结的权威结果通知
```

批处理按 harness 规则：**有序 pre → 并发 execute → 有序 post**，
带 barrier 与有界滚动池。两个后果值得单独说：

1. 子智能体派发、查票查医院这类调用**真并发**，不再一个个等（旧实现是
   ``for tc in resp.tool_calls`` 严格串行）。
2. 高危调用被拦截时，**同批次其余调用照样结算**。旧实现在挂起处 ``break``
   然后 ``return SUSPENDED_REPLY``，剩下的 tool_calls 连结果都没有 ——
   模型下一轮看到的是一堆无主的调用声明，因果链直接烂掉。

``bypass_confirmation_id`` 仍是恢复执行的唯一凭证，且必须与冻结的 tool_args
完全一致（服务端比对，防篡改重放）——见 ARCHITECTURE.md ADR-1。
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from app.core.bus import (
    EventBus,
    TOOLS_EXECUTE,
    TOOLS_POST_EXECUTE,
    TOOLS_PRE_EXECUTE,
    TOOLS_RESULT,
)
from app.core.guard import Guard, GuardResult, GuardVerdict

logger = logging.getLogger(__name__)

CONCURRENT = "concurrent"   # 可与同批次其它调用并发
BARRIER = "barrier"         # 独占执行：等前面全部结算，自己跑完再放行后面

# 并发上限（有界滚动池）：演示规模够用，也避免把 Mock Provider 打满
DEFAULT_CONCURRENCY = 4

# to_model_content 的实体字段白名单：多轮对话要引用的事实（车次、医院、
# 医生、价格、时间、地点）。键名是工具结果的通用词表，不是某个工具的私有契约。
_ENTITY_KEYS = {
    "id", "name", "doctor", "hospital", "department", "time_slot",
    "train_no", "flight_no", "price", "departure_time", "arrival_time",
    "origin", "destination", "seat_type", "date", "time", "city",
    "hotel_name", "address", "phone", "status", "confirmation_id",
}
_ENTITY_LIST_CAP = 5    # 列表最多给模型看前几项：够引用，不撑上下文
_ENTITY_DEPTH_CAP = 3


def _slim_data(value: Any, depth: int = 0) -> Any:
    """从工具结果的 data 里挑实体字段（递归，只留标量），取不到返回 None。"""
    if depth > _ENTITY_DEPTH_CAP:
        return None
    if isinstance(value, dict):
        out: dict = {}
        for key, val in value.items():
            if key in _ENTITY_KEYS and isinstance(val, (str, int, float, bool)):
                out[key] = val
            elif isinstance(val, (dict, list)):
                sub = _slim_data(val, depth + 1)
                if sub:
                    out[key] = sub
        return out or None
    if isinstance(value, list):
        items = [x for x in (_slim_data(v, depth + 1)
                             for v in value[:_ENTITY_LIST_CAP]) if x]
        return items or None
    return None


@dataclass
class Tool:
    name: str
    description: str                       # 供 LLM function-calling 的工具说明
    parameters: dict                       # JSON Schema（function calling 格式）
    handler: Callable[..., Awaitable[dict]]
    # 生成子女端确认卡片的大白话摘要（仅高危工具有意义）
    child_summary: Callable[[dict], str] | None = None
    agent: str = "common"                  # 归属子智能体，供路由与免责声明判定
    # 高危/写操作设成 BARRIER：绝不允许两笔支付并发发出
    execution_mode: str = CONCURRENT
    timeout_s: float | None = None          # 覆盖全局单工具超时
    # 这个工具的结果在 AgentReport.data 里占哪个键。空 = 不进回报。
    # 交付物渲染器只认这些键（见 agents/plan_builder.py），所以键名就是契约：
    # search_hospital→hospital_options · register_appointment→appointment
    # search_train→train_options · book_ticket→ticket · book_hotel→hotel …
    report_key: str = ""


@dataclass
class ToolCall:
    """一次待执行的调用。id 就是 function-calling 的 tool_call_id。

    ``agent_id`` 是发起方的作用域。``tools/result`` 的观察者靠它区分
    "这是我这一支的结果"还是兄弟智能体的 —— 并发扇出时不串味。
    """

    id: str
    name: str
    args: dict = field(default_factory=dict)
    agent_id: str = "main"

    @classmethod
    def new(cls, name: str, args: dict | None = None, *,
            agent_id: str = "main") -> ToolCall:
        return cls(id=f"call_{uuid.uuid4().hex[:12]}", name=name,
                   args=args or {}, agent_id=agent_id)


@dataclass
class ToolOutcome:
    """结算后的权威结果（冻结）。"""

    call: ToolCall
    result: dict
    denied: bool = False
    suspended: bool = False
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.result.get("ok"))

    def to_model_content(self) -> str:
        """给模型看的 tool 消息内容：剥掉富负载，保留可推理的实体字段。

        旧实现把 ``data`` 整段剔掉 —— 于是查到的车次、医院、医生、价格
        模型自己一轮都看不见，多轮对话让它"刚才查到的是哪趟车"必然答不上。
        现在保留白名单内的实体字段（标量值），只剥 card 与富文本/二进制。
        """
        slim = {k: v for k, v in self.result.items() if k != "card"}
        entities = _slim_data(slim.pop("data", None))
        if entities:
            slim["data"] = entities
        return json.dumps(slim or self.result, ensure_ascii=False, default=str)


@dataclass
class PipelineContext:
    """一次调用在流水线里的可变状态（各阶段共享）。"""

    turn: Any
    tool: Tool
    call: ToolCall
    bypass_confirmation_id: str | None = None
    decision: str = "allow"                 # allow | deny | suspend
    guard: GuardResult | None = None
    result: dict | None = None
    timed_out: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def for_agent(self, agent: str | None = None) -> list[Tool]:
        if agent is None:
            return self.all()
        return [t for t in self._tools.values() if t.agent in (agent, "common")]

    def schemas(self, names: list[str]) -> list[dict]:
        out = []
        for n in names:
            t = self._tools.get(n)
            if t:
                out.append({
                    "type": "function",
                    "function": {"name": t.name, "description": t.description,
                                 "parameters": t.parameters},
                })
        return out


@runtime_checkable
class ConfirmationPort(Protocol):
    """core 对 safety/confirmation 的最小依赖（倒置依赖，避免循环导入）。"""

    async def suspend(self, turn: Any, tool: Tool, args: dict,
                      guard_result: GuardResult) -> dict: ...
    async def check_bypass(self, confirmation_id: str, tool_name: str,
                           args: dict) -> bool: ...


@runtime_checkable
class PostToolFilter(Protocol):
    """工具输出后置过滤器（如健康免责声明强制注入）。"""

    async def apply(self, turn: Any, tool: Tool, result: dict) -> dict: ...


class ToolDispatcher:
    def __init__(self, tools: ToolRegistry, guards: list[Guard],
                 confirmation: ConfirmationPort | None = None,
                 post_filters: list[PostToolFilter] | None = None,
                 bus: EventBus | None = None, *,
                 concurrency: int = DEFAULT_CONCURRENCY):
        self.tools = tools
        self.guards = guards
        self.confirmation = confirmation
        self.post_filters = post_filters or []
        self.bus = bus or EventBus()
        self.concurrency = concurrency

    # ------------------------------------------------------------ 单次（兼容入口）
    async def execute(self, turn: Any, tool_name: str, args: dict, *,
                      bypass_confirmation_id: str | None = None,
                      call_id: str | None = None) -> dict:
        call = ToolCall(id=call_id or f"call_{uuid.uuid4().hex[:12]}",
                        name=tool_name, args=args,
                        agent_id=getattr(turn, "agent_id", "main"))
        outcomes = await self.execute_batch(
            turn, [call], bypass_confirmation_id=bypass_confirmation_id)
        return outcomes[0].result

    # ------------------------------------------------------------ 批处理
    async def execute_batch(self, turn: Any, calls: list[ToolCall], *,
                            bypass_confirmation_id: str | None = None,
                            ) -> list[ToolOutcome]:
        """有序 pre → 并发 execute（barrier 分段）→ 有序 post。

        返回的 outcome 与入参 calls **一一对应且同序** —— 批次里每一个调用
        都会结算，一个不落。
        """
        contexts: list[PipelineContext | None] = []
        unknown: dict[int, ToolOutcome] = {}

        for index, call in enumerate(calls):
            tool = self.tools.get(call.name)
            if tool is None:
                unknown[index] = ToolOutcome(
                    call=call, denied=True,
                    result={"ok": False, "error": f"未知工具: {call.name}",
                            "summary": f"没有叫 {call.name} 的本事"})
                contexts.append(None)
                continue
            pctx = PipelineContext(
                turn=turn, tool=tool, call=call,
                bypass_confirmation_id=bypass_confirmation_id)
            await self._stage_pre(pctx)
            contexts.append(pctx)

        # ---- 并发执行：barrier 分段 + 有界滚动池 ----
        live = [c for c in contexts if c is not None]
        semaphore = asyncio.Semaphore(self.concurrency)

        async def run_one(pctx: PipelineContext) -> None:
            async with semaphore:
                await self._stage_execute(pctx)

        segment: list[PipelineContext] = []
        for pctx in live:
            if pctx.tool.execution_mode == BARRIER:
                if segment:
                    await asyncio.gather(*(run_one(p) for p in segment))
                    segment = []
                await self._stage_execute(pctx)        # 独占
            else:
                segment.append(pctx)
        if segment:
            await asyncio.gather(*(run_one(p) for p in segment))

        # ---- 有序 post（按模型给出的顺序结算）----
        outcomes: list[ToolOutcome] = []
        for index, pctx in enumerate(contexts):
            if pctx is None:
                outcomes.append(unknown[index])
                continue
            outcomes.append(await self._stage_post(pctx))
        return outcomes

    # ------------------------------------------------------------ 阶段 1：pre
    async def _stage_pre(self, pctx: PipelineContext) -> None:
        """tools/pre-execute 瀑布 → 单调 guards → 确认询问（fail-closed）。"""
        async def terminal(ctx: PipelineContext) -> PipelineContext:
            deny: GuardResult | None = None
            intercept: GuardResult | None = None
            for guard in self.guards:
                verdict = await guard.check(ctx.turn, ctx.call.name, ctx.call.args)
                if verdict.verdict is GuardVerdict.DENY:
                    deny = verdict
                    break                     # DENY 短路，身份受保护不可重排
                if verdict.verdict is GuardVerdict.INTERCEPT and intercept is None:
                    intercept = verdict       # 第一个 INTERCEPT 胜出

            if deny is not None:
                ctx.decision, ctx.guard = "deny", deny
                return ctx

            if intercept is None:
                ctx.decision = "allow"
                return ctx

            ctx.guard = intercept
            # fail-closed：没有应答者就是拒绝。旧实现这里会 AttributeError
            # 或（更糟）在配置缺失时把高危操作放过去。
            if self.confirmation is None:
                ctx.decision = "deny"
                ctx.guard = GuardResult(
                    GuardVerdict.DENY,
                    reason="需要家人确认，但确认服务没有就绪，已按最严处理。",
                    payload={"advice": "先给家里人打个电话，让他们帮您办。"})
                return ctx

            if ctx.bypass_confirmation_id is None:
                ctx.decision = "suspend"
                return ctx

            allowed = await self.confirmation.check_bypass(
                ctx.bypass_confirmation_id, ctx.call.name, ctx.call.args)
            if not allowed:
                ctx.decision = "deny"
                ctx.guard = GuardResult(
                    GuardVerdict.DENY,
                    reason="确认凭证无效或参数与审批时不一致，已拦截。")
                return ctx
            ctx.decision = "allow"
            return ctx

        await self.bus.waterfall(TOOLS_PRE_EXECUTE, pctx, terminal)

    # ------------------------------------------------------------ 阶段 2：execute
    async def _stage_execute(self, pctx: PipelineContext) -> None:
        """tools/execute 瀑布（超时/重试/指标环绕派发）→ 工具体。"""
        if pctx.decision == "deny":
            guard = pctx.guard
            pctx.result = {
                "ok": False, "denied": True,
                "summary": (guard.reason if guard else "")
                           or "该操作存在风险，已被安全管控拦截。",
                "advice": (guard.payload.get("advice") if guard else None)
                          or "建议您先和家人商量一下。",
            }
            return

        if pctx.decision == "suspend":
            # 挂起也是一种结算：这一格必须有结果，模型才看得懂后面的事
            pctx.result = await self.confirmation.suspend(
                pctx.turn, pctx.tool, pctx.call.args, pctx.guard)
            return

        async def terminal(ctx: PipelineContext) -> dict:
            return await _invoke(ctx.tool.handler, ctx.turn, ctx.call.args)

        try:
            pctx.result = await self.bus.waterfall(TOOLS_EXECUTE, pctx, terminal)
        except Exception as exc:  # noqa: BLE001 —— 工具异常归一成结果，不炸整轮
            logger.exception("工具 %s 执行异常", pctx.call.name)
            pctx.result = {"ok": False, "error": str(exc),
                           "summary": f"{pctx.call.name} 没办成，我稍后再试。"}

    # ------------------------------------------------------------ 阶段 3：post
    async def _stage_post(self, pctx: PipelineContext) -> ToolOutcome:
        """tools/post-execute 瀑布 → finalize → tools/result 冻结通知。"""
        async def terminal(ctx: PipelineContext) -> dict:
            result = ctx.result or {"ok": False, "summary": "没有结果"}
            for post_filter in self.post_filters:
                result = await post_filter.apply(ctx.turn, ctx.tool, result)
            return result

        try:
            result = await self.bus.waterfall(TOOLS_POST_EXECUTE, pctx, terminal)
        except Exception as exc:  # noqa: BLE001
            logger.exception("工具 %s 后置过滤异常", pctx.call.name)
            result = {"ok": False, "error": str(exc),
                      "summary": "结果处理出了点问题。"}

        result = _finalize(pctx.tool, result)
        outcome = ToolOutcome(
            call=pctx.call, result=result,
            denied=bool(result.get("denied")),
            suspended=bool(result.get("suspended")),
            timed_out=bool(result.get("timed_out")),
        )
        self.bus.emit(TOOLS_RESULT, outcome)     # 同步通知，观察冻结后的结果
        return outcome


async def _invoke(handler: Callable[..., Awaitable[dict]], turn: Any,
                  args: dict) -> dict:
    out = handler(turn, args)
    if inspect.isawaitable(out):
        out = await out
    return out if isinstance(out, dict) else {"ok": bool(out), "data": out}


def _finalize(tool: Tool, result: dict) -> dict:
    """最后一道 content-only 不变式：结果必须可序列化、字段齐、语义明确。"""
    if not isinstance(result, dict):
        result = {"ok": False, "summary": str(result)}
    result.setdefault("ok", True)
    summary = result.get("summary")
    if not isinstance(summary, str):
        result["summary"] = "" if summary is None else str(summary)
    result.setdefault("tool", tool.name)
    return result
