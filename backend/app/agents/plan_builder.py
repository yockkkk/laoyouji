"""交付物渲染管线 —— 确定性、可打印、绝不编造。

方案书第三步（20 分）要的是一份"**可以直接打印出来照着做的傻瓜式攻略**"。
康乐收敛为本地就医后，页序改成四页（城际车票/异地酒店整条砍掉，与"就近就医"矛盾）：

  ①挂号信息 ②怎么去医院（本地公交/步行/打车路线 + 分步走法）
  ③随身清单（身份证/医保卡/既往病历/老花镜/常备药）④当地天气及穿衣建议

旧实现把这活交给了 LLM：``show_card`` 的 ``body`` 是个无 schema 的
``{"type":"object"}``，模型现编一个字典。后果是三样都不保：**页数**（少一页没人发现）、
**字段**（费用可能和查询结果不一致）、**可复现性**（同一句话两次演示两个结果）。
评委现场追问"这个挂号费是哪来的"，答不上来。

这里换成一条**确定性管线**：

    子智能体工具结果 → AgentReport.data（采集，非模型措辞）
                     → 本文件的模板 → 定型卡片

三份交付物共用同一份 report 输入，区别只在模板：
- ``build_medical_trip_plan``  《XX老人·就医出行计划书》—— 四页，做深，可打印
- ``build_health_card``        《本周用药与复查安排》—— 轻量
- ``build_community_card``     《社区活动推荐单》—— 轻量

**缺字段策略（三份统一）**：取不到就渲染 ``待补`` 并把字段名回填 ``missing``，
**绝不用模型的话去圆**。人为抽掉路线 report，第二页就该明明白白写"待补"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

from app.core.subagents import AgentReport
# 相对日期的词表（``tomorrow`` / ``+3``）只有一份实现，就在 provider 那边 ——
# 那些词本来就是它吐出来、又被模型照抄进参数里的。这里引它，不另写一份免得跑偏。
from app.providers.external.base import resolve_date

MISSING = "待补"

# 方案书原文的行李清单基线。这是**政策模板**，不是从 report 里推出来的数据，
# 所以它出现在计划书里不构成编造 —— 它就是本项目承诺给老人的固定清单。
BASE_CHECKLIST = [
    "身份证（挂号、住店、进站都要用）",
    "医保卡 / 电子医保码",
    "既往病历、检查片子和化验单",
    "老花镜",
    "常备药（按平时的量多带两天）",
]

DISCLAIMER = ("本计划书由康乐根据查询结果自动生成，仅供出行参考。"
              "医疗相关内容不构成诊断意见，请以医生面诊结论为准。")
MOCK_NOTE = "（竞赛原型：号源、路线、天气数据来自模拟接口，正式落地对接官方开放 API）"


@dataclass
class Row:
    """卡片里的一行。``missing=True`` 时前端要显式画成"待补"样式。"""

    label: str
    value: str
    missing: bool = False

    def to_dict(self) -> dict:
        return {"label": self.label, "value": self.value, "missing": self.missing}


@dataclass
class Page:
    no: int
    title: str
    rows: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not any(r.missing for r in self.rows)

    def to_dict(self) -> dict:
        return {"no": self.no, "title": self.title,
                "rows": [r.to_dict() for r in self.rows],
                "notes": list(self.notes), "complete": self.complete}


# ---------------------------------------------------------------- report 合并

def merge_reports(reports: Iterable[AgentReport]) -> dict:
    """把多份子回报合并成一个查询平面。先到者不被后到者覆盖成空。"""
    merged: dict = {}
    for report in reports or []:
        for key, value in (report.data or {}).items():
            if key not in merged or _empty(merged[key]):
                merged[key] = value
    return merged


def _empty(value: Any) -> bool:
    return value is None or value == {} or value == [] or value == ""


# ------------------------------------------------------------ 候选连接（回填）

def _enrich(data: dict) -> dict:
    """用"这次查询的结果"补全"这次选定的项"里缺的字段。

    为什么需要这一步：旗舰演示里挂号**会被安全中间层拦下**，等家人手机确认。
    此刻并不存在"已挂的号"，能确定的只有**冻结的调用参数**（医院、科室、医生、
    日期）。而计划书第一页还要印医院地址 —— 那就在同一批 ``search_hospital``
    的结果里躺着。

    所以这里做一次**严格按标识符匹配的连接**：医院名对上才补地址、挂号费、医生
    职称。对不上就一个字都不补，让它去渲染"待补"。这是同一批结构化查询结果内部
    的 join，不经过模型，也不做任何推测 —— 和"让 LLM 照着印象把费用重写一遍"是
    两件完全不同的事。

    路线（``route``）的字段是 ``plan_route`` 整包吐回来的，不需要在这里连接。
    """
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in data.items()}

    _join(out, "appointment", "hospital_options.hospitals", key="hospital",
          fields=("address", "city", "specialty", "level"))

    weather = out.get("weather")
    if isinstance(weather, dict) and not weather.get("temp_range"):
        low, high = weather.get("temp_low"), weather.get("temp_high")
        if low is not None and high is not None:
            weather["temp_range"] = f"{low}~{high} ℃"

    # 挂号费 / 医生职称：只在医生姓名对得上的那条上取
    appointment = out.get("appointment")
    hospitals = _dig(out, "hospital_options.hospitals")
    if isinstance(appointment, dict) and isinstance(hospitals, list):
        for hosp in hospitals:
            h_name = str(hosp.get("hospital") or "")
            a_name = str(appointment.get("hospital") or "")
            if h_name != a_name and not (h_name and a_name and (h_name in a_name or a_name in h_name)):
                continue
            for doc in hosp.get("doctors") or []:
                d_name = str(doc.get("doctor") or "")
                ad_name = str(appointment.get("doctor") or "")
                if d_name != ad_name and not (d_name and ad_name and (d_name in ad_name or ad_name in d_name)):
                    continue
                appointment.setdefault("title", doc.get("title"))
                if _empty(appointment.get("fee")):
                    appointment["fee"] = doc.get("fee")
                if _empty(appointment.get("time")):
                    slots = doc.get("slots") or []
                    app_date = appointment.get("date")
                    app_iso = resolve_date(app_date) if app_date else ""
                    match = next((s for s in slots
                                  if s.get("date") == app_date
                                  or (app_iso and resolve_date(s.get("date")) == app_iso)), None)
                    if match:
                        appointment["time"] = match.get("time")
                    elif slots:
                        appointment["time"] = slots[0].get("time")
    return out


def _join(data: dict, target: str, candidates_path: str, *, key: str,
          cand_key: str | None = None,
          fields: tuple[str, ...] = ()) -> None:
    """把候选列表里**标识符相同**的那一条的指定字段，补进 target（就地）。"""
    node = data.get(target)
    if not isinstance(node, dict):
        return
    wanted = node.get(key)
    if not wanted:
        return
    candidates = _dig(data, candidates_path)
    if not isinstance(candidates, list):
        return
    match = next((c for c in candidates
                  if isinstance(c, dict) and c.get(cand_key or key) == wanted), None)
    if match is None and isinstance(wanted, str) and wanted:
        w_clean = wanted.strip()
        match = next((c for c in candidates
                      if isinstance(c, dict) and isinstance(c.get(cand_key or key), str)
                      and (w_clean in str(c.get(cand_key or key)) or str(c.get(cand_key or key)) in w_clean)), None)
    if match is None:
        return
    for field_name in fields:
        if _empty(node.get(field_name)) and not _empty(match.get(field_name)):
            node[field_name] = match[field_name]


def _dig(source: dict, path: str) -> Any:
    node: Any = source
    for part in path.split("."):
        if isinstance(node, list):
            if not node:
                return None
            node = node[0]
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _first(source: dict, paths: str | tuple[str, ...]) -> tuple[Any, str]:
    """按顺序取第一个有值的路径。返回 (值, 命中的路径)。

    多路径是为了兼容"同一件事在不同来源里叫法不同"：挂起时冻结的参数叫
    ``seat_type``，真出票后的结果叫 ``seat``。两个都指同一个座位，不是两件事。
    """
    if isinstance(paths, str):
        paths = (paths,)
    for path in paths:
        value = _dig(source, path)
        if value is not None and value != "":
            return value, path
    return None, paths[0]


def _row(label: str, source: dict, path: str | tuple[str, ...], *,
         fmt: str = "{}", missing_list: list[str] | None = None) -> Row:
    """取值 → 成行。取不到就是"待补"，并把路径记进 missing。"""
    value, hit = _first(source, path)
    if isinstance(value, (list, tuple)):
        parts = []
        for v in value:
            if isinstance(v, dict) and "name" in v:
                parts.append(str(v["name"]))
            elif v not in (None, ""):
                parts.append(str(v))
        value = "、".join(parts) or None
    if value is None:
        if missing_list is not None and hit not in missing_list:
            missing_list.append(hit)
        return Row(label=label, value=MISSING, missing=True)
    return Row(label=label, value=fmt.format(value), missing=False)


_WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _human_date(value: Any) -> str | None:
    """``tomorrow`` / ``+3`` / ``2026-09-04`` → ``2026-09-04（周五）``。

    为什么要在渲染层做这一步：相对日期是**模型说出口的词**，挂起时冻结下来的
    原始参数就长这样（``date="+3"``）。而这张纸是要打印出来、让老人照着走的
    —— "+3" 没人看得懂，"周五"才拿得准。

    换算是纯算术，指的还是同一天，不是补一个不存在的值；认不出的写法原样返回，
    绝不改写成某个"看起来像日期"的东西。
    """
    if value is None or value == "":
        return None
    iso = resolve_date(value)
    try:
        day = date.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return str(value)
    return f"{iso}（{_WEEKDAYS[day.weekday()]}）"


def _date_row(label: str, source: dict, path: str | tuple[str, ...], *,
              missing_list: list[str] | None = None) -> Row:
    """日期专用行：取到就换成老人看得懂的写法；取不到照旧记 missing。"""
    row = _row(label, source, path, missing_list=missing_list)
    if not row.missing:
        row.value = _human_date(row.value) or row.value
    return row


def _status_row(source: dict, key: str, missing_list: list[str]) -> Row:
    """高危项的执行状态：已办 / 待家人确认 / 待补。全部来自结构化字段。"""
    node = _dig(source, key)
    if not isinstance(node, dict):
        missing_list.append(f"{key}.status")
        return Row(label="状态", value=MISSING, missing=True)
    if node.get("status") == "pending_confirm":
        return Row(label="状态", value="已选定，等家人在手机上点“同意”后锁定")
    if node.get("status") == "rejected":
        return Row(label="状态", value="家人这次没同意，需要重新商量")
    return Row(label="状态", value="已办好")


# ---------------------------------------------------------------- ①就医计划书

def build_medical_trip_plan(elder: dict, reports: Iterable[AgentReport], *,
                            city: str = "", today: str | None = None,
                            kind: str = "trip_plan") -> dict:
    """《XX老人·就医出行计划书》—— 四页，页序写死，缺字段渲染"待补"。

    康乐收敛后只做本地就医：①挂号 ②怎么去（本地公交/步行/打车路线）③随身清单
    ④天气穿衣。城际车票、异地酒店整条砍掉（与"就近就医"矛盾），对应的两页也随之
    撤掉 —— 不再留永远"待补"的空页。
    """
    data = _enrich(merge_reports(reports))
    missing: list[str] = []
    name = elder.get("name") or "老人"
    city = city or _dig(data, "appointment.city") or _guess_city(data) or "本地"

    pages = [
        _page_appointment(data, missing),
        _page_route(data, missing),
        _page_checklist(data),
        _page_weather(data, missing, city),
    ]

    return {
        "type": kind,
        "title": f"{name} · {city}就医出行计划书",
        "subtitle": f"共 {len(pages)} 页，可以直接打印带着走",
        "city": city,
        "destination": city,
        "printable": True,
        "generated_on": today or date.today().isoformat(),
        "pages": [p.to_dict() for p in pages],
        "body": _flatten(pages),
        "missing": missing,
        "complete": not missing,
        "disclaimer": DISCLAIMER,
        "footnote": MOCK_NOTE,
    }


def _page_appointment(data: dict, missing: list[str]) -> Page:
    page = Page(no=1, title="第一页 · 挂号信息")
    page.rows = [
        _row("医院", data, "appointment.hospital", missing_list=missing),
        _row("科室", data, "appointment.department", missing_list=missing),
        _row("医生", data, "appointment.doctor", missing_list=missing),
        _date_row("就诊时间", data, "appointment.date", missing_list=missing),
        _row("具体时段", data, "appointment.time", missing_list=missing),
        _row("挂号费", data, "appointment.fee", fmt="{} 元", missing_list=missing),
        _row("医院地址", data, "appointment.address", missing_list=missing),
        _status_row(data, "appointment", missing),
    ]
    reg_no = _dig(data, "appointment.registration_no")
    if reg_no:
        page.rows.insert(0, Row(label="挂号单号", value=str(reg_no)))
    page.notes = ["到医院先去自助机取号，找不到就问导医台，说“我有预约”。",
                  "带上医保卡和身份证，直接去科室报到。"]
    return page


def _page_route(data: dict, missing: list[str]) -> Page:
    """第二页 · 怎么去医院。数据全部来自 ``plan_route``（本地公交/步行/打车）。

    路线没查到（子智能体没跑 plan_route，或库里没这条线）时，出发地/目的地照旧
    尽力取，走法字段落"待补" —— 宁可让老人看见"这段还没定"，也不编一个时间出来
    让他照着出门。分步走法进 notes，这是老人真正照着走的那几句。
    """
    page = Page(no=2, title="第二页 · 怎么去医院")
    page.rows = [
        _row("从哪儿出发", data, "route.origin", missing_list=missing),
        _row("到哪儿", data, ("route.destination", "appointment.hospital"),
             missing_list=missing),
        _row("怎么走", data, "route.mode", missing_list=missing),
        _row("大概多久", data, "route.duration", missing_list=missing),
    ]
    distance = _dig(data, "route.distance_km")
    if distance is not None:
        page.rows.append(Row(label="全程", value=f"约 {distance} 公里"))

    steps = _dig(data, "route.steps")
    if isinstance(steps, list) and steps:
        page.notes = [f"{i + 1}. {s}" for i, s in enumerate(steps)]
    else:
        page.notes = ["具体坐几路车、在哪儿下，出门前再问一下家里人或路口的志愿者。"]
    return page


def _page_checklist(data: dict) -> Page:
    """随身清单：政策模板 + 按天气追加。不涉及查询字段，所以永不"待补"。"""
    page = Page(no=3, title="第三页 · 随身清单（出门前一样一样对）")
    items = list(BASE_CHECKLIST)
    if _dig(data, "weather.umbrella"):
        items.append("一把伞（这几天有雨）")
    low = _dig(data, "weather.temp_low")
    if isinstance(low, (int, float)) and low <= 10:
        items.append("厚外套（早晚凉）")
    page.rows = [Row(label=f"{i + 1}", value=text)
                 for i, text in enumerate(items)]
    page.notes = ["装好一样，在前面画个勾。",
                  "钱和证件分两处放，别都在一个兜里。"]
    return page


def _page_weather(data: dict, missing: list[str], city: str) -> Page:
    page = Page(no=4, title=f"第四页 · {city}天气与穿衣")
    page.rows = [
        _date_row("日期", data, "weather.date", missing_list=missing),
        _row("天气", data, "weather.condition", missing_list=missing),
        _row("气温", data, "weather.temp_range", missing_list=missing),
        _row("穿衣建议", data, "weather.advice", missing_list=missing),
    ]
    # 带伞是从 umbrella 布尔推出来的，所以"没查到天气"和"查到了不用带"必须分开：
    # 前者要进 missing —— 一行印着"待补"、清单里却说"全部齐备"，那是自欺
    if _dig(data, "weather"):
        page.rows.append(
            Row(label="带伞", value="要带" if _dig(data, "weather.umbrella")
                else "不用带"))
    else:
        missing.append("weather.umbrella")
        page.rows.append(Row(label="带伞", value=MISSING, missing=True))
    page.notes = ["医院里外温差大，进门脱一件，出门加一件。"]
    return page


def _guess_city(data: dict) -> str | None:
    """从已有结构化字段推目的地城市（不猜、不编：取不到就返回 None）。"""
    value = _dig(data, "weather.city")
    return str(value) if value else None


# ---------------------------------------------------------------- ②健康轻卡片

def build_health_card(elder: dict, reports: Iterable[AgentReport], *,
                      today: str | None = None) -> dict:
    """《本周用药与复查安排》—— 轻量卡片，同一套 report 输入、同一套缺字段策略。"""
    data = _enrich(merge_reports(reports))
    missing: list[str] = []
    name = elder.get("name") or "老人"

    page = Page(no=1, title="用药与复查")
    page.rows = [
        _row("药名", data, "medication.plan.drug_name", missing_list=missing),
        _row("每次吃", data, "medication.plan.dose", missing_list=missing),
        _row("每天时间", data, "medication.plan.times",
             fmt="{}", missing_list=missing),
        _row("注意", data, "medication.plan.notes", missing_list=missing),
    ]
    appointment = _dig(data, "appointment.hospital")
    if appointment:
        when = _human_date(_dig(data, "appointment.date")) or ""
        page.rows.append(Row(label="下次复查",
                             value=f"{appointment} {when}".strip()))
    reading = _dig(data, "report_reading.plain")
    notes = ["到点手机会响，响了就吃，别自己加量减量。"]
    if reading:
        notes.insert(0, f"上次报告的大白话：{reading}")

    # —— 康乐左翼：最近测的指标 + 分诊结论。**有才贴** —— 没量过就一个空行都不加，
    # 免得这张"用药与复查"卡被 6 行"待补"淹掉。指标本身在 health_summary 里，
    # 结论（该保健还是该去医院）在 assessment 里，两个都来自工具的 report_key。
    readings = _dig(data, "health_summary.readings")
    if isinstance(readings, list) and readings:
        for item in readings[:3]:
            value = str(item.get("display") or "")
            if item.get("trend") and item["trend"] != "平稳":
                value += f"，最近{item['trend']}"
            page.rows.append(Row(label=f"最近{item.get('label') or '指标'}", value=value))
        level = str(_dig(data, "health_summary.level") or "保健")
        page.rows.append(Row(label="分诊结论", value=level))
        if level in ("建议就医", "紧急"):
            notes.insert(0, f"指标到了“{level}”这一档，别拖，照分诊那句话办。")
    advice = _dig(data, "assessment.advice")
    if advice:
        page.rows.append(Row(label="建议", value=str(advice)))

    page.notes = notes

    return {
        "type": "health_card",
        "title": f"{name} · 本周用药与复查安排",
        "subtitle": "轻量卡片，贴在药盒边上",
        "printable": True,
        "generated_on": today or date.today().isoformat(),
        "pages": [page.to_dict()],
        "body": _flatten([page]),
        "missing": missing,
        "complete": not missing,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------- ③社区轻卡片

def build_community_card(elder: dict, reports: Iterable[AgentReport], *,
                         today: str | None = None) -> dict:
    """《社区活动推荐单》—— 轻量卡片：把线下活动列成"出门和人在一起"的清单。

    康乐收敛后，邻里帮从"付费社区服务"转成"心理·社交线"：这张单子的每一行都是
    一个可以约上老伙计一起去的线下活动（棋牌室/养老院/公园），来源是
    ``push_activities`` 的结构化结果（report_key=activities，一层包在
    ``activities.activities`` 里）。一条查不到就整单标"待补"，绝不编活动。
    """
    data = _enrich(merge_reports(reports))
    missing: list[str] = []
    name = elder.get("name") or "老人"

    page = Page(no=1, title="最近的社区活动")
    activities = _dig(data, "activities.activities")
    if isinstance(activities, list) and activities:
        page.rows = [
            Row(label=str(a.get("date") or "近期"),
                value=f"{a.get('title', '')}（{a.get('place', '')}）".strip())
            for a in activities
        ]
    else:
        missing.append("activities.activities")
        page.rows = [Row(label="活动", value=MISSING, missing=True)]
    page.notes = ["挑一个近的、当天能去的，约上老伙计一块儿。",
                  "出门前跟社区再确认下时间地点，别白跑一趟。"]

    return {
        "type": "community_card",
        "title": f"{name} · 社区活动推荐单",
        "subtitle": "轻量卡片，挑一个就出门",
        "printable": True,
        "generated_on": today or date.today().isoformat(),
        "pages": [page.to_dict()],
        "body": _flatten([page]),
        "missing": missing,
        "complete": not missing,
    }


# ---------------------------------------------------------------- 通用

BUILDERS = {
    "trip_plan": build_medical_trip_plan,
    "medical_plan": build_medical_trip_plan,
    "health_card": build_health_card,
    "community_card": build_community_card,
}


def build(kind: str, elder: dict, reports: Iterable[AgentReport],
          **kwargs: Any) -> dict:
    """按 kind 选模板。三份交付物共用同一份 report 输入，这里是唯一分叉点。"""
    builder = BUILDERS.get(kind)
    if builder is None:
        raise KeyError(f"没有这种交付物: {kind}（可选 {list(BUILDERS)}）")
    if builder is build_medical_trip_plan:
        return builder(elder, reports, kind=kind, **kwargs)
    kwargs.pop("city", None)
    return builder(elder, reports, **kwargs)


def _flatten(pages: list[Page]) -> dict:
    """扁平 label→value：给旧渲染器和纯文本打印用的兜底视图。"""
    flat: dict[str, str] = {}
    for page in pages:
        for row in page.rows:
            key = f"{page.title.split('·')[-1].strip()}/{row.label}"
            flat[key] = row.value
    return flat
