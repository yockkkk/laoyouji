"""健康工具（安康助手）：指标记录/健康概览/慢病登记/分诊 + 挂号/报告解读/用药/饮食。

红线 R1/R2/R4：不做诊断、不做处方；输出强制带免责声明（HealthDisclaimerGuard）。

分诊（assess_health）是康乐左翼的入口：它把"记下来的指标"翻译成一个**行动档位**
（保健/观察/建议就医/紧急），档位再决定下一步是"在家照顾好"还是"帮您就近挂号"。
阈值与合并逻辑全在 ``app.safety.health_rules``（纯函数、可单测），这里只负责取数、
落库、把结论摆成老人看得懂的样子 —— 工具层不做判断，判断层不碰库。

**就医知会不审批**：挂号（register_appointment）不在高危审批线上，立即办好；
办好那一刻写一条 ``appointment_notice`` 知会全部绑定子女，内容含医院/科室/医生/
时间/挂号费 + 触发原因（复用上面那个分诊大脑，子女看到的理由和老人端的分诊同源）。
"""
from __future__ import annotations

import logging
from datetime import datetime

from app.core.tool import BARRIER
from app.db.repositories import utcnow_iso
from app.providers.external.base import resolve_date
from app.safety import health_rules as hr
from app.tools.common import fail, human_date, make_tool, ok

logger = logging.getLogger(__name__)

# 指标名（"血压""血糖"…）。它们**长得像症状，其实是测量项的名字** —— 科室映射里也
# 收着它们（"血压高"配心内科，配得没错），但老人报一个数时命中的那个词，回答的是
# "该去查什么"，不是"哪儿难受"。两种身份必须分开，见 ``_as_symptom``。
_METRIC_WORDS: tuple[str, ...] = tuple(m["label"] for m in hr.METRICS.values())


def _as_symptom(phrase) -> str | None:
    """把"为什么去"里那个词当症状用之前，先确认它**不是一句指标名**。

    老人报一个数（"血压 178/105"）走的是"报数 → 分诊 → 该就医 → 就近挂号"这条路，
    主智能体顺手把科室映射命中的关键词当 reason 传了下来 —— 而那个词是"血压"。
    不拦的话，子女收到的知会长成这样："去的原因：提到“血压”，先观察，持续或加重就
    去看医生；血压 178/105，中重度偏高。分诊为「建议就医」。" 前半句让人先观察、
    后半句说分诊建议就医，家人得自己猜哪句算数 —— 而老人**一个字的不舒服都没提**，
    他只是在念血压计上的数。那条主诉是系统替他编的。

    只拦"整句就是一个指标名"这一种。老人真说了"血压高得头晕"，那句话里有他自己的
    说法，照传不误 —— 宁可漏，不替老人编话。
    """
    text = str(phrase or "").strip()
    if not text:
        return None
    if any(w in text for w in _METRIC_WORDS):
        rest = text
        for w in _METRIC_WORDS:
            rest = rest.replace(w, "")
        if not rest.strip():
            return None
    return text


