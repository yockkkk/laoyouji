"""循环卫生守卫 —— 挂在钩子上的小插件，不改 agent loop。

harness 把这类东西叫 guards：它们只做一件事，可装可卸，语义单调。
本文件两个，一个强制、一个建议：

- ``timeout_policy``（强制）环绕 ``tools/execute``。超时返回**明确的**超时结果，
  而不是让协程悬着。旧实现没有单工具 deadline，一个卡住的外部调用能把整条
  SSE 拖死；老人看到的是永远转圈的界面。
- ``repeat_tool_reminder``（**建议性**）挂 ``tools/post-execute``。检测到同参数
  重复调用只在结果里加一句提醒，**绝不阻断** —— 阻断会把"重试一次本该成功"
  的场景也误杀。harness 对这类启发式的态度一贯是"提醒，不裁决"。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable

from app.core.bus import EventBus, TOOLS_EXECUTE, TOOLS_POST_EXECUTE

logger = logging.getLogger(__name__)

REPEAT_HINT = "（提醒：这个调用刚才用同样的参数试过了，换个思路或直接给结论。）"


def make_timeout_policy(default_s: float = 20.0):
    """环绕 ``tools/execute`` 的超时策略。单工具可用 ``Tool.timeout_s`` 覆盖。"""

    async def timeout_policy(pctx: Any, next_: Callable[..., Awaitable[Any]]) -> Any:
        deadline = getattr(pctx.tool, "timeout_s", None) or default_s
        try:
            return await asyncio.wait_for(next_(), timeout=deadline)
        except asyncio.TimeoutError:
            logger.warning("工具 %s 超过 %.1fs 未返回，按超时收尾",
                           pctx.call.name, deadline)
            return {
                "ok": False,
                "timed_out": True,
                "summary": f"{pctx.call.name} 等了 {deadline:.0f} 秒还没回话，"
                           f"这次先不等了，稍后我再试。",
            }

    return timeout_policy


def make_repeat_tool_reminder(window: int = 6):
    """同参数重复调用的建议性提醒。按 (作用域, 工具, 参数) 记账。

    挂在 ``tools/post-execute``（而不是 pre）：只有到了 post 才有结果可以追加
    提醒，pre 阶段整批都还没执行。计数在有序 post 里进行，因此是确定的。
    """
    seen: dict[tuple[str, str, str], int] = {}

    async def repeat_tool_reminder(pctx: Any,
                                   next_: Callable[..., Awaitable[Any]]) -> Any:
        # 记账键必须含 session_id：同一个工具的同样参数（查"南京明天的火车票"）
        # 在不同会话里是两件完全正当的事。不含它，跨老人跨会话会互相误报
        # "这个调用刚试过"，而这提醒会进模型上下文，直接带偏下一步决策。
        session_id = getattr(getattr(pctx, "turn", None), "session_id", "")
        key = (session_id, pctx.call.agent_id, pctx.call.name,
               json.dumps(pctx.call.args, ensure_ascii=False, sort_keys=True,
                          default=str))
        count = seen.get(key, 0) + 1
        seen[key] = count
        if len(seen) > window * 8:                    # 简单防膨胀
            seen.clear()
            seen[key] = count

        result = await next_()
        if count > 1 and isinstance(result, dict):
            summary = result.get("summary") or ""
            if REPEAT_HINT not in summary:
                result["summary"] = f"{summary}{REPEAT_HINT}"
            result["repeat_count"] = count
        return result

    return repeat_tool_reminder


def install_loop_guards(bus: EventBus, *, tool_timeout_s: float = 20.0
                        ) -> list[Callable[[], None]]:
    """装配点：返回 disposer 列表（测试里可整体卸载）。"""
    return [
        bus.on(TOOLS_EXECUTE, make_timeout_policy(tool_timeout_s),
               order=-100, label="timeout-policy"),
        bus.on(TOOLS_POST_EXECUTE, make_repeat_tool_reminder(),
               order=100, label="repeat-tool-reminder"),
    ]
