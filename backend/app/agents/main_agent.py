"""总智能体「康乐」—— 主入口：意图识别 / 任务规划 / 并行调度 / 交付物聚合。

它自己的工具只有四件，且每一件都对应架构里的一条承诺：

- ``todo_write``          真进度（落 ``todo/write`` 事件，不是前端内存里的假进度条）
- ``delegate``            真扇出（**接列表**，一次派多个 → ``subagents.run_parallel``）
- ``compose_deliverable`` 确定性交付物（走 ``plan_builder``，模型不参与拼字典）
- ``ask_user``            一次只问一个的澄清

旧版这里有两件反面教材，都删了：

1. ``route_to_agent`` 在父工具体内 ``await agent.run(turn, ...)`` —— 嵌套执行、
   天然串行，提示词还写死"一次派一个"。演示时评委看不到任何"调度"，
   只看到一个助手排队干三份活。
2. ``show_card`` 的 ``body`` 是无 schema 的 ``{"type":"object"}``，模型现编字典。
   方案书第三步那 20 分（四页可打印计划书）就压在这个自由发挥上。

子智能体的回报走 ``agent/report`` 事件落日志，``compose_deliverable`` 再从日志读回
——所以"这份计划书是哪几条回报拼出来的"可以逐条指认，hydrate 之后也照样成立。
"""
from __future__ import annotations

from app.agents import plan_builder
from app.agents.base import BaseAgent
from app.core import todo
from app.core.events import AGENT_REPORT
from app.core.subagents import AgentReport, SubagentSpec
from app.core.system_prompt_sections import build_modular_system_prompt
from app.shared.plan_helpers import dispatch_plan_created_notification, upsert_trip_plan
from app.tools.common import fail, make_tool, ok

SYSTEM_PROMPT = build_modular_system_prompt()

# 模型偶尔会用中文或近义词报 kind，这里收口，别让旗舰演示卡在一个字上
_KIND_ALIASES = {
    "trip_plan": "trip_plan", "plan": "trip_plan", "trip": "trip_plan",
    "计划书": "trip_plan", "出行计划": "trip_plan", "出行计划书": "trip_plan",
    "medical_plan": "medical_plan", "medical": "medical_plan",
    "就医计划": "medical_plan", "就医计划书": "medical_plan",
    "就医出行计划书": "medical_plan",
    "bds_escort_plan": "bds_escort_plan", "bds_plan": "bds_escort_plan",
    "北斗护航方案": "bds_escort_plan", "北斗适老出行护航方案书": "bds_escort_plan",
    "护航方案": "bds_escort_plan", "北斗方案": "bds_escort_plan",
    "bds_walk_escort_plan": "bds_walk_escort_plan", "walk_plan": "bds_walk_escort_plan",
    "walk": "bds_walk_escort_plan", "散步": "bds_walk_escort_plan",
    "散步计划": "bds_walk_escort_plan", "散步计划书": "bds_walk_escort_plan",
    "散步方案": "bds_walk_escort_plan", "散步护航方案": "bds_walk_escort_plan",
    "北斗散步护航方案书": "bds_walk_escort_plan", "北斗漫步方案": "bds_walk_escort_plan",
    "漫步方案": "bds_walk_escort_plan", "公园散步": "bds_walk_escort_plan",
    "health_card": "health_card", "health": "health_card", "用药": "health_card",
    "community_card": "community_card", "community": "community_card",
    "service": "community_card",
}

_KIND_ANNOUNCE = {
    "trip_plan": "计划书给您做好啦，一共四页：挂号、怎么去、要带的东西、天气。"
                 "打印出来照着走就行。",
    "medical_plan": "就医出行计划书给您做好啦，一共四页：挂号、怎么去、要带的东西、天气。"
                    "打印出来照着走就行。",
    "bds_escort_plan": "《北斗适老出行护航方案书》给您做好啦，一共五页：体征适配、北斗路线、微地形与长椅、气象防护、安全守护与就医绿通。打印出来照着走就行。",
    "bds_walk_escort_plan": "《北斗适老散步护航方案书》给您做好啦，一共五页：步道体征适配、北斗路线、微地形与长椅、气象防护、安全走廊与报平安。您可以点下方大按钮开启安心导航跟着走。",
    "health_card": "用药和复查的安排给您写在一张卡上了，贴在药盒边上。",
    "community_card": "社区活动推荐单给您列好了，挑一个近的约上老伙计去。",
}


