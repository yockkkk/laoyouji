"""EventBus —— 四种派发模式（对齐 deepseek-harness 的 microkernel event taxonomy）。

harness 把"钩子该怎么被调用"收敛成四种模式，本文件是它在本项目的落点。
新行为一律挂钩子，不改 agent loop —— 这是"一切皆插件"能成立的前提。

| 模式        | 语义                                       | 用在哪 |
|------------|--------------------------------------------|--------|
| waterfall  | 环绕中间件，监听者拿到 next() 决定是否继续    | pre-step / request / tools 三段 |
| serial     | 有序检查点，第一个给出非 None 的即裁决        | turn-stopping |
| parallel   | 扇出并等待全部完成                           | session/flush |
| emit       | 同步即发即忘，绝不阻塞热路径                  | 通知 / 生命周期 / tools/result |

waterfall 约定：监听者签名 ``async fn(payload, next_)``。
调 ``next_()`` 表示放行（可传新 payload 做改写）；**不调 next_ 直接 return 即短路**，
返回值就是权威裁决 —— 这是 pre-execute 拒绝、guard 拦截的表达方式。

注册返回 disposer（可逆副作用）：调用它即摘掉监听者，便于测试与运行时换实现。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# ---- 钩子名（harness 词表）------------------------------------------------
PRE_STEP = "agent/pre-step"                  # waterfall：进 step 前（压缩/预算/注入）
REQUEST = "agent/request"                    # waterfall：构造模型请求
REQUEST_ERROR = "agent/request-error"        # waterfall：模型请求失败后的重试决策
TURN_STOPPING = "agent/turn-stopping"        # serial：轮次终止检查点
TOOLS_PRE_EXECUTE = "tools/pre-execute"      # waterfall：钩子 / 权限 / 沙箱
TOOLS_EXECUTE = "tools/execute"              # waterfall：环绕派发（超时/重试/指标）
TOOLS_POST_EXECUTE = "tools/post-execute"    # waterfall：接受/阻断/改写/追加上下文
TOOLS_RESULT = "tools/result"                # emit：冻结后的权威结果通知
SESSION_FLUSH = "session/flush"              # parallel：轮次结束的持久化检查点

Next = Callable[..., Awaitable[Any]]
WaterfallFn = Callable[[Any, Next], Awaitable[Any]]
SerialFn = Callable[[Any], Awaitable[Any]]
ParallelFn = Callable[[Any], Awaitable[Any]]
EmitFn = Callable[[Any], None]

_UNSET = object()


@dataclass(order=True)
class _Listener:
    order: int
    seq: int
    fn: Any = field(compare=False, default=None)
    label: str = field(compare=False, default="")


class EventBus:
    """极小事件内核：注册 + 四种派发。没有特权核心，行为都在监听者里。"""

    def __init__(self) -> None:
        self._hooks: dict[str, list[_Listener]] = {}
        self._counter = 0

    # ------------------------------------------------------------ 注册
    def on(self, hook: str, fn: Any, *, order: int = 0,
           label: str = "") -> Callable[[], None]:
        """挂监听者，返回 disposer（调用即卸载，注册是可逆副作用）。"""
        self._counter += 1
        listener = _Listener(order=order, seq=self._counter, fn=fn,
                             label=label or getattr(fn, "__name__", "anon"))
        bucket = self._hooks.setdefault(hook, [])
        bucket.append(listener)
        bucket.sort()

        def dispose() -> None:
            if listener in self._hooks.get(hook, []):
                self._hooks[hook].remove(listener)

        return dispose

    def listeners(self, hook: str) -> list[str]:
        """已挂载监听者标签（按执行序）—— 答辩时可现场 dump 装配。"""
        return [x.label for x in self._hooks.get(hook, [])]

    # ------------------------------------------------------------ waterfall
    async def waterfall(self, hook: str, payload: Any,
                        terminal: Callable[[Any], Awaitable[Any]]) -> Any:
        """环绕中间件洋葱：外层可改写 payload、可短路、可加工返回值。"""
        chain = list(self._hooks.get(hook, []))

        async def step(index: int, current: Any) -> Any:
            if index >= len(chain):
                return await terminal(current)
            listener = chain[index]
            called = False

            async def next_(new_payload: Any = _UNSET) -> Any:
                nonlocal called
                called = True
                return await step(index + 1,
                                  current if new_payload is _UNSET else new_payload)

            out = await listener.fn(current, next_)
            if not called:
                logger.debug("%s 监听者 %s 短路返回", hook, listener.label)
            return out

        return await step(0, payload)

    # ------------------------------------------------------------ serial
    async def serial(self, hook: str, payload: Any) -> Any | None:
        """有序检查点：第一个返回非 None 的监听者即裁决，其余不再执行。"""
        for listener in list(self._hooks.get(hook, [])):
            out = await listener.fn(payload)
            if out is not None:
                return out
        return None

    # ------------------------------------------------------------ parallel
    async def parallel(self, hook: str, payload: Any) -> list[Any]:
        """扇出并等待全部完成；单个失败不拖垮其它（记日志）。"""
        chain = list(self._hooks.get(hook, []))
        if not chain:
            return []
        results = await asyncio.gather(
            *(x.fn(payload) for x in chain), return_exceptions=True)
        for listener, out in zip(chain, results):
            if isinstance(out, Exception):
                logger.warning("%s 监听者 %s 失败: %s", hook, listener.label, out)
        return list(results)

    # ------------------------------------------------------------ emit
    def emit(self, hook: str, payload: Any) -> None:
        """同步即发即忘。监听者必须是同步函数，异常吞掉 —— 热路径不可被通知拖垮。"""
        for listener in list(self._hooks.get(hook, [])):
            try:
                listener.fn(payload)
            except Exception as exc:  # noqa: BLE001 —— 通知失败绝不影响主流程
                logger.warning("%s 通知 %s 失败: %s", hook, listener.label, exc)
