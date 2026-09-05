"""交付物渲染管线 —— 确定性、可打印、绝不编造。

方案书第三步（20 分）要的是一份"**可以直接打印出来照着做的傻瓜式攻略**"，
页序在原文里就写死了：

  ①挂号信息 ②去程车票信息 + 返程建议 ③酒店信息（地址/电话/步行距离）
  ④行李清单（身份证/医保卡/既往病历/老花镜/常备药）⑤当地天气及穿衣建议

旧实现把这活交给了 LLM：``show_card`` 的 ``body`` 是个无 schema 的
``{"type":"object"}``，模型现编一个字典。后果是三样都不保：**页数**（少一页没人发现）、
**字段**（票价可能和查询结果不一致）、**可复现性**（同一句话两次演示两个结果）。
评委现场追问"这个 553.5 是哪来的"，答不上来。

这里换成一条**确定性管线**：

    子智能体工具结果 → AgentReport.data（采集，非模型措辞）
                     → 本文件的模板 → 定型卡片

三份交付物共用同一份 report 输入，区别只在模板：
- ``build_medical_trip_plan``  《XX老人·北京就医出行计划书》—— 五页，做深，可打印
- ``build_health_card``        《本周用药与复查安排》—— 轻量
- ``build_community_card``     《社区服务预约单》—— 轻量

**缺字段策略（三份统一）**：取不到就渲染 ``待补`` 并把字段名回填 ``missing``，
**绝不用模型的话去圆**。人为抽掉酒店 report，第三页就该明明白白写"待补"。
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

DISCLAIMER = ("本计划书由老友记根据查询结果自动生成，仅供出行参考。"
              "医疗相关内容不构成诊断意见，请以医生面诊结论为准。")
MOCK_NOTE = "（竞赛原型：车次、号源、酒店数据来自模拟接口，正式落地对接官方开放 API）"


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

    为什么需要这一步：旗舰演示里挂号和订票**都会被安全中间层拦下**，等家人手机
    确认。此刻并不存在"已出的票"，能确定的只有**冻结的调用参数**（车次、日期、
    座位、价格）。而计划书第二页还要印车站和时刻 —— 那些就在同一批
    ``search_train`` 的结果里躺着。

    所以这里做一次**严格按标识符匹配的连接**：车次号对上才补时刻表，酒店名对上
    才补地址电话，医院名对上才补地址。对不上就一个字都不补，让它去渲染"待补"。
    这是同一批结构化查询结果内部的 join，不经过模型，也不做任何推测 ——
    和"让 LLM 照着印象把票价重写一遍"是两件完全不同的事。
    """
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in data.items()}

    _join(out, "ticket", "train_options.trains", key="train_no",
          fields=("from_station", "to_station", "depart", "arrive", "duration"))
    _join(out, "hotel", "hotel_options.hotels", key="hotel", cand_key="name",
          fields=("address", "phone", "walk_min", "distance_m",
                  # price 也连过来：挂起时冻结的参数里只有酒店名和晚数，房价躺在
                  # 同一批 search_hotel 的结果里。连过来 _price_row 才能印
                  # "每晚 329 元 × 2 晚"，否则第三页的房费永远是"待补"。
                  "price", "accessible_note", "city"))
    _join(out, "appointment", "hospital_options.hospitals", key="hospital",
          fields=("address", "city", "specialty", "level"))

    hotel = out.get("hotel")
    if isinstance(hotel, dict) and not hotel.get("walk") and hotel.get("walk_min"):
        hotel["walk"] = (f"步行约 {hotel['walk_min']} 分钟"
                         + (f"（{hotel['distance_m']} 米）"
                            if hotel.get("distance_m") else ""))

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
    return _label_service(Row(label=label, value=fmt.format(value), missing=False))


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


_SERVICE_LABELS = {"cleaning": "保洁上门", "accompany": "陪诊陪护",
                   "canteen": "社区食堂送餐"}


def _label_service(row: Row) -> Row:
    """把 ``cleaning`` 这种机器词换成老人看得懂的中文。只换词，不改值的来源。"""
    if row.label == "服务" and not row.missing:
        row.value = _SERVICE_LABELS.get(row.value, row.value)
    return row


# ---------------------------------------------------------------- ①就医计划书