class MainAgent(BaseAgent):
    name = "main"
    display_name = "康乐"
    description = "总智能体：理解指令、规划任务、并行调度子助理、聚合交付物"
    system_prompt = SYSTEM_PROMPT
    # get_weather 只由 travel 子智能体持有（见 travel_agent.py 与本类 SYSTEM_PROMPT
    # 第 58 行的调度约定）。此前主、travel 两处都注册，一次出行请求里主链路与
    # travel 会各查一遍天气，入参完全相同却是两个不同 call_id —— 老人端就看到
    # 两张一模一样的 get_weather 卡。天气归 travel 独有，从主智能体摘掉，从源头消重。
    tool_names = ["todo_write", "delegate", "compose_deliverable", "ask_user",
                  "plain_say"]


# ------------------------------------------------------------------ 主智能体专属工具

async def todo_write(turn, args: dict) -> dict:
    """整列表覆盖写清单。这是老人端进度条唯一的事实来源。"""
    try:
        items = todo.write(
            turn.ctx.event_log, turn.session_id, args.get("todos"),
            agent_id=turn.agent_id, user_id=turn.user.get("id"),
            turn_id=turn.turn_id, step_id=turn.step_id,
        )
    except todo.TodoError as exc:
        return fail(f"清单没写成：{exc}")

    payload = {"todos": [i.to_dict() for i in items],
               "progress": todo.progress(items)}
    # todo.write 已经落了 todo/write 事件，这里只推 SSE，不重复记账
    await turn.emit("todo", payload, persist=False)
    return ok(summary="当前清单：\n" + "\n".join(_todo_line(i) for i in items),
              data=payload)


def _todo_line(item: todo.TodoItem) -> str:
    mark = {"completed": "[x]", "in_progress": "[>]"}.get(item.status, "[ ]")
    return f"{mark} {item.content}"


async def delegate(turn, args: dict) -> dict:
    """把任务**成批**派给子助理，并行跑，收结构化回报。

    这是"真多智能体"的落点：``tasks`` 给几条就并发几支，各自独立作用域
    （子助理看不到彼此的对话），回报是字段而不是一段话。
    """
    raw_tasks = args.get("tasks") or args.get("task") or []
    if isinstance(raw_tasks, dict):
        raw_tasks = [raw_tasks]
    specs: list[SubagentSpec] = []
    for raw in raw_tasks if isinstance(raw_tasks, list) else []:
        spec = SubagentSpec.parse(raw)
        if spec is not None:
            specs.append(spec)
    if not specs:
        return fail("没看懂要派给谁。tasks 里每条要有 agent 和 instruction。")

    known = set((turn.ctx.subagents.names() if turn.ctx.subagents else []))
    unknown = [s.name for s in specs if s.name not in known]
    if unknown:
        return fail(f"没有叫 {'、'.join(unknown)} 的子助理，"
                    f"可选：{'、'.join(sorted(known)) or '（还没注册子助理）'}")

    reports = await turn.ctx.subagents.run_parallel(turn, specs)

    for report in reports:
        # 回报落日志：交付物的输入因此可回放、可逐条指认
        await turn.emit("report", report.to_dict())

    lines = []
    agent_names = {
        "health": "安康助手", "travel": "银发导航", "community": "邻里帮",
        "bds_nav": "北斗导航", "weather": "气象感知",
    }
    for report in reports:
        who = agent_names.get(report.agent, report.agent)
        mark = "✔" if report.ok else ("⏳" if report.suspended else "✘")
        content = report.summary or report.error or ("已完成" if report.ok else "未完成")
        line = f"{mark} {who}：{content}".strip()
        digest_parts = _digest(report)
        tier = _triage(report)
        if tier:
            digest_parts.insert(0, f"{_TRIAGE_LABEL}: {tier}")
        if digest_parts:
            line += "\n   " + "；".join(digest_parts)
        lines.append(line)
    any_ok = any(r.ok or r.suspended for r in reports) or any(bool(r.summary) for r in reports)
    summary = f"已协调子助理处理完毕：\n" + "\n".join(lines)
    return {"ok": any_ok, "summary": summary,
            "data": {"reports": [r.to_dict() for r in reports]}}


