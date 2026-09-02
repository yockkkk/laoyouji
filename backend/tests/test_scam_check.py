"""反诈判定 —— 这条加分项最容易变成"看起来有"。

三件事分别会让它在真正要用的那一刻失效，各钉一组：

- **判定的理由和建议必须是这件事的**。旧匹配按字符集重合度算分（阈值 4），
  中文里"我""了""先""钱"加一个逗号就凑满了 —— 于是"中奖了让我先交钱"命中
  "孙子摔了手机借钱"那条语料，播给老人的建议是"给孙子本人打个电话确认"。
  档位碰巧对了，人是错的。
- **说不准的时候要说说不准**。语料和词表都没话说时才问模型，而模型离线时
  回的是一句寒暄；把它当判定播出去，等于替老人下了个没人下过的结论。
- **反诈工具自己不能被反诈规则拦掉**。它的入参就是那条骗子短信，守卫每次
  都会命中；被拦住的话，最该生效的那一刻它是空的。
"""
from __future__ import annotations

from app.core.context import TurnContext

# 语料库里那条冒充孙辈借钱的原文，老人念的时候一般会自己加一圈话
_READ_OUT = "我收到一条短信，说是我孙子，手机摔坏了急用钱，让我先转到一个账户"
# 旧算法在这句话上出的错：语义上跟孙子毫无关系
_PRIZE_FEE = "有人给我打电话说我中奖了，让我先交钱"


async def _check(ctx, elder, content: str) -> dict:
    """走完整流水线（含守卫），不是直接调函数 —— 拦不拦得住也是被测行为。"""
    turn = TurnContext(ctx=ctx, session_id="s-scam-check", user=elder)
    return await ctx.dispatcher.execute(turn, "check_scam", {"content": content})


async def test_the_advice_belongs_to_what_the_elder_actually_read(ctx, elder):
    """命中语料库时，理由和建议都来自命中的那一条。"""
    result = await _check(ctx, elder, _READ_OUT)

    assert result["ok"] is True
    assert result["data"]["verdict"] == "high_risk"
    assert "孙" in result["data"]["advice"], "这条就是冒充孙辈，建议该指向孙子本人"
    assert "先别转" in result["announce"]


async def test_a_different_scam_does_not_borrow_another_ones_advice(ctx, elder):
    """"中奖交钱"要判高风险，但不许套用"给孙子打电话"那句建议。

    这是旧算法唯一的错法：判定对、建议错。老人照着一句提到不相干的人的建议做，
    比没有建议更糊涂 —— 他会先去打那个电话，而骗子等的就是这段时间。
    """
    result = await _check(ctx, elder, _PRIZE_FEE)

    assert result["data"]["verdict"] == "high_risk"
    advice = result["data"]["advice"]
    for wrong in ("孙", "医保", "神药"):
        assert wrong not in advice, f"这句建议是别条语料的：{advice}"
    assert "中奖" in result["data"]["reason"], "理由要说出是哪个词可疑"
    assert "别转" in advice or "别照着做" in advice, "得给一句能照着做的话"


async def test_it_says_it_cannot_tell_instead_of_guessing(ctx, elder):
    """语料外 + 词表外：给"拿不准"，不给一个编出来的判定。

    离线时模型对这类请求回的是"好的，我在呢。您慢慢说。"。旧实现把这句话原样
    当判定 summary 和播报发给老人 —— 断网兜底和冒烟脚本走的正是这条路。
    """
    result = await _check(ctx, elder, "老同事约我明天下午去公园下棋")

    assert result["data"]["verdict"] == "unknown"
    assert "我在呢" not in result["announce"], "寒暄不是判定"
    assert "拿不准" in result["announce"]
    assert "家人" in result["announce"], "拿不准就把事交回给家人，别让老人自己拍板"


async def test_judging_a_scam_is_not_itself_treated_as_one(ctx, elder):
    """入参里带"转账"也要放行 —— 判断内容不等于照着内容办事。

    这是刻意的豁免（``risk_rules._JUDGES_CONTENT``）：这个工具不动钱、不下单、
    不锁号源，只出一个判断。R5 管的是执行。
    """
    result = await _check(ctx, elder, "【某银行】您的账户异常，请转账到安全账户")

    assert result.get("denied") is not True, "反诈工具被反诈规则拦了，等于没有反诈"
    assert result["ok"] is True
    assert result["data"]["verdict"] == "high_risk"


async def test_every_check_lands_in_the_elders_record(ctx, elder):
    """三条支线都要留痕。原来只有命中语料那一支写档案，语料外的查不到 ——
    子女事后问"我妈那天到底收到了什么"，翻不出来。"""
    for content in (_READ_OUT, _PRIZE_FEE, "老同事约我明天下午去公园下棋"):
        await _check(ctx, elder, content)

    rows = await ctx.repos.list("health_records",
                                where={"elder_id": elder["id"],
                                       "record_type": "scam_check"})
    assert len(rows) == 3
    for row in rows:
        assert row["plain_summary"], "档案里那句话是给子女看的，不能是空的"
        assert row["content"]["verdict"] in {"high_risk", "normal", "unknown"}


async def test_the_offline_script_can_actually_reach_this_tool(ctx, run_turn):
    """离线跑一整轮：老人念短信 → 派给安康助手 → 真的调用了 check_scam。

    这一条钉的是可达性。工具注册了、判定写对了，但 MockLLM 的安康助手支线原来
    只会"查医院 → 挂号"，于是离线剧本里这个工具一次也到不了 —— 而断网兜底和
    ``scripts/demo_smoke.py`` 走的都是离线剧本。
    """
    _sid, events = await run_turn(_READ_OUT)

    called = [e.data["tool"] for e in events if e.event == "tool_call"]
    assert "check_scam" in called, f"离线剧本没走到反诈：{called}"

    results = [e.data for e in events
               if e.event == "tool_result" and e.data["tool"] == "check_scam"]
    assert len(results) == 1
    assert results[0]["ok"] is True
    # R4：健康域输出强制带免责声明，反诈判定也在其列
    assert "遵医嘱" in results[0]["summary"]
