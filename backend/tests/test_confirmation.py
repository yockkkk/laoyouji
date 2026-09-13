"""高危确认状态机 —— 红线 R5"不做无人监护的自动执行"的门禁。

**这里守的是钱。** 本次产品反转把"要花钱"和"要就医"拆开了：挂号
（register_appointment）已移出高危集、立即执行，办完由 health_tools 写一条
``appointment_notice`` 知会子女 —— 就医不需要家人审批，老人不该为看病等谁点头。
所以下面凡是要"真的经过 dispatcher 把一次高危调用拦下来"的用例，探针都换成
``pay``（本文件里现注册的假工具）：把挂号留在这些用例里，测的就不再是这条线了；
而把审批整条拆掉，又会开出"不用同意就花钱"的口子 —— 两条都得钉住。

前半部分是状态机本身：挂起 → 批准执行 / 拒绝 / 过期 / 重复审批 409，
以及冻结参数防篡改重放。这套设计改造前就是对的，所以一个字没动 ——
通用高危状态机仍在，只是线上的活体用例从挂号变成了付款。

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

import re
from datetime import datetime, timedelta, timezone

import pytest

from app.core.context import TurnContext
from app.core.guard import GuardResult, GuardVerdict
from app.core.tool import ToolDispatcher
from app.safety.confirmation import ConfirmationError

_FROZEN = {"hospital": "南京鼓楼医院", "department": "骨科", "doctor": "邱勇",
           "date": "+1", "time": "上午 08:30", "fee": 70}

# 金融动作的探针。``pay`` 在 HIGH_RISK_TOOLS 里，但仓库里**没有**注册这个工具
# （真实产品里挂在支付/代付那条线上）。挂号移出高危集之后，它是唯一能触发
# INTERCEPT 的工具，所以要"经 dispatcher 证明高危仍被拦下"就得现注册一个真的。
# 假的是它的实现（什么都不扣），不是它的风险等级。
_PAY_ARGS = {"subject": "代办费", "amount": 70}


async def _pay(turn, args: dict) -> dict:
    return {"ok": True, "summary": f"已付款 {args.get('amount')} 元",
            "announce": "钱付好啦。"}


def _register_pay(ctx) -> None:
    from app.tools.common import make_tool

    ctx.tools.register(make_tool(
        "pay", "支付一笔费用（金融动作：高危，需家人确认）。",
        {"subject": {"type": "string", "description": "付款事由"},
         "amount": {"type": "number", "description": "金额（元）"}},
        _pay,
        child_summary=lambda a: f"母亲张桂芳有一笔 {a.get('amount')} 元的支出要付",
    ))


def _drain(turn: TurnContext) -> list:
    events = []
    while not turn.queue.empty():
        events.append(turn.queue.get_nowait())
    return events


async def _suspend_appointment(ctx, elder) -> str:
    """直接调 ``confirmation.suspend`` —— 演练的是**通用高危状态机**，不经 guard。

    线上已经没有"挂号被拦下"这条路了（挂号立即办好），但状态机、冻结参数、
    过期清扫、审批归属这些不变量一件都没少，只是活体用例换成了 pay。
    这里留着 register_appointment 是因为它的 child_summary 与结果字段最完整，
    当作状态机的"满载样本"最好用 —— 它测的是状态机，不是挂号该不该审批。
    """
    turn = TurnContext(ctx=ctx, session_id="s-1", user=elder)
    tool = ctx.tools.get("register_appointment")
    result = await ctx.confirmation.suspend(
        turn, tool, dict(_FROZEN),
        GuardResult(GuardVerdict.INTERCEPT, reason="挂号费 70 元，需要家人确认",
                    risk_level="high", amount=70),
    )
    assert result["suspended"] is True
    return result["confirmation_id"]


async def test_suspend_creates_pending_task(ctx, elder, child):
    task_id = await _suspend_appointment(ctx, elder)
    task = await ctx.repos.get("confirmation_tasks", task_id)
    assert task["status"] == "pending"
    assert task["child_id"] == child["id"]
    assert task["tool_args"]["hospital"] == "南京鼓楼医院"
    assert task["summary_for_child"]["amount"] == 70


async def test_approve_executes_frozen_call(ctx, elder, child):
    task_id = await _suspend_appointment(ctx, elder)
    result = await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])
    assert result["ok"] is True
    assert result["status"] == "executed"
    # 挂号结果带老人播报话术
    announce = result["result"].get("announce", "")
    assert "南京鼓楼医院" in announce
    task = await ctx.repos.get("confirmation_tasks", task_id)
    assert task["status"] == "executed"


async def test_double_approve_rejected(ctx, elder, child):
    task_id = await _suspend_appointment(ctx, elder)
    await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])
    with pytest.raises(ConfirmationError) as exc_info:
        await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])
    assert exc_info.value.status_code == 409


async def test_reject_then_approve_rejected(ctx, elder, child):
    task_id = await _suspend_appointment(ctx, elder)
    await ctx.confirmation.reject(task_id, ctx, child["id"])
    with pytest.raises(ConfirmationError):
        await ctx.confirmation.approve_and_execute(task_id, ctx, child["id"])


async def test_expired_task_cannot_approve(ctx, elder, child):
    task_id = await _suspend_appointment(ctx, elder)
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
    task_id = await _suspend_appointment(ctx, elder)
    await ctx.repos.update("confirmation_tasks", task_id,
                           {"status": "approved"})
    assert await ctx.confirmation.check_bypass(
        task_id, "register_appointment", dict(_FROZEN)) is True
    # 只改一个字段（挂号费）就不再放行 —— 批的是那一次调用，不是那个工具
    assert await ctx.confirmation.check_bypass(
        task_id, "register_appointment", {**_FROZEN, "fee": 1.0}) is False
    # 换工具名失败
    assert await ctx.confirmation.check_bypass(
        task_id, "pay", {}) is False


async def test_list_for_child_lazy_expires_stale(ctx, elder, child):
    task_id = await _suspend_appointment(ctx, elder)
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

    探针用 ``pay`` 而不是 register_appointment：挂号已不审批，fail-closed 这条线
    现在只剩钱来守 —— 让挂号去测，测出来的会是"挂号放行"，与这条不变量的命题无关。
    """
    _register_pay(ctx)
    blind = ToolDispatcher(ctx.tools, ctx.guards, None, ctx.post_filters,
                           bus=ctx.bus)
    turn = TurnContext(ctx=ctx, session_id="s-noanswer", user=elder)

    result = await blind.execute(turn, "pay", dict(_PAY_ARGS))

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

    result = await ctx.dispatcher.execute(turn, "plan_route", {
        "origin": "家", "destination": "保健品神药根治骨关节炎套餐"})

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
    task_id = await _suspend_appointment(ctx, elder)

    assert await ctx.confirmation.check_bypass(
        task_id, "register_appointment", dict(_FROZEN)) is False, "还没批，任务存在不等于批了"
    assert await ctx.confirmation.check_bypass(
        "no-such-task", "register_appointment", dict(_FROZEN)) is False

    approved = await ctx.confirmation.approve_and_execute(
        task_id, ctx, child["id"])
    assert approved["status"] == "executed"

    assert await ctx.confirmation.check_bypass(
        task_id, "register_appointment", dict(_FROZEN)) is False, "用过的凭证不能再放行"