async def compose_deliverable(turn, args: dict) -> dict:
    """出交付物：读回本会话所有 ``agent/report``，套模板渲染，落库并展示。

    模型只决定"出哪一份"，字段一个都不经过它。缺的字段渲染成"待补"，
    并把清单回给模型，让它照实告诉老人还差什么 —— 而不是替它圆上。
    """
    kind = _KIND_ALIASES.get(str(args.get("kind") or "trip_plan").strip(),
                             "trip_plan")
    reports = _reports_from_log(turn)
    if not reports:
        return fail("还没有子助理的回报，先用 delegate 把活派出去。")

    kwargs = {}
    if kind in ("trip_plan", "medical_plan") and args.get("city"):
        kwargs["city"] = str(args["city"])
    if kind in ("bds_escort_plan", "bds_walk_escort_plan"):
        if args.get("city"):
            kwargs["city"] = str(args["city"])
        if args.get("destination"):
            kwargs["destination"] = str(args["destination"])
        elif hasattr(turn, "topic_anchor") and getattr(turn.topic_anchor, "target_destination", None):
            kwargs["destination"] = str(turn.topic_anchor.target_destination)
    card = plan_builder.build(kind, turn.user, reports, **kwargs)

    # card 由驱动器统一 emit（``_run_tools`` 看到结果里的 card 就推 + 落
    # artifact/card），这里不自己再 emit 一次 —— 否则老人端会看到两张一样的卡
    if kind in ("trip_plan", "medical_plan", "bds_escort_plan", "bds_walk_escort_plan"):
        # 计划书落库为 trip（幂等去重 upsert，避免重复生成）：既是可验收交付物，也是行程守护的起点
        trip_row, _ = await upsert_trip_plan(turn.ctx.repos, turn.user.get("id"), card)
        # 向绑定的家属生成未读通知
        await dispatch_plan_created_notification(
            turn.ctx.repos, turn.user, card, trip_row.get("id", ""), kind
        )

    pages = card.get("pages") or []
    missing = card.get("missing") or []
    summary = (f"已生成《{card['title']}》，共 {len(pages)} 页"
               + ("，全部字段齐备。" if not missing
                  else f"。以下 {len(missing)} 项没查到，纸上已标“待补”："
                       f"{'、'.join(missing)}"))
    announce = _KIND_ANNOUNCE.get(kind, "东西给您做好啦。")
    if missing:
        announce += "有几项还没定下来，纸上写着“待补”，我接着帮您办。"
    return ok(summary=summary, announce=announce,
              data={"kind": kind, "missing": missing,
                    "pages": len(pages), "complete": card.get("complete")},
              card=card)


def _reports_from_log(turn) -> list[AgentReport]:
    """本会话的全部子回报（按 seq 顺序）。不存第二份状态。"""
    from app.core.events import AGENT_REPORT, CONFIRM_RESOLVED, TOOL_RESULT
    reports = [AgentReport.from_dict(e.payload)
               for e in turn.ctx.event_log.events(turn.session_id)
               if e.type == AGENT_REPORT]
    common_data = {}
    resolved_map = {}
    for e in turn.ctx.event_log.events(turn.session_id):
        if e.type == CONFIRM_RESOLVED:
            cid = (e.payload or {}).get("confirmation_id")
            st = (e.payload or {}).get("status")
            tname = (e.payload or {}).get("tool")
            if cid:
                resolved_map[cid] = (tname, st)
        elif e.type == TOOL_RESULT:
            p = e.payload or {}
            tool_name = p.get("tool")
            tool_obj = turn.ctx.tools.get(tool_name) if turn.ctx.tools else None
            key = getattr(tool_obj, "report_key", "")
            d = p.get("data") or (p.get("result") or {}).get("data")
            if key and p.get("ok") and isinstance(d, dict):
                common_data[key] = d

    # 将确认任务的处理结果（如部分拒绝/通过）反哺回子智能体报告字段
    for r in reports:
        for k, v in list((r.data or {}).items()):
            if isinstance(v, dict):
                cid = v.get("confirmation_id")
                if cid and cid in resolved_map:
                    _, st = resolved_map[cid]
                    v["status"] = st
                elif not cid and resolved_map:
                    for r_cid, (r_tool, r_st) in resolved_map.items():
                        tool_obj = turn.ctx.tools.get(r_tool) if turn.ctx.tools else None
                        if tool_obj and getattr(tool_obj, "report_key", "") == k:
                            v["status"] = r_st

    if common_data:
        reports.append(AgentReport(
            agent="common", ok=True, summary="公共服务结果", data=common_data,
        ))
    return reports


# 回报摘要里带哪些**标识符**给总智能体看。只带"这件事是哪一件"，不带明细。
# 这不是为了让模型复述内容，而是为了让它能写出第二波指令：
# "规划从家到**南京鼓楼医院**的路线" —— 医院名必须是第一波挂号查出来的那家，
# 不能靠模型印象。明细（挂号费、地址、时刻、几路车）一律不进摘要，由渲染器直接取字段。
_DIGEST_FIELDS = {
    "appointment": ("hospital", "department", "doctor", "date", "time"),
    "route": ("origin", "destination", "mode"),
    "bds_route": ("route_name", "total_distance_m", "stairs_count", "barrier_free_score"),
    "weather": ("city", "date", "condition"),
    "weather_escort": ("city", "condition", "temp_range", "shade_coverage_percent"),
    "activities": ("title", "date", "place"),
}

