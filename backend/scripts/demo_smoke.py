"""无前端全链路冒烟：旗舰场景（去北京看腿）从语音指令到计划书 + 子女批准出票，
再加一轮反诈判定 —— 剧本里承诺的加分项，离线也要真的走一遍。

用法：
    cd backend
    python scripts/demo_smoke.py            # 使用 .env（默认 mock/local，离线可跑）
    python scripts/demo_smoke.py --deepseek # 用真实 DeepSeek（需 .env 配 key）
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Windows 控制台默认 GBK，中文/emoji 输出强制 UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.bootstrap import build_context  # noqa: E402
from app.config import Settings, settings  # noqa: E402
from app.core.context import TurnContext  # noqa: E402
from app.db.seed import seed_demo  # noqa: E402


def header(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


async def main() -> None:
    cfg = settings
    if "--deepseek" in sys.argv:
        cfg = Settings(llm_provider="deepseek")
    ctx = build_context(cfg)
    header(f"老友记冒烟测试 llm={cfg.llm_provider} storage={cfg.storage_backend}")

    result = await seed_demo(ctx.repos)
    elder, child = result["elder"], result["child"]
    print(f"演示家庭：{elder['name']}（老人 · {elder.get('city', '')}）"
          f"— {child['name']}（儿子 · {child.get('city', '')}）")

    # ---------------------------------------------------------------- 老人发起旗舰指令
    header("第 1 步 · 老人对老友记说：我想去北京看腿疼的老毛病")
    session = await ctx.event_log.create_session(elder["id"], "去北京看病")
    turn = TurnContext(ctx=ctx, session_id=session["id"], user=elder)
    await turn.emit("user_msg", {"text": "我想去北京看腿疼的老毛病"})

    consumer_state: dict[str, Any] = {"cards": [], "reports": []}

    async def consume() -> None:
        """把 SSE 线格式原样打在终端上 —— 这份输出就是"没有前端时的前端"。

        事件名按 core/events.py 的线格式（下划线那一套）。原来这里筛的是
        ``plan``，那个事件在新内核里已经不存在了（改成 ``todo`` 整表快照），
        于是步骤条和子 Agent 回报两样最该看见的东西一条都不打印。
        """
        while True:
            ev = await turn.queue.get()
            data = ev.data or {}
            if ev.event == "delta":
                print(data.get("text", ""), end="", flush=True)
                continue

            if ev.event == "todo":
                # 真进度：整表覆盖写。打成一行，看得出哪一步在跑
                p = data.get("progress") or {}
                marks = {"pending": "·", "in_progress": "→", "completed": "✓"}
                items = " ".join(
                    f"{marks.get(t.get('status'), '?')}{t.get('content', '')}"
                    for t in data.get("todos") or [])
                print(f"\n  [todo {p.get('done', 0)}/{p.get('total', 0)}] {items}")
            elif ev.event == "report":
                # 子 Agent 的结构化回报 —— "真多智能体"在终端里唯一看得见的证据
                consumer_state["reports"].append(data)
                miss = data.get("missing") or []
                print(f"\n  [report {data.get('agent')}] ok={data.get('ok')} "
                      f"字段={sorted((data.get('data') or {}).keys())}"
                      f"{' 缺=' + str(miss) if miss else ''}")
            elif ev.event == "card":
                consumer_state["cards"].append(data)
                pages = data.get("pages") or []
                print(f"\n  [card {data.get('type')}] {data.get('title')} "
                      f"（{len(pages)} 页，complete={data.get('complete')}）")
                for page in pages:
                    filled = sum(1 for r in page.get("rows") or []
                                 if not r.get("missing"))
                    print(f"      {page.get('title')} — {filled}/"
                          f"{len(page.get('rows') or [])} 项已填")
                if data.get("footnote"):
                    print(f"      脚注：{data['footnote']}")
            elif ev.event in ("tool_call", "tool_result", "suspended",
                              "agent_status", "agent_msg", "guardian_alert"):
                text = data.get("summary") or data.get("text") or data.get("message") or ""
                print(f"\n  [{ev.event}] {str(text)[:120]}")
            elif ev.event == "error":
                print(f"\n  [error] {data.get('message', '')}")
            elif ev.event == "final":
                print(f"\n  [final] {str(data.get('text', ''))[:200]}")

    consumer = asyncio.create_task(consume())
    final = await ctx.agents["main"].run(turn)
    await turn.emit("final", {"text": final})
    await asyncio.sleep(0.3)
    consumer.cancel()

    # ---------------------------------------------------------------- 子女端确认
    header("第 2 步 · 子女端待确认列表")
    pending = await ctx.confirmation.list_for_child(child["id"], status="pending")
    for task in pending:
        print(f"  - {task['summary_for_child']['summary']}（{task['amount']}元，"
              f"{task['status']}）")
    assert pending, "应有待确认任务"

    header("第 3 步 · 子女逐项批准 → 冻结调用重放执行")
    for task in pending:
        r = await ctx.confirmation.approve_and_execute(task["id"], ctx, child["id"])
        announce = r["result"].get("announce") or r["result"].get("summary", "")
        print(f"  [{r['status']}] {announce[:120]}")

    # ---------------------------------------------------------------- 行程守护
    header("第 4 步 · 行程守护（模拟位置上报）")
    trips = await ctx.repos.list("trips", where={"elder_id": elder["id"]},
                                 order="-created_at", limit=1)
    if trips:
        trip_id = trips[0]["id"]
        from app.api.routes_guardian import CheckpointIn, process_checkpoint

        for location in ("南京南站", "济南西站", "徐州某个陌生地方"):
            resp = await process_checkpoint(ctx, trip_id, CheckpointIn(location=location))
            print(f"  上报 {location} → {resp['status']}"
                  f"{'（已告警子女端）' if resp['alert_sent'] else ''}")

    # ---------------------------------------------------------------- 反诈判定
    header("第 5 步 · 反诈：老人把收到的短信念给老友记")
    # 这一步是给"全部翻车"预案用的：加分项里的反诈演示不能只在联网时成立。
    # 走的是完整一轮（总智能体 → 安康助手 → check_scam），不是直接调工具 ——
    # 派发这一段本身就是被冒烟的对象。
    scam_text = "我收到一条短信，说是我孙子，手机摔坏了急用钱，让我先转到一个账户"
    scam_session = await ctx.event_log.create_session(elder["id"], "反诈检查")
    scam_turn = TurnContext(ctx=ctx, session_id=scam_session["id"], user=elder)
    await scam_turn.emit("user_msg", {"text": scam_text})
    scam_final = await ctx.agents["main"].run(scam_turn)
    print(f"  老人念：{scam_text}")
    while not scam_turn.queue.empty():
        ev = scam_turn.queue.get_nowait()
        data = ev.data or {}
        if ev.event in ("tool_call", "tool_result"):
            print(f"  [{ev.event} {data.get('tool')}] "
                  f"{str(data.get('summary') or '')[:120]}")
    print(f"  [final] {scam_final[:160]}")
    checks = await ctx.repos.list("health_records",
                                  where={"elder_id": elder["id"],
                                         "record_type": "scam_check"})
    print(f"  健康档案里的反诈记录 {len(checks)} 条"
          f"（判定：{[c['content'].get('verdict') for c in checks]}）")
    # 这一轮自己的事件也要落库：write-behind 是按会话缓冲的，只 flush 旗舰那条
    # 会话，反诈这一轮就永远停在内存里 —— 而"能事后回放"是这套日志的全部意义。
    print(f"  本轮落库 {await ctx.event_log.flush(scam_session['id'])} 条")

    # ---------------------------------------------------------------- 收尾
    header("第 6 步 · 会话事件日志（审计回放）")
    events = await ctx.event_log.recent(session["id"], limit=200)
    types: dict[str, int] = {}
    for ev in events:
        types[ev["type"]] = types.get(ev["type"], 0) + 1
    print(f"  内存事件 {len(events)} 条：{types}")

    # 写后缓冲落库 —— "事件已记录"和"事件已入库"是两件事，这一步把窗口关上。
    # recent() 读的是内存，所以上面那个数字不证明落库；这个数字才证明。
    written = await ctx.event_log.flush(session["id"])
    print(f"  落库 {written} 条（write-behind 缓冲已清空）")

    cards, reports = consumer_state["cards"], consumer_state["reports"]
    print(f"  子 Agent 回报 {len(reports)} 条 · 交付卡片 {len(cards)} 张")
    for card in cards:
        miss = card.get("missing") or []
        print(f"    {card.get('title')}：{len(card.get('pages') or [])} 页"
              f"{'，待补 ' + str(len(miss)) + ' 项' if miss else '，字段齐全'}")

    print("\n冒烟测试通过 ✅  （完整流程：模糊指令→规划→子智能体调度"
          "→高危拦截→子女确认→计划书→守护告警→反诈判定）")


if __name__ == "__main__":
    asyncio.run(main())
