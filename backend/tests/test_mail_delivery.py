"""邮件送达通道：子女知会的**跨设备**那一层。

这组用例守的是四件事，每一件都是"能不能在评委面前站住"级别的：

1. **两个通道说同一句话** —— 邮件正文必须与站内知会正文**逐字相同**。
   各写各的措辞，迟早会飘；子女在邮件里和 app 里读到两套说法，那时候该信哪个？
2. **投递失败不算失败** —— 挂号已经办完了。邮件发不出去（没配 SMTP、没留邮箱、
   服务器拒收）绝不能反过来把老人看病这件事回滚或抛异常。
3. **回执如实** —— ``ok``（这次投递被接受了没有）与 ``delivered``（真的投出去了没有）
   必须分开。演示模式下 delivered 永远是 False，因为那封邮件**没有交给任何
   邮件服务器**；把这两个字段混成一个，就是拿一句乐观话冒充送达。
4. **不重复打扰** —— 同一笔挂号再下一遍，不能给子女发第二封邮件。
"""
from __future__ import annotations

import pytest

from app.config import Settings
from app.core.context import TurnContext
from app.providers.external.mailer import (
    MockMailer, SmtpMailer, build_mailer,
)

APPOINTMENT = {"hospital": "南京鼓楼医院", "department": "骨科",
               "doctor": "邱勇", "fee": 70}


def _mailer(ctx) -> MockMailer:
    """取装配里那个邮件通道，并断言它就是离线版（默认配置下必须是）。"""
    mailer = ctx.registry.resolve("mail")
    assert isinstance(mailer, MockMailer), "默认配置下应当是离线 outbox，不联网"
    return mailer


# ---------------------------------------------------------------- 选实现

def test_default_configuration_yields_an_offline_outbox(tmp_path):
    """不配 SMTP 时是**离线 outbox**，不是"报错的真邮件"。

    评委的笔记本上没有 SMTP 凭据，这套东西必须能原样跑起来（与 LLM/ASR 同哲学）。
    """
    cfg = Settings(storage_backend="local", local_data_dir=str(tmp_path))
    mailer = build_mailer(cfg)
    assert isinstance(mailer, MockMailer)
    assert mailer.outbox_path is not None
    assert mailer.outbox_path.parent == tmp_path


def test_asking_for_smtp_without_a_host_still_degrades_quietly(tmp_path):
    """说了要 smtp、却没给主机名 —— 退回离线 outbox，**不抛异常**。

    配置写了一半是最常见的事。这时候抛出去，等于让一个笔误把整条知会链路打死。
    """
    cfg = Settings(mail_provider="smtp", smtp_host="",
                   storage_backend="local", local_data_dir=str(tmp_path))
    assert isinstance(build_mailer(cfg), MockMailer)


def test_smtp_is_chosen_only_when_actually_configured():
    cfg = Settings(mail_provider="smtp", smtp_host="smtp.example.com",
                   smtp_user="postmaster@example.com", smtp_password="not-a-real-secret",
                   smtp_from="kangle@example.com")
    mailer = build_mailer(cfg)
    assert isinstance(mailer, SmtpMailer)
    assert mailer.sender == "kangle@example.com"


# ---------------------------------------------------------------- 回执语义

async def test_offline_outbox_says_it_did_not_really_deliver(tmp_path):
    """离线 outbox 的回执必须**自己承认没送出去**。

    这是本文件存在的理由：一句"已通知子女"如果背后什么都没发生，
    那它比不通知更糟 —— 子女以为有人管，其实没有。
    """
    mailer = MockMailer(outbox_path=tmp_path / "outbox.jsonl")
    receipt = await mailer.send(to="liming@example.com",
                                subject="【就医知会】", body="正文")
    assert receipt["ok"] is True, "投递被接受了"
    assert receipt["delivered"] is False, "但**没有**真的交给任何邮件服务器"
    assert "演示模式" in receipt["reason"]
    # 落盘是给人看的证据：演示现场要能把邮件拿出来
    written = (tmp_path / "outbox.jsonl").read_text(encoding="utf-8")
    assert "liming@example.com" in written and "正文" in written


@pytest.mark.parametrize("bad", ["", "   ", "not-an-email", "a@b", "a@@b.com"])
async def test_a_broken_address_is_a_receipt_not_an_exception(tmp_path, bad):
    mailer = MockMailer(outbox_path=tmp_path / "outbox.jsonl")
    receipt = await mailer.send(to=bad, subject="s", body="b")
    assert receipt["ok"] is False and receipt["delivered"] is False
    assert "邮箱" in receipt["reason"]
    assert mailer.sent == [], "地址不合法就不该往 outbox 里记一条"


async def test_smtp_failure_returns_a_receipt_instead_of_raising(monkeypatch):
    """SMTP 挂了（连不上、认证失败、超时）→ 一条如实的失败回执，**不抛**。

    投递这一层一旦抛出去，异常会一路走到挂号成功之后的知会循环里，
    把一次**已经办成的挂号**变成一个失败 —— 那正是"送达失败卡住看病"。
    """
    mailer = SmtpMailer(host="smtp.example.com", user="u@example.com",
                        password="not-a-real-secret")

    def boom(*_a, **_kw):
        raise OSError("connection refused")

    monkeypatch.setattr(mailer, "_send_blocking", boom)
    receipt = await mailer.send(to="liming@example.com", subject="s", body="b")
    assert receipt["ok"] is False and receipt["delivered"] is False
    assert "SMTP 投递失败" in receipt["reason"]
    # 失败原因里**不许**带口令
    assert "not-a-real-secret" not in receipt["reason"]


