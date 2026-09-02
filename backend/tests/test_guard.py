"""Guard 流水线三态测试：ALLOW / INTERCEPT / DENY。"""
from __future__ import annotations

from app.core.context import TurnContext
from app.core.guard import GuardVerdict
from app.safety.risk_rules import PaymentRiskRule, ScamContentRule


async def _check(guard, tool_name, args, ctx, elder):
    turn = TurnContext(ctx=ctx, session_id="s-test", user=elder)
    return await guard.check(turn, tool_name, args)


async def test_low_risk_tool_allowed(ctx, elder):
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "search_train",
                           {"from_city": "南京", "to_city": "北京"}, ctx, elder)
    assert verdict.verdict is GuardVerdict.ALLOW


async def test_high_risk_tool_intercepted(ctx, elder):
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "book_ticket",
                           {"train_no": "G102", "price": 553.5}, ctx, elder)
    assert verdict.verdict is GuardVerdict.INTERCEPT
    assert verdict.amount == 553.5
    assert verdict.risk_level == "high"


async def test_small_amount_intercepted_because_high_risk_tool(ctx, elder):
    """高危工具集即使金额小也拦截（红线 R5）。"""
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "register_appointment",
                           {"hospital": "积水潭", "fee": 20}, ctx, elder)
    assert verdict.verdict is GuardVerdict.INTERCEPT
    assert verdict.risk_level == "medium"


async def test_amount_over_threshold_intercepted(ctx, elder):
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "canteen_order",
                           {"menu_item": "满汉全席", "amount": 99}, ctx, elder)
    assert verdict.verdict is GuardVerdict.INTERCEPT


async def test_scam_content_denied(ctx, elder):
    rule = ScamContentRule()
    verdict = await _check(rule, "canteen_order",
                           {"menu_item": "保健品神药根治骨关节炎"}, ctx, elder)
    assert verdict.verdict is GuardVerdict.DENY
    assert "advice" in verdict.payload


async def test_untrusted_link_denied(ctx, elder):
    rule = ScamContentRule()
    verdict = await _check(rule, "search_train",
                           {"to_city": "http://yibao-verify.xyz"}, ctx, elder)
    assert verdict.verdict is GuardVerdict.DENY


async def test_normal_content_allowed(ctx, elder):
    rule = ScamContentRule()
    verdict = await _check(rule, "search_train",
                           {"to_city": "北京"}, ctx, elder)
    assert verdict.verdict is GuardVerdict.ALLOW


# ------------------------------------------------------------------ 金额口径
# 家人在手机上按"同意"，按的是**这一笔**的钱。单价当总额报给家人，就是让他
# 用一晚的价钱批一整趟住店。

async def test_unit_price_times_nights_is_the_amount(ctx, elder):
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "book_hotel",
                           {"hotel": "如家精选", "price": 329, "nights": 2},
                           ctx, elder)
    assert verdict.amount == 658.0
    assert "658" in verdict.reason


async def test_explicit_total_wins_over_unit_price(ctx, elder):
    """两个都在时按总额，不再乘一遍。"""
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "book_hotel",
                           {"price": 329, "nights": 2, "total": 658},
                           ctx, elder)
    assert verdict.amount == 658.0


async def test_price_without_quantity_is_taken_as_is(ctx, elder):
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "book_ticket",
                           {"train_no": "G102", "price": 553.5}, ctx, elder)
    assert verdict.amount == 553.5


async def test_missing_amount_still_intercepts_high_risk_tool(ctx, elder):
    """算不出金额不等于免检 —— 高危工具照拦，理由里不硬凑一个数字。"""
    rule = PaymentRiskRule(amount_threshold=50)
    verdict = await _check(rule, "book_hotel", {"hotel": "如家精选"}, ctx, elder)
    assert verdict.verdict is GuardVerdict.INTERCEPT
    assert verdict.amount == 0.0
    assert "0.00" not in verdict.reason
