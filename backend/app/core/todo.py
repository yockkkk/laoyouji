"""todo/write —— 任务清单：真进度的唯一事实源。

严格照搬 deepseek-harness 的 todo 语义，包括它刻意的"少"：

- ``TodoItem`` 只有 ``content`` 和三态 ``status``，**没有 id、没有 priority**。
  因为每次写入都是整列表覆盖（last-write-wins），条目不需要稳定身份。
- ``todo/write`` 是 **log-only** 事件：不另开一张表、不留第二份状态，
  当前清单永远是"日志里最后一条 todo/write"的投影。
- 伴随不变式校验状态合法性（见 ``SessionEventLog.check_invariants``）。

这修掉的是原型里最扎眼的一处作假：前端 ``chat.vue`` 收到任意 ``tool_call``
就把第一个待办标成"进行中"、收到 ``tool_result`` 就标"完成"，而计划本身只活在
组件内存里 —— 刷新即丢，和真实任务零绑定。现在进度是后端事件，前端只做渲染。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.events import TODO_WRITE, MAIN_SCOPE, SessionEventLog

PENDING = "pending"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
STATUSES = (PENDING, IN_PROGRESS, COMPLETED)


@dataclass
class TodoItem:
    """清单里的一条。content 是给老人看的一句话，status 是完整生命周期。"""

    content: str
    status: str = PENDING

    def to_dict(self) -> dict:
        return asdict(self)


class TodoError(ValueError):
    """清单不合法（状态越界 / 内容为空）—— 宁可报错也不写脏状态。"""


def normalize(raw: Any) -> list[TodoItem]:
    """把 LLM 给的任意形状归一成合法清单。非法状态直接报错，不静默纠正。"""
    if not isinstance(raw, list):
        raise TodoError("todos 必须是数组")
    items: list[TodoItem] = []
    for entry in raw:
        if isinstance(entry, str):
            items.append(TodoItem(content=entry.strip()))
            continue
        if not isinstance(entry, dict):
            raise TodoError(f"清单条目类型不对: {type(entry).__name__}")
        content = str(entry.get("content") or "").strip()
        if not content:
            raise TodoError("清单条目 content 不能为空")
        status = str(entry.get("status") or PENDING)
        if status not in STATUSES:
            raise TodoError(f"状态只能是 {STATUSES}，收到 {status!r}")
        items.append(TodoItem(content=content, status=status))
    return items


def write(log: SessionEventLog, session_id: str, todos: Any, *,
          agent_id: str = MAIN_SCOPE, user_id: str | None = None,
          turn_id: str | None = None,
          step_id: str | None = None) -> list[TodoItem]:
    """整列表覆盖写。返回归一化后的清单。"""
    items = normalize(todos)
    log.append(session_id, user_id, TODO_WRITE,
               {"todos": [i.to_dict() for i in items]},
               agent_id=agent_id, turn_id=turn_id, step_id=step_id)
    return items


def current(log: SessionEventLog, session_id: str, *,
            agent_id: str = MAIN_SCOPE) -> list[TodoItem]:
    """当前清单 = 日志里最后一条 todo/write 的投影（不存第二份状态）。"""
    for event in reversed(log.events(session_id)):
        if event.type == TODO_WRITE and event.agent_id == agent_id:
            return [TodoItem(content=t.get("content", ""),
                             status=t.get("status", PENDING))
                    for t in event.payload.get("todos") or []]
    return []


def progress(items: list[TodoItem]) -> dict:
    """给前端的进度摘要。"""
    done = sum(1 for i in items if i.status == COMPLETED)
    return {"total": len(items), "done": done,
            "doing": sum(1 for i in items if i.status == IN_PROGRESS)}
