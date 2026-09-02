"""Guard 流水线 —— 安全管控中间层的核心（参考 deepseek-harness 的 tools/pre-execute 瀑布）。

三种裁决：
- ALLOW      放行执行
- INTERCEPT  拦截挂起 → 创建 confirmation_task，等子女确认后恢复执行
- DENY       直接拒绝（如识别到诈骗内容），给出替代建议
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class GuardVerdict(str, Enum):
    ALLOW = "allow"
    INTERCEPT = "intercept"
    DENY = "deny"


@dataclass
class GuardResult:
    verdict: GuardVerdict
    reason: str = ""
    risk_level: str = "medium"      # low / medium / high
    amount: float = 0.0             # 涉及金额（元）
    payload: dict = field(default_factory=dict)


class Guard(ABC):
    """pre-execute 守卫。check 只做裁决，不产生副作用。"""

    name: str = "guard"

    @abstractmethod
    async def check(self, turn: Any, tool_name: str, args: dict) -> GuardResult:
        ...


class AllowAll(Guard):
    """测试用：全放行。"""

    name = "allow_all"

    async def check(self, turn: Any, tool_name: str, args: dict) -> GuardResult:
        return GuardResult(GuardVerdict.ALLOW)
