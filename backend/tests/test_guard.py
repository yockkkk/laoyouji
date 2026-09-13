"""Guard 流水线三态测试：ALLOW / INTERCEPT / DENY。

康乐收敛为本地健康后，高危工具集只剩 ``{pay}`` —— 城际订票/订酒店、社区付费下单
整条砍掉，反诈降级为后台规则。**这一集现在只装"要花钱"**：就医挂号已经移出，
改走"知会不审批"（挂号立即办好 + 给子女写一条 appointment_notice，见
tools/health_tools.py）。两种高危从此各走各的门：钱等家人点头，看病不等。

这里的守卫是**直接调用**的纯函数，不经过注册表，所以工具名只是给
PaymentRiskRule 查"是不是高危集成员"、给 ScamContentRule 扫参数用；用哪个
留下来的工具名都不改变判定逻辑，改的只是这份测试读起来是否还指着真实存在的能力。
"""
from __future__ import annotations

from app.core.context import TurnContext
from app.core.guard import GuardVerdict
from app.safety.risk_rules import (
    HIGH_RISK_TOOLS,
    PaymentRiskRule,
    ScamContentRule,
)


async def _check(guard, tool_name, args, ctx, elder):
    turn = TurnContext(ctx=ctx, session_id="s-test", user=elder)
    return await guard.check(turn, tool_name, args)


async def test_low_risk_tool_allowed(ctx, elder):
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "get_weather",
                           {"city": "南京", "date": "明天"}, ctx, elder)
    assert verdict.verdict is GuardVerdict.ALLOW


async def test_high_risk_tool_intercepted(ctx, elder):
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "pay",
                           {"subject": "挂号费", "amount": 553.5}, ctx, elder)
    assert verdict.verdict is GuardVerdict.INTERCEPT
    assert verdict.amount == 553.5
    assert verdict.risk_level == "high"


async def test_small_amount_intercepted_because_high_risk_tool(ctx, elder):
    """高危工具集即使金额小也拦截（红线 R5）。

    工具名从 register_appointment 换成 pay：挂号已不审批，钱这条线现在由 pay 守。
    """
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "pay",
                           {"subject": "挂号费", "amount": 20}, ctx, elder)
    assert verdict.verdict is GuardVerdict.INTERCEPT
    assert verdict.risk_level == "medium"


async def test_amount_over_threshold_intercepted(ctx, elder):
    """非高危工具，但金额过阈值照样拦（打车费 99 元也要家人知道）。"""
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "hail_ride",
                           {"destination": "南京鼓楼医院", "amount": 99}, ctx, elder)
    assert verdict.verdict is GuardVerdict.INTERCEPT


async def test_scam_content_denied(ctx, elder):
    rule = ScamContentRule()
    verdict = await _check(rule, "add_medication",
                           {"drug_name": "保健品神药根治骨关节炎"}, ctx, elder)
    assert verdict.verdict is GuardVerdict.DENY
    assert "advice" in verdict.payload


async def test_untrusted_link_denied(ctx, elder):
    rule = ScamContentRule()
    verdict = await _check(rule, "search_hospital",
                           {"city": "http://yibao-verify.xyz"}, ctx, elder)
    assert verdict.verdict is GuardVerdict.DENY


async def test_normal_content_allowed(ctx, elder):
    rule = ScamContentRule()
    verdict = await _check(rule, "search_hospital",
                           {"city": "南京"}, ctx, elder)
    assert verdict.verdict is GuardVerdict.ALLOW


# ------------------------------------------------------------------ 金额口径
# 家人在手机上按"同意"，按的是**这一笔**的钱。单价当总额报给家人，就是让他
# 用一份的价钱批下一整批 —— 份数必须乘进去。

async def test_unit_price_times_quantity_is_the_amount(ctx, elder):
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "pay",
                           {"subject": "挂号费", "price": 329, "count": 2},
                           ctx, elder)
    assert verdict.amount == 658.0
    assert "658" in verdict.reason


async def test_explicit_total_wins_over_unit_price(ctx, elder):
    """两个都在时按总额，不再乘一遍。"""
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "pay",
                           {"price": 329, "count": 2, "total": 658}, ctx, elder)
    assert verdict.amount == 658.0


async def test_price_without_quantity_is_taken_as_is(ctx, elder):
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "pay",
                           {"subject": "挂号费", "price": 553.5}, ctx, elder)
    assert verdict.amount == 553.5


async def test_missing_amount_still_intercepts_high_risk_tool(ctx, elder):
    """算不出金额不等于免检 —— 高危工具照拦，理由里不硬凑一个数字。

    同样换成 pay：判据是"在高危集里"，不是"金额算得出来"。
    """
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "pay",
                           {"subject": "代付"}, ctx, elder)
    assert verdict.verdict is GuardVerdict.INTERCEPT
    assert verdict.amount == 0.0
    assert "0.00" not in verdict.reason


# ---------------------------------------------------------------- 钱与看病分家
# 本次产品反转的核心：把"要花钱"和"要就医"从同一道家人闸门里拆开。
# 这两条放在一起看才有意义 —— 只钉其中一条，把集合**清空**也能让它通过，
# 那就把"花钱要审批"整个拆掉了。


async def test_paying_still_needs_approval_while_booking_does_not(ctx, elder):
    """钱要审批、看病不要：pay 拦，register_appointment 放行。

    挂号那条还额外钉了**金额门槛的豁免**：70 元的专家号金额本身超过阈值 50，
    只把工具移出高危集是不够的 —— 金额规则会再拦一次，老人照样得等家人点头。
    所以这里用的是真实挂号费（70），不是随便一个小数。
    """
    rule = PaymentRiskRule(amount_threshold=50)

    paying = await _check(rule, "pay", {"subject": "药费", "amount": 99}, ctx, elder)
    assert paying.verdict is GuardVerdict.INTERCEPT, "钱这条线一个字都不能松"

    booking = await _check(rule, "register_appointment",
                           {"hospital": "南京鼓楼医院", "department": "骨科",
                            "doctor": "邱勇", "fee": 70}, ctx, elder)
    assert booking.verdict is GuardVerdict.ALLOW, \
        "挂号费不是康乐替老人花出去的钱，不能让 70 元把老人拦回等家人确认"

    assert "pay" in HIGH_RISK_TOOLS
    assert "register_appointment" not in HIGH_RISK_TOOLS
