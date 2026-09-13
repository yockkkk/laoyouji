"""康乐全链路冒烟（无前端）：装配自检 → 就医闭环（分诊→挂号→知会子女）→
四页就医出行计划书 → 反向链（保健档不去医院）。离线可跑。

**它取代了旧版"去北京看腿 + 子女批准出票 + 反诈"那一份。** 旧链对应的三样东西
在产品收敛后整条不存在了：跨城车票/机票/异地酒店砍了（康乐只做本市就近就医）、
就医审批砍了（挂号当场办好、同一步给子女写一条知会）、反诈与付费不在范围内。
照着旧脚本彩排会当场翻车 —— 它在第 2 步断言"应有待确认任务"，而真实库里一条都没有。

现在冒烟按**八步**跑（**53 条断言**，实跑打印 56 个 ✅ —— 多出来的 3 个是脚本运行时
补打的信息行），每一步都对应 DEMO_SCRIPT.md 里会当众念的一句：

  第 1 步 装配自检          —— 工具数 / Agent 数，台上要念的数字先自己数一遍
  第 2 步 演示数据复位      —— 切到默认档 hypertension_spike（相对"今天"生成）
  第 3 步 旗舰链            —— 就医出行 → 四页计划书（标题带姓名、页序齐全、脚注披露）
  第 4 步 幂等              —— 同一笔挂号 / 同一份计划书重复下一遍，不叠第二张卡
  第 5 步 报数 178/105      —— 真分诊到「建议就医」→ 真挂号 → 一条知会落到子女端
                             （知会还**再走一遍邮件**——跨设备兜底，回执如实记着送没送到）
  第 6 步 0 张挂起卡        —— ``confirmation_tasks`` 表是空的（就医不需要子女审批）
  第 7 步 会话事件日志      —— 三个会话都落了库、可事后回放（审计）
  第 8 步 反向链 138/86     —— 保健档**不去医院**（康乐最想证明的一件事）

> 数字口径：数一下 `check(` 出现在**行首缩进处**的次数，就是断言条数（现 53 条）。
> 直接搜 `check(` 会多出两条：`def check(` 本身的定义，以及本段引用的这行文字。
> （这里刻意不写那条正则 —— 它不是 raw 字符串，反斜杠转义会被 Python 当成无效转义并告警。）
> 改脚本时**别只改这里**，台上以脚本当场跑出来的为准。
>
> **两种存储都必须跑一遍**（`STORAGE_BACKEND=mariadb` 与 `=local`）。这一步不是洁癖：
> 不带 `order=` 的 `repos.list` 在两种存储上返回顺序并不一样（local 是文件序，
> MariaDB 那条 SELECT 压根不发 ORDER BY），脚本里凡是靠"取最后一条"找新行的写法，
> 都只会在其中一种存储上对。实测挂过一次：local 全绿、MariaDB 挂在第 5 步。
> 产品代码自己不依赖这个序，所以那一次是**脚本的毛病**——但验收脚本挂了，台上一样难看。

用法：
    cd backend
    # 全离线（不需要外网，也不需要数据库服务）
    STORAGE_BACKEND=local LLM_PROVIDER=mock ./.venv/Scripts/python.exe -X utf8 scripts/demo_smoke.py
    # 走 .env 里配的存储（LLM 默认仍是 mock）
    ./.venv/Scripts/python.exe -X utf8 scripts/demo_smoke.py
    # 真 DeepSeek（需 .env 配 key）
    ./.venv/Scripts/python.exe -X utf8 scripts/demo_smoke.py --deepseek
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
from app.db.seed import seed_demo, seed_kangle_persona  # noqa: E402

# 旗舰指令：**本地**就近就医。旧稿那句"我想去北京看腿疼的老毛病"不能再用了 ——
# 跨城就医已经砍掉，而离线剧本会把"北京"当成目的地，整条链就演成"去北京挂号"。
FLAGSHIP = "我想在南京就近看腿疼的老毛病"

# 报数链。**必须是 "178/105" 这种写法**：离线剧本 `_vital_in` 的血压正则是
# ``(\d{2,3})\s*/\s*(\d{2,3})``，只认带斜杠的读数。"高压 178 低压 105" 那种说法
# 它认不出来 —— 会跳过 log_vital/assess_health 直接去挂号（**没有分诊**）。
# 这是 mock 剧本的已知边界，写在这里免得彩排时换一句话就翻车。
SPIKE_READING = "帮我记一下血压，178/105"
# 反向链：同一套工具、同一段分诊代码，喂进平稳的数就该"不用特意跑医院"
CALM_READING = "帮我记一下血压，138/86"

# 计划书页序（``agents/plan_builder.py`` 的 build_medical_trip_plan 写死四页）。
# 少一页、多一页都要红：页数是最容易被"改模板忘了改文档"悄悄带走的东西。
EXPECT_PAGES = ["第一页 · 挂号信息", "第二页 · 怎么去医院",
                "第三页 · 随身清单", "第四页 · 南京天气与穿衣"]
# 分诊档位挂在子回报的哪个字段下（工具自己的 report_key，见 health_tools 注册处）
_TRIAGE_KEYS = ("assessment", "vital_logged", "health_summary")


def header(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def check(cond: Any, msg: str) -> None:
    """一条断言一行输出。**不吞异常**：对不上就抛，退出码非 0 才算失败。"""
    if not cond:
        raise AssertionError(msg)
    print(f"  ✅ {msg}")


# ------------------------------------------------------------------ SSE 消费

class Wire:
    """把 SSE 线格式原样打在终端上 —— 这份输出就是"没有前端时的前端"。

    事件名按 core/events.py 的线格式（下划线那一套）。三样最该看见的东西各有专门
    的打印：``todo``（步骤条整表快照）、``report``（子 Agent 的结构化回报）、
    ``card``（交付物）。它们是"真多智能体"在终端里唯一看得见的证据。
    """

    def __init__(self) -> None:
        self.cards: list[dict] = []
        self.reports: list[dict] = []
        self.todos: list[dict] = []

    async def consume(self, turn: TurnContext) -> None:
        while True:
            ev = await turn.queue.get()
            data = ev.data or {}
            if ev.event == "delta":
                print(data.get("text", ""), end="", flush=True)
                continue
            if ev.event == "todo":
                self.todos.append(data)
                p = data.get("progress") or {}
                marks = {"pending": "·", "in_progress": "→", "completed": "✓"}
                items = " ".join(
                    f"{marks.get(t.get('status'), '?')}{t.get('content', '')}"
                    for t in data.get("todos") or [])
                print(f"\n  [todo {p.get('done', 0)}/{p.get('total', 0)}] {items}")
            elif ev.event == "report":
                self.reports.append(data)
                miss = data.get("missing") or []
                print(f"\n  [report {data.get('agent')}] ok={data.get('ok')} "
                      f"字段={sorted((data.get('data') or {}).keys())}"
                      f"{' 缺=' + str(miss) if miss else ''}")
            elif ev.event == "card":
                self.cards.append(data)
                self._print_card(data)
            elif ev.event in ("tool_call", "tool_result", "suspended",
                              "agent_status", "agent_msg", "guardian_alert"):
                text = data.get("summary") or data.get("text") or data.get("message") or ""
                print(f"\n  [{ev.event}] {str(text)[:120]}")
            elif ev.event == "error":
                print(f"\n  [error] {data.get('message', '')}")
            elif ev.event == "final":
                print(f"\n  [final] {str(data.get('text', ''))[:200]}")

    @staticmethod
    def _print_card(data: dict) -> None:
        pages = data.get("pages") or []
        print(f"\n  [card {data.get('type')}] {data.get('title')} "
              f"（{len(pages)} 页，complete={data.get('complete')}）")
        for page in pages:
            rows = page.get("rows") or []
            title = page.get("title") or ""
            if rows:
                filled = sum(1 for r in rows if not r.get("missing"))
                print(f"      {title} — {filled}/{len(rows)} 项已填")
            else:
                print(f"      {title}")
        if data.get("footnote"):
            print(f"      脚注：{data['footnote']}")

    def card_of(self, ctype: str) -> dict | None:
        return next((c for c in self.cards if c.get("type") == ctype), None)

    def plan_card(self) -> dict | None:
        """就医出行计划书那张卡（``trip_plan`` 或 ``medical_plan``）。

        **不是一个字面量**。``compose_deliverable`` 的 ``kind`` 是模型给的，而
        ``main_agent._KIND_ALIASES`` 把 ``trip_plan``／``medical_plan``（以及中文的
        "就医计划""出行计划书"等）收成**两个**并列的合法类型，两者都会被渲染成那份
        四页计划书 —— 前端也是两边都认的（``chat.vue`` 的 ``compact`` 判断、
        ``dashboard.vue`` 的 ``isMedical()`` 徽标）。所以这一条要问的是"计划书卡在
        不在"，不是"模型这次恰好报了哪个近义词"。钉死一个，等于把一条**完全正确**
        的运行判红：实测真 DeepSeek 下就报过 ``medical_plan``，脚本当场上不去台。
        """
        return self.card_of("trip_plan") or self.card_of("medical_plan")

    def triage_levels(self) -> list[str]:
        """子回报里的分诊档位。**取结构化字段**，不从中文摘要里猜。

        档位挂在工具自己的 report_key 下面（``assessment`` / ``vital_logged``），
        不是回报的顶层 —— 顶层只有 ``agent/ok/summary/data``。
        """
        out: list[str] = []
        for report in self.reports:
            data = report.get("data") or {}
            for key in _TRIAGE_KEYS:
                node = data.get(key)
                if isinstance(node, dict) and node.get("level"):
                    out.append(str(node["level"]))
        return out


async def run_turn(ctx, user: dict, title: str, text: str) -> tuple[str, Wire]:
    """跑一整轮：建会话 → 推用户原话 → 跑总智能体 → 把线格式打出来。"""
    session = await ctx.event_log.create_session(user["id"], title)
    turn = TurnContext(ctx=ctx, session_id=session["id"], user=user)
    await turn.emit("user_msg", {"text": text})
    wire = Wire()
    consumer = asyncio.create_task(wire.consume(turn))
    final = await ctx.agents["main"].run(turn)
    await turn.emit("final", {"text": final})
    await asyncio.sleep(0.3)
    consumer.cancel()
    # 这一轮自己的事件也要落库：write-behind 是按会话缓冲的，不 flush 就永远停在
    # 内存里 —— 而"能事后回放"是这套日志的全部意义。
    written = await ctx.event_log.flush(session["id"])
    print(f"\n  [flush] 本轮落库 {written} 条事件")
    return final, wire


# ------------------------------------------------------------------ 库存查询

async def appointments(ctx, elder_id: str) -> list[dict]:
    return await ctx.repos.list(
        "health_records", where={"elder_id": elder_id, "record_type": "appointment"})


async def notices(ctx, child_id: str) -> list[dict]:
    return await ctx.repos.list(
        "notifications", where={"user_id": child_id, "type": "appointment_notice"})


# ------------------------------------------------------------------ 各步

async def step_flagship(ctx, elder: dict, child: dict) -> dict:
    """旗舰链：就医出行 → 四页计划书 + 挂号卡 + 一条知会。"""
    header(f"第 3 步 · 旗舰链：{FLAGSHIP}")
    final, wire = await run_turn(ctx, elder, "就医出行", FLAGSHIP)
    print(f"\n  老人听到：{final}")

    # 步骤条：每一波调度推一次整表快照（todo_write 每次重写整张表）。
    # ⚠ 最后一波**只把第四项标到 in_progress**（离线剧本 mock.py 的收口那一波），
    # 所以收口时步骤条停在 3/4、第四项一直转 —— 前端 AgentExecutionTree 上看得见。
    # 这是产品侧的小瑕疵（要改的是 app/providers/llm/mock.py，不是本脚本）。
    #
    # 这条**刻意是"至少"**：它要证的性质是"后端每一波都推整表快照，不是前端按工具
    # 调用猜的"—— 那是次数下界，多推一波不该判失败。措辞与断言口径一致（都写"至少"）。
    # 真正靠等值挡住回归的是第 4 步的幂等那两条，见下面。
    check(len(wire.todos) >= 3,
          f"步骤条至少推过 3 次整表快照（实测 {len(wire.todos)} 次，不是前端按工具调用猜的）")
    last = (wire.todos[-1].get("todos") if wire.todos else []) or []
    done = [t.get("content") for t in last if t.get("status") == "completed"]
    print(f"      收口快照：{[(t.get('status'), t.get('content')) for t in last]}")
    check(len(last) == 4,
          f"待办清单是四项（挂号 / 天气 / 路线 / 计划书），实测 {len(last)} 项")
    # 断言的是"这份档案该有的样子"，不是"当前缺陷长什么样"。
    # 原来这里写的是 `len(last) == 4 and len(done) == 3` —— 把 mock 收口那一波没标完成
    # 的**已知瑕疵**钉成了期望值：谁真去 app/providers/llm/mock.py 把第四项标上 completed，
    # 这条就会变红，把"修好了"判成"失败了"。那是反向的断言。
    # 现在只钉"前三项（挂号/天气/路线）确实推完了"这一件稳定事实；第四项的状态属于
    # 已知可以变好的部分，它变好时下面那句 ⚠ 自然消失，不需要改断言。
    check(all(t.get("status") == "completed" for t in last[:3]),
          f"前三项都已 completed（实测 {len(done)}/{len(last)} 项完成）")
    stuck = [t.get("content") for t in last if t.get("status") != "completed"]
    if stuck:
        print(f"      ⚠ 还有 {len(stuck)} 项没标完成：{stuck}")
        print("        mock 收口那一波漏标（改点在 app/providers/llm/mock.py，不是本脚本），"
              "前端步骤条会停在三格 —— 已知小瑕疵，如实打 ⚠，不算本步失败。")
    else:
        print("      ✅ 四项全部 completed")


    # 子智能体回报 —— 界面上唯一看得见的扇出证据（挂号 ‖ 天气，再规划路线）
    agents_seen = {r.get("agent") for r in wire.reports}
    print(f"  子 Agent 回报 {len(wire.reports)} 条：{sorted(agents_seen)}")
    check({"health", "travel"} <= agents_seen,
          f"安康助手与银发导航都回报过（真扇出，不是串行代办）：{sorted(agents_seen)}")

    # 挂号卡：**绿的**，就医不需要谁点头
    card = wire.card_of("appointment")
    check(card is not None, "挂号卡出现在老人端（type=appointment）")
    if card:
        check(card.get("title") == "专家号已预约", f"挂号卡标题：{card.get('title')}")
        body = card.get("body") or {}
        print(f"      挂号卡：{body}")
        told = str(body.get("家人知会") or "")
        check("已告诉" in told and "等待" not in told and "确认" not in told,
              f"「家人知会」那行是「{told}」—— 是知会，不是「等家人确认」")

    plan = wire.plan_card()
    check(plan is not None,
          "计划书卡片出现在老人端（type=trip_plan 或 medical_plan —— kind 由模型给，两个都合法）")
    if not plan:
        return {"plan_pages": 0}
    print(f"      计划书卡类型：{plan.get('type')}")
    title = plan.get("title") or ""
    print(f"      计划书标题：{title}")
    check("张桂芳" in title, "计划书标题带老人姓名（取自记录，不是模型印象）")
    check("就医出行计划书" in title, "标题写明「就医出行计划书」")
    check("南京" in title, f"目的地是本地：{title}（跨城那套已砍，康乐只做本市就医）")

    headings = [p.get("title") or "" for p in plan.get("pages") or []]
    print(f"      页标题：{' / '.join(headings)}")
    check(len(headings) == 4, f"共 4 页（实测 {len(headings)} 页）")
    missing = [w for w in EXPECT_PAGES if not any(w in h for h in headings)]
    check(not missing, f"四页齐全且页序一致：{' / '.join(headings)}")
    for page in plan.get("pages") or []:
        rows = page.get("rows") or []
        todo = [r.get("label") for r in rows if r.get("missing")]
        print(f"      {page.get('title')}：{len(rows) - len(todo)}/{len(rows)} 项已填"
              f"{'  待补=' + str(todo) if todo else ''}")

    footnote = plan.get("footnote") or ""
    print(f"      脚注：{footnote}")
    check("模拟接口" in footnote, "脚注披露了模拟数据（合规要求，不是装饰）")

    # 交付物与知会落库
    check(len(await appointments(ctx, elder["id"])) == 1,
          "真挂号 1 条落库（health_records.record_type=appointment）")
    check(len(await notices(ctx, child["id"])) == 1, "子女端收到 1 条知会")
    trips = await ctx.repos.list("trips", where={"elder_id": elder["id"]})
    check(len(trips) == 1, f"计划书落库为 1 条行程记录（守护页有据可依）")
    return {"plan_pages": len(headings)}


async def step_idempotent(ctx, elder: dict, child: dict, before: dict) -> None:
    """同一件事重复下一遍：不叠挂号卡、不叠知会、不叠行程。"""
    header("第 4 步 · 幂等：同一笔挂号再下一次")
    final, wire = await run_turn(ctx, elder, "就医出行（重复）", FLAGSHIP)
    print(f"\n  老人听到：{final}")
    cards = [c for c in wire.cards if c.get("type") == "appointment"]
    check(len(cards) == 1, f"本轮仍只出 1 张挂号卡（实测 {len(cards)} 张）")
    check(len(await appointments(ctx, elder["id"])) == before["appts"],
          "挂号记录条数不变 —— 同一医院+科室+医生+日期按幂等复用，不重复挂号")
    check(len(await notices(ctx, child["id"])) == before["notices"],
          "子女端知会条数不变 —— 同一件事家人手机上不会出现两条（按 registration_no 幂等）")
    trips = await ctx.repos.list("trips", where={"elder_id": elder["id"]})
    check(len(trips) == before["trips"], "计划书 upsert 复用同一趟行程，不新建")


async def step_vital_spike(ctx, elder: dict, child: dict, before: dict) -> None:
    """报一个数 178/105 → 真分诊 → 真挂号 → 一条知会落到子女端。"""
    header(f"第 5 步 · 报一个数：{SPIKE_READING}")
    seen = {r.get("id") for r in await ctx.repos.list(
        "health_metrics", where={"elder_id": elder["id"], "metric_type": "bp"})}
    # 挂号记录与知会也先记下已有 id。**不能拿 `rows[-1]` 当"最新那条"**：不带
    # `order=` 的 ``repos.list`` 在两种存储上顺序并不一样 —— local 是文件序（=插入序），
    # 而 MariaDB 那条 SELECT **根本不发 ORDER BY**，回来什么序由 MySQL 说了算。
    # 产品代码自己不依赖这个序（子女端与守护端都显式传了 `order=`，健康趋势窗又在
    # Python 里另排过一遍），所以这是脚本的毛病，不是产品的；但脚本一依赖它，就会
    # **只在演示用的那套存储上挂**：实测 local 全绿、MariaDB 挂在这一步。
    # 差集取新行与存储顺序无关，和上面 bp 那条同一个写法。
    seen_appts = {r.get("id") for r in await appointments(ctx, elder["id"])}
    seen_notices = {r.get("id") for r in await notices(ctx, child["id"])}
    final, wire = await run_turn(ctx, elder, "报血压", SPIKE_READING)
    print(f"\n  老人听到：{final}")

    levels = wire.triage_levels()
    print(f"  子回报里的分诊档位：{levels}")
    check("建议就医" in levels,
          f"真分诊到「建议就医」（子回报 assessment/vital_logged 里的 level={levels}）")

    # 这里原来写的是：
    #   any(t in ("log_vital",) for t in [c.get("tool") for c in wire.cards] + ["log_vital"])
    # 候选列表里被手工 append 了一个字面量 "log_vital"，于是 any() **恒为真**；
    # 而 wire.cards 里根本没有 tool 键，那个推导本身就是空的。整条断言实际只剩后半句。
    # 它照旧打 ✅ —— 属于"看起来在测、其实测不到"那一类，比没有断言更坏。
    # 现在直接去库里数行：报数前后的 id 差集就是这一轮真落下的读数，再核对值对不对。
    after_rows = await ctx.repos.list(
        "health_metrics", where={"elder_id": elder["id"], "metric_type": "bp"})
    fresh = [r for r in after_rows if r.get("id") not in seen]
    print(f"  入库前后 bp 行数：{len(seen)} → {len(after_rows)}（新增 {len(fresh)} 行）")
    landed = any(
        int(r.get("systolic") or 0) == 178 and int(r.get("diastolic") or 0) == 105
        for r in fresh
    )
    check(bool(fresh) and landed,
          f"指标真落了库：新增 bp 读数 {len(fresh)} 行，且其中有一行就是 "
          f"{SPIKE_READING}（不是只回了一句话）")

    # 落库时刻对齐（**已知数据层小瑕疵**）：这一轮记下的读数带的是 **UTC** 时刻，
    # 而档案里的读数是**本地裸时刻**。两者直接比大小，"刚报的 178/105"会排到档案
    # 今天晨起那几条**后面**，分诊看到的"最新一条"仍是档案那条。本步之所以还能到
    # 「建议就医」，是因为档案本身就是升高的（hypertension_spike）—— 不是这条新读数
    # 顶上去的。改点在 app/tools/health_tools.py 的 measured_at 与 seed 的口径统一，
    # 不属本文件；这里只把两个时刻打出来，让彩排的人一眼看见，不假装它对上了。
    metrics = await ctx.repos.list(
        "health_metrics", where={"elder_id": elder["id"], "metric_type": "bp"})
    added = [r for r in metrics if r.get("id") not in seen]
    archive_latest = max((str(r.get("measured_at") or "") for r in metrics if r.get("id") in seen),
                         default="")
    if added:
        print(f"      新读数落库时刻 {added[0].get('measured_at')}  ← UTC")
        print(f"      档案最新一条   {archive_latest}  ← 本地裸时刻（口径不一致，见脚本注释）")

    appts = await appointments(ctx, elder["id"])
    check(len(appts) == before["appts"] + 1,
          f"真挂了一个号（挂号记录 {before['appts']} → {len(appts)}）")
    fresh_appts = [r for r in appts if r.get("id") not in seen_appts]
    check(len(fresh_appts) == 1,
          f"这一轮**新**挂的那条取得出来（差集 {len(fresh_appts)} 条）")
    newest = (fresh_appts[0] if fresh_appts else appts[-1])["content"]
    print(f"      新挂号：{newest.get('registration_no')} · {newest.get('hospital')}"
          f"{newest.get('department')} {newest.get('doctor')} "
          f"{newest.get('date')} {newest.get('time')} · {newest.get('fee')} 元")

    rows = await notices(ctx, child["id"])
    check(len(rows) == before["notices"] + 1,
          f"子女端多收到 1 条知会（{before['notices']} → {len(rows)}）")
    fresh_notices = [r for r in rows if r.get("id") not in seen_notices]
    check(len(fresh_notices) == 1,
          f"这一轮**新**写的那条知会取得出来（差集 {len(fresh_notices)} 条）")
    n = fresh_notices[0] if fresh_notices else rows[-1]
    print(f"      知会标题：{n.get('title')}")
    print(f"      知会正文：{n.get('summary')}")
    check(str(n.get("title", "")).startswith("【就医知会】"),
          "标题以「【就医知会】」开头 —— 一眼分得清「知道」和「待办」")
    check(n.get("task_id") is None,
          "这条知会**没有 task_id**：它不进任何人的待办列表，点不点都一样")
    summary = str(n.get("summary") or "")
    told = [k for k in ("挂号费", "去的原因", "分诊为") if k in summary]
    check(len(told) == 3,
          f"知会正文完整（含 {'/'.join(told)}）：哪天、哪家医院、哪位医生、多少钱、为什么去")

    # 跨设备那一层：邮件。站内知会只有打开 app 才看得到，而"子女要及时知道"这件事
    # 的本质是**跨设备传递** —— 老人那台机器关不关都改变不了这一点（App 是 WebView
    # 壳，关掉就没有推送通道；厂商离线推送要企业资质、短信要签名报备）。邮件是唯一
    # 零资质、真送达、且与 app 开关无关的通道，所以它必须在验收里有一条。
    receipt = (n.get("data") or {}).get("email")
    check(isinstance(receipt, dict) and "delivered" in receipt,
          "这条知会挂着**投递回执** —— 「到底送出去没有」看得见，而不是一句"
          "乐观的『已通知子女』")
    print(f"      邮件回执：ok={receipt.get('ok')} delivered={receipt.get('delivered')}"
          f" channel={receipt.get('channel')}")
    print(f"      邮件理由：{receipt.get('reason')}")

    # 两个字段必须**分开**看：ok = 这次投递被接受了，delivered = 真的投出去了。
    # 离线 outbox 下 delivered 永远是 False —— 那封邮件没有交给任何邮件服务器。
    # 这不是失败，是如实；把它当成失败，或反过来把它当成"已送达"，都是错的。
    if receipt.get("channel") == "mock_mail":
        mailed = await mail_outbox(ctx)
        check(len(mailed) >= 1, f"离线 outbox 收到了这封知会（{len(mailed)} 封）")
        last = mailed[-1]
        check(last.get("subject") == n.get("title")
              and last.get("body") == n.get("summary"),
              "**邮件正文与站内知会逐字相同** —— 两个通道不许各说各话，"
              "否则子女在邮件里和 app 里读到两套说法，他该信哪个？")
        check(last.get("to") == child.get("email"),
              f"收件人是子女账号上的邮箱（{last.get('to')}）")
        check(receipt.get("delivered") is False,
              "离线模式下 delivered 如实为 False —— 没发出去就不说发出去了")
    else:
        check(receipt.get("delivered") is True,
              f"配了真 SMTP 就该真投出去（channel={receipt.get('channel')}）")


async def mail_outbox(ctx) -> list[dict]:
    """取离线邮件 outbox 里的记录（见 providers/external/mailer.py）。

    只有离线通道（mock_mail）才有这个东西；配了真 SMTP 时邮件直接发出去了、
    不落本地，调用方会先看回执里的 channel 再决定查不查它。
    """
    mailer = ctx.registry.resolve("mail")
    return list(getattr(mailer, "sent", []) or [])


async def step_no_suspend_cards(ctx, child: dict) -> None:
    """全程 0 张挂起卡 —— "就医不需要子女审批"在数据结构上的样子。"""
    header("第 6 步 · 挂起卡清查（就医不需要子女审批）")
    all_tasks = await ctx.repos.list("confirmation_tasks")
    print(f"  confirmation_tasks 表共 {len(all_tasks)} 行")
    check(len(all_tasks) == 0, "confirmation_tasks 表是空的 —— 全程 0 张挂起卡")
    pending = await ctx.confirmation.list_for_child(child["id"], status="pending")
    check(not pending, "子女端「待我审批」列表为空 —— 没有任何同意/拒绝按钮可点")
    every = await ctx.confirmation.list_for_child(child["id"])
    check(not every, "连历史维度也是空的（不是「挂着但被筛掉了」）")


async def step_audit(ctx, elder: dict) -> None:
    """会话事件日志：可事后回放。"""
    header("第 7 步 · 会话事件日志（审计回放）")
    sessions = await ctx.repos.list("sessions", where={"user_id": elder["id"]})
    total = 0
    for s in sessions:
        total += len(await ctx.event_log.recent(s["id"], limit=500))
    print(f"  本次冒烟共建 {len(sessions)} 个会话 · 内存事件 {total} 条")
    # 等值，不是"至少"：本脚本一共就跑三个回合（旗舰 / 重复一遍 / 报 178-105），
    # 少一个就说明有回合没落库。原来写的是 `>= 3`，措辞却是"三个会话都落了库"——
    # 断言比措辞松，等于给自己留了一条"丢了一个会话也算过"的后门。
    check(len(sessions) == 3,
          f"本次冒烟共建的 3 个会话（旗舰 / 重复 / 报数）都落了库，实测 {len(sessions)} 个")
    check(total > 0, "事件日志非空 —— 「能事后回放」是这套日志的全部意义")


# 撵人去看病的措辞。它不是"哪句话必须出现"，而是"哪些意思不许在没有否定的情况下出现"。
_PUSH_WORDS = ("挂号", "去医院", "上医院", "跑医院", "就医", "看医生")
# 否定词。判断"有没有被否定"看的是**同一个小句内**、紧挨着的前几个字。
_NEGATIONS = ("不用", "不必", "不需要", "无需", "没必要", "犯不上", "先别", "暂不", "先不", "别")
# 小句边界：越过标点的否定管不到这边。
_CLAUSE_BREAKS = "，。；！？、,.!?;：:\n"


def _negated(text: str, at: int) -> bool:
    """``text[at:]`` 处的那个就医词，是否被它**前面几个字**否定了。"""
    window = text[max(0, at - 8):at]
    for p in _CLAUSE_BREAKS:
        window = window.rsplit(p, 1)[-1]
    return any(n in window for n in _NEGATIONS)


def unnegated_pushes(text: str) -> list[str]:
    """回复里**没有被否定**的就医催促词（没有就是空表）。

    刻意**不是**"把否定词从原文里删掉再找"——那个写法在本脚本上现过原形：
    "不用特意跑医院"删掉"不用"就剩"特意跑医院"，**正好把我们要看到的那句话
    判成了撵人**，而且它判红的是一次完全正确的运行。要看的是"这个词出现的时候，
    同一个小句里前面几个字有没有否定它"。
    """
    hits: list[str] = []
    for word in _PUSH_WORDS:
        start = 0
        while True:
            at = text.find(word, start)
            if at < 0:
                break
            if not _negated(text, at):
                hits.append(word)
                break
            start = at + 1        # 这一处是被否定的，接着找下一处
    return hits


async def step_back_to_care(ctx, elder: dict, child: dict) -> None:
    """反向链：切到 stable 档，报 138/86 —— 老人该听到"不用特意跑医院"。"""
    header("第 8 步 · 反向链：保健档不去医院（种子切 stable + 报 138/86）")
    # 这一步会 reset 全库（seed_demo 就是"复位"），所以它排在最后 ——
    # 前面几步的断言都已经落定，不受影响。
    await seed_demo(ctx.repos)
    persona = await seed_kangle_persona(ctx.repos, elder, scenario="stable")
    print(f"  已切到 stable 档：库里最新血压 {persona['latest_bp'][0]}/{persona['latest_bp'][1]}，"
          f"读回库里的数再分诊 = {persona['level']}（剧本声明 {persona['declared_level']}）")
    check(persona["level"] == persona["declared_level"] == "保健",
          "脚本把数从库里读回来再喂给真规则，与剧本声明一致（它不自说自话）")

    # 先记下库里已有的行 id（30 天档案里本来就有几条 138/86），这一轮只该**多出一行**。
    # 用差集找新行，不按数值筛 —— 筛出来的是档案里的旧读数，不是这一轮记的。
    rows = await ctx.repos.list(
        "health_metrics", where={"elder_id": elder["id"], "metric_type": "bp"})
    seen = {r.get("id") for r in rows}

    final, wire = await run_turn(ctx, elder, "报血压", CALM_READING)
    print(f"\n  老人听到：{final}")
    levels = wire.triage_levels()
    print(f"  子回报里的分诊档位：{levels}")
    check(levels and set(levels) == {"保健"}, f"138/86 真分诊到「保健」（{levels}）")
    # 措辞**不能钉死一句话**。这一轮跑的是真模型（见脚本抬头的 llm=…），同一个意思
    # 每次措辞都不一样，"不用特意跑医院"这七个字换个说法就没了 —— 那样一条**完全
    # 正确**的运行会被判红。实测就是这样：连跑两次，一次挂在旗舰那步的计划书卡片、
    # 一次挂在这一句，红的地方都不一样。钉死措辞，等于把验收变成抽奖。
    #
    # 但也不能因此放宽成"看着差不多就行"—— 这条链唯一要证明的是"见数不撵人"，
    # 所以改成**正反两面**都查，两面都比原来那句话更贴住要证明的东西：
    #   反面（硬）：回复里不许出现**没被否定**的撵人措辞；
    #   正面：得有一句"在家照顾好"的意思。
    pushes = unnegated_pushes(final)
    check(not pushes,
          f"保健档不撵人：回复里不该出现 {pushes}（原文：{final[:100]}）")
    check(any(w in final for w in ("不用", "在家", "保健", "先观察", "留意")),
          f"保健档给的是「在家照顾」的话（原文：{final[:100]}）")

    check(not await appointments(ctx, elder["id"]),
          "保健档**没有**产生任何挂号（0 条）")
    check(not await notices(ctx, child["id"]),
          "保健档**没有**给子女写知会（0 条）")
    check(not await ctx.repos.list("confirmation_tasks"), "全程依然 0 张挂起卡")

    rows = await ctx.repos.list(
        "health_metrics", where={"elder_id": elder["id"], "metric_type": "bp"})
    added = [r for r in rows if r.get("id") not in seen]
    check(len(added) == 1 and added[0].get("systolic") == 138
          and added[0].get("diastolic") == 86,
          f"这一条读数真落了库（health_metrics 只多出 1 行：{[(r.get('systolic'), r.get('diastolic')) for r in added]}）")
    if added:
        print(f"      新行档位 {added[0].get('level')} · 记录时刻 {added[0].get('measured_at')}")


# ------------------------------------------------------------------ 主流程

async def main() -> None:
    cfg = settings
    if "--deepseek" in sys.argv:
        cfg = Settings(llm_provider="deepseek")
    ctx = build_context(cfg)

    header(f"康乐冒烟测试 llm={cfg.llm_provider} storage={cfg.storage_backend}")

    # ---------------------------------------------------------- ① 装配自检
    tools = [t.name for t in ctx.tools.all()]
    agents = list(ctx.agents)
    print(f"  工具 {len(tools)} 个 · Agent {len(agents)} 个（{'/'.join(agents)}）")
    print(f"  providers: llm={ctx.registry.provider_name('llm')} "
          f"asr={ctx.registry.provider_name('asr')} storage={cfg.storage_backend}")
    print(f"  工具清单：{'、'.join(sorted(tools))}")
    # 这两个数是台上要念的，先从代码里数出来钉住（DEMO_SCRIPT §6 检查单也对这一条）
    check(len(agents) == 4, f"Agent {len(agents)} 个：main/travel/health/community")
    check(len(tools) == 22, f"工具 {len(tools)} 个（22：check_scam 等已随收敛砍掉）")
    for gone in ("check_scam", "pay", "book_train", "book_hotel"):
        check(gone not in tools, f"已砍的工具不在册：{gone}")

    # ---------------------------------------------------------- ② 演示数据复位
    header("第 2 步 · 演示数据复位（默认档 hypertension_spike）")
    result = await seed_demo(ctx.repos)
    elder, child = result["elder"], result["child"]
    persona = await seed_kangle_persona(ctx.repos, elder)
    print(f"演示家庭：{elder['name']}（老人 · {elder.get('city', '')}）"
          f"— {child['name']}（{child.get('relation_to_elder') or '儿子'} · {child.get('city', '')}）")
    print(f"  档位剧本：{persona['scenario']} · 声明 {persona['declared_level']} · "
          f"库里算出来 {persona['level']} · 指标 {persona['readings']} 条 · "
          f"漏测 {len(persona['missed_days'])} 天")
    check(persona["level"] == "建议就医",
          f"默认档落在「建议就医」（最新血压 {persona['latest_bp'][0]}/{persona['latest_bp'][1]}）")

    # ---------------------------------------------------------- ③ 旗舰链
    await step_flagship(ctx, elder, child)
    snapshot = {
        "appts": len(await appointments(ctx, elder["id"])),
        "notices": len(await notices(ctx, child["id"])),
        "trips": len(await ctx.repos.list("trips", where={"elder_id": elder["id"]})),
    }
    await step_idempotent(ctx, elder, child, snapshot)
    await step_vital_spike(ctx, elder, child, snapshot)
    await step_no_suspend_cards(ctx, child)
    await step_audit(ctx, elder)
    await step_back_to_care(ctx, elder, child)

    print("\n冒烟测试通过 ✅  （装配自检 → 四页计划书 → 幂等 → 分诊「建议就医」→ 就近挂号"
          "→ 知会子女 → 0 张挂起卡 → 保健档不去医院）")


if __name__ == "__main__":
    asyncio.run(main())