# 分诊档位进摘要，用的是**工具自己的 report_key**（见 health_tools.py 的
# report_key=）。整体分诊（assessment，指标+慢病+症状合成的那一个）优先于
# 单次测量的档位（vital_logged）—— 前者才是"现在该怎么办"的结论。
_TRIAGE_KEYS = ("assessment", "vital_logged")
_TRIAGE_LABEL = "分诊"


def _triage(report: AgentReport) -> str:
    """这份回报给的是哪个行动档位（保健/观察/建议就医/紧急），没有就空串。

    档位必须进摘要：主智能体 SYSTEM_PROMPT 第 4 条要求它"照档位办事"
    （保健/观察 → 在家照顾，建议就医 → 就近挂号，紧急 → 先找家人），
    而它只能看见摘要。档位只活在子助理那句中文里的话，主智能体读到的是
    一句人话而不是一个档位，"照档位办事"就无从谈起。
    """
    for key in _TRIAGE_KEYS:
        node = report.data.get(key)
        if isinstance(node, dict) and node.get("level"):
            return str(node["level"])
    return ""


def _digest(report: AgentReport) -> list[str]:
    out: list[str] = []
    for key, fields in _DIGEST_FIELDS.items():
        node = report.data.get(key)
        if not isinstance(node, dict):
            continue
        parts = [str(node[f]) for f in fields
                 if node.get(f) not in (None, "", [], {})]
        if parts:
            out.append(f"{key}: " + " / ".join(parts))
    return out


async def ask_user(turn, args: dict) -> dict:
    question = args.get("question", "您想说什么？")
    await turn.emit("agent_msg", {"text": question, "agent": "main"}, persist=False)
    return ok(summary=f"已向老人追问：{question}")


def register_main_agent_tools(registry) -> None:
    registry.register(make_tool(
        "todo_write", "写下/更新任务清单（整张清单一起重写，是老人端进度条的来源）。",
        {"todos": {
            "type": "array",
            "description": "完整清单。每条 {content, status}，"
                           "status 取 pending/in_progress/completed",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "给老人看的一句话"},
                    "status": {"type": "string",
                               "enum": ["pending", "in_progress", "completed"]},
                },
            },
        }},
        todo_write, agent="main",
    ))
    registry.register(make_tool(
        "delegate", "把任务派给子助理。能同时办的一次派多个（并行执行）。",
        {"tasks": {
            "type": "array",
            "description": "要并行派出的任务列表",
            "items": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string",
                              "enum": ["health", "travel", "community", "bds_nav", "weather"],
                              "description": "health=安康助手, travel=银发导航, "
                                             "community=邻里帮, bds_nav=北斗导航规划, "
                                             "weather=气象感知"},
                    "instruction": {"type": "string",
                                    "description": "给子助理的任务说明，"
                                                   "要含老人原话里的关键信息"
                                                   "（城市、日期、症状、预算等）"},
                    "label": {"type": "string", "description": "这件事的简称"},
                },
            },
        }},
        delegate, agent="main",
        # 子助理有自己的预算（父的 60%），一次扇出可能几十秒 —— 不能吃全局 20s
        timeout_s=180.0,
    ))
    registry.register(make_tool(
        "compose_deliverable",
        "生成确定性交付物（字段由系统从子助理结果里取，不要自己复述内容）。",
        {
            "kind": {"type": "string",
                     "enum": ["trip_plan", "medical_plan", "bds_escort_plan", "health_card", "community_card"],
                     "description": "bds_escort_plan=北斗适老出行护航方案书（五页可打印）, "
                                    "trip_plan=出行计划书, medical_plan=就医出行计划书（四页可打印）, "
                                    "health_card=用药与复查卡, "
                                    "community_card=社区活动推荐单"},
            "city": {"type": "string", "description": "就医目的地城市（trip_plan / medical_plan / bds_escort_plan 用）"},
        },
        compose_deliverable, agent="main",
    ))
    registry.register(make_tool(
        "ask_user", "向老人追问一个澄清问题（一次只问一个，必要时才用）。",
        {"question": {"type": "string"}},
        ask_user, agent="main",
    ))
