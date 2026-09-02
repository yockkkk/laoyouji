"""BaseAgent —— 智能体的身份声明（薄壳）。

循环、预算、作用域、事件记账全在 ``core/session.AgentDriver`` 里。这里只剩
"我是谁、我说什么话、我能用哪些工具、我承诺回报哪些字段"四件事。

旧版这个文件塞着 100 行 ``run_agent_loop``：自己攒 ``messages`` 跨步传递、自己
拼 ``role:"tool"`` 消息、遇到挂起就 ``break`` 丢掉同批次其余调用、除步数外没有
任何止损。那些问题不是靠改这个循环解决的，是靠把循环搬到内核、让它只有一份。
"""
from __future__ import annotations

import logging
from abc import ABC

from app.core.context import TurnContext
from app.core.events import MAIN_SCOPE
from app.core.session import AgentDriver, AgentTurn

logger = logging.getLogger(__name__)

MAX_STEPS = 8

SUSPENDED_REPLY = (
    "好嘞，这步要先过您家人的确认。我已经把这件事发给{relation}了，"
    "他点一下“同意”，我就马上帮您办好。您先歇着，别着急。"
)


class BaseAgent(ABC):
    """子智能体基类：声明身份 + 提示词 + 可用工具 + 回报字段。"""

    name: str = "agent"
    display_name: str = "助手"
    description: str = ""
    system_prompt: str = ""
    tool_names: list[str] = []
    max_steps: int = MAX_STEPS

    # 这个智能体**承诺**能回报的字段（AgentReport.data 的键）。
    # 缺了就进 report.missing，交付物渲染成"待补"而不是编一个。
    # 键名与工具的 report_key 一一对应，见 tools/*.py。
    report_schema: tuple[str, ...] = ()

    async def run(self, turn: TurnContext, instruction: str | None = None) -> str:
        """跑一轮，返回最终文本。子智能体一般不走这里，走 ctx.subagents。"""
        agent_turn = await self.run_turn(turn, instruction)
        return agent_turn.final_text

    async def run_turn(self, turn: TurnContext,
                       instruction: str | None = None) -> AgentTurn:
        await turn.status(self.display_name, f"{self.display_name}正在处理…")
        scope = getattr(turn, "agent_id", MAIN_SCOPE)
        driver = AgentDriver(self, turn, agent_id=scope, scopes=[scope])
        agent_turn = await driver.run(instruction)
        if agent_turn.suspended and not agent_turn.final_text.strip():
            # 模型没自己交代就替它交代：老人必须知道"为什么停在这儿"
            agent_turn.final_text = SUSPENDED_REPLY.format(
                relation=relation_name(turn))
        return agent_turn


def relation_name(turn: TurnContext) -> str:
    return (turn.user or {}).get("child_relation") or "家人"
