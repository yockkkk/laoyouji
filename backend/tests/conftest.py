"""pytest 公共夹具：LocalFileRepo + MockLLM 的离线 AppContext。"""
from __future__ import annotations

import pytest

from app.bootstrap import build_context
from app.config import Settings
from app.core.context import TurnContext
from app.db.seed import seed_demo


@pytest.fixture()
async def ctx(tmp_path):
    cfg = Settings(
        llm_provider="mock",
        asr_provider="mock",
        storage_backend="local",
        local_data_dir=str(tmp_path / "data"),
        confirm_timeout_min=30,
    )
    context = build_context(cfg)
    result = await seed_demo(context.repos)
    context.demo = result
    return context


@pytest.fixture()
async def elder(ctx):
    return ctx.demo["elder"]


@pytest.fixture()
async def child(ctx):
    return ctx.demo["child"]


@pytest.fixture()
def run_turn(ctx, elder):
    """跑完一轮总智能体，返回 ``(session_id, SSE 事件列表)``。

    做成夹具而不是模块函数，是为了让每个测试文件都能直接用而不必互相 import。

    子智能体走 ``TurnContext.scoped()`` 派生，**队列是同一个** —— 所以这里收到的
    是全场动静：父的 ``delegate`` 和子的 ``search_*`` 都在里面，顺序就是前端看到的
    顺序。断言"父子两层都在"时靠的就是这一点。
    """
    async def _run(text: str, user: dict | None = None) -> tuple[str, list]:
        who = user or elder
        session = await ctx.event_log.create_session(who["id"], text[:12])
        turn = TurnContext(ctx=ctx, session_id=session["id"], user=who)
        await turn.emit("user_msg", {"text": text})
        final = await ctx.agents["main"].run(turn)
        await turn.emit("final", {"text": final})
        events = []
        while not turn.queue.empty():
            events.append(turn.queue.get_nowait())
        return session["id"], events

    return _run
