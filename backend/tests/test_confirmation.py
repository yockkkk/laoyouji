"""高危确认状态机 —— 红线 R5"不做无人监护的自动执行"的门禁。

前半部分是状态机本身：挂起 → 批准执行 / 拒绝 / 过期 / 重复审批 409，
以及冻结参数防篡改重放。这套设计改造前就是对的，所以一个字没动。

后半部分是这次补上的**流水线耦合**。状态机写得再严，只要询问那一步能被绕过，
整条防线就等于没有。所以补了四条：

- **没有应答者就是拒绝**（fail-closed）。装配缺了确认服务时，旧实现要么
  ``AttributeError``，要么更糟 —— 把高危操作放过去。现在它变成一次明确的拒绝，
  而且给老人一句可执行的建议。
- **DENY 早于询问**：像骗子话术这种事不该拿去问家人（"要不要同意转账"本身
  就是骗局的下一步）。守卫是单调的，DENY 短路，连确认任务都不建。
- **凭证是一次性的**：``approved`` 之外的任何状态都不放行 —— 包括还没批的
  ``pending``，和已经用过的 ``executed``。
- **没认下家人时，这件事永远办不成**。任务照样落库，但谁都领不走 ——
  宁可永远办不成，也不许在无人监护的情况下办成。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.context import TurnContext
from app.core.guard import GuardResult, GuardVerdict
from app.core.tool import ToolDispatcher
from app.safety.confirmation import ConfirmationError

_FROZEN = {"train_no": "G102", "date": "tomorrow", "seat_type": "二等座",
           "price": 553.5}


def _drain(turn: TurnContext) -> list:
    events = []
    while not turn.queue.empty():
        events.append(turn.queue.get_nowait())
    return events


async def _suspend_ticket(ctx, elder) -> str:
    turn = TurnContext(ctx=ctx, session_id="s-1", user=elder)
    tool = ctx.tools.get("book_ticket")
    result = await ctx.confirmation.suspend(
        turn, tool, dict(_FROZEN),
        GuardResult(GuardVerdict.INTERCEPT, reason="车票 553.5 元", risk_level="high",
                    amount=553.5),
    )
    assert result["suspended"] is True
    return result["confirmation_id"]


async def test_suspend_creates_pending_task(ctx, elder, child):
    task_id = await _suspend_ticket(ctx, elder)
    task = await ctx.repos.get("confirmation_tasks", task_id)
    assert task["status"] == "pending"
    assert task["child_id"] == child["id"]
    assert task["tool_args"]["train_no"] == "G102"
    assert task["summary_for_child"]["amount"] == 553.5


async def test_approve_executes_frozen_call(ctx, elder, child):
    task_id = await _suspend_ticket(ctx, elder)
    result = await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])
    assert result["ok"] is True
    assert result["status"] == "executed"
    # 出票结果带老人播报话术
    announce = result["result"].get("announce", "")
    assert "G102" in announce
    task = await ctx.repos.get("confirmation_tasks", task_id)
    assert task["status"] == "executed"


async def test_double_approve_rejected(ctx, elder, child):
    task_id = await _suspend_ticket(ctx, elder)
    await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])
    with pytest.raises(ConfirmationError) as exc_info:
        await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])
    assert exc_info.value.status_code == 409


async def test_reject_then_approve_rejected(ctx, elder, child):
    task_id = await _suspend_ticket(ctx, elder)
    await ctx.confirmation.reject(task_id, ctx, child["id"])
    with pytest.raises(ConfirmationError):
        await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])


async def test_expired_task_cannot_approve(ctx, elder, child):
    task_id = await _suspend_ticket(ctx, elder)
    # 把过期时间改到过去
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    await ctx.repos.update("confirmation_tasks", task_id, {"expires_at": past})
    with pytest.raises(ConfirmationError) as exc_info:
        await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])
    assert exc_info.value.status_code == 409
    task = await ctx.repos.get("confirmation_tasks", task_id)
    assert task["status"] == "expired"


async def test_bypass_requires_matching_args(ctx, elder, child):
    """防篡改重放：bypass 凭证只放行冻结的那一次调用参数。"""
    task_id = await _suspend_ticket(ctx, elder)
    await ctx.repos.update("confirmation_tasks", task_id,
                           {"status": "approved"})
    assert await ctx.confirmation.check_bypass(
        task_id, "book_ticket", dict(_FROZEN)) is True
    # 只改一个字段（金额）就不再放行 —— 批的是那一次调用，不是那个工具
    assert await ctx.confirmation.check_bypass(
        task_id, "book_ticket", {**_FROZEN, "price": 1.0}) is False
    # 换工具名失败
    assert await ctx.confirmation.check_bypass(
        task_id, "pay", {}) is False


async def test_list_for_child_lazy_expires_stale(ctx, elder, child):
    task_id = await _suspend_ticket(ctx, elder)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    await ctx.repos.update("confirmation_tasks", task_id, {"expires_at": past})
    rows = await ctx.confirmation.list_for_child(child["id"], status="pending")
    assert rows == []  # 惰性清扫：读取时过期任务不再出现在 pending
    task = await ctx.repos.get("confirmation_tasks", task_id)
    assert task["status"] == "expired"


# ------------------------------------------------------------------ 流水线耦合


async def test_a_high_risk_call_is_denied_when_nobody_can_be_asked(ctx, elder):
    """装配里没有确认服务 → 拒绝，而不是放过去（fail-closed）。

    这不是假想的配置事故：确认服务依赖库连接，线上真出过"服务没起来"的时候。
    那一刻的默认行为决定了这条红线是真的还是纸上的 —— 靠 30 分钟静默过期
    兜不住，因为静默过期的前提是**任务已经建起来了**。
    """
    blind = ToolDispatcher(ctx.tools, ctx.guards, None, ctx.post_filters,
                           bus=ctx.bus)
    turn = TurnContext(ctx=ctx, session_id="s-noanswer", user=elder)

    result = await blind.execute(turn, "book_ticket", dict(_FROZEN))

    assert result["ok"] is False and result["denied"] is True
    assert "确认服务没有就绪" in result["summary"]
    assert result["advice"] == "先给家里人打个电话，让他们帮您办。"
    assert result.get("suspended") is not True, "不能假装已经发出去问了"
    # 也不该留下一个谁都看不见的确认任务
    assert await ctx.repos.list(
        "confirmation_tasks", where={"session_id": "s-noanswer"}) == []


async def test_a_scam_is_refused_outright_instead_of_asked_about(ctx, elder):
    """骗子话术直接拒绝，连确认任务都不建 —— 这种事不该拿去问家人。

    "要不要同意这笔转账"本身就是骗局的下一步：把它做成一张待确认卡片，
    等于替骗子把话传到了。守卫是单调的，DENY 短路在询问之前，
    所以两条守卫谁先谁后都不影响结论。
    """
    turn = TurnContext(ctx=ctx, session_id="s-scam", user=elder)

    result = await ctx.dispatcher.execute(turn, "canteen_order", {
        "menu_item": "保健品神药根治骨关节炎套餐", "count": 1, "amount": 880})

    assert result["denied"] is True and result["ok"] is False
    assert result["summary"] == "这个内容像是骗子的话术，先别操作。"
    assert result["advice"], "拒绝之后得给一句能照着做的话"
    assert result.get("suspended") is not True
    assert await ctx.repos.list(
        "confirmation_tasks", where={"session_id": "s-scam"}) == []


async def test_an_approval_voucher_is_good_for_exactly_one_replay(
        ctx, elder, child):
    """凭证只在"已批准"这一瞬有效：批之前不行，用过之后也不行。

    单次可用和参数比对是两件事 —— 参数一致的重放如果能反复放行，
    子女点一次同意就等于永久授权了这个工具。
    """
    task_id = await _suspend_ticket(ctx, elder)

    assert await ctx.confirmation.check_bypass(
        task_id, "book_ticket", dict(_FROZEN)) is False, "还没批，任务存在不等于批了"
    assert await ctx.confirmation.check_bypass(
        "no-such-task", "book_ticket", dict(_FROZEN)) is False

    approved = await ctx.confirmation.approve_and_execute(
        task_id, ctx, child["id"])
    assert approved["status"] == "executed"

    assert await ctx.confirmation.check_bypass(
        task_id, "book_ticket", dict(_FROZEN)) is False, "用过的凭证不能再放行"


async def test_an_elder_with_nobody_bound_can_never_complete_a_risky_call(
        ctx, elder, child):
    """没认下家人时：钱一分不动，任务落库但谁都领不走 —— 于是永远办不成。

    这是刻意的结局。R5 说的是"不做**无人监护**的自动执行"，没有监护人时
    唯一正确的行为就是这件事一直办不成，而不是"没人管所以放过去"。
    """
    binding = await ctx.repos.find_one("family_bindings",
                                       {"elder_id": elder["id"]})
    assert await ctx.repos.delete("family_bindings", binding["id"]) is True

    turn = TurnContext(ctx=ctx, session_id="s-unbound", user=elder)
    result = await ctx.dispatcher.execute(turn, "book_ticket", dict(_FROZEN))

    # 挂起结果里只有这几样：一张出好的票该有的字段一个都没有
    assert set(result) == {"ok", "suspended", "confirmation_id", "summary",
                           "tool"}
    assert result["suspended"] is True and result["ok"] is False
    assert "家人" in result["summary"], "没认下关系就用中性称呼，不编一个"

    rows = await ctx.repos.list("confirmation_tasks",
                                where={"session_id": "s-unbound"})
    assert len(rows) == 1 and rows[0]["child_id"] is None
    assert await ctx.confirmation.list_for_child(child["id"]) == [], \
        "解绑之后这张卡片不该出现在任何人的待办里"


async def test_the_elder_is_told_that_the_family_was_asked(ctx, elder):
    """老人当场听到的那句话：说清"发给家人了、同意后我就办"，不含黑话。

    挂起对老人来说是**一次进展**，不是一个错误。说成"操作被拦截"会让人
    以为自己做错了事，然后就不敢再用了。
    """
    turn = TurnContext(ctx=ctx, session_id="s-notice", user=elder)
    await ctx.dispatcher.execute(turn, "book_ticket", dict(_FROZEN))

    notices = [e.data for e in _drain(turn) if e.event == "suspended"]
    assert len(notices) == 1
    notice = notices[0]

    assert notice["tool"] == "book_ticket"
    assert notice["amount"] == 553.5, "金额由守卫算出，不是提示词里抄来的"
    assert notice["confirmation_id"] and notice["expires_at"]
    assert "G102" in notice["summary"]

    message = notice["message"]
    assert "确认" in message and "帮您办好" in message
    for jargon in ("拦截", "高危", "失败", "错误", "权限"):
        assert jargon not in message, f"{jargon} 是黑话：{message}"


async def test_every_hand_that_touched_it_is_on_the_record(ctx, elder, child):
    """建了、批了各留一条审计，冻结参数一并入档 —— 事后能核对办的是哪一笔。"""
    task_id = await _suspend_ticket(ctx, elder)
    await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])

    rows = {r["action"]: r for r in
            await ctx.repos.list("audit_log", where={"target": task_id})}

    assert set(rows) == {"confirmation_created", "confirmation_approved"}
    assert rows["confirmation_created"]["actor_id"] == elder["id"]
    assert rows["confirmation_created"]["detail"]["args"] == _FROZEN
    assert rows["confirmation_approved"]["actor_id"] == child["id"], \
        "批的人是子女，不是老人 —— 记成老人自己批的就等于没有这道关"


# --------------------------------------------------------------- 结果回到老人端
# 家人在自己手机上点完，老人屏幕上那张黄卡必须跟着变。这几条钉的是"变成什么"：
# 不同意和"同意了但没办成"是两件不同的事，合成一句"没成功"就等于替家人表态。


async def _resolved(ctx, session_id: str) -> dict:
    rows = [r for r in await ctx.event_log.recent(session_id, limit=200)
            if r["type"] == "confirmation/resolved"]
    assert len(rows) == 1, f"该有且只有一条结果事件，实际 {len(rows)} 条"
    return rows[0]


async def test_an_approval_is_announced_as_executed(ctx, elder, child):
    task_id = await _suspend_ticket(ctx, elder)
    await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])

    row = await _resolved(ctx, "s-1")
    assert row["payload"]["status"] == "executed"
    assert row["payload"]["ok"] is True
    assert row["payload"]["confirmation_id"] == task_id, "老人端要靠它找回那张卡"
    assert row["user_id"] == elder["id"], "这条播报是给老人的，归属人就是老人"


async def test_a_rejection_is_not_reported_as_a_failure(ctx, elder, child):
    """``ok=False`` 是两件事的并集，所以 status 必须单独发。

    少了它，老人端只能在"家人不同意"和"家人同意了但没办成"之间猜一个 ——
    猜错哪一头都是在替家人表态。
    """
    task_id = await _suspend_ticket(ctx, elder)
    await ctx.confirmation.reject(task_id, ctx, child["id"])

    row = await _resolved(ctx, "s-1")
    assert row["payload"]["status"] == "rejected"
    assert row["payload"]["ok"] is False
    # 拒绝这条也要记在老人名下：否则按人查审计时，"同意"有主、"不同意"没主
    assert row["user_id"] == elder["id"]

    said = [r["payload"]["text"] for r in
            await ctx.event_log.recent("s-1", limit=200)
            if r["type"] == "assistant/final"]
    assert said and "先不办" in said[-1]
    for jargon in ("拦截", "高危", "失败", "错误", "权限"):
        assert jargon not in said[-1], f"{jargon} 是黑话：{said[-1]}"
