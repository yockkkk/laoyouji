"""健康工具（安康助手）：挂号引导/报告大白话解读/用药提醒/反诈/饮食推荐。

红线 R1/R2/R4：不做诊断、不做处方；输出强制带免责声明（HealthDisclaimerGuard）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.core.tool import BARRIER
from app.tools.common import fail, human_date, make_tool, ok


async def search_hospital(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("hospital")
    department = args.get("department", "")
    if not department and args.get("symptom"):
        department = await provider.suggest_department(args["symptom"]) or "骨科"
    hospitals = await provider.search(args.get("city", "北京"), department)
    if not hospitals:
        return fail(f"没查到 {args.get('city')} 的 {department} 医院")
    lines = []
    for h in hospitals[:3]:
        for doc in h["doctors"][:2]:
            for slot in doc["slots"]:
                lines.append(
                    f"{h['hospital']}（{h['specialty']}）{h['department']} "
                    f"{doc['doctor']} {doc['title']} {slot['date']} {slot['time']} "
                    f"挂号费{doc['fee']}元 余{slot['remaining']}个号"
                )
    return ok(
        summary=f"为您找到{department}的号源：\n" + "\n".join(lines[:6]),
        data={"hospitals": hospitals[:3], "department": department},
    )


async def register_appointment(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("hospital")
    reg = await provider.register(
        args.get("hospital", ""), args.get("department", ""),
        args.get("doctor", ""), args.get("date"),
    )
    if not reg.get("ok"):
        return fail(reg.get("error", "挂号失败"))
    await turn.ctx.repos.insert("health_records", {
        "elder_id": turn.user.get("id"),
        "record_type": "appointment",
        "title": f"{reg['hospital']} {reg['department']} {reg['doctor']}",
        "content": reg,
    })
    return ok(
        summary=(f"已挂号：{reg['hospital']} {reg['department']} {reg['doctor']}医生 "
                 f"{reg['date']} {reg['time']}，挂号费 {reg['fee']} 元"),
        announce=reg["announce"],
        data=reg,
        card={
            "type": "appointment",
            "title": "专家号已预约",
            "body": {
                "医院": reg["hospital"],
                "科室": reg["department"],
                "医生": f"{reg['doctor']}（{reg['title']}）",
                "时间": f"{reg['date']} {reg['time']}",
                "挂号费": f"{reg['fee']} 元",
                "地址": reg["address"],
                "家人确认": "已确认",
            },
        },
    )


async def interpret_report(turn, args: dict) -> dict:
    """体检报告大白话解读 —— 是“通俗化翻译”，不是医学结论（红线 R1）。"""
    text = args.get("report_text", "")
    if not text:
        return fail("请把体检报告上的文字念给我或发给我")
    engine = turn.ctx.resolve("plain_language")
    plain = await engine.chat_with_rules(
        "你是安康助手。把老人体检报告里的每一项，翻译成60岁以上老人听得懂的大白话。"
        "规则：每项一句话；每句不超过25个字；只解释“这项查的是什么、值高还是低、"
        "一般意味着什么方向”，不下诊断、不给用药建议；最后提醒“具体听医生的”。"
        "不要添加报告里没有的项目。",
        text,
    )
    await turn.ctx.repos.insert("health_records", {
        "elder_id": turn.user.get("id"),
        "record_type": "report",
        "title": args.get("title", "体检报告解读"),
        "content": {"report_text": text},
        "plain_summary": plain,
    })
    return ok(summary=f"报告解读（大白话）：{plain}", announce=plain, data={"plain": plain})


async def add_medication(turn, args: dict) -> dict:
    times = args.get("times") or ["08:00"]
    if isinstance(times, str):
        times = [t.strip() for t in times.split(",") if t.strip()]
    row = await turn.ctx.repos.insert("medication_plans", {
        "elder_id": turn.user.get("id"),
        "drug_name": args.get("drug_name", ""),
        "dose": args.get("dose", ""),
        "times": times,
        "notes": args.get("notes", "医生已开，遵医嘱服用"),
        "active": True,
    })
    return ok(
        summary=f"已添加用药提醒：{row['drug_name']} {row['dose']}，每天 {'、'.join(times)}",
        announce=(f"记好啦。{row['drug_name']}，每天 {'、'.join(times)} 吃，"
                  f"到点我会提醒您。"),
        data={"plan": row},
    )


# ------------------------------------------------------------------------ 反诈
#
# 语料匹配用**二元字组**（连着的两个字），不用字符集重合度。
#
# 旧算法是 ``sum(1 for ch in set(item["text"][:40]) if ch in content)``、阈值 4：
# 中文里"我""了""先""钱"和一个全角逗号，随便一句话就凑满 4 分。于是老人说
# "有人给我打电话说我中奖了，让我先交钱"，命中的是语料库里"孙子摔了手机借钱"
# 那一条 —— 判定档位碰巧对了（都是高风险），但播给老人的建议是"挂了电话给孙子
# 本人打一个"，而这件事里没有孙子。给错了人名的建议，老人照着做只会更糊涂。
#
# 二元字组要求连着两个字都一样，凑不出这种巧合；除以较短一方的长度（包含度而非
# 交并比），是因为老人念的时候会自己加一圈话（"我收到一条短信，说是……"）。
_SCAM_MATCH_MIN = 0.34

# 老人念出来的原文里的高信号词。**和 ScamContentRule 那份是两份，故意的** ——
# 分工写在 `safety/risk_rules.py:_SCAM_PATTERNS` 的注释里：那份看工具参数、命中
# 即硬拒绝，所以要窄；这份看老人念的原文、只出判断不动钱，所以可以宽，宁可多
# 提醒一句。
_SCAM_MARKERS = (
    "转账", "汇款", "打款", "转到", "安全账户", "保证金", "解冻费", "冻结",
    "中奖", "领奖", "交钱", "先交", "验证码", "刷单", "神药", "根治", "包治",
)

_CORPUS: list[dict] | None = None


def _scam_corpus() -> list[dict]:
    """语料库读一次就留着 —— 它是只读数据，每次判定都读盘是白花的 I/O。"""
    global _CORPUS
    if _CORPUS is None:
        path = Path(__file__).resolve().parent.parent / "data" / "scam_corpus.json"
        _CORPUS = json.loads(path.read_text(encoding="utf-8"))["corpus"]
    return _CORPUS


def _bigrams(text: str) -> set[str]:
    """连续两字的集合。标点、空格都先去掉：一个逗号不是共同语义。"""
    plain = re.sub(r"[^0-9A-Za-z一-鿿]", "", text)
    return {plain[i:i + 2] for i in range(len(plain) - 1)}


def _judge_scam(content: str) -> tuple[str, str, str, str]:
    """返回 ``(verdict, reason, advice, announce)``；判不出来 verdict 是 unknown。

    announce 一起返回，不在外面按 verdict 拼前缀 —— 四条支线各有各的说法，
    靠事后嗅探字符串补前缀会拼出"这个像是骗子！不像诈骗"这种话。
    """
    said = _bigrams(content)
    best, best_score = None, 0.0
    for item in _scam_corpus():
        known = _bigrams(item["text"])
        score = len(said & known) / max(1, min(len(said), len(known)))
        if score > best_score:
            best, best_score = item, score
    if best and best_score >= _SCAM_MATCH_MIN:
        announce = (f"这个像是骗子！{best['advice']}"
                    if best["verdict"] == "high_risk" else best["advice"])
        return best["verdict"], best["reason"], best["advice"], announce

    hits = [w for w in _SCAM_MARKERS if w in content]
    if hits:
        advice = "先别照着做，钱一分都别转。把这条原话发给家人，让他们看一眼。"
        return ("high_risk", f"出现了骗子常用的说法：{'、'.join(hits[:3])}。",
                advice, f"这个像是骗子常用的说法。{advice}")
    return "unknown", "", "", ""


async def _judge_by_model(turn, content: str) -> tuple[str, str, str, str]:
    """语料和词表都没话说时问模型 —— 但只认它给出的那个**判定词**。

    原来这里把模型返回的整段话直接当判定播给老人。离线时 ``plain_language``
    背后是 MockLLM，对一个不带工具的请求回的是"好的，我在呢。您慢慢说。"，
    于是反诈的结论变成了这句寒暄 —— 而断网兜底和 ``demo_smoke`` 走的正是离线。
    """
    engine = turn.ctx.resolve("plain_language")
    answer = await engine.chat_with_rules(
        "你是反诈助手。判断下面老人收到的内容是否疑似诈骗。"
        "判断标准：要求转账汇款、点不明链接、夸大疗效卖药、冒充熟人借钱，都是诈骗。"
        "回答格式：第一句“像诈骗”或“不像诈骗”；第二句用大白话给一条建议。两句话以内。",
        content,
    )
    text = (answer or "").strip()
    if text.startswith("不像诈骗"):
        return "normal", "判断为不像诈骗话术。", text, text
    if text.startswith("像诈骗"):
        return "high_risk", "判断为像诈骗话术。", text, text
    advice = "我拿不准这条是真是假。先别回、也别转钱，把它发给家人看一眼。"
    return "unknown", "这条我拿不准，没敢下结论。", advice, advice


async def check_scam(turn, args: dict) -> dict:
    """反诈识别：对可疑内容给出判定和可执行建议。

    三级判断，从确定到不确定：**语料库命中 → 高信号词命中 → 交给模型**，
    三级都说不出话时给的是"我拿不准"，而不是一个编出来的判定。

    第三档必须存在。这件事上猜错哪一头都有代价：说"没事"会让老人把钱转出去，
    说"是骗子"会让老人不敢接自己孩子的电话。
    """
    content = args.get("content", "")
    if not content:
        return fail("请把收到的短信或消息念给我听")

    verdict, reason, advice, announce = _judge_scam(content)
    if verdict == "unknown":
        verdict, reason, advice, announce = await _judge_by_model(turn, content)

    # 每次检查都入健康档案。原来只有语料库命中那一支写，于是语料外的检查在老人
    # 档案里查不到 —— 子女事后问"我妈那天到底收到了什么"，翻不出来。
    await turn.ctx.repos.insert("health_records", {
        "elder_id": turn.user.get("id"),
        "record_type": "scam_check",
        "title": "反诈检查",
        "content": {"content": content, "verdict": verdict},
        "plain_summary": advice,
    })
    prefix = {"high_risk": "疑似诈骗：", "normal": "正常内容：",
              "unknown": "拿不准："}[verdict]
    return ok(summary=f"{prefix}{reason}", announce=announce,
              data={"verdict": verdict, "reason": reason, "advice": advice})


async def diet_advice(turn, args: dict) -> dict:
    engine = turn.ctx.resolve("plain_language")
    profile = turn.user.get("name", "老人")
    advice = await engine.chat_with_rules(
        "你是安康助手的饮食顾问。根据老人的慢性病情况（默认：骨关节炎、轻度高血压），"
        "推荐今天的饮食。规则：大白话；每句不超过20字；只说家常菜和日常搭配；"
        "不下诊断、不推荐药物或保健品；共3到4句话。",
        f"为{profile}推荐今天三餐（{args.get('preference', '清淡软烂')}）。",
    )
    return ok(summary=f"饮食推荐：{advice}", announce=advice, data={"advice": advice})


def register_health_tools(registry) -> None:
    registry.register(make_tool(
        "search_hospital", "按城市和科室（或症状）查找医院和可预约的专家号。",
        {
            "city": {"type": "string", "description": "城市，如 北京"},
            "department": {"type": "string", "description": "科室，如 骨科"},
            "symptom": {"type": "string", "description": "症状描述（腿疼、心口闷等）"},
        },
        search_hospital, agent="health", report_key="hospital_options",
    ))
    registry.register(make_tool(
        "register_appointment", "预约挂号（挂号费需家人确认后才锁定号源）。",
        {
            "hospital": {"type": "string", "description": "医院名称"},
            "department": {"type": "string", "description": "科室"},
            "doctor": {"type": "string", "description": "医生姓名"},
            "date": {"type": "string", "description": "就诊日期"},
            "time": {"type": "string", "description": "就诊时段（照抄号源结果，如 上午）"},
            "fee": {"type": "number", "description": "从查询结果获得的挂号费（元）"},
        },
        register_appointment, agent="health",
        # 挂号要付费 → 高危 → 独占执行，且这份参数会被冻结给家人确认
        execution_mode=BARRIER, report_key="appointment",
        # 家人看到的就是这一句。日期和时段必须在里面 —— 挂号是"某天某个时段的
        # 一个号"，只写医院和费用，家人批的是一件缺了主语的事。
        child_summary=lambda a: (f"母亲张桂芳想挂 {a.get('hospital', '')} "
                                 f"{a.get('department', '')} 的号"
                                 f"（{a.get('doctor', '')}），"
                                 f"{human_date(a.get('date'))}"
                                 f"{a.get('time', '')}，"
                                 f"挂号费约 {a.get('fee', '?')} 元"),
    ))
    registry.register(make_tool(
        "interpret_report", "把体检报告的文字翻译成大白话（仅供参考，不替代医生诊断）。",
        {"report_text": {"type": "string", "description": "报告上的文字内容"},
         "title": {"type": "string", "description": "报告名称"}},
        interpret_report, agent="health", report_key="report_reading",
    ))
    registry.register(make_tool(
        "add_medication", "添加用药提醒计划（必须是医生已开的药）。",
        {
            "drug_name": {"type": "string", "description": "药名"},
            "dose": {"type": "string", "description": "剂量，如 每次1粒"},
            "times": {"type": "array", "items": {"type": "string"},
                      "description": "每天服药时间列表，如 ['08:00','20:00']"},
            "notes": {"type": "string", "description": "注意事项"},
        },
        add_medication, agent="health", report_key="medication",
    ))
    registry.register(make_tool(
        "check_scam", "反诈识别：判断老人收到的短信/消息/链接是否疑似诈骗。",
        {"content": {"type": "string", "description": "收到的内容原文"}},
        check_scam, agent="health", report_key="scam_check",
    ))
    registry.register(make_tool(
        "diet_advice", "根据老人慢性病情况推荐今天的饮食（家常建议，非医疗处方）。",
        {"preference": {"type": "string", "description": "口味偏好，如 清淡软烂"}},
        diet_advice, agent="health", report_key="diet",
    ))
