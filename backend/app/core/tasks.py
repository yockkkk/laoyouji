"""backend/app/core/tasks.py —— 共享任务看板 (Shared Task Board).

参考 Claude Code src/utils/tasks.ts 设计：
1. 单调自增 ID 发生器 (.highwatermark)：生成 "1", "2", "3" 等稳定纯数字标识，绝不重用；
2. 任务状态三态流转：pending -> in_progress -> completed；
3. 有向无环依赖阻断与级联解锁：blocks / blocked_by 双向维护，前置完成自动解锁后继任务；
4. 原子互斥认领与繁忙校验 (claim_task_with_busy_check)：基于 asyncio.Lock 防范 TOCTOU 竞态；
5. 成员离线/退出任务自动解绑回退 (unassign_teammate_tasks)；
6. 面向 SSE 流式协议序列化 (sync_payload -> event: task_board_sync)。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ClaimTaskReason(str, Enum):
    SUCCESS = "success"
    TASK_NOT_FOUND = "task_not_found"
    ALREADY_CLAIMED = "already_claimed"
    ALREADY_RESOLVED = "already_resolved"
    BLOCKED = "blocked"
    AGENT_BUSY = "agent_busy"


class BoardTask(BaseModel):
    """看板任务模型 (严格遵循 PROJECT.md 契约 2)."""
    id: str                                                 # 单调递增纯数字字符串 "1", "2", "3"
    subject: str                                            # 任务标题
    description: str = ""                                   # 验收标准与任务详情
    active_form: str = ""                                   # 运行态动名词 (如 "正在测算微地形坡度")
    owner: Optional[str] = None                             # 认领智能体名称 (如 "bds_nav")
    status: str = TaskStatus.PENDING.value                  # 核心三态
    blocks: List[str] = Field(default_factory=list)         # 阻断的后继任务 ID 列表
    blocked_by: List[str] = Field(default_factory=list)     # 阻断当前任务的前置任务 ID 列表
    metadata: Dict[str, Any] = Field(default_factory=dict)  # 扩展元数据
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ClaimTaskResult(BaseModel):
    """任务认领回执."""
    success: bool
    reason: str
    task: Optional[BoardTask] = None
    blocked_by_tasks: List[str] = Field(default_factory=list)
    busy_with_tasks: List[str] = Field(default_factory=list)
    message: str = ""


class SharedTaskBoard:
    """多智能体共享任务看板 (线程/协程安全)."""

    def __init__(self, board_id: str = "default"):
        self.board_id = board_id
        self._tasks: Dict[str, BoardTask] = {}
        self._highwatermark: int = 0
        self._lock = asyncio.Lock()
        self._listeners: List[Callable[[str, BoardTask], Any]] = []

    @property
    def highwatermark(self) -> int:
        return self._highwatermark

    def add_listener(self, cb: Callable[[str, BoardTask], Any]) -> None:
        self._listeners.append(cb)

    def _notify(self, action: str, task: BoardTask) -> None:
        for cb in self._listeners:
            try:
                res = cb(action, task)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception:
                pass

    def _check_circular_dependency(
        self,
        task_id: str,
        new_blocked_by: List[str],
        new_blocks: List[str],
    ) -> bool:
        """检测添加依赖是否会导致有向环 (DFS)."""
        if task_id in new_blocked_by or task_id in new_blocks:
            return True
        if set(new_blocked_by) & set(new_blocks):
            return True

        for target in new_blocked_by:
            visited: Set[str] = set()

            def can_reach(current: str) -> bool:
                if current == target:
                    return True
                if current in visited:
                    return False
                visited.add(current)
                curr_task = self._tasks.get(current)
                if not curr_task:
                    return False
                for child_id in curr_task.blocks:
                    if can_reach(child_id):
                        return True
                return False

            for start in new_blocks:
                if can_reach(start):
                    return True

        return False

    async def add_task(
        self,
        subject: str,
        description: str = "",
        active_form: str = "",
        owner: Optional[str] = None,
        blocks: Optional[List[str]] = None,
        blocked_by: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BoardTask:
        """新建任务，分配严格单调递增 ID，并双向链接前后置依赖."""
        async with self._lock:
            self._highwatermark += 1
            task_id = str(self._highwatermark)

            initial_blocked_by = list(blocked_by or [])
            initial_blocks = list(blocks or [])
            if self._check_circular_dependency(task_id, initial_blocked_by, initial_blocks):
                self._highwatermark -= 1
                raise ValueError(f"Circular dependency detected for task {task_id}")

            status_val = TaskStatus.IN_PROGRESS.value if owner else TaskStatus.PENDING.value
            task = BoardTask(
                id=task_id,
                subject=subject,
                description=description,
                active_form=active_form,
                owner=owner,
                status=status_val,
                blocks=initial_blocks,
                blocked_by=initial_blocked_by,
                metadata=metadata or {},
            )
            self._tasks[task_id] = task

            # 双向依赖维护：前置任务的 blocks 添加当前 task_id
            for p_id in initial_blocked_by:
                if p_id in self._tasks and task_id not in self._tasks[p_id].blocks:
                    self._tasks[p_id].blocks.append(task_id)

            # 双向依赖维护：后置任务的 blocked_by 添加当前 task_id
            for s_id in initial_blocks:
                if s_id in self._tasks and task_id not in self._tasks[s_id].blocked_by:
                    self._tasks[s_id].blocked_by.append(task_id)

            self._notify("task_added", task)
            return task

    def get_task(self, task_id: str) -> Optional[BoardTask]:
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        status: Optional[TaskStatus | str] = None,
        owner: Optional[str] = None,
    ) -> List[BoardTask]:
        """列出符合条件的所有任务 (按 ID 顺序)."""
        tasks = list(self._tasks.values())
        if status:
            s_val = status.value if isinstance(status, TaskStatus) else status
            tasks = [t for t in tasks if t.status == s_val]
        if owner is not None:
            tasks = [t for t in tasks if t.owner == owner]
        return tasks

    def get_ready_tasks(self, for_agent: Optional[str] = None) -> List[BoardTask]:
        """获取所有处于就绪状态 (pending 且所有前置已完成) 的任务."""
        ready = []
        for t in self._tasks.values():
            if t.status != TaskStatus.PENDING.value:
                continue
            # 检查 blocked_by 中的任务是否全为 completed
            unresolved = [
                bid for bid in t.blocked_by
                if bid in self._tasks and self._tasks[bid].status != TaskStatus.COMPLETED.value
            ]
            if not unresolved:
                if for_agent is None or t.owner is None or t.owner == for_agent:
                    ready.append(t)
        return ready

    async def claim_task_with_busy_check(
        self,
        task_id: str,
        claimant_agent_id: str,
        check_agent_busy: bool = True,
    ) -> ClaimTaskResult:
        """原子认领任务并执行防竞态前置与繁忙状态校验 (参考 Claude Code)."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return ClaimTaskResult(
                    success=False,
                    reason=ClaimTaskReason.TASK_NOT_FOUND.value,
                    message=f"Task {task_id} not found",
                )

            # 1. 任务已完成
            if task.status == TaskStatus.COMPLETED.value:
                return ClaimTaskResult(
                    success=False,
                    reason=ClaimTaskReason.ALREADY_RESOLVED.value,
                    task=task,
                    message=f"Task {task_id} is already completed",
                )

            # 2. 任务已被其他智能体抢占
            if task.owner and task.owner != claimant_agent_id:
                return ClaimTaskResult(
                    success=False,
                    reason=ClaimTaskReason.ALREADY_CLAIMED.value,
                    task=task,
                    message=f"Task {task_id} is already claimed by {task.owner}",
                )

            # 3. 依赖阻断校验：前置任务必须 100% completed
            unresolved_blockers = [
                bid for bid in task.blocked_by
                if bid in self._tasks and self._tasks[bid].status != TaskStatus.COMPLETED.value
            ]
            if unresolved_blockers:
                return ClaimTaskResult(
                    success=False,
                    reason=ClaimTaskReason.BLOCKED.value,
                    task=task,
                    blocked_by_tasks=unresolved_blockers,
                    message=f"Task {task_id} is blocked by incomplete tasks: {unresolved_blockers}",
                )

            # 4. 智能体繁忙校验：认领者当前是否持有其他未闭环任务
            if check_agent_busy:
                agent_active_tasks = [
                    t.id for t in self._tasks.values()
                    if t.status != TaskStatus.COMPLETED.value and t.owner == claimant_agent_id and t.id != task_id
                ]
                if agent_active_tasks:
                    return ClaimTaskResult(
                        success=False,
                        reason=ClaimTaskReason.AGENT_BUSY.value,
                        task=task,
                        busy_with_tasks=agent_active_tasks,
                        message=f"Agent {claimant_agent_id} is already busy with task(s) {agent_active_tasks}",
                    )

            # 5. 原子写入认领状态
            task.owner = claimant_agent_id
            task.status = TaskStatus.IN_PROGRESS.value
            task.updated_at = datetime.now(timezone.utc).isoformat()
            self._notify("task_claimed", task)

            return ClaimTaskResult(
                success=True,
                reason=ClaimTaskReason.SUCCESS.value,
                task=task,
                message=f"Task {task_id} successfully claimed by {claimant_agent_id}",
            )

    async def complete_task(
        self,
        task_id: str,
        result_metadata: Optional[Dict[str, Any]] = None,
    ) -> tuple[BoardTask, List[BoardTask]]:
        """完成任务，级联解锁所有下游受阻任务，返回 (已完成任务, 新就绪任务列表)."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                raise KeyError(f"Task {task_id} not found")

            task.status = TaskStatus.COMPLETED.value
            if result_metadata:
                task.metadata.update(result_metadata)
            task.updated_at = datetime.now(timezone.utc).isoformat()

            # 扫描下游任务，检查是否有任务因为当前任务完成而全新就绪
            newly_unblocked: List[BoardTask] = []
            for successor_id in task.blocks:
                successor = self._tasks.get(successor_id)
                if not successor or successor.status != TaskStatus.PENDING.value:
                    continue
                # 检查 successor 的所有前置是否全完成
                remaining_blockers = [
                    bid for bid in successor.blocked_by
                    if bid in self._tasks and self._tasks[bid].status != TaskStatus.COMPLETED.value
                ]
                if not remaining_blockers:
                    newly_unblocked.append(successor)

            self._notify("task_completed", task)
            for unblocked in newly_unblocked:
                self._notify("task_ready", unblocked)

            return task, newly_unblocked

    async def unassign_teammate_tasks(
        self,
        agent_id: str,
        reason: str = "shutdown",
    ) -> Dict[str, Any]:
        """智能体离线/崩溃时自动释放其未闭环任务，状态回退为 pending，防止看板死锁."""
        async with self._lock:
            unassigned: List[BoardTask] = []
            for t in self._tasks.values():
                if t.owner == agent_id and t.status != TaskStatus.COMPLETED.value:
                    t.owner = None
                    t.status = TaskStatus.PENDING.value
                    t.updated_at = datetime.now(timezone.utc).isoformat()
                    unassigned.append(t)
                    self._notify("task_unassigned", t)

            return {
                "agent_id": agent_id,
                "reason": reason,
                "unassigned_tasks": [t.id for t in unassigned],
                "count": len(unassigned),
            }

    def sync_payload(self) -> List[Dict[str, Any]]:
        """为前端 SSE event: task_board_sync 生成全量看板快照."""
        return [t.model_dump() for t in self._tasks.values()]
