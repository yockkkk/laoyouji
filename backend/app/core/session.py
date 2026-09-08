"""Turn / Step 分层与 AgentDriver —— 智能体循环的骨架。

harness 的定义原样搬过来：

> 一个 **step** = 一次模型请求 + 它调用的工具；一个 **turn** = 零个或多个 step。

旧实现是一个扁平的 ``for _step in range(agent.max_steps)``：没有 turn 概念、
没有预算、没有可挂钩的检查点，唯一的止损是步数。本文件把这三件补上：

- **分层**：``AgentTurn`` 持有 ``AgentStep`` 列表，两级都有 id 并落进事件日志的
  ``turn_id`` / ``step_id`` 字段 —— 事后能精确回放"第几步干了什么"。
- **三级预算** ``Budget``：步数 / token / 墙钟，外加单工具 deadline
  （单工具超时由 ``core/guards.timeout_policy`` 环绕 ``tools/execute`` 落实）。
  以前 LLM 卡住会把 SSE 一起拖死，现在墙钟一到就带着明确理由收尾。
- **可挂钩**：``agent/pre-step``（压缩/注入）、``agent/request``（重试/指标）、
  ``agent/request-error``（失败决策）、``agent/turn-stopping``（终止检查点）。
  新行为挂钩子，不改这个循环。

历史来源只有一个：``event_log.derive_messages(scopes=…)``。驱动器不自己攒
``messages`` 列表跨步传递 —— 每一步都从事件日志重新派生。这是
"model-visible means logged" 的字面落实，也是子智能体作用域隔离能成立的原因。
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.bus import (
    EventBus,
    PRE_STEP,
    REQUEST,
    REQUEST_ERROR,
    SESSION_FLUSH,
    TURN_STOPPING,
)
from app.core.events import (
    ASSISTANT_MESSAGE,
    MAIN_SCOPE,
    STEP_END,
    STEP_START,
    TURN_END,
    TURN_START,
    USER_MESSAGE,
)
from app.core.tool import ToolCall
from app.providers.llm.base import LLMResponse

logger = logging.getLogger(__name__)

# 给老人的兜底话术都放这儿（不说"超时""token""模型"这类黑话）。
#
# 两条硬规矩，都是踩过的坑：
# ① 不许说"我再想想 / 请稍等"—— 模型失败这一步是直接 return 收尾的，
#    REQUEST_ERROR 瀑布上并没有挂重试中间件。说了"稍等"，老人就真的坐在那儿
#    等一句永远不会来的话。
# ② 不许说"没听清，您再说一遍"—— 一是把锅推给老人的口音，他会越说越大声；
#    二是接口真挂了的时候，他重说一遍还是挂，变成一个说不完的死循环。
#    所以要么明说是"我这边"的问题，要么给一个带间隔的动作（歇一会儿再说）。
BUDGET_REPLY = "这事儿有点多，我先办到这儿。剩下的我记着，稍后再跟您说进展。"
LLM_FAILED_REPLY = (
    "我这边一时连不上，刚才那句没能帮您办 —— 不是您没说清楚，是我的问题。"
    "您歇口气，过一小会儿再跟我说一次。"
)
# 智能体整轮抛异常（不只是模型失败）时，SSE 走 error 事件用这句
TURN_FAILED_REPLY = (
    "我这儿出了点岔子，这件事没办成，先跟您说一声。"
    "您稍等一会儿再说一次；要是着急，就先给家人打个电话。"
)


@dataclass
class Budget:
    """三级预算 + 单工具 deadline。任何一项耗尽都以明确理由收尾。"""

    max_steps: int = 8
    max_tokens: int = 60_000
    wall_clock_s: float = 90.0
    tool_timeout_s: float = 20.0

    steps_used: int = 0
    tokens_used: int = 0
    started_at: float = 0.0

    def start(self) -> None:
        self.started_at = time.monotonic()

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at if self.started_at else 0.0

    def charge(self, *, steps: int = 0, tokens: int = 0) -> None:
        self.steps_used += steps
        self.tokens_used += tokens

    def exhausted(self) -> str | None:
        """返回耗尽理由（用于 stop_reason 与日志），未耗尽返回 None。"""
        if self.steps_used >= self.max_steps:
            return f"budget/steps({self.steps_used}/{self.max_steps})"
        if self.tokens_used >= self.max_tokens:
            return f"budget/tokens({self.tokens_used}/{self.max_tokens})"
        if self.started_at and self.elapsed_s >= self.wall_clock_s:
            return f"budget/wall_clock({self.elapsed_s:.1f}s/{self.wall_clock_s}s)"
        return None

    def snapshot(self) -> dict:
        return {"steps_used": self.steps_used, "tokens_used": self.tokens_used,
                "elapsed_s": round(self.elapsed_s, 2)}


@dataclass
class AgentStep:
    """一次模型请求及其工具调用。"""

    id: str
    index: int
    turn_id: str
    agent_id: str
    messages: list[dict] = field(default_factory=list)
    response: LLMResponse | None = None
    tool_names: list[str] = field(default_factory=list)


@dataclass
class AgentTurn:
    """一个智能体的一轮任务。"""

    id: str
    session_id: str
    agent_id: str
    agent_name: str
    instruction: str | None
    budget: Budget
    steps: list[AgentStep] = field(default_factory=list)
    stop_reason: str = ""
    final_text: str = ""
    suspended: bool = False

    @property
    def tool_names(self) -> list[str]:
        return [n for s in self.steps for n in s.tool_names]


@dataclass
class StepRequest:
    """``agent/pre-step`` 与 ``agent/request`` 两个瀑布的可变载荷。

    压缩中间件改 ``messages``、重试中间件环绕 ``next()`` —— 都不用碰驱动器。
    """

    turn: Any                       # TurnContext（环境）
    agent: Any                      # BaseAgent
    step: AgentStep
    agent_turn: AgentTurn
    messages: list[dict] = field(default_factory=list)
    tools: list[dict] | None = None


class AgentDriver:
    """驱动一个智能体跑完一轮。事件日志是唯一状态，驱动器本身无状态残留。"""

    def __init__(self, agent: Any, turn: Any, *, agent_id: str = MAIN_SCOPE,
                 scopes: list[str] | None = None, budget: Budget | None = None,
                 flush_on_end: bool = True):
        self.agent = agent
        self.turn = turn                       # 已按 agent_id 作用域化的 TurnContext
        self.agent_id = agent_id
        self.scopes = scopes or [agent_id]
        self.budget = budget or _budget_for(agent, turn)
        self.flush_on_end = flush_on_end

    # ------------------------------------------------------------------ 便捷
    @property
    def ctx(self) -> Any:
        return self.turn.ctx

    @property
    def bus(self) -> EventBus:
        return self.ctx.bus

    @property
    def log(self) -> Any:
        return self.ctx.event_log

    def _append(self, type: str, payload: dict, *,
                step_id: str | None = None) -> None:
        self.log.append(self.turn.session_id, self.turn.user.get("id"),
                        type, payload, agent_id=self.agent_id,
                        turn_id=self.turn.turn_id, step_id=step_id)

    # ------------------------------------------------------------------ 主流程
    async def run(self, instruction: str | None = None) -> AgentTurn:
        turn_id = f"turn_{uuid.uuid4().hex[:12]}"
        self.turn.turn_id = turn_id
        self.budget.start()

        agent_turn = AgentTurn(
            id=turn_id, session_id=self.turn.session_id, agent_id=self.agent_id,
            agent_name=getattr(self.agent, "name", "agent"),
            instruction=instruction, budget=self.budget)

        self._append(TURN_START, {"agent": agent_turn.agent_name,
                                  "instruction": instruction or ""})
        if instruction:
            # 子智能体的指令写进**它自己的作用域**：它因此看不到老人的原话，
            # 也看不到兄弟智能体的往来 —— 这是作用域隔离的落点。
            self._append(USER_MESSAGE, {"text": instruction})

        try:
            await self._loop(agent_turn)
        finally:
            self.turn.step_id = None
            self._append(TURN_END, {
                "agent": agent_turn.agent_name,
                "stop_reason": agent_turn.stop_reason,
                "budget": self.budget.snapshot(),
            })
            if self.flush_on_end:
                # session/flush：写后落库的唯一 await 点（parallel 检查点）
                await self.bus.parallel(SESSION_FLUSH,
                                        {"session_id": self.turn.session_id,
                                         "ctx": self.ctx})
        return agent_turn

    async def _loop(self, agent_turn: AgentTurn) -> None:
        while True:
            reason = self.budget.exhausted()
            if reason:
                agent_turn.stop_reason = reason
                agent_turn.final_text = agent_turn.final_text or BUDGET_REPLY
                logger.info("轮次收尾: %s (%s)", reason, self.agent_id)
                return

            step = AgentStep(id=f"step_{uuid.uuid4().hex[:8]}",
                             index=len(agent_turn.steps),
                             turn_id=agent_turn.id, agent_id=self.agent_id)
            agent_turn.steps.append(step)
            self.turn.step_id = step.id
            self._append(STEP_START, {"index": step.index}, step_id=step.id)

            response = await self._request(step, agent_turn)
            self.budget.charge(steps=1, tokens=_tokens_of(step.messages, response))

            if response is None:                     # 模型彻底失败
                agent_turn.stop_reason = "llm/failed"
                agent_turn.final_text = LLM_FAILED_REPLY
                self._append(STEP_END, {"index": step.index, "error": "llm_failed"},
                             step_id=step.id)
                return

            step.response = response
            await self._record_assistant(step, response)

            if not response.tool_calls:
                agent_turn.final_text = response.content or ""
                self._append(STEP_END, {"index": step.index, "tool_calls": 0},
                             step_id=step.id)
                if await self._should_stop(agent_turn):
                    agent_turn.stop_reason = agent_turn.stop_reason or "model/idle"
                    return
                continue

            await self._run_tools(step, response, agent_turn)
            self._append(STEP_END, {"index": step.index,
                                    "tool_calls": len(response.tool_calls)},
                         step_id=step.id)

    # ------------------------------------------------------------------ 请求
    async def _request(self, step: AgentStep,
                       agent_turn: AgentTurn) -> LLMResponse | None:
        """pre-step 瀑布（构造 messages）→ request 瀑布（环绕模型调用）。"""
        llm = self.ctx.resolve("llm")

        async def build(req: StepRequest) -> StepRequest:
            # 唯一的历史来源：按作用域派生。绝不手搓跨步 messages 列表。
            user = getattr(self.turn, "user", None) or {}
            user_anchor = ""
            if user and isinstance(user, dict):
                name = user.get("name") or "长辈"
                city = user.get("city") or "本地"
                dialect = user.get("dialect") or "普通话"
                user_anchor = (
                    f"# 当前服务对象档案（系统已知核心事实，绝对严禁重复询问老人）：\n"
                    f"- 姓名：{name}\n"
                    f"- 角色：老人（银发长辈）\n"
                    f"- 常住城市：{city}（极其重要：若老人未指定其他出发城市，老人当前所在位置默认即为此城市）\n"
                    f"- 方言习惯：{dialect}\n\n"
                )
            system_prompt = user_anchor + (self.agent.system_prompt or "")
            req.messages = ([{"role": "system",
                              "content": system_prompt}]
                            + self.log.derive_messages(self.turn.session_id,
                                                       scopes=self.scopes))
            req.tools = self.ctx.tools.schemas(self.agent.tool_names) or None
            return req

        request = StepRequest(turn=self.turn, agent=self.agent, step=step,
                              agent_turn=agent_turn)
        request = await self.bus.waterfall(PRE_STEP, request, build)
        step.messages = request.messages

        async def call(req: StepRequest) -> LLMResponse:
            async def on_delta(text: str) -> None:
                await self.turn.emit(
                    "delta", {"text": text,
                              "agent": getattr(self.agent, "display_name", "")},
                    persist=False)
            return await llm.chat(req.messages, req.tools, on_delta=on_delta)

        try:
            return await self.bus.waterfall(REQUEST, request, call)
        except Exception as exc:  # noqa: BLE001
            logger.warning("模型请求失败 (%s): %s", self.agent_id, exc)
            # request-error 瀑布：重试策略挂在这里；无人处理则本轮以明确理由收尾
            recovered = await self.bus.waterfall(
                REQUEST_ERROR, {"request": request, "error": exc},
                lambda payload: _none())
            return recovered if isinstance(recovered, LLMResponse) else None

    async def _record_assistant(self, step: AgentStep,
                                response: LLMResponse) -> None:
        """assistant 消息落日志（含 tool_calls），有正文才推 SSE 气泡。"""
        payload: dict = {"text": response.content or "",
                         "agent": getattr(self.agent, "name", "agent")}
        if response.tool_calls:
            payload["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in response.tool_calls
            ]
        self._append(ASSISTANT_MESSAGE, payload, step_id=step.id)
        if response.content:
            if response.tool_calls:
                # 中间规划/工具调用的思考文本，推至链路独白通道，不推给老人主对话框
                await self.turn.emit("agent_thought", {
                    "thought": response.content,
                    "agent": payload["agent"],
                }, persist=False)
            else:
                # 最终定稿回复老人
                await self.turn.emit("agent_msg", {
                    "text": response.content,
                    "agent": payload["agent"],
                }, persist=False)


    # ------------------------------------------------------------------ 工具
    async def _run_tools(self, step: AgentStep, response: LLMResponse,
                         agent_turn: AgentTurn) -> None:
        calls = [ToolCall(id=tc.id, name=tc.name, args=tc.arguments or {},
                          agent_id=self.agent_id)
                 for tc in response.tool_calls]
        step.tool_names = [c.name for c in calls]

        for call in calls:
            await self.turn.emit("tool_call", {
                "call_id": call.id, "tool": call.name,
                "agent": getattr(self.agent, "name", "agent"),
                "args": call.args,
                "summary": tool_summary(self.ctx, call.name, call.args),
            })

        outcomes = await self.ctx.dispatcher.execute_batch(self.turn, calls)

        for outcome in outcomes:
            if outcome.suspended:
                agent_turn.suspended = True
            payload = {
                "call_id": outcome.call.id,
                "tool": outcome.call.name,
                "ok": outcome.ok,
                "summary": outcome.result.get("summary", ""),
                # content 是模型侧要读的那份（derive_messages 用它配对 tool 消息）
                "content": outcome.to_model_content(),
                "data": outcome.result.get("data"),
            }
            if outcome.suspended:
                payload["suspended"] = True
                payload["confirmation_id"] = outcome.result.get("confirmation_id")
            if outcome.denied:
                payload["denied"] = True
            await self.turn.emit("tool_result", payload)
            if outcome.result.get("card"):
                await self.turn.emit("card", outcome.result["card"])

    # ------------------------------------------------------------------ 终止
    async def _should_stop(self, agent_turn: AgentTurn) -> bool:
        """agent/turn-stopping 有序检查点：第一个给出裁决的监听者说话。

        默认语义：模型不再调用工具即收尾。监听者可返回
        ``{"continue": True, "reason": …}`` 让这一轮继续（例如"清单没做完"）。
        """
        verdict = await self.bus.serial(TURN_STOPPING, agent_turn)
        if isinstance(verdict, dict) and verdict.get("continue"):
            agent_turn.stop_reason = ""
            logger.debug("turn-stopping 要求继续: %s", verdict.get("reason"))
            return False
        return True


def tool_summary(ctx: Any, tool_name: str, args: dict) -> str:
    """给前端工具气泡的人话摘要。"""
    tool = ctx.tools.get(tool_name)
    label = tool.description.split("。")[0] if tool else tool_name
    keys = ", ".join(f"{k}={v}" for k, v in list(args.items())[:3])
    return f"{label}（{keys}）" if keys else label


def _budget_for(agent: Any, turn: Any) -> Budget:
    cfg = getattr(turn.ctx, "settings", None)
    return Budget(
        max_steps=getattr(agent, "max_steps", 8),
        max_tokens=getattr(cfg, "budget_max_tokens", 60_000),
        wall_clock_s=getattr(cfg, "budget_wall_clock_s", 90.0),
        tool_timeout_s=getattr(cfg, "tool_timeout_s", 20.0),
    )


def _tokens_of(messages: list[dict], response: LLMResponse | None) -> int:
    """优先用 provider 报的 usage；Mock 没有 usage 时按字符数粗估。

    中文约 0.6 token/字，这里取 0.5 —— 预算守卫宁可估多不可估少。
    """
    if response is not None and response.usage:
        total = response.usage.get("total_tokens")
        if total:
            return int(total)
    chars = sum(len(str(m.get("content") or "")) for m in messages)
    if response is not None:
        chars += len(response.content or "")
    return max(1, chars // 2)


async def _none() -> None:
    return None