async def test_an_elder_with_nobody_bound_can_never_complete_a_risky_call(
        ctx, elder, child):
    """没认下家人时：钱一分不动，任务落库但谁都领不走 —— 于是永远办不成。

    这是刻意的结局。R5 说的是"不做**无人监护**的自动执行"，没有监护人时
    唯一正确的行为就是这件事一直办不成，而不是"没人管所以放过去"。

    换成 ``pay`` 之后这里守的才是钱：挂号没有家人也一样要能办成 ——
    老人看病不该因为"没绑上子女"就被卡住（挂号那一路的结局见本文件末尾）。
    """
    _register_pay(ctx)
    binding = await ctx.repos.find_one("family_bindings",
                                       {"elder_id": elder["id"]})
    assert await ctx.repos.delete("family_bindings", binding["id"]) is True

    turn = TurnContext(ctx=ctx, session_id="s-unbound", user=elder)
    result = await ctx.dispatcher.execute(turn, "pay", dict(_PAY_ARGS))

    # 挂起结果里只有这几样：一笔款该有的结果字段一个都没有
    assert set(result) == {"ok", "suspended", "confirmation_id", "summary",
                           "tool"}
    assert result["suspended"] is True and result["ok"] is False
    assert "家人" in result["summary"], "没认下关系就用中性称呼，不编一个"

    rows = await ctx.repos.list("confirmation_tasks",
                                where={"session_id": "s-unbound"})
    assert len(rows) == 1 and rows[0]["child_id"] is None
    assert await ctx.confirmation.list_for_child(child["id"]) == [], \
        "解绑之后这张卡片不该出现在任何人的待办里"


