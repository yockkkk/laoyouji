"""上下文压缩 —— 挂在 ``agent/pre-step`` 上的两级策略。

harness 的顺序是刻意的：**先裁工具输出，再摘要**。
理由很实在 —— 一次体检报告解读、一张车次列表就能顶掉半个上下文窗口，
而它们的价值在"结论"不在"原文"。先把这类肥肉削掉，往往就不必摘要；
真到了要摘要的地步，也只摘那些已经瘦身过的消息，摘出来的东西更准。

演示会话就三五轮，这层几乎不会触发。留着是为了两件事：
1. 答辩时"长会话怎么办"有可指的代码，不是口头承诺；
2. 真接了 DeepSeek 长对话时不至于直接 400。

压缩**只改这一步送进模型的 messages**，不改事件日志。日志永远是全量事实，
换一句话说：压缩是**投影层**的事，不是历史层的事。这条界线一旦破了，
"model-visible means logged" 就没法验证了。
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.core.bus import EventBus, PRE_STEP

logger = logging.getLogger(__name__)

# 单条工具结果超过这个字符数就裁（中文按 0.5 token/字 粗算 ≈ 900 token）
TOOL_RESULT_MAX_CHARS = 1800
# 全部 messages 超过这个字符数才启动摘要
COMPACT_TRIGGER_CHARS = 24_000
# 摘要时保留最近多少条原文（近期消息信息密度最高，不能摘）
KEEP_RECENT = 8

TRUNCATED_MARK = "…（结果较长，已省略中间部分；需要完整内容请重新查询）"
SUMMARY_PREFIX = "【前情摘要】"


def _chars(messages: list[dict]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)


def prune_tool_results(messages: list[dict], *,
                       max_chars: int = TOOL_RESULT_MAX_CHARS) -> list[dict]:
    """第一级：裁掉超大工具输出的中段，头尾都留（JSON 的键名信息在两头）。"""
    out: list[dict] = []
    for message in messages:
        content = message.get("content")
        if message.get("role") != "tool" or not isinstance(content, str) \
                or len(content) <= max_chars:
            out.append(message)
            continue
        head = content[: max_chars // 2]
        tail = content[-(max_chars // 4):]
        pruned = dict(message)
        pruned["content"] = f"{head}{TRUNCATED_MARK}{tail}"
        out.append(pruned)
    return out


def summarize(messages: list[dict], *, keep_recent: int = KEEP_RECENT) -> list[dict]:
    """第二级：把久远消息压成一条摘要，近期原文保留。

    摘要是**规则生成**的（谁说了什么、用了哪些工具），不再调一次模型：
    压缩本身不该消耗预算，也不该引入新的编造来源。
    """
    system = [m for m in messages[:1] if m.get("role") == "system"]
    body = messages[len(system):]
    if len(body) <= keep_recent:
        return messages

    old, recent = body[:-keep_recent], body[-keep_recent:]
    asked = [str(m.get("content"))[:60] for m in old if m.get("role") == "user"]
    tools_used: list[str] = []
    for message in old:
        for call in message.get("tool_calls") or []:
            name = (call.get("function") or {}).get("name")
            if name and name not in tools_used:
                tools_used.append(name)

    lines = [f"{SUMMARY_PREFIX}前面共 {len(old)} 条对话已折叠。"]
    if asked:
        lines.append("老人提过：" + "；".join(asked[-3:]))
    if tools_used:
        lines.append("已经办过：" + "、".join(tools_used))
    lines.append("完整记录在会话日志里，需要细节可以重新查询。")

    # role 用 user：DeepSeek 只认一条 system，摘要挤进去会顶掉人格设定
    digest = {"role": "user", "content": "\n".join(lines)}
    # 折叠后第一条不能是 role:tool（会成为无主的 tool 消息）
    while recent and recent[0].get("role") == "tool":
        recent = recent[1:]
    return system + [digest] + recent


def make_compactor(*, trigger_chars: int = COMPACT_TRIGGER_CHARS,
                   tool_result_max_chars: int = TOOL_RESULT_MAX_CHARS,
                   keep_recent: int = KEEP_RECENT):
    """``agent/pre-step`` 中间件：先裁工具输出，仍超阈值才摘要。"""

    async def compactor(request: Any,
                        next_: Callable[..., Awaitable[Any]]) -> Any:
        out = await next_()                      # 先让终端把 messages 派生出来
        target = out if getattr(out, "messages", None) is not None else request
        messages = list(getattr(target, "messages", []) or [])
        if not messages:
            return out

        before = _chars(messages)
        messages = prune_tool_results(messages, max_chars=tool_result_max_chars)
        if _chars(messages) > trigger_chars:
            messages = summarize(messages, keep_recent=keep_recent)
        after = _chars(messages)

        if after < before:
            logger.info("上下文压缩: %d → %d 字符", before, after)
            target.messages = messages
        return out

    return compactor


def install_compaction(bus: EventBus, **kwargs: Any) -> Callable[[], None]:
    """装配点。order 取正数：压缩要在其它 pre-step 中间件**之后**收尾。"""
    return bus.on(PRE_STEP, make_compactor(**kwargs), order=100,
                  label="compaction")
