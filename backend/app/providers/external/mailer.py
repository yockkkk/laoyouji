"""告警/知会的**跨设备送达**通道 —— 邮件。

为什么是邮件，而不是推送或短信：

康乐的 App 是一个 WebView 壳（服务器端 aapt+d8+apksigner 打包，见部署文档），
**app 一关就没有后台、没有定时、没有推送通道**。而"子女要及时知道老人去就医了"
这件事的本质是**跨设备传递** —— 信息必须经网络落到子女的**另一台**手机上，
老人这台机器关不关都改变不了这一点。厂商离线推送需要企业资质（平台决策②：不做），
短信需要签名报备。**SMTP 邮件是唯一零资质、真送达、且与 app 开关无关的通道**，
所以由它兜这个底。

与其它 provider 同一套写法：Mock 版不联网、把邮件原样收进本地 outbox（离线可测、
演示可看），Real 版走 SMTP。**没配 SMTP 不是报错，是降级**：如实返回"没发出去"
和原因，挂号与站内知会照常完成 —— 送达失败绝不能反过来把老人看病这件事卡住。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)

OUTBOX_NAME = "mail_outbox.jsonl"


def _valid_address(to: str) -> bool:
    """够用的收件人校验：有且只有一个 @，两边都非空。

    不追求 RFC 5322 完备 —— 这里的用途是"别把邮件发给一个空串"，
    真正的合法性由 SMTP 服务器说了算。
    """
    to = (to or "").strip()
    if to.count("@") != 1:
        return False
    local, _, domain = to.partition("@")
    return bool(local and domain and "." in domain)


class Mailer:
    """邮件投递协议。实现必须**只返回结果、不抛异常**（失败也是一种结果）。"""

    name = ""

    async def send(self, *, to: str, subject: str, body: str) -> dict:
        """投递一封邮件，返回投递回执。

        回执字段：
        - ``ok``：本次调用是否被**接受**（配置齐全、地址合法、SMTP 没报错）
        - ``delivered``：是否**真的投出去了**。mock 永远是 False —— 演示模式
          没有把邮件交给任何邮件服务器，这两个字段必须分开，否则"发出去了"
          这句话会变成一句谎
        - ``channel`` / ``reason``：谁送的、为什么没送成
        """
        raise NotImplementedError


class MockMailer(Mailer):
    """离线邮件：不联网，把邮件原样收进内存与本地 outbox。

    保留 ``sent`` 列表是为了让测试直接断言"发了什么给谁"，不用去读磁盘；
    落盘是为了演示现场能**把邮件拿出来给人看** —— 一个只在内存里的
    "已通知子女"是没法证明的。
    """

    name = "mock_mail"

    def __init__(self, outbox_path: str | os.PathLike | None = None):
        self.outbox_path = Path(outbox_path) if outbox_path else None
        self.sent: list[dict] = []

    async def send(self, *, to: str, subject: str, body: str) -> dict:
        if not _valid_address(to):
            return {"ok": False, "delivered": False, "channel": self.name,
                    "reason": "子女账号没留可用的邮箱地址"}
        record = {"to": to.strip(), "subject": subject, "body": body,
                  "channel": self.name}
        self.sent.append(record)
        self._persist(record)
        return {"ok": True, "delivered": False, "channel": self.name,
                "reason": "演示模式：邮件未交给邮件服务器，已收进本地 outbox"}

    def _persist(self, record: dict) -> None:
        """落盘是**尽力而为**：写不进去不该让"知会子女"这件事失败。

        outbox 只是给人看的证据，不是事实源 —— 站内知会已经写进库了。
        """
        if not self.outbox_path:
            return
        try:
            self.outbox_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.outbox_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as err:                       # noqa: BLE001
            logger.warning("mail outbox 落盘失败（不影响知会）: %s", err)


class SmtpMailer(Mailer):
    """真投递：SMTP（465 隐式 SSL / 其它端口 STARTTLS）。

    ``smtplib`` 是阻塞 IO，放进线程跑，别把事件循环堵住 —— 一次超时十秒，
    堵住的话整轮对话都停在那儿。
    """

    name = "smtp_mail"

    def __init__(self, host: str, port: int = 465, user: str = "",
                 password: str = "", sender: str = "", use_ssl: bool = True,
                 timeout_s: float = 10.0):
        self.host = (host or "").strip()
        self.port = int(port)
        self.user = user or ""
        self.password = password or ""
        self.sender = (sender or user or "").strip()
        self.use_ssl = bool(use_ssl)
        self.timeout_s = float(timeout_s)

    async def send(self, *, to: str, subject: str, body: str) -> dict:
        if not self.host:
            return {"ok": False, "delivered": False, "channel": self.name,
                    "reason": "没配 SMTP_HOST，邮件通道未启用"}
        if not _valid_address(to):
            return {"ok": False, "delivered": False, "channel": self.name,
                    "reason": "子女账号没留可用的邮箱地址"}
        try:
            await asyncio.to_thread(self._send_blocking, to.strip(), subject, body)
        except Exception as err:                       # noqa: BLE001
            # 异常文本可能带主机名与响应码，但**不带口令**（smtplib 不会把它放进异常）
            logger.warning("SMTP 投递失败: %s", err)
            return {"ok": False, "delivered": False, "channel": self.name,
                    "reason": f"SMTP 投递失败：{type(err).__name__}"}
        return {"ok": True, "delivered": True, "channel": self.name, "reason": ""}

    def _send_blocking(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body, charset="utf-8")
        if self.use_ssl:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout_s) as smtp:
                if self.user:
                    smtp.login(self.user, self.password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout_s) as smtp:
                smtp.starttls()
                if self.user:
                    smtp.login(self.user, self.password)
                smtp.send_message(msg)


def build_mailer(cfg) -> Mailer:
    """按配置选实现。**配不全就退回 mock，不抛异常** —— 与 LLM/ASR 同哲学：
    缺 key 的环境（比如评委的笔记本）必须能原样跑起来。
    """
    provider = (getattr(cfg, "mail_provider", "mock") or "mock").lower()
    host = getattr(cfg, "smtp_host", "") or ""
    if provider == "smtp" and host:
        return SmtpMailer(
            host=host,
            port=getattr(cfg, "smtp_port", 465),
            user=getattr(cfg, "smtp_user", ""),
            password=getattr(cfg, "smtp_password", ""),
            sender=getattr(cfg, "smtp_from", ""),
            use_ssl=getattr(cfg, "smtp_use_ssl", True),
            timeout_s=getattr(cfg, "smtp_timeout_s", 10.0),
        )
    outbox = Path(getattr(cfg, "local_data_dir", ".")) / OUTBOX_NAME
    return MockMailer(outbox_path=outbox)