async def test_a_stranger_family_is_never_picked_as_approver(ctx, elder, child):
    """库里存在**别家**的 active 绑定时，未绑定老人的任务也不许挂到陌生人头上。

    这是上一个测试缺的那半个世界：测试库删光绑定后一个 active 都不剩，
    旧代码的"全局兜底"拿不到东西，R5 看着成立；生产库里随便有一家别人，
    同一条不变量立刻破 —— 陌生人的子女会收到别人家老人的医院和金额。

    同样换成 ``pay``：挂号那条线已经没有"审批人"这个概念了，认错人的风险
    只可能出在钱这条线上。
    """
    _register_pay(ctx)
    # 别家：一个和 elder 毫无关系的 active 家庭
    other_elder = await ctx.repos.insert("users", {
        "username": "otherelder", "role": "elder", "name": "别人家的老人",
        "status": "active"})
    other_child = await ctx.repos.insert("users", {
        "username": "otherchild", "role": "child", "name": "别人家的子女",
        "status": "active"})
    await ctx.repos.insert("family_bindings", {
        "elder_id": other_elder["id"], "child_id": other_child["id"],
        "relation": "女儿", "status": "active"})
    # 当前老人彻底无绑定
    binding = await ctx.repos.find_one("family_bindings",
                                       {"elder_id": elder["id"]})
    assert await ctx.repos.delete("family_bindings", binding["id"]) is True

    turn = TurnContext(ctx=ctx, session_id="s-stranger", user=elder)
    result = await ctx.dispatcher.execute(turn, "pay", dict(_PAY_ARGS))
    assert result["suspended"] is True

    rows = await ctx.repos.list("confirmation_tasks",
                                where={"session_id": "s-stranger"})
    assert len(rows) == 1
    assert rows[0]["child_id"] is None, \
        "不许从库里随便挑一个 active 绑定来审批别人家的老人"
    assert await ctx.confirmation.list_for_child(other_child["id"]) == [], \
        "陌生人的待办里不能出现这张卡"
    assert await ctx.repos.list(
        "notifications", where={"user_id": other_child["id"]}) == [], \
        "陌生人也不许收到含医院和金额的通知"


async def test_a_revoked_binding_sees_no_pending_tasks(ctx, elder, child):
    """绑定 revoked 之后，列表接口一条都不给 —— approve 那路有校验，列表也不能漏。"""
    task_id = await _suspend_appointment(ctx, elder)
    binding = await ctx.repos.find_one(
        "family_bindings", {"elder_id": elder["id"], "child_id": child["id"]})
    await ctx.repos.update("family_bindings", binding["id"],
                           {"status": "revoked"})

    assert await ctx.confirmation.list_for_child(child["id"]) == []
    assert await ctx.confirmation.list_for_child(
        child["id"], status="pending") == []
    task = await ctx.repos.get("confirmation_tasks", task_id)
    assert task["status"] == "pending", "任务还在，只是谁都不该看见"


async def test_pending_tasks_survive_a_long_history(ctx, elder, child):
    """1 条 pending + 120 条 executed：pending 必须看得见。

    旧实现拉全表最新 100 行再内存过滤，历史一多 pending 就被挤出窗口 ——
    老人那一轮永远挂着，没人能批。这不是显示问题，是功能性死锁。
    """
    task_id = await _suspend_appointment(ctx, elder)
    for i in range(120):
        # 日期取将来值：让 executed 全部比 pending 新，旧实现的全表 100 行
        # 窗口才会把 pending 挤出去（这正是生产里的情形：审批永远在催，
        # 历史任务不断堆在它头上）。
        await ctx.repos.insert("confirmation_tasks", {
            "session_id": "s-hist", "elder_id": elder["id"],
            "child_id": child["id"], "tool_name": "register_appointment",
            "tool_args": dict(_FROZEN), "status": "executed",
            "created_at": f"2027-06-{(i % 28) + 1:02d}T{i % 24:02d}:00:00+00:00",
        })

    rows = await ctx.confirmation.list_for_child(child["id"], status="pending")
    assert [t["id"] for t in rows] == [task_id]


