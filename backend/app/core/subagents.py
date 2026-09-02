"""子智能体接缝（``ctx.subagents``）—— 真多智能体的落点。

harness 的 subagent seam 有三个要素，这里都实现了：

1. **发现**：``available()`` 列出已注册的子智能体及其职责，供总智能体的提示词
   与答辩现场自证装配。
2. **spawn vs fork**：``spawn`` 开**全新作用域**（独立 ``agent_id``、独立派生历史）；
   ``fork`` 从父的已完成历史播种（作用域列表 = ``[父, 己]``）。默认用 spawn ——
   出行子智能体没有理由知道健康子智能体和老人聊了什么。
3. **结构化子→父回报**：``AgentReport``，不是自由文本。

第 3 点是本次大改的关键。旧实现里 ``route_to_agent`` 直接
``final = await agent.run(turn, instruction)``，父拿到的是一段话；
于是《就医出行计划书》只能靠总智能体照着那段话**重新编一遍**字典 ——
缺页、错价、张冠李戴全都可能，而且不可复现。

现在字段是**采集**来的：子智能体每个工具结果里的 ``report`` 段被 ``tools/result``
同步通知收集（按 ``call.agent_id`` 过滤，只收自己这一支的），合并成
``AgentReport.data``。计划书渲染器只读它。子智能体没查到的字段进 ``missing``，
渲染成"待补"——**宁可留白，绝不编造**。

采集用的监听者注册返回 disposer，跑完即卸载：注册是可逆副作用，
并发的兄弟智能体各挂各的，互不串味。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.bus import TOOLS_RESULT
from app.core.session import AgentDriver, AgentTurn, Budget

logger = logging.getLogger(__name__)

SPAWN = "spawn"
FORK = "fork"


@dataclass
class AgentReport:
    """子→父的结构化回报。交付物渲染管线的**唯一**输入。"""

    agent: str
    ok: bool
    summary: str
    data: dict = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    error: str = ""
    scope: str = ""
    suspended: bool = False
    tools_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"agent": self.agent, "ok": self.ok, "summary": self.summary,
                "data": self.data, "missing": self.missing, "error": self.error,
                "scope": self.scope, "suspended": self.suspended,
                "tools_used": self.tools_used}

    @classmethod
    def from_dict(cls, raw: dict) -> AgentReport:
        """从 ``agent/report`` 事件还原。回报因此不必额外存一份状态：

        总智能体聚合交付物时从事件日志里读回来 —— hydrate 之后照样成立，
        并且"这份计划书是由哪几条回报拼出来的"可以逐条指认。
        """
        return cls(
            agent=str(raw.get("agent") or ""),
            ok=bool(raw.get("ok")),
            summary=str(raw.get("summary") or ""),
            data=dict(raw.get("data") or {}),
            missing=list(raw.get("missing") or []),
            error=str(raw.get("error") or ""),
            scope=str(raw.get("scope") or ""),
            suspended=bool(raw.get("suspended")),
            tools_used=list(raw.get("tools_used") or []),
        )

    def get(self, path: str, default: Any = None) -> Any:
        """``report.get("appointment.doctor")`` —— 取不到就是取不到，不猜。"""
        node: Any = self.data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


@dataclass
class SubagentSpec:
    """一次派发。总智能体一次给一串，就是一次真扇出。"""

    name: str                      # travel | health | community
    instruction: str
    mode: str = SPAWN              # spawn | fork
    label: str = ""

    @classmethod
    def parse(cls, raw: Any) -> SubagentSpec | None:
        if isinstance(raw, str):
            return cls(name=raw, instruction="")
        if not isinstance(raw, dict):
            return None
        name = str(raw.get("agent") or raw.get("name") or "").strip()
        if not name:
            return None
        return cls(name=name,
                   instruction=str(raw.get("instruction") or raw.get("task") or ""),
                   mode=str(raw.get("mode") or SPAWN),
                   label=str(raw.get("label") or ""))


class SubagentRegistry:
    """``ctx.subagents``：注册 + 发现 + 运行（一次性子会话）。"""

    def __init__(self, ctx: Any):
        self.ctx = ctx
        # 已分配但事件还没落下的作用域。并发扇出时 `_next_scope` 光看日志会撞号：
        # 两个 travel 任务同时起步时，谁的 turn/start 都还没 append，
        # 两边都会算出 travel#1 —— 于是两个采集监听者认领同一批结果，串味。
        self._reserved: dict[str, set[str]] = {}

    # ------------------------------------------------------------------ 发现
    def available(self, *, exclude: tuple[str, ...] = ("main",)) -> list[dict]:
        out = []
        for name, agent in (self.ctx.agents or {}).items():
            if name in exclude:
                continue
            out.append({"name": name,
                        "display_name": getattr(agent, "display_name", name),
                        "description": getattr(agent, "description", ""),
                        "reports": list(getattr(agent, "report_schema", ()))})
        return out

    def names(self, *, exclude: tuple[str, ...] = ("main",)) -> list[str]:
        return [x["name"] for x in self.available(exclude=exclude)]

    # ------------------------------------------------------------------ 运行
    async def spawn(self, turn: Any, spec: SubagentSpec) -> AgentReport:
        """全新子作用域：子智能体只看到自己的指令和自己的工具结果。"""
        return await self._run(turn, spec, inherit=False)

    async def fork(self, turn: Any, spec: SubagentSpec) -> AgentReport:
        """从父已完成历史播种：需要上文时才用（作用域 = [父, 己]）。"""
        return await self._run(turn, spec, inherit=True)

    async def run_parallel(self, turn: Any,
                           specs: list[SubagentSpec]) -> list[AgentReport]:
        """真扇出：多个子智能体并发跑，各自独立作用域。

        这是修 #2 的地方 —— 旧实现在父工具体内 ``await agent.run()``，
        天然串行且嵌套；现在是同级并发，时间戳会重叠（测试里断墙钟）。
        """
        if not specs:
            return []
        if len(specs) == 1:
            return [await self._dispatch(turn, specs[0])]
        results = await asyncio.gather(
            *(self._dispatch(turn, spec) for spec in specs),
            return_exceptions=True)
        reports: list[AgentReport] = []
        for spec, out in zip(specs, results):
            if isinstance(out, BaseException):
                logger.exception("子智能体 %s 异常", spec.name, exc_info=out)
                reports.append(AgentReport(
                    agent=spec.name, ok=False,
                    summary=f"{spec.name} 这边没办成",
                    error=str(out)))
            else:
                reports.append(out)
        return reports

    async def _dispatch(self, turn: Any, spec: SubagentSpec) -> AgentReport:
        return await (self.fork(turn, spec) if spec.mode == FORK
                      else self.spawn(turn, spec))

    # ------------------------------------------------------------------ 内部
    async def _run(self, turn: Any, spec: SubagentSpec, *,
                   inherit: bool) -> AgentReport:
        agent = (self.ctx.agents or {}).get(spec.name)
        if agent is None:
            return AgentReport(agent=spec.name, ok=False,
                               summary=f"没有叫 {spec.name} 的子助理",
                               error="unknown_agent")

        scope = self._next_scope(turn.session_id, spec.name)
        scopes = [turn.agent_id, scope] if inherit else [scope]
        child_turn = turn.scoped(scope)

        collected: list[dict] = []

        def collect(outcome: Any) -> None:
            # 只收自己这一支的结果：并发的兄弟不会串味
            if getattr(outcome.call, "agent_id", None) == scope:
                collected.append({"tool": outcome.call.name,
                                  "args": dict(outcome.call.args or {}),
                                  "result": outcome.result,
                                  "suspended": outcome.suspended,
                                  "denied": outcome.denied})

        dispose = self.ctx.bus.on(TOOLS_RESULT, collect, label=f"collect:{scope}")
        await child_turn.status(getattr(agent, "display_name", spec.name),
                               f"{getattr(agent, 'display_name', spec.name)}正在处理…")
        try:
            driver = AgentDriver(agent, child_turn, agent_id=scope, scopes=scopes,
                                 budget=_child_budget(agent, turn),
                                 flush_on_end=False)
            agent_turn = await driver.run(spec.instruction or None)
        finally:
            dispose()            # 可逆副作用：跑完就摘

        return _build_report(agent, spec, scope, agent_turn, collected,
                             self.ctx.tools)

    def _next_scope(self, session_id: str, name: str) -> str:
        """作用域编号从事件日志推出来（无第二份状态，hydrate 后依然正确），
        再并上本进程内已预留的号 —— 后者只为闭合并发分配的那个窗口。"""
        prefix = f"{name}#"
        reserved = self._reserved.setdefault(session_id, set())
        used = {e.agent_id for e in self.ctx.event_log.events(session_id)
                if e.agent_id.startswith(prefix)}
        used |= {s for s in reserved if s.startswith(prefix)}
        scope = f"{prefix}{len(used) + 1}"
        reserved.add(scope)
        return scope


def _build_report(agent: Any, spec: SubagentSpec, scope: str,
                  agent_turn: AgentTurn, collected: list[dict],
                  tools: Any = None) -> AgentReport:
    """把采集到的工具结果合并成结构化回报。字段来自工具，不来自模型措辞。

    归档规则，按优先级：

    1. 结果里有 ``report`` 段 → **整段合并**（工具自己最清楚该给什么形状）
    2. 否则看 ``Tool.report_key``：
       - **被挂起**（等家人确认）→ 存**冻结的调用参数** + ``status=pending_confirm``
         + ``confirmation_id``。这条是旗舰演示的关键：订票和挂号在演示里都会被
         拦下，此时并不存在"已订好的票"，计划书只能写"已选定，等家人确认"。
         旧实现让模型照着自己的话编一份"已订成功"，那是假的。
       - **成功** → ``data`` 整段进 ``report_key``
       - **被拒 / 失败** → **不写**。字段留空 → 落进 ``missing`` → 渲染成"待补"
    3. 都没有但成功且 ``data`` 是 dict → 按工具名兜底归档（仍是真数据）
    """
    data: dict = {}
    tools_used: list[str] = []
    ok_any = False
    for entry in collected:
        name = entry["tool"]
        tools_used.append(name)
        result = entry["result"] or {}
        if result.get("ok"):
            ok_any = True

        report = result.get("report")
        if isinstance(report, dict):
            data.update(report)
            continue

        tool = tools.get(name) if tools is not None else None
        key = getattr(tool, "report_key", "") if tool else ""
        if key:
            if entry.get("suspended"):
                # 参数已在 confirmation.suspend 里冻结，这里存的就是那一份
                data[key] = {**entry["args"], "status": "pending_confirm",
                             "confirmation_id": result.get("confirmation_id", "")}
                ok_any = True      # "已挂起待确认"是有效进展，不是失败
            elif result.get("ok") and isinstance(result.get("data"), dict):
                data[key] = result["data"]
            # 被拒 / 失败：故意什么都不写，让它留在 missing 里
        elif isinstance(result.get("data"), dict) and result.get("ok"):
            data.setdefault(name, result["data"])

    required = tuple(getattr(agent, "report_schema", ()))
    missing = [key for key in required if key not in data]

    return AgentReport(
        agent=spec.name,
        # ok 只回答"这一支有没有真办成事"。``missing`` 是**提示**而不是判决：
        # report_schema 是这个子智能体**能给**的字段清单，不是每次派发都必须给的
        # —— 让健康助理只加个用药提醒，它当然不产出 appointment，那不叫失败。
        # 交付物那边不看这个标志，缺字段一律自己渲染成"待补"。
        ok=ok_any,
        summary=agent_turn.final_text or "",
        data=data,
        missing=missing,
        scope=scope,
        suspended=agent_turn.suspended,
        tools_used=tools_used,
    )


def _child_budget(agent: Any, turn: Any) -> Budget:
    """子智能体的预算比父紧：一支跑飞不该拖垮整轮。"""
    cfg = getattr(turn.ctx, "settings", None)
    return Budget(
        max_steps=getattr(agent, "max_steps", 6),
        max_tokens=int(getattr(cfg, "budget_max_tokens", 60_000) * 0.6),
        wall_clock_s=float(getattr(cfg, "budget_wall_clock_s", 90.0)) * 0.6,
        tool_timeout_s=float(getattr(cfg, "tool_timeout_s", 20.0)),
    )
