"""会话失效后不许"静悄悄没反应"的回归测试。

这个坑是真的踩到脸上的：演示前我重新灌了一次种子数据（TRUNCATE 整表），
老人端页面里还存着灌库之前的 session_id（它落在 localStorage 里，刷新也带回来）。
于是老人说了一句"我要去北京看腿"，然后：

1. ``POST /api/chat/stream`` 拿着那个死会话 -> 404 会话不存在；
2. 前端 SSE 失败自动退到 ``GET /api/sessions/{id}/events`` 轮询兜底；
3. 那个接口对不存在的会话回的是 **200 + 空列表** —— 在前端看来就是
   "还没轮到我，再等等"，于是空转 60 轮 x 2 秒；
4. 两分钟后轮询循环自然结束，调 ``onDone``，而 chat.vue 里 onDone 是个空函数。

结果：老人盯着"处理中"转两分钟，然后它不转了，**一句话都没有**。
没有报错、没有提示、没有回复 —— 这是最糟的一种失败。

所以这里钉三件事：
① 不存在的会话，轮询接口必须 404（让前端立刻知道"没了"，而不是"再等等"）；
② 存在的会话照旧 200（别把正常的断线恢复一起毒死）；
③ 前端 sse.js 不许把轮询结果丢掉 —— 没等到 final 就必须说话。
"""
from __future__ import annotations

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "laoyouji-app" / "src"


async def _get(ctx, path: str, user: dict):
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_ctx
    from app.auth.security import create_access_token
    from app.main import app

    app.dependency_overrides[get_ctx] = lambda: ctx
    try:
        headers = {"Authorization":
                   "Bearer " + create_access_token(user, ctx.settings)}
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path, headers=headers)
    finally:
        app.dependency_overrides.clear()


async def test_polling_a_vanished_session_404s_instead_of_looking_idle(ctx, elder):
    """不存在的会话要 404。

    回 200 + 空列表的话，前端分不清"这个会话没了"和"轮次还没产出"，
    只能一直等 —— 这就是老人干等两分钟的根。
    """
    gone = "8f14e45f-ceea-467a-9c1e-000000000000"
    res = await _get(ctx, f"/api/sessions/{gone}/events?after_seq=0", elder)

    assert res.status_code == 404, (
        f"不存在的会话回了 {res.status_code}：{res.text}。"
        " 回 200+空列表前端就会空转两分钟然后一句话不说"
    )


async def test_polling_a_real_session_still_works(ctx, elder, run_turn):
    """别为了修上面那条，把正常的断线恢复一起弄坏。"""
    sid, _ = await run_turn("我要去北京看腿")

    res = await _get(ctx, f"/api/sessions/{sid}/events?after_seq=0", elder)

    assert res.status_code == 200, f"正常会话被误伤：{res.status_code} {res.text}"
    items = res.json()["items"]
    assert items, "正常会话应该有事件，拿到空列表说明轮询恢复也废了"


def test_frontend_does_not_discard_the_polling_result():
    """``pollEvents`` 的返回值必须被用上。

    它返回"有没有等到 final"。原来 chatStream 里是 ``await pollEvents(...)``
    —— 返回值直接扔掉，没等到结果也当成功收场，老人什么都看不到。
    """
    sse = (FRONTEND / "api" / "sse.js").read_text(encoding="utf-8")

    assert not re.search(r"^\s*await pollEvents\(", sse, re.M), (
        "sse.js 里 pollEvents 的返回值被丢掉了：没等到 final 也会静悄悄收场，"
        "老人只看到'处理中'转完然后没有任何回应"
    )
    assert "reachedFinal" in sse, "应当接住 pollEvents 的返回值并在没等到时报错"


def test_frontend_recovers_from_a_vanished_session():
    """会话没了要能自愈：另开一段 + 把老人那句原样重发，别让他重复劳动。"""
    sse = (FRONTEND / "api" / "sse.js").read_text(encoding="utf-8")
    chat = (FRONTEND / "pages" / "elder" / "chat.vue").read_text(encoding="utf-8")

    assert "sessionGone" in sse, "sse.js 要能把 404（会话没了）单独标出来"
    assert "onSessionGone" in chat, "chat.vue 要接住会话作废并自愈"
    assert "_recoverSession" in chat, "自愈得真的另开一段新会话"
    # 进页面时历史拉不动，那个死 id 必须扔掉，否则第一句话又打到死会话上
    assert "removeStorageSync('laoyouji_elder_session_id')" in chat, (
        "历史拉不动时要把存着的死 session_id 删掉，"
        "否则界面看着正常、老人第一句话就掉进同一个坑"
    )