async def test_the_notification_uses_the_same_shape_as_the_schema(
        ctx, elder, child):
    """通知表只有一套行形状（schema.sql：summary/is_read/data）。

    旧写法塞 content/payload/status='unread' —— 单表 JSON 存储不报错，
    但前端靠 is_read 判未读：confirmation_request 行没有 is_read，
    永远显示"未读"，点了已读也不变。
    """
    await _suspend_appointment(ctx, elder)

    rows = await ctx.repos.list(
        "notifications", where={"user_id": child["id"]})
    assert len(rows) == 1
    notif = rows[0]
    assert notif["type"] == "confirmation_request"
    assert notif["is_read"] is False, "未读要靠 is_read，不是另一套 status 字段"
    assert notif["summary"], "摘要放在 summary，不是 content"
    assert notif["data"]["task_id"], "载荷放在 data，不是 payload"
    assert notif["elder_id"] == elder["id"]
    assert "content" not in notif and "payload" not in notif
    assert "status" not in notif and "family_id" not in notif


async def test_approve_while_the_gate_is_held_gets_a_409_not_a_500(
        ctx, elder, child):
    """会话闸门被老人新一轮对话占着时，审批返回 409，不是 500。

    TurnBusy 不是 ConfirmationError 的子类，路由那个 except 接不住它 ——
    不修的话，老人在等审批期间又说了一句话，子女点批准就撞上 500。
    """
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_ctx
    from app.auth.security import create_access_token
    from app.core.turn_gate import TurnBusy
    from app.main import app

    task_id = await _suspend_appointment(ctx, elder)

    original = ctx.confirmation.approve_and_execute

    async def _busy(*args, **kwargs):
        raise TurnBusy("老人正在说下一件事，请稍后再点")

    ctx.confirmation.approve_and_execute = _busy
    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        token = create_access_token(child, ctx.settings)
        headers = {"Authorization": f"Bearer {token}"}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport,
                               base_url="http://test") as ac:
            res = await ac.post(f"/api/confirmations/{task_id}/approve",
                                headers=headers)
            assert res.status_code == 409
            assert "稍后" in res.json()["detail"]
    finally:
        ctx.confirmation.approve_and_execute = original
        app.dependency_overrides.clear()


async def test_the_elder_is_told_that_the_family_was_asked(ctx, elder):
    """老人当场听到的那句话：说清"发给家人了、同意后我就办"，不含黑话。

    挂起对老人来说是**一次进展**，不是一个错误。说成"操作被拦截"会让人
    以为自己做错了事，然后就不敢再用了。

    探针换成 ``pay``：这句"等家人回话"的播报现在只该在**钱**上出现。
    挂号那条线走的是完全相反的措辞（见本文件末尾 test_the_elder_hears_...）。
    """
    _register_pay(ctx)
    turn = TurnContext(ctx=ctx, session_id="s-notice", user=elder)
    await ctx.dispatcher.execute(turn, "pay", dict(_PAY_ARGS))

    notices = [e.data for e in _drain(turn) if e.event == "suspended"]
    assert len(notices) == 1
    notice = notices[0]

    assert notice["tool"] == "pay"
    assert notice["amount"] == 70, "金额由守卫算出，不是提示词里抄来的"
    assert notice["confirmation_id"] and notice["expires_at"]
    assert "70" in notice["summary"] and "支出" in notice["summary"]

    message = notice["message"]
    assert "确认" in message and "帮您办好" in message
    for jargon in ("拦截", "高危", "失败", "错误", "权限"):
        assert jargon not in message, f"{jargon} 是黑话：{message}"