async def search_hospital(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("hospital")
    department = args.get("department", "")
    if not department and args.get("symptom"):
        department = await provider.suggest_department(args["symptom"]) or "骨科"
    # 城市默认取老人档案里的常住地，**不是写死的北京**：南京的张桂芳问挂号却拿到
    # 北京的号源，"就近就医"就成了一句空话。模型没传 city 时这里兜住。
    city = args.get("city") or turn.user.get("city") or "北京"
    hospitals = await provider.search(city, department)
    if not hospitals:
        return fail(f"没查到 {city} 的 {department} 医院")
    lines = []
    for h in hospitals[:3]:
        # "离家多远"要印在老人看得见的那句话里。只影响排序的话，老人从字面上
        # 看不出推荐的为什么是这家 —— 而"就近"正是这条链路要他信的东西。
        near = f"（{h['distance_text']}）" if h.get("distance_text") else ""
        for doc in h["doctors"][:2]:
            for slot in doc["slots"]:
                lines.append(
                    f"{h['hospital']}{near}（{h['specialty']}）{h['department']} "
                    f"{doc['doctor']} {doc['title']} {slot['date']} {slot['time']} "
                    f"挂号费{doc['fee']}元 余{slot['remaining']}个号"
                )
    return ok(
        summary=f"为您找到{department}的号源：\n" + "\n".join(lines[:6]),
        data={"hospitals": hospitals[:3], "department": department, "city": city},
    )


# ------------------------------------------------------- 就医知会（知会不审批）
# 用户的原话："就医不需要家人审批，但必须及时把完整情况知会子女。"
# 所以挂号这条线上没有"等同意"这一步 —— provider.register 成功的那一刻就算办好了，
# 紧接着做的是**告知**：把完整的就诊情况写进 notifications，子女端通知中心就看到了。
#
# 知会与审批在数据结构上必须能一眼分开：
#   · 审批 → confirmation_tasks + type='confirmation_request' 的通知，带 task_id，要人点；
#   · 知会 → 只有一条 type='appointment_notice' 的通知，**没有 task_id**，点不点都一样。
# 子女手机上出现的是"知道了一件事"，不是"有件事等你办"。


async def _bound_children(repos, elder_id: str) -> list[dict]:
    """该老人的**全部**绑定子女（active），按 child_id 去重。

    是"全部"，不是随便挑一个：知会不是审批，没有"谁来批"这个问题 —— 每个子女
    都该知道老人要去看病。revoked 的绑定要滤掉：解除关系之后不该再收到老人的病历。
    """
    rows = await repos.list("family_bindings", where={"elder_id": elder_id})
    out, seen = [], set()
    for b in rows:
        if b.get("status") not in (None, "active"):
            continue
        child_id = b.get("child_id")
        if not child_id or child_id in seen:
            continue
        seen.add(child_id)
        out.append(b)
    return out


def _relation_for_elder(binding: dict, child: dict | None) -> str:
    """老人端怎么称呼这位子女：``您儿子李明`` / ``您女儿`` / 没绑定时 ``家人``。

    与 ``ConfirmationService.suspend`` 里那一段保持同一算法 —— 同一件事在老人端
    有两种称呼法，比称呼得不够亲更糟。叫不出名字时不硬编一个（那会叫错人）。
    """
    relation = (binding or {}).get("relation") or "家人"
    name = (child or {}).get("name") or ""
    return f"您{relation}{name}" if name else f"您{relation}"


async def _visit_reason(turn, args: dict) -> dict:
    """**这次为什么要去** —— 从已落库的指标 + 慢病 +（可选）症状算出来。

    复用分诊大脑（``_grouped_history`` / ``_active_conditions`` / ``triage_overview``），
    不是另写一套判断：知会里那句"为什么去"必须和老人端的分诊是**同一个结论**。
    两条路各算各的，就会出现子女看到"血压偏高"、老人端却是"紧急"这种对不上号的情况，
    而子女是照着这条知会去判断要不要回一趟家的。

    返回 ``{level, drivers, readings, symptom, text}``。库里没指标又没症状就返回空
    （不编理由）；driver 的 reason 形如"血压 178/105，中重度偏高"，是**事实**，
    天然不含诊断结论 —— R1/R2 不需要在这里额外特判。
    """
    repos, elder_id = turn.ctx.repos, turn.user.get("id")
    # 过一道 ``_as_symptom``：模型（和离线剧本）都可能把"血压"这个**测量项的名字**
    # 当成主诉传进来，理由见那个函数。
    symptom = _as_symptom(args.get("symptom") or args.get("reason"))
    grouped = await _grouped_history(repos, elder_id)
    conditions = await _active_conditions(repos, elder_id)
    if not grouped and not symptom:
        return {"level": "", "drivers": [], "readings": [],
                "symptom": "", "text": ""}
    overview = triage_overview(grouped, conditions, symptom=symptom)
    # 症状**排在指标前面**：老人这趟是"因为腿疼"去的，血压高是同时查出来的另一件事。
    # triage_overview 按档位轻重排序（建议就医的血压排在观察级的症状之上），那个顺序
    # 是给"先处理哪一档"用的，直接拿来当知会的叙述顺序，子女读到的第一句就是
    # "血压 178/105" —— 会以为老人是为血压去看的，而老人一个字没提血压。
    sym = [d["reason"] for d in overview["drivers"] if d["metric"] == "symptom"]
    others = [d["reason"] for d in overview["drivers"] if d["metric"] != "symptom"]
    return {
        "level": overview["level"], "drivers": overview["drivers"],
        "readings": overview["readings"], "symptom": symptom or "",
        "text": "；".join(sym + others),
    }


async def _deliver_by_email(turn, child: dict, *, title: str, summary: str) -> dict:
    """把这条知会再走一遍**跨设备**通道（邮件），返回投递回执。

    邮件正文**就是站内那条知会的正文**（同一个 title / summary），一个字不改 ——
    两条通道各写各的措辞，迟早会飘，子女在邮件里和 app 里读到两套说法，那时候
    该信哪个？所以这里只做搬运，不重新组织语言。

    收件人取子女账号上的 ``email``。**没留邮箱不是异常**，是一条如实的回执：
    "没留邮箱，这封没发出去"。绝不因此把挂号或站内知会回滚 —— 挂号已经办完了，
    老人看病这件事不能被"邮件发不出去"卡住。

    这一层**保证不抛**：投递层已经承诺只返回结果，这里再兜一层，因为调用点
    在挂号成功之后的知会循环里，任何异常都会把一次已经办成的挂号变成失败。
    """
    try:
        mailer = turn.ctx.registry.resolve("mail")
    except Exception as err:                           # noqa: BLE001
        logger.warning("邮件通道未装配: %s", err)
        return {"ok": False, "delivered": False, "channel": "",
                "reason": "邮件通道未装配"}
    try:
        return await mailer.send(to=(child or {}).get("email") or "",
                                 subject=title, body=summary)
    except Exception as err:                           # noqa: BLE001
        logger.warning("邮件投递异常: %s", err)
        return {"ok": False, "delivered": False,
                "channel": getattr(mailer, "name", ""),
                "reason": f"投递异常：{type(err).__name__}"}


async def _notify_children_of_appointment(turn, reg: dict, args: dict) -> dict:
    """挂号成功那一刻，给每个绑定子女写一条**知会**（不是待办、不是请求批准）。

    行形状严格照 ``schema.sql`` 的 notifications（``user_id/elder_id/type/title/
    summary/is_read/data/created_at``）—— 前端靠 ``is_read`` 判未读，写成
    content/payload/那一套就是永久"未读"。

    幂等按 ``registration_no`` 判：provider 是幂等出号的（同一件事拿到同一个号），
    所以模型把同一笔挂号再下一遍时，通知层不会叠第二张卡。家人手机上同一件事
    出现两条通知，比不通知更糟 —— 他会以为老人挂了两次号。

    返回 ``{notified, relations, stamp, relation_for_elder}``，供老人端播报使用。
    """
    repos = turn.ctx.repos
    elder_id = turn.user.get("id")
    children = await _bound_children(repos, elder_id)
    if not children:
        return {"notified": [], "relations": [], "stamp": "",
                "relation_for_elder": ""}

    reason = await _visit_reason(turn, args)
    stamp = datetime.now().strftime("%H:%M")
    elder_name = turn.user.get("name") or "老人"
    reg_no = reg.get("registration_no", "")

    # 完整，不是半句：哪天、哪个时段、哪家医院、哪位医生、多少钱、为什么去。
    # 子女只能看到这一条，少一样他都要打电话回来问 —— 而那正是"知会"没做到位。
    why = reason["text"] or str(args.get("reason") or "").strip()
    summary = (f"{elder_name}已在{reg['hospital']}{reg['department']}挂好"
               f"{reg['doctor']}医生的号，{reg['date']} {reg['time']}，"
               f"挂号费 {reg['fee']} 元。"
               # 真没记到就写"没记到"，不拿一句"身体不适"糊上：那句话看起来
               # 像事实，其实是编的，而子女会照着它判断要不要回家。宁可留个空，
               # 也不替老人说一句他没说过的话（与 plan_builder 的"待补"同一口径）。
               + (f"去的原因：{why}。" if why else "去的原因：这次没记到。"))
    if reason["level"]:
        summary += f"分诊为「{reason['level']}」。"

    notified, relations = [], []
    for binding in children:
        child_id = binding["child_id"]
        child = await repos.get("users", child_id)
        relation_for_elder = _relation_for_elder(binding, child)
        existing = await repos.list(
            "notifications",
            where={"user_id": child_id, "type": "appointment_notice"})
        if any((row.get("data") or {}).get("registration_no") == reg_no
               for row in existing):
            notified.append(child_id)          # 已告知过，不重复打扰
            relations.append(relation_for_elder)
            continue
        title = f"【就医知会】{elder_name}已挂好{reg['hospital']}{reg['department']}的号"
        notice_data = {
            "hospital": reg["hospital"], "department": reg["department"],
            "doctor": reg["doctor"], "doctor_title": reg.get("title", ""),
            "date": reg["date"], "time": reg["time"], "fee": reg["fee"],
            "registration_no": reg_no, "address": reg.get("address", ""),
            "level": reason["level"], "reason": reason["text"],
            "drivers": reason["drivers"], "readings": reason["readings"],
            "symptom": reason["symptom"], "notified_at": stamp,
        }
        row = await repos.insert("notifications", {
            "user_id": child_id,
            "elder_id": elder_id,
            "type": "appointment_notice",
            "title": title,
            "summary": summary,
            "is_read": False,
            "data": notice_data,
            "created_at": datetime.now().astimezone().isoformat(),
        })
        # 同一份文案再走一遍**跨设备**通道：邮件（见 providers/external/mailer.py）。
        # 顺序是**先写站内知会、再发邮件**：站内那条是事实源，邮件是兜底。
        # 反过来的话，邮件已经到子女手机上了、站内却没记录，重跑一遍还会再发一封。
        # 回执写回这条知会的 data 里 —— "到底送出去没有"要能被看见，
        # 而不是只有一句乐观的"已通知子女"。
        receipt = await _deliver_by_email(turn, child, title=title, summary=summary)
        if row and row.get("id"):
            notice_data["email"] = receipt
            await repos.update("notifications", row["id"], {"data": notice_data})
        notified.append(child_id)
        relations.append(relation_for_elder)

    return {"notified": notified, "relations": relations, "stamp": stamp,
            "relation_for_elder": relations[0] if relations else ""}


async def _find_recent_appointment(repos, elder_id: str, args: dict) -> dict | None:
    """这件事是不是刚刚已经办过了（同一医院+科室+医生+日期）。

    挂号原来走"挂起等确认"，判重由 ``ConfirmationService._find_pending_duplicate``
    兜着；改成立即执行之后，那层护栏就够不着了 —— 模型在同一会话里把挂号再下一遍
    （suspended 那套它看不到了，结果又像"没办成"），就会真去 provider 挂第二次、
    health_records 里多出一行，老人时间线上出现两个一样的号。
    provider 是幂等出号的（同一件事同一个号），所以这不是重复扣费，但仍然是
    "同一件事记了两笔"，会让人以为挂了两个号。去重下沉到这一步。
    """
    when = resolve_date(args["date"]) if args.get("date") else None
    rows = await repos.list(
        "health_records", where={"elder_id": elder_id, "record_type": "appointment"})
    for row in rows:
        content = row.get("content") or {}
        if (content.get("hospital") == args.get("hospital", "")
                and content.get("department") == args.get("department", "")
                and content.get("doctor") == args.get("doctor", "")
                and content.get("date") == when):
            # 给一份拷贝，不是库里那一行本身：这份结果会一路带到回报与计划书渲染，
            # 那些地方会往字段里写东西（如补一个 status）—— 写进库里那一行，
            # 就等于让"第二次挂号"把第一张回执改成了别的样子。
            return dict(content)
    return None


async def register_appointment(turn, args: dict) -> dict:
    """预约挂号 —— **立即办好**，办完把完整就诊情况知会子女。

    这条线上没有"等家人确认"：老人看病不该等谁点头（用户原话是"就医不需要家人审批"）。
    挂号成功的同一个动作里写一条知会，把"为什么去"也算出来 —— 子女收到的是
    一件已经发生的事 + 全部细节，而不是一张要他点同意的卡片。
    """
    repos = turn.ctx.repos
    elder_id = turn.user.get("id")
    existing = await _find_recent_appointment(repos, elder_id, args)
    if existing:
        reg = existing
    else:
        provider = turn.ctx.resolve("hospital")
        reg = await provider.register(
            args.get("hospital", ""), args.get("department", ""),
            args.get("doctor", ""), args.get("date"),
        )
        if not reg.get("ok"):
            return fail(reg.get("error", "挂号失败"))
        await repos.insert("health_records", {
            "elder_id": elder_id,
            "record_type": "appointment",
            "title": f"{reg['hospital']} {reg['department']} {reg['doctor']}",
            "content": reg,
        })

    notice = await _notify_children_of_appointment(turn, reg, args)
    noticed = bool(notice["notified"])
    relation_for_elder = notice["relation_for_elder"] or "家人"
    if len(notice["notified"]) > 1:
        relation_for_elder = f"{relation_for_elder}等 {len(notice['notified'])} 位家人"

    summary = (f"已挂号：{reg['hospital']} {reg['department']} {reg['doctor']}医生 "
               f"{reg['date']} {reg['time']}，挂号费 {reg['fee']} 元")
    announce = (f"已为您挂好号：{reg['hospital']}{reg['department']}"
                f"{reg['doctor']}医生，{reg['date']} {reg['time']}，"
                f"挂号费 {reg['fee']} 元。")
    if noticed:
        # 措辞是需求本身：说"已为您挂好号"+"已经把情况告诉您儿子李明了（18:04）"，
        # 不是"已提交，等待家人确认"。老人不该为看病等谁点头。
        summary += f"。已把完整就诊情况知会{relation_for_elder}（{notice['stamp']}）。"
        announce += (f"同时已经把情况告诉{relation_for_elder}了"
                     f"（{notice['stamp']}）。")
    else:
        summary += "。还没绑定家人，这次的就诊情况暂无人可告知。"
        announce += "还没绑上家人，等您绑好了我把这次的情况也告诉他们。"
    return ok(
        summary=summary,
        announce=announce,
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
                # 这一步已经不是"家人点头"了。卡片上再写"确认/已确认"，
                # 就是把"知会"说成了"审批" —— 老人看到会以为还得等家里回话。
                "家人知会": (f"已告诉{relation_for_elder}（{notice['stamp']}）"
                             if noticed else "暂未绑定家人"),
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


# ---------------------------------------------------------------- 左翼·身体核心

# 概览/分诊一次最多往回看多少条（够算趋势，又不至于把整本流水账念一遍）。
_HISTORY_WINDOW = 7


async def _grouped_history(repos, elder_id: str, *,
                           window: int = _HISTORY_WINDOW) -> dict[str, list[dict]]:
    """读该老人记下的指标，按 metric_type 分组，每组按时间**正序**（旧→新）。

    排序键是 ``measured_at``，缺失时退回 ``created_at``（仓储自动补）—— 保证任何一行
    都有键可比，不会因为某条没填测量时刻就把顺序搅乱。每组只留最近 ``window`` 条：
    趋势看的是"最近这几天"，翻三年前的数据对分诊没有意义。

    收 ``(repos, elder_id)`` 而不是 ``turn``：老人端那个健康页（REST）读的是同一份
    数据、同一套趋势算法，换个入口不该换出另一种"最近怎么样"。
    """
    rows = await repos.list("health_metrics", where={"elder_id": elder_id})
    grouped: dict[str, list[dict]] = {}
    for r in rows:
        grouped.setdefault(str(r.get("metric_type") or ""), []).append(r)
    for mtype, items in list(grouped.items()):
        items.sort(key=lambda r: str(r.get("measured_at") or r.get("created_at") or ""))
        grouped[mtype] = items[-window:]
    return grouped


def _latest_by_type(grouped: dict[str, list[dict]]) -> dict[str, dict]:
    return {m: items[-1] for m, items in grouped.items() if items}


def _trends_by_type(grouped: dict[str, list[dict]]) -> dict[str, str]:
    """每类指标的近期走向。条数不够就干脆不报走向 —— 两条点连不出趋势。"""
    out: dict[str, str] = {}
    for mtype, items in grouped.items():
        series = [v for v in (hr.metric_scalar(r) for r in items) if v is not None]
        if len(series) >= 4:
            out[mtype] = hr.trend(series)
    return out


async def _active_conditions(repos, elder_id: str) -> list[dict]:
    rows = await repos.list("health_conditions", where={"elder_id": elder_id})
    return [r for r in rows if r.get("active", True)]


def triage_overview(grouped: dict[str, list[dict]], conditions: list[dict], *,
                    symptom: str | None = None) -> dict:
    """分组历史 + 慢病 → 一次完整分诊。**概览与分诊两个工具共用这一段**。

    返回 ``{level, advice, headline, drivers, latest, trends, readings}``：
    前四项是分诊引擎的原样输出，后三项是页面渲染要用的（每条读数配上档位与走向）。
    """
    latest = _latest_by_type(grouped)
    trends = _trends_by_type(grouped)
    verdict = hr.triage(latest, conditions=conditions, trends=trends, symptom=symptom)
    drivers = [
        {**d, "label": hr.metric_label(d["metric"]) if d["metric"] != "symptom" else "症状"}
        for d in verdict["drivers"]
    ]
    readings = []
    for mtype in hr.METRICS:                      # 固定顺序：页面每行位置不跳
        row = latest.get(mtype)
        if not row:
            continue
        level, reason = hr.classify_reading(
            mtype, value=row.get("value"), systolic=row.get("systolic"),
            diastolic=row.get("diastolic"), context=row.get("context"))
        readings.append({
            "metric_type": mtype, "label": hr.metric_label(mtype),
            "display": hr.format_reading({**row, "metric_type": mtype}),
            "level": level, "reason": reason,
            "normal": hr.METRICS[mtype]["normal"],
            "trend": trends.get(mtype, "平稳"),
            "measured_at": row.get("measured_at") or row.get("created_at") or "",
        })
    return {
        "level": verdict["level"], "advice": verdict["advice"],
        "headline": verdict["headline"], "drivers": drivers,
        "readings": readings, "latest": latest, "trends": trends,
        "conditions": conditions, "symptom": symptom or "",
    }


async def record_reading(repos, elder_id: str, args: dict) -> dict:
    """校验 → 分诊 → 入库。**工具和 REST 都走这里**。

    抽出来是为了让"老人对着手机点一下记血压"和"老人跟康乐说一句血压 178/105"
    落在同一段代码上：档位、单位、格式、失败时的说法，一个字都不会有两种。
    两边各写一遍的话，同一个 178/105 在聊天里是"建议就医"、在页面上是别的档，
    这种不一致比没有页面更糟。

    返回形状与工具结果一致（``{"ok", "summary", "data"}``），失败时 ``ok=False``；
    调用方各自决定怎么呈现（工具直接回模型，REST 映射成状态码）。
    """
    reading = hr.coerce_reading(args)
    mtype = reading["metric_type"]
    if mtype not in hr.METRICS:
        return fail(f"这个指标我暂时记不了：{mtype or '（没说是哪一项）'}")
    if mtype == "bp":
        if reading.get("systolic") is None or reading.get("diastolic") is None:
            return fail("血压要高压和低压两个数，比方说 178/105")
    elif reading.get("value") is None:
        return fail(f"{hr.metric_label(mtype)}得是个数字，您再说一遍？")

    level, reason = hr.classify_reading(
        mtype, value=reading.get("value"), systolic=reading.get("systolic"),
        diastolic=reading.get("diastolic"), context=reading.get("context"),
    )
    payload: dict = {
        "elder_id": elder_id,
        "metric_type": mtype,
        "unit": hr.metric_unit(mtype),
        "measured_at": args.get("measured_at") or utcnow_iso(),
        "source": args.get("source") or "手动记录",
        "level": level,
    }
    if mtype == "bp":
        payload["systolic"] = reading["systolic"]
        payload["diastolic"] = reading["diastolic"]
    else:
        payload["value"] = reading["value"]
    if reading.get("context"):
        payload["context"] = reading["context"]
    if args.get("note"):
        payload["note"] = args["note"]
    saved = await repos.insert("health_metrics", payload)

    display = hr.format_reading({**saved, "metric_type": mtype})
    label = hr.metric_label(mtype)
    tip = ""
    if hr.level_rank(level) >= 2:
        tip = "这个数偏得有点多，要不要我帮您看看该怎么办？"
    return ok(
        summary=f"已记录：{label} {display}（{reason}）。{tip}".strip(),
        announce=f"记好了。{label}{display}，{reason}。{tip}".strip(),
        data={
            "reading": saved, "display": display, "label": label,
            "level": level, "reason": reason,
        },
    )


async def log_vital(turn, args: dict) -> dict:
    """记一条指标（血压/血糖/心率/血氧/体温/体重）。

    记完**当场分诊**并把档位一并回给老人 —— 记录不该是"存进去就没下文"。数偏了就
    当场说一句，数平稳就给个肯定，这样"每天量一量"才有反馈，老人才愿意接着量。
    """
    return await record_reading(turn.ctx.repos, turn.user.get("id"), args)


async def get_health_summary(turn, args: dict) -> dict:
    """把这阵子记下的指标收成一张"最近怎么样"的概览（含分诊结论与建议）。"""
    repos, elder_id = turn.ctx.repos, turn.user.get("id")
    grouped = await _grouped_history(repos, elder_id)
    conditions = await _active_conditions(repos, elder_id)
    overview = triage_overview(grouped, conditions)

    lines = []
    for r in overview["readings"]:
        text = f"{r['label']} {r['display']}"
        if r["trend"] != "平稳":
            text += f"，最近{r['trend']}"
        lines.append(text)
    if conditions:
        names = "、".join(str(c.get("name") or "") for c in conditions if c.get("name"))
        if names:
            lines.append(f"慢病：{names}")

    if not overview["readings"]:
        summary = "您还没记过指标呢。量一次血压报给我，我帮您记上。"
    else:
        summary = ("最近记下的指标：" + "；".join(lines)
                   + f"。分诊结论：{overview['level']}。")

    return ok(
        summary=summary,
        announce=summary,
        data={
            "readings": overview["readings"], "conditions": conditions,
            "level": overview["level"], "advice": overview["advice"],
            "headline": overview["headline"], "lines": lines,
            "count": len(overview["readings"]),
        },
    )


async def add_condition(turn, args: dict) -> dict:
    """登记一条慢病（老人自己说的、医生确诊过的）。只记，不判断、不评论。"""
    name = str(args.get("name") or "").strip()
    if not name:
        return fail("您说的是哪种病呢？我记上，往后的建议好照着来。")
    row = await turn.ctx.repos.insert("health_conditions", {
        "elder_id": turn.user.get("id"),
        "name": name,
        "diagnosed_at": args.get("diagnosed_at") or "",
        "severity": args.get("severity") or "",
        "notes": args.get("notes") or "",
        "active": True,
    })
    since = f"，{human_date(row['diagnosed_at'])}查出来的" if row["diagnosed_at"] else ""
    # 措辞上把"确诊"归给医生：这条病是**医生说过的**，康乐只是记下来。
    # "您有××病"和"医生确诊的××病，我记上了"是两件事，前者正是红线 R1 要防的。
    return ok(
        summary=f"已记下慢病：{row['name']}{since}。往后的饮食和提醒我会照着这个来。",
        announce=f"记下了，医生确诊的{row['name']}{since}。以后我说话会照着您的情况来。",
        data={"condition": row},
    )


async def assess_health(turn, args: dict) -> dict:
    """分诊：把最近的指标 + 慢病 +（可选）症状，合成一个行动档位。

    这是康乐左翼的入口 —— 输出不是"您得了什么病"，而是"下一步做什么"：
    保健（在家照顾好）/ 观察（过两天再测）/ 建议就医（帮您就近挂号）/ 紧急（先找家人、120）。
    阈值与合并规则全在 ``app.safety.health_rules``，这里只负责取数、跑规则、摆结论。
    """
    repos, elder_id = turn.ctx.repos, turn.user.get("id")
    # 同上：分诊只认"哪儿难受"，不认"量了哪一项"。模型传 "血压" 进来时，
    # 那句话里没有一处主诉，替它编一条出来就是往分诊结论里掺假。
    symptom = _as_symptom(args.get("symptom"))
    grouped = await _grouped_history(repos, elder_id)
    conditions = await _active_conditions(repos, elder_id)

    if not grouped and not symptom:
        return fail("您先量一下血压或者说说哪儿不舒服，我才好帮您看。")

    overview = triage_overview(grouped, conditions, symptom=symptom)
    drivers = overview["drivers"]
    detail = "；".join(d["reason"] for d in drivers) or "各项都还平稳"
    return ok(
        summary=f"{overview['headline']}{overview['advice']}",
        announce=f"{detail}。{overview['advice']}",
        data={
            "level": overview["level"], "advice": overview["advice"],
            "headline": overview["headline"], "drivers": drivers,
            "symptom": symptom or "",
        },
    )


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
        "register_appointment", "预约挂号（立即办好，挂号成功后会把完整就诊情况知会子女）。",
        {
            "hospital": {"type": "string", "description": "医院名称"},
            "department": {"type": "string", "description": "科室"},
            "doctor": {"type": "string", "description": "医生姓名"},
            "date": {"type": "string", "description": "就诊日期"},
            "time": {"type": "string", "description": "就诊时段（照抄号源结果，如 上午）"},
            "fee": {"type": "number", "description": "从查询结果获得的挂号费（元）"},
            # 这一项是给**知会**用的：没有指标可看时（如旗舰那条只说了"腿疼"），
            # 子女看到的"为什么去"就全落在老人原话上。照抄原话，不要改写成病名。
            "reason": {"type": "string",
                       "description": "这次为什么要挂号（照抄老人原话里的症状，如 腿疼好几天了）；用于把触发原因知会子女"},
        },
        register_appointment, agent="health",
        # 写操作独占执行（不是审批闸门）：挂号仍不许并发发出，但它不等家人点头 ——
        # 审批闸门已经整条挪走了（见 risk_rules.HIGH_RISK_TOOLS）。
        execution_mode=BARRIER, report_key="appointment",
        # 家人看到的那句摘要。挂号已不挂起，正常走不到这里 —— 保留作**兜底**：
        # 万一还有别的路径把这次调用交回确认服务，家人看到的仍是一句人话，
        # 而不是一串字段。日期和时段必须在里面：只写医院和费用，
        # 家人批的就是一件缺了主语的事。
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
        "diet_advice", "根据老人慢性病情况推荐今天的饮食（家常建议，非医疗处方）。",
        {"preference": {"type": "string", "description": "口味偏好，如 清淡软烂"}},
        diet_advice, agent="health", report_key="diet",
    ))

    # —— 左翼·身体核心：记录指标 → 概览 → 分诊。（顺序即使用顺序，注册序不影响调度）
    registry.register(make_tool(
        "log_vital", "记录一条健康指标（血压/血糖/心率/血氧/体温/体重），记完当场给分诊档位。",
        {
            "metric_type": {"type": "string",
                            "enum": list(hr.METRICS),
                            "description": "指标类型：bp=血压 glucose=血糖 heart_rate=心率 spo2=血氧 temperature=体温 weight=体重"},
            "value": {"type": "number", "description": "数值（血压不用填这个，填下面两个）"},
            "systolic": {"type": "number", "description": "血压·收缩压（高压），如 178"},
            "diastolic": {"type": "number", "description": "血压·舒张压（低压），如 105"},
            "context": {"type": "string", "description": "测量情境，血糖要填 空腹/餐后"},
            "measured_at": {"type": "string", "description": "测量时间，不填就是现在"},
            "note": {"type": "string", "description": "备注，如 刚爬完楼"},
        },
        log_vital, agent="health", report_key="vital_logged",
    ))
    registry.register(make_tool(
        "get_health_summary", "汇总最近记录的健康指标（含最近趋势与分诊结论），用于回顾身体状况。",
        {"days": {"type": "number", "description": "回顾天数，默认 7"}},
        get_health_summary, agent="health", report_key="health_summary",
    ))
    registry.register(make_tool(
        "add_condition", "登记一条老人确诊的慢性病（如高血压、糖尿病），用于后续饮食与提醒。",
        {
            "name": {"type": "string", "description": "疾病名称"},
            "diagnosed_at": {"type": "string", "description": "确诊时间"},
            "severity": {"type": "string", "description": "程度，如 轻度/中度"},
            "notes": {"type": "string", "description": "备注，如 吃药控制中"},
        },
        add_condition, agent="health", report_key="condition",
    ))
    registry.register(make_tool(
        "assess_health", "健康分诊：结合最近指标、慢病和症状，给出行动档位（保健/观察/建议就医/紧急）与建议。",
        {"symptom": {"type": "string", "description": "老人自述的不适，如 头晕、胸口闷"}},
        assess_health, agent="health", report_key="assessment",
    ))