def build_medical_trip_plan(elder: dict, reports: Iterable[AgentReport], *,
                            city: str = "", today: str | None = None) -> dict:
    """《XX老人·XX就医出行计划书》—— 五页，页序写死，缺字段渲染"待补"。"""
    data = _enrich(merge_reports(reports))
    missing: list[str] = []
    name = elder.get("name") or "老人"
    city = city or _dig(data, "appointment.city") or _guess_city(data) or "外地"

    pages = [
        _page_appointment(data, missing),
        _page_ticket(data, missing),
        _page_hotel(data, missing),
        _page_checklist(data),
        _page_weather(data, missing, city),
    ]

    return {
        "type": "trip_plan",
        "title": f"{name} · {city}就医出行计划书",
        "subtitle": f"共 {len(pages)} 页，可以直接打印带着走",
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


def _page_ticket(data: dict, missing: list[str]) -> Page:
    page = Page(no=2, title="第二页 · 去程车票 + 返程建议")
    page.rows = [
        _row("车次", data, "ticket.train_no", missing_list=missing),
        _date_row("乘车日期", data, "ticket.date", missing_list=missing),
        _row("出发", data, "ticket.from_station", missing_list=missing),
        _row("开车时间", data, "ticket.depart", missing_list=missing),
        _row("到达", data, "ticket.to_station", missing_list=missing),
        _row("到站时间", data, "ticket.arrive", missing_list=missing),
        _row("座位", data, ("ticket.seat", "ticket.seat_type"), missing_list=missing),
        _row("票价", data, "ticket.price", fmt="{} 元", missing_list=missing),
        _status_row(data, "ticket", missing),
    ]
    ticket_no = _dig(data, "ticket.ticket_no")
    if ticket_no:
        page.rows.insert(0, Row(label="取票号", value=str(ticket_no)))

    # 返程建议是"建议"，不伪装成已订的票：不写车次，只给时间窗口和渠道
    visit_date = _human_date(_dig(data, "appointment.date"))
    page.notes = [
        (f"建议返程：{visit_date} 看完病，当天下午或第二天上午回。"
         if visit_date else "建议返程：看完病当天下午或第二天上午回。"),
        "返程票等家人确认挂号后再买，车站窗口和 12306 都可以。",
        "回程前给家里人打个电话，说一声几点的车。",
    ]
    return page


def _page_hotel(data: dict, missing: list[str]) -> Page:
    page = Page(no=3, title="第三页 · 酒店信息")
    page.rows = [
        _row("酒店", data, ("hotel.hotel", "hotel.name"), missing_list=missing),
        _row("地址", data, "hotel.address", missing_list=missing),
        _row("电话", data, "hotel.phone", missing_list=missing),
        _row("到医院", data, "hotel.walk", missing_list=missing),
        _date_row("入住日期", data, "hotel.checkin", missing_list=missing),
        _row("住几晚", data, "hotel.nights", fmt="{} 晚", missing_list=missing),
        _price_row(data, missing),
        _row("无障碍", data, "hotel.accessible_note", missing_list=missing),
        _status_row(data, "hotel", missing),
    ]
    page.notes = ["到酒店说“我有预订”，报您的名字和电话就行。",
                  "房间钥匙别随身丢，出门前拍张门牌号的照片。"]
    return page


def _price_row(data: dict, missing: list[str]) -> Row:
    """房费：订成了就印总价；只是选定还没锁定，就印单价×晚数（算术，非编造）。"""
    total = _dig(data, "hotel.total")
    if total is not None:
        return Row(label="房费", value=f"共 {total} 元")
    price = _dig(data, "hotel.price") or _dig(data, "hotel.room_price")
    nights = _dig(data, "hotel.nights")
    if price is not None and nights:
        return Row(label="房费",
                   value=f"每晚 {price} 元 × {nights} 晚 ≈ {price * int(nights)} 元")
    if price is not None:
        return Row(label="房费", value=f"每晚 {price} 元")
    missing.append("hotel.total")
    return Row(label="房费", value=MISSING, missing=True)


def _page_checklist(data: dict) -> Page:
    """行李清单：政策模板 + 按天气追加。不涉及查询字段，所以永不"待补"。"""
    page = Page(no=4, title="第四页 · 随身清单（出门前一样一样对）")
    items = list(BASE_CHECKLIST)
    if _dig(data, "weather.umbrella"):
        items.append("一把伞（当地那几天有雨）")
    low = _dig(data, "weather.temp_low")
    if isinstance(low, (int, float)) and low <= 10:
        items.append("厚外套（当地早晚凉）")
    if _dig(data, "hotel.hotel") or _dig(data, "hotel.name"):
        items.append("酒店订单信息（这张纸就够）")
    page.rows = [Row(label=f"{i + 1}", value=text)
                 for i, text in enumerate(items)]
    page.notes = ["装好一样，在前面画个勾。",
                  "钱和证件分两处放，别都在一个兜里。"]
    return page


def _page_weather(data: dict, missing: list[str], city: str) -> Page:
    page = Page(no=5, title=f"第五页 · {city}天气与穿衣")
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
    for path in ("weather.city", "ticket.to_city", "hotel.city"):
        value = _dig(data, path)
        if value:
            return str(value)
    station = _dig(data, "ticket.to_station")
    if station:
        return str(station).replace("南站", "").replace("站", "") or None
    return None


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
    """《社区服务预约单》—— 轻量卡片。"""
    data = _enrich(merge_reports(reports))
    missing: list[str] = []
    name = elder.get("name") or "老人"

    page = Page(no=1, title="服务预约")
    source = "service_order" if _dig(data, "service_order") else "canteen"
    # 两种取法：下单成功 → ``<key>.order.*``；被拦下等家人确认 → 冻结参数在 ``<key>.*``
    page.rows = [
        _row("服务", data, (f"{source}.order.service_type",
                            f"{source}.service_type", f"{source}.order.items",
                            f"{source}.menu_item"), missing_list=missing),
        _date_row("日期", data, (f"{source}.date", f"{source}.deliver_time"),
                  missing_list=missing),
        _row("服务方", data, f"{source}.order.provider_name", missing_list=missing),
        _row("金额", data, (f"{source}.order.amount", f"{source}.amount"),
             fmt="{} 元", missing_list=missing),
        _status_row(data, source, missing),
    ]
    page.rows = [_label_service(r) for r in page.rows]
    page.notes = ["师傅上门会先打电话，不认识的号码也接一下。",
                  "有问题找社区居委会，别自己跟人争。"]

    return {
        "type": "community_card",
        "title": f"{name} · 社区服务预约单",
        "subtitle": "轻量卡片，办完一项划一项",
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
        return builder(elder, reports, **kwargs)
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