async def test_every_hand_that_touched_it_is_on_the_record(ctx, elder, child):
    """建了、批了各留一条审计，冻结参数一并入档 —— 事后能核对办的是哪一笔。"""
    task_id = await _suspend_appointment(ctx, elder)
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
    task_id = await _suspend_appointment(ctx, elder)
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
    task_id = await _suspend_appointment(ctx, elder)
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


# ------------------------------------------------------------ 就医：知会不审批
# 用户的原话："就医不需要家人审批，但必须及时把完整情况知会子女。"
# 下面五条把这句话拆成可执行的三件事，缺一条这个改动就是半截的：
#   (a) 挂号立即办好 —— 不挂起、不建任务、不变黄卡；
#   (b) 办完**必须**有一条写给子女的知会，且内容完整（含"为什么去"）；
#   (c) 知会是"知道"，不是"待办" —— 没有 task_id，不进任何人的待办列表；
#   (d) 措辞不能退回"等家人确认" —— 老人不该为看病等谁点头；
#   (e) 没绑家人的老人照样看得上病（钱那条线的结局与本条相反，见上文）。


async def test_a_registration_runs_immediately_instead_of_waiting_for_approval(
        ctx, elder, child):
    """(a) 挂号不再阻塞：经完整 dispatcher 走一遍，当场办完。"""
    turn = TurnContext(ctx=ctx, session_id="s-booked", user=elder)
    result = await ctx.dispatcher.execute(turn, "register_appointment", dict(_FROZEN))

    assert result["ok"] is True, f"挂号该直接办成：{result}"
    assert result.get("suspended") is not True
    assert result["data"]["registration_no"], "真回执，不是冻结参数"
    assert result["card"]["type"] == "appointment"

    assert await ctx.repos.list(
        "confirmation_tasks", where={"session_id": "s-booked"}) == [], \
        "挂号不该再建确认任务"
    assert await ctx.repos.list(
        "notifications", where={"user_id": child["id"],
                                "type": "confirmation_request"}) == [], \
        "子女端不该出现一张要点的审批卡"

    records = await ctx.repos.list(
        "health_records", where={"elder_id": elder["id"],
                                 "record_type": "appointment"})
    assert len(records) == 1


async def test_the_children_are_told_the_full_picture_when_an_appointment_is_booked(
        ctx, elder, child):
    """(b) 知会必须**完整**：医院/科室/医生/时间/挂号费 + 为什么去。

    子女只能看到这一条。缺哪一项，他都要打电话回来问 —— 而"及时把完整情况
    知会子女"里的"完整"就是冲着这个来的：子女据此判断要不要回一趟家。
    触发原因走的是同一个分诊大脑，所以是事实（血压 178/105，中重度偏高），
    不是结论。
    """
    from app.safety.risk_rules import _DIAGNOSIS_PATTERNS

    turn = TurnContext(ctx=ctx, session_id="s-told", user=elder)
    await ctx.dispatcher.execute(turn, "log_vital",
                                 {"metric_type": "bp", "systolic": 178, "diastolic": 105})
    result = await ctx.dispatcher.execute(turn, "register_appointment", dict(_FROZEN))
    reg = result["data"]

    rows = await ctx.repos.list(
        "notifications", where={"user_id": child["id"], "type": "appointment_notice"})
    assert len(rows) == 1, "知会该有且只有一条"
    notif, summary = rows[0], rows[0]["summary"]

    for piece in (elder["name"], reg["hospital"], reg["department"], reg["doctor"],
                  reg["date"], reg["time"], str(reg["fee"]),
                  "178/105", "建议就医"):
        assert str(piece) in summary, f"知会缺了「{piece}」：{summary}"
    assert "去的原因" in summary
    assert notif["is_read"] is False, "未读：子女端靠 is_read 出小红点"
    assert notif["elder_id"] == elder["id"]
    assert notif["data"]["registration_no"] == reg["registration_no"]
    assert notif["data"]["level"] == "建议就医"
    assert notif["data"]["drivers"], "触发原因要结构化地带上，不只是句子"

    # R1/R2：知会里只能出现事实，不能有诊断口吻
    for pattern in _DIAGNOSIS_PATTERNS:
        assert not re.search(pattern, summary), f"知会里出现了诊断口吻：{summary}"


