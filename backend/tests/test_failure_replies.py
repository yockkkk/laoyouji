"""兜底话术的回归测试。

为什么值得单独一个文件：这些句子在后端有两处、前端还有三处，改文案时只改了一处、
漏掉其余的，老人看到的还是旧话 —— 这次就是这么漏的（session.py 改了，
routes_chat.py 里那句"您再说一遍试试"还活着）。所以这里断言的不是"文案好不好看"，
而是**几处有没有对齐**、以及有没有踩那两个已知的坑：

① 不许承诺没在做的重试（"请稍等""我再想想"）—— 模型失败是直接收尾的，
   REQUEST_ERROR 瀑布上没挂任何重试中间件，说了老人就白等。
② 不许让老人立刻重说一遍（"再说一遍""没听清"）—— 接口挂着的时候重说还是挂，
   是个说不完的死循环；"没听清"还会让他以为是自己口音问题，越说越大声。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.core.session import BUDGET_REPLY, LLM_FAILED_REPLY, TURN_FAILED_REPLY

# 老人能看到/听到的兜底话术，全都要过这两道闸
ELDER_FACING = {
    "BUDGET_REPLY": BUDGET_REPLY,
    "LLM_FAILED_REPLY": LLM_FAILED_REPLY,
    "TURN_FAILED_REPLY": TURN_FAILED_REPLY,
}

# 坑 ①：承诺重试。真有重试中间件挂上来的那天，再来放宽这条。
FALSE_PROMISE = ("请稍等", "稍等一下", "重新想", "再想想", "正在重试", "马上就好")
# 坑 ②：把锅推给老人 / 催他立刻重说
BLAME_AND_LOOP = ("再说一遍", "没听清", "再说一次试试")
# 黑话
JARGON = ("token", "超时", "timeout", "500", "接口", "模型", "服务器", "异常", "报错")

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "laoyouji-app" / "src"


@pytest.mark.parametrize("name", sorted(ELDER_FACING))
def test_no_false_retry_promise(name):
    """别让老人等一句永远不会来的话。"""
    text = ELDER_FACING[name]
    hit = [w for w in FALSE_PROMISE if w in text]
    assert not hit, (
        f"{name} 里出现了 {hit}：模型失败这一步是直接 return 收尾的，"
        f"没有任何重试，说'稍等'老人就真的坐着等。原文：{text}"
    )


@pytest.mark.parametrize("name", sorted(ELDER_FACING))
def test_no_blame_or_dead_loop(name):
    """别把锅推给老人的口音，也别催他立刻重说（会死循环）。"""
    text = ELDER_FACING[name]
    hit = [w for w in BLAME_AND_LOOP if w in text]
    assert not hit, (
        f"{name} 里出现了 {hit}：接口挂着时重说一遍还是挂，是个说不完的死循环。"
        f"要给带间隔的动作（歇一会儿再说）。原文：{text}"
    )


@pytest.mark.parametrize("name", sorted(ELDER_FACING))
def test_no_jargon(name):
    text = ELDER_FACING[name]
    hit = [w for w in JARGON if w in text.lower()]
    assert not hit, f"{name} 里有黑话 {hit}，老人听不懂。原文：{text}"


@pytest.mark.parametrize("name", sorted(ELDER_FACING))
def test_says_whose_fault_and_gives_action(name):
    """明说是"我这边"的问题，并且给一条老人能做的事。"""
    text = ELDER_FACING[name]
    assert re.search(r"我(这边|这儿|先)", text), f"{name} 没说清是我们这边的问题：{text}"
    assert len(text) >= 12, f"{name} 太短，说不清楚：{text}"


@pytest.mark.asyncio
async def test_sse_error_event_uses_the_constant(ctx, elder, monkeypatch):
    """智能体整轮抛异常时，SSE 的 error 事件必须发常量，不是硬编码的旧话。

    这条就是冲着"改了 session.py、漏了 routes_chat.py"来的。
    """
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from app.api.deps import get_ctx
    from app.auth.security import create_access_token

    async def boom(*a, **kw):
        raise RuntimeError("故意炸的：模拟智能体整轮失败")

    monkeypatch.setattr(ctx.agents["main"], "run", boom)
    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        token = create_access_token(elder, ctx.settings)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.post("/api/chat/stream",
                             json={"text": "帮我买张去北京的票"},
                             headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            body = r.text

        # 找出 error 事件里那句话
        msgs = [json.loads(m)["message"]
                for m in re.findall(r"data:\s*(\{.*?\})\s*$", body, re.M)
                if '"message"' in m]
        assert TURN_FAILED_REPLY in msgs, (
            "SSE error 事件没发 TURN_FAILED_REPLY —— 大概率是 routes_chat.py 里"
            f"又硬编码了一句。实际发的是：{msgs}"
        )
        for bad in BLAME_AND_LOOP:
            assert not any(bad in m for m in msgs), f"error 事件里还有'{bad}'：{msgs}"
    finally:
        app.dependency_overrides.pop(get_ctx, None)


@pytest.mark.skipif(not FRONTEND.exists(), reason="没有前端源码目录")
def test_frontend_has_no_hardcoded_dead_loop_text():
    """前端也不许自己写一份"再说一遍"。

    后端文案改好了、前端还留着旧句子的话，老人看到的仍然是旧的 —— 前端那几处
    才是真正显示在屏幕上的。允许 LyjMic 例外：麦克风真没录上声音时，
    "再按住说一遍"是对的，重按一次确实能好，不构成死循环。
    """
    allowed = {"LyjMic.vue"}          # ASR 真没收到音，催他重按是对的
    offenders: list[str] = []
    for path in list(FRONTEND.rglob("*.vue")) + list(FRONTEND.rglob("*.js")):
        if path.name in allowed or path.name == "messages.js":
            continue
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("//")[0].split("*")[0]      # 注释里提这几个词没关系
            if any(w in code for w in ("再说一遍", "没听清")) and (
                    "'" in code or '"' in code):
                offenders.append(f"{path.relative_to(FRONTEND)}:{i}: {line.strip()}")
    assert not offenders, (
        "前端硬编码了死循环话术，请改成 import api/messages.js 里的常量：\n  "
        + "\n  ".join(offenders))
