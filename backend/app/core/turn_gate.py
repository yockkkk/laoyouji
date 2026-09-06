"""会话轮次闸门 —— 同一个会话的轮次必须一个接一个。

**这修的是什么**：老人连点两次"发送"、或者子女端和老人端同时开着同一个会话时，
两个轮次会同时跑。两边都往同一份事件日志里 append，派生给模型的历史就交错成：

    user 我要去北京看病 / assistant 好嘞 / user 帮我买点菜 / assistant 我在呢

模型下一步看到的是这么一锅粥，它无法分辨哪句回答对着哪句提问 —— 因果链断了，
接下来的工具调用参数就可能张冠李戴（拿"买菜"的上下文去订去北京的票）。

**为什么是排队而不是拒绝**：拒绝第二次请求最省事，但老人那句话就丢了，
他只会觉得"我说了它没反应"。排队则两句都答，顺序还是对的。等的时候推一条
``agent_status`` 出去，前端能显示"我还在办上一件事"，演示里这一下是加分项 ——
它让"系统在认真排队"这件事看得见，而不是界面假装没事发生。

等待有上限（``max_wait_s``）：前一轮的预算墙钟是 90 秒，等它等到天荒地老不如
早点说实话，让老人重说一遍。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# 排队时给老人的话（不说"锁""并发"这类黑话）
QUEUED_HINT = "我还在办上一件事，马上就来听您说。"
# 等太久了：说实话，别让他一直看着转圈
TIMEOUT_HINT = "上一件事还没办完，您稍等一下再跟我说这句，好吗？"


class TurnBusy(RuntimeError):
    """等不到闸门 —— 前一轮迟迟不结束。带一句能直接说给老人听的话。"""

    def __init__(self, message: str = TIMEOUT_HINT):
        super().__init__(message)
        self.message = message


class SessionTurnGate:
    """每会话一把闸。``hold()`` 是异步上下文管理器，出了 with 块自动放行。"""

    def __init__(self, max_wait_s: float = 100.0):
        self.max_wait_s = max_wait_s
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiting: dict[str, int] = {}

    def _lock(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = self._locks[session_id] = asyncio.Lock()
        return lock

    def busy(self, session_id: str) -> bool:
        lock = self._locks.get(session_id)
        return bool(lock and lock.locked())

    def waiting(self, session_id: str) -> int:
        return self._waiting.get(session_id, 0)

    @asynccontextmanager
    async def hold(self, session_id: str, *, on_wait=None,
                   max_wait_s: float | None = None):
        """占住这个会话的闸门。已有轮次在跑时排队等待。

        ``on_wait`` 是个可等待回调，只在**真的需要等**时调一次 —— 让调用方推一条
        "我还在办上一件事"出去。不需要等时一次都不调，界面上不会闪一下无谓的提示。
        """
        lock = self._lock(session_id)
        deadline = self.max_wait_s if max_wait_s is None else max_wait_s

        acquired = False
        # 同步递增等待计数：必须在任何 await / yielding 之前执行，
        # 彻底杜绝 on_wait 让出期间产生的重入与漏判
        self._waiting[session_id] = self._waiting.get(session_id, 0) + 1
        acq_task = None
        try:
            need_wait = lock.locked() or (self._waiting.get(session_id, 0) > 1)
            if need_wait:
                # 在让出事件循环执行 on_wait 之前先挂号进入锁排队队列，
                # 确保持有者释放后严格遵循 FIFO 调度，防止后来的协程插队抢锁
                acq_task = asyncio.create_task(lock.acquire())
                try:
                    if on_wait is not None:
                        await on_wait()
                    logger.info("会话 %s 已有轮次在跑，本轮排队（前面 %d 个）",
                                session_id, self._waiting.get(session_id, 0))
                    await asyncio.wait_for(asyncio.shield(acq_task), timeout=deadline)
                    acquired = True
                except asyncio.TimeoutError:
                    raise TurnBusy() from None
                finally:
                    if not acquired:
                        if acq_task.done() and not acq_task.cancelled():
                            lock.release()
                        else:
                            acq_task.cancel()
            else:
                await asyncio.wait_for(lock.acquire(), timeout=deadline)
                acquired = True
        except asyncio.TimeoutError:
            raise TurnBusy() from None
        finally:
            left = self._waiting.get(session_id, 1) - 1
            if left > 0:
                self._waiting[session_id] = left
            else:
                self._waiting.pop(session_id, None)
            if not acquired and not lock.locked() and not self._waiting.get(session_id):
                self._locks.pop(session_id, None)

        try:
            yield
        finally:
            lock.release()
            # 没人在等也没人占着，就别把这把锁留在字典里长年累月堆着
            if not lock.locked() and not self._waiting.get(session_id):
                self._locks.pop(session_id, None)