async def test_a_notice_is_not_a_request_for_permission(ctx, elder, child):
    """(c) 子女手机上出现的是"知道了一件事"，不是"有件事等你办"。

    这条是"知会"与"审批"的分界线，也是它俩能被分别统计、分别提醒的前提：
    一条没有 task_id 的通知，前端再怎么点也点不出"批准/拒绝"两个按钮。
    """
    turn = TurnContext(ctx=ctx, session_id="s-not-a-task", user=elder)
    await ctx.dispatcher.execute(turn, "register_appointment", dict(_FROZEN))

    rows = await ctx.repos.list(
        "notifications", where={"user_id": child["id"], "type": "appointment_notice"})
    assert len(rows) == 1
    assert "task_id" not in rows[0]["data"], "知会不是待办：没有可审批的对象"
    assert await ctx.confirmation.list_for_child(child["id"]) == [], \
        "待办列表里不该有它 —— 子女没有需要点的东西"


async def test_the_elder_hears_booked_and_told_not_asked(ctx, elder, child):
    """(d) 老人听到的是"已挂好号 + 已告诉家人"，不是"已提交，等待确认"。

    措辞不是装饰：说成"等家人确认"，老人就会坐着等一个不会来的回话，
    甚至不敢去看病。这条把旧措辞的几个词也钉成禁词。
    """
    turn = TurnContext(ctx=ctx, session_id="s-hears", user=elder)
    result = await ctx.dispatcher.execute(turn, "register_appointment", dict(_FROZEN))
    announce, summary = result["announce"], result["summary"]

    assert "已为您挂好号" in announce
    assert "告诉" in announce and "您儿子李明" in announce, \
        f"称呼要落到具体的人：{announce}"
    assert re.search(r"\d{2}:\d{2}", announce), f"知会的时间点要念出来：{announce}"
    for word in ("等待", "确认", "审批", "提交", "拦截"):
        assert word not in announce, f"「{word}」是审批口吻：{announce}"
        assert word not in summary, f"「{word}」是审批口吻：{summary}"
    assert "遵医嘱" in announce, "R4：挂号仍在 HEALTH_TOOLS，免责声明照挂"


async def test_an_elder_with_nobody_bound_can_still_see_the_doctor(ctx, elder, child):
    """(e) 没绑家人也不耽误看病 —— 这与钱那条线的结局**正好相反**。

    "钱没人管就不许动"是对的；"病没人管就不许看"是错的。这一条就是那个区别。
    """
    binding = await ctx.repos.find_one("family_bindings",
                                       {"elder_id": elder["id"]})
    assert await ctx.repos.delete("family_bindings", binding["id"]) is True

    turn = TurnContext(ctx=ctx, session_id="s-lonely", user=elder)
    result = await ctx.dispatcher.execute(turn, "register_appointment", dict(_FROZEN))

    assert result["ok"] is True and result.get("suspended") is not True
    assert "已为您挂好号" in result["announce"]
    assert "还没绑上家人" in result["announce"], "没绑家人就照实说，不假装发过了"
    assert await ctx.repos.list(
        "notifications", where={"user_id": child["id"]}) == []


async def test_a_second_registration_does_not_stack_notices(ctx, elder, child):
    """同一件事再下一遍：不叠通知，也不记第二笔挂号。

    挂号不再挂起之后，``ConfirmationService`` 那层"同会话同工具只留一张待办"
    的判重就够不着它了。判重下沉到工具里：provider 幂等出号，通知再按
    registration_no 去重 —— 不然家人会在通知中心看到同一次就诊两条知会，
    以为老人挂了两个号。
    """
    turn = TurnContext(ctx=ctx, session_id="s-twice", user=elder)
    await ctx.dispatcher.execute(turn, "register_appointment", dict(_FROZEN))
    await ctx.dispatcher.execute(turn, "register_appointment", dict(_FROZEN))

    rows = await ctx.repos.list(
        "notifications", where={"user_id": child["id"], "type": "appointment_notice"})
    assert len(rows) == 1, f"同一笔挂号只该有一条知会：{[r['summary'] for r in rows]}"
    records = await ctx.repos.list(
        "health_records", where={"elder_id": elder["id"],
                                 "record_type": "appointment"})
    assert len(records) == 1, "同一件事不该在老人的时间线上记两笔"
