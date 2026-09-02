"""工具构造辅助：统一 JSON Schema 风格与返回结构约定。

工具返回 dict 约定：
  ok        bool   是否成功
  summary   str    给 LLM 的结果摘要（也用于前端 tool_result 气泡）
  announce  str    （可选）给老人的大白话播报
  data      dict   （可选）结构化数据
  card      dict   （可选）前端渲染的结构化卡片
  report    dict   （可选）**显式**指定这次结果在 AgentReport.data 里的形状，
                   整段合并。不给就走 ``Tool.report_key`` 的默认归档规则
                   （见 core/subagents._build_report）。

``report`` / ``report_key`` 是交付物管线的入口：《就医出行计划书》的每个字段都
必须能追到某个工具结果里的某个键，模型不参与拼装 —— 这是方案书第三步能不能
被验收的分界线。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

from app.core.tool import CONCURRENT, Tool
from app.providers.external.base import resolve_date

_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def human_date(value: Any) -> str:
    """``tomorrow`` / ``+3`` / ``2026-09-04`` → ``2026-09-04（周五）``。

    相对日期是**模型说出口的词** —— 工具 schema 明写了 ``date`` 可以是
    ``'tomorrow'`` 或 ``'+2'``，挂起时冻结下来的参数就长这样。凡是这份参数要
    给**人**看的地方（家人手机上的确认卡、打印出来的计划书），都得先过这一道：
    家人要在一张写着 553.5 元的卡片上点"同意"，卡上却写着 ``tomorrow``，
    他没法确认自己批的是哪天。

    换算是纯算术，指的还是同一天；认不出的写法原样返回，绝不改写成某个
    "看起来像日期"的东西 —— 编一个日期比留一个看不懂的词糟糕得多。
    """
    if value is None or value == "":
        return ""
    iso = resolve_date(value)
    try:
        day = date.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return str(value)
    return f"{iso}（{_WEEKDAYS[day.weekday()]}）"


def make_tool(name: str, description: str, params: dict,
              handler: Callable[..., Any], *, agent: str = "common",
              child_summary: Callable[[dict], str] | None = None,
              execution_mode: str = CONCURRENT,
              timeout_s: float | None = None,
              report_key: str = "") -> Tool:
    return Tool(
        name=name,
        description=description,
        parameters={"type": "object", "properties": params, "required": []},
        handler=handler,
        child_summary=child_summary,
        agent=agent,
        execution_mode=execution_mode,
        timeout_s=timeout_s,
        report_key=report_key,
    )


def ok(summary: str, **extra: Any) -> dict:
    return {"ok": True, "summary": summary, **extra}


def fail(summary: str, **extra: Any) -> dict:
    return {"ok": False, "summary": summary, **extra}