async def test_smtp_without_a_host_refuses_up_front():
    receipt = await SmtpMailer(host="").send(to="a@b.com", subject="s", body="b")
    assert receipt["ok"] is False
    assert "SMTP_HOST" in receipt["reason"]


# ---------------------------------------------------------------- 接通挂号知会

async def _book(ctx, elder, **overrides):
    turn = TurnContext(ctx=ctx, session_id="s-mail", user=elder)
    args = dict(APPOINTMENT)
    args.update(overrides)
    return await ctx.dispatcher.execute(turn, "register_appointment", args)


async def test_the_email_carries_the_very_same_words_as_the_in_app_notice(
        ctx, elder, child):
    """**两个通道说同一句话** —— 逐字比对，不是"意思差不多"。

    这是本文件最重要的一条。邮件是兜底通道，站内是事实源；两者一旦各写各的，
    子女在邮件里读到"建议就医"、在 app 里读到"紧急"，他该信哪个？
    所以邮件只能**搬运**站内那条的 title/summary，一个字都不许自己组织。
    """
    result = await _book(ctx, elder)
    assert result["ok"] is True

    notices = await ctx.repos.list(
        "notifications", where={"user_id": child["id"], "type": "appointment_notice"})
    assert len(notices) == 1
    notice = notices[0]

    sent = _mailer(ctx).sent
    assert len(sent) == 1, "给一个子女就该发一封"
    assert sent[0]["to"] == child["email"]
    assert sent[0]["subject"] == notice["title"], "邮件标题必须是站内那条的标题"
    assert sent[0]["body"] == notice["summary"], "邮件正文必须是站内那条的正文"


async def test_the_receipt_is_written_back_so_delivery_is_visible(ctx, elder, child):
    """回执要写回那条知会里 —— "到底送出去没有"得能被看见。

    只写一句"已通知子女"而不留投递结果，等于让最该被追问的一件事没有痕迹。
    """
    await _book(ctx, elder)
    notices = await ctx.repos.list(
        "notifications", where={"user_id": child["id"], "type": "appointment_notice"})
    receipt = (notices[0].get("data") or {}).get("email")
    assert receipt, "知会的 data 里要挂着这次投递的回执"
    assert receipt["ok"] is True and receipt["delivered"] is False
    assert receipt["channel"] == "mock_mail"


async def test_a_child_without_an_email_still_gets_the_notice(ctx, elder, child):
    """子女没留邮箱：知会照写，回执如实说"这封没发出去"，全程不崩。

    没留邮箱是常态，不是错误。把"发不出去"当成失败，就会把一个健康的知会
    变成一次异常。
    """
    await ctx.repos.update("users", child["id"], {"email": ""})
    result = await _book(ctx, elder)
    assert result["ok"] is True

    notices = await ctx.repos.list(
        "notifications", where={"user_id": child["id"], "type": "appointment_notice"})
    assert len(notices) == 1, "站内知会与邮箱无关，照样要写"
    receipt = notices[0]["data"]["email"]
    assert receipt["ok"] is False and receipt["delivered"] is False
    assert "邮箱" in receipt["reason"]
    assert _mailer(ctx).sent == []


async def test_a_dead_mail_channel_cannot_break_a_booked_appointment(
        ctx, elder, child, monkeypatch):
    """邮件层整个炸掉（装配缺失、投递层违约抛异常）→ **挂号照样办成**。

    这条直接钉住"送达失败不能卡住看病"：挂号已经办完了，知会也写进库了，
    不能因为一封邮件发不出去就让老人白跑一趟。
    """
    mailer = _mailer(ctx)

    async def boom(**_kw):
        raise RuntimeError("mailer 违约抛异常")

    monkeypatch.setattr(mailer, "send", boom)
    result = await _book(ctx, elder)
    assert result["ok"] is True, "挂号必须照样办成"
    assert "知会" in result["summary"]

    notices = await ctx.repos.list(
        "notifications", where={"user_id": child["id"], "type": "appointment_notice"})
    assert len(notices) == 1, "站内知会不受邮件异常影响"
    receipt = notices[0]["data"]["email"]
    assert receipt["ok"] is False
    assert "投递异常" in receipt["reason"]


async def test_a_second_identical_appointment_does_not_mail_twice(ctx, elder, child):
    """同一笔挂号再下一遍，**不叠第二封邮件**。

    家人手机上同一件事出现两条，比不通知更糟 —— 他会以为老人挂了两次号。
    站内那条知会的幂等是按 registration_no 判的，邮件必须跟着同一个判据走。
    """
    await _book(ctx, elder)
    assert len(_mailer(ctx).sent) == 1

    await _book(ctx, elder)
    assert len(_mailer(ctx).sent) == 1, "重复挂号不该再发一封"
    notices = await ctx.repos.list(
        "notifications", where={"user_id": child["id"], "type": "appointment_notice"})
    assert len(notices) == 1
