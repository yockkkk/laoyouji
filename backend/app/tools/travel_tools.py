"""出行工具（银发导航）：查票/订票/查酒店/订酒店/路线/叫车。

``report_key`` 是这些工具与《就医出行计划书》的契约：查询结果进
``*_options``，落定结果进单数键。渲染器只认这些键，模型不参与拼装
（见 agents/plan_builder.py 与 core/subagents._build_report）。

订票、订房是**高危写操作** → ``execution_mode=BARRIER``：同批次里独占执行，
绝不允许两笔钱并发发出去。
"""
from __future__ import annotations

from app.core.tool import BARRIER
from app.tools.common import fail, human_date, make_tool, ok


async def search_train(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("train")
    from_city = args.get("from_city") or turn.user.get("city", "南京")
    to_city = args.get("to_city", "")
    if not to_city:
        return fail("请告诉我要去哪个城市")
    trains = await provider.search(from_city, to_city, args.get("date"))
    if not trains:
        return fail(f"没查到 {from_city} 到 {to_city} 的车次")
    lines = [
        f"{t['train_no']} {t['depart']}开 {t['arrive']}到 "
        f"{'；'.join(f'{s['seat_type']}{s['price']}元余{s['remaining']}张' for s in t['seats'])}"
        for t in trains
    ]
    return ok(
        summary=f"查到 {from_city}→{to_city} 车次：\n" + "\n".join(lines),
        data={"trains": trains, "from_city": from_city, "to_city": to_city},
    )


async def book_ticket(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("train")
    ticket = await provider.book(
        args.get("train_no", ""), args.get("date"),
        turn.user.get("name", "乘客"), args.get("seat_type", "二等座"),
    )
    if not ticket.get("ok"):
        return fail(ticket.get("error", "订票失败"))
    return ok(
        summary=(f"已出票：{ticket['date']} {ticket['train_no']} 次 "
                 f"{ticket['seat']}，票价 {ticket['price']} 元，取票号 {ticket['ticket_no']}"),
        announce=ticket["announce"],
        data=ticket,
        card={
            "type": "ticket",
            "title": "高铁票已出票",
            "body": {
                "车次": f"{ticket['train_no']}（{ticket['date']}）",
                "出发": f"{ticket['from_station']} {ticket['depart']} 开",
                "到达": f"{ticket['to_station']} {ticket['arrive']} 到",
                "座位": ticket["seat"],
                "票价": f"{ticket['price']} 元",
                "取票号": ticket["ticket_no"],
                "家人确认": "已确认",
            },
        },
    )


async def search_hotel(turn, args: dict) -> dict:
    """查医院附近的无障碍酒店。

    补这个工具是因为旧版没有它：``book_hotel`` 要一个酒店名，而子智能体手里
    没有任何候选，只能**自己编一个名字**再去订 —— 订不到就整条链断。
    现在先查后订，计划书第三页的地址/电话/步行距离也都有出处。
    """
    provider = turn.ctx.resolve("hotel")
    city = args.get("city", "北京")
    near = args.get("near_hospital") or None
    hotels = await provider.search(city, near, bool(args.get("accessible", True)))
    if not hotels:
        return fail(f"没查到 {city} {near or ''} 附近的无障碍酒店")
    lines = [
        f"{h['name']}：{h['price']}元/晚，离{h['near_hospital']}"
        f"步行{h['walk_min']}分钟（{h['distance_m']}米），{h['accessible_note']}，"
        f"电话{h['phone']}"
        for h in hotels
    ]
    return ok(
        summary=f"{city}{near or ''}附近的无障碍酒店：\n" + "\n".join(lines),
        data={"hotels": hotels, "city": city, "near_hospital": near or ""},
    )


async def plan_route(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("map")
    route = await provider.plan_route(args.get("origin", ""), args.get("destination", ""))
    return ok(summary=route["summary"], data=route)


async def hail_ride(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("ride")
    ride = await provider.hail(args.get("origin", ""), args.get("destination", ""))
    if not ride.get("ok"):
        return fail("叫车失败，请稍后再试")
    return ok(
        summary=f"已叫车：{ride['driver']}（{ride['plate']}）约{ride['eta_min']}分钟到达",
        announce=ride["announce"],
        data=ride,
    )


async def book_hotel(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("hotel")
    result = await provider.book(
        args.get("hotel", ""), args.get("checkin"), int(args.get("nights", 1)),
        turn.user.get("name", "住客"),
    )
    if not result.get("ok"):
        return fail(result.get("error", "订房失败"))
    return ok(
        summary=(f"已订房：{result['hotel']} {result['checkin']} 入住 {result['nights']} 晚，"
                 f"共 {result['total']} 元，{result['walk']}"),
        announce=result["announce"],
        data=result,
        card={
            "type": "hotel",
            "title": "酒店已预订",
            "body": {
                "酒店": result["hotel"],
                "地址": result["address"],
                "入住": f"{result['checkin']}（{result['nights']}晚）",
                "总价": f"{result['total']} 元",
                "电话": result["phone"],
                "到医院": result["walk"],
                "无障碍": result["accessible_note"],
                "家人确认": "已确认",
            },
        },
    )


def register_travel_tools(registry) -> None:
    registry.register(make_tool(
        "search_train", "查询两地之间的高铁车次、时刻和票价。",
        {
            "from_city": {"type": "string", "description": "出发城市，默认用户所在城市"},
            "to_city": {"type": "string", "description": "到达城市"},
            "date": {"type": "string", "description": "出发日期：'tomorrow'、'+2' 或 'YYYY-MM-DD'"},
        },
        search_train, agent="travel", report_key="train_options",
    ))
    registry.register(make_tool(
        "book_ticket", "购买高铁票（需要家人确认后才会真正出票）。",
        {
            "train_no": {"type": "string", "description": "车次号，如 G102"},
            "date": {"type": "string", "description": "出发日期"},
            "seat_type": {"type": "string", "description": "座位类型，如 二等座"},
            "price": {"type": "number", "description": "从查询结果获得的票价（元）"},
            # 下面四项照抄 search_train 选中的那趟车。家人在手机上看到的
            # 就是这份冻结参数，写全了才看得懂自己在批什么；计划书第二页也直接用它。
            "from_station": {"type": "string", "description": "出发车站（照抄查询结果）"},
            "to_station": {"type": "string", "description": "到达车站（照抄查询结果）"},
            "depart": {"type": "string", "description": "发车时刻（照抄查询结果）"},
            "arrive": {"type": "string", "description": "到达时刻（照抄查询结果）"},
        },
        book_ticket, agent="travel",
        execution_mode=BARRIER, report_key="ticket",
        child_summary=lambda a: (f"母亲张桂芳想买 {human_date(a.get('date'))} "
                                 f"{a.get('train_no', '')} 次"
                                 f"高铁票（{a.get('seat_type', '二等座')}），"
                                 f"约 {a.get('price', '?')} 元"),
    ))
    registry.register(make_tool(
        "search_hotel", "查询医院附近的无障碍酒店（含地址、电话、步行距离、房价）。",
        {
            "city": {"type": "string", "description": "城市，如 北京"},
            "near_hospital": {"type": "string", "description": "目标医院全名"},
            "accessible": {"type": "boolean", "description": "是否只要无障碍房，默认 true"},
        },
        search_hotel, agent="travel", report_key="hotel_options",
    ))
    registry.register(make_tool(
        "plan_route", "规划从出发地到目的地的出行路线。",
        {"origin": {"type": "string"}, "destination": {"type": "string"}},
        plan_route, agent="travel", report_key="route",
    ))
    registry.register(make_tool(
        "hail_ride", "为老人叫一辆网约车。",
        {"origin": {"type": "string"}, "destination": {"type": "string"}},
        hail_ride, agent="travel", timeout_s=30.0,
    ))
    registry.register(make_tool(
        "book_hotel", "预订酒店（先用 search_hotel 查到候选，再订；需家人确认）。",
        {
            "hotel": {"type": "string", "description": "酒店名称（照抄 search_hotel 结果）"},
            "checkin": {"type": "string", "description": "入住日期"},
            "nights": {"type": "integer", "description": "住几晚"},
            "price": {"type": "number", "description": "每晚价格（元，照抄查询结果）"},
        },
        book_hotel, agent="travel",
        execution_mode=BARRIER, report_key="hotel",
        child_summary=lambda a: (f"母亲张桂芳想订酒店 {a.get('hotel', '')}，"
                                 f"{human_date(a.get('checkin'))} 入住 "
                                 f"{a.get('nights', 1)} 晚，"
                                 f"约 {a.get('price', '?')} 元/晚"),
    ))
