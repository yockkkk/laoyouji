"""社区服务工具（邻里帮）：食堂订餐/保洁陪诊下单/订单进度/活动推送。"""
from __future__ import annotations

from app.core.tool import BARRIER
from app.providers.external.community import MockCommunityProvider
from app.tools.common import fail, human_date, make_tool, ok


async def canteen_order(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("community")
    menu = await provider.menu()
    item_name = (args.get("menu_item") or "").strip()
    item = next((m for m in menu if item_name in m["name"] or m["name"] in item_name), None)
    if not item and item_name:
        item = next((m for m in menu if item_name in m.get("detail", "")
                     or any(t in item_name for t in m.get("tag", []))), None)
    if not item and menu:
        item = menu[0]  # 默认提供适老软食套餐A
    count = int(args.get("count", 1))
    amount = item["price"] * count
    order = await turn.ctx.repos.insert("orders", {
        "elder_id": turn.user.get("id"),
        "service_type": "canteen",
        "items": [{"name": item["name"], "count": count, "price": item["price"]}],
        "amount": amount,
        "status": "dispatching",
        "provider_name": "社区食堂",
        "timeline": [
            {"at": _now(), "text": "订餐已创建"},
            {"at": _now(), "text": f"食堂已接单，{args.get('deliver_time', '11:30')} 送达"},
        ],
    })
    return ok(
        summary=f"已订餐：{item['name']}×{count}，共 {amount} 元，"
                f"{args.get('deliver_time', '11:30')} 送到家",
        announce=(f"饭订好啦！{item['name']}，{args.get('deliver_time', '11:30')} "
                  f"送到家。一共 {amount} 块钱。"),
        data={"order": order},
        card={
            "type": "canteen_order",
            "title": "社区食堂订餐成功",
            "body": {
                "套餐": f"{item['name']} ×{count}",
                "菜品": item["detail"],
                "标签": "、".join(item["tag"]),
                "金额": f"{amount} 元",
                "送达": args.get("deliver_time", "11:30"),
                "订单号": order["id"][:8],
            },
        },
    )


async def order_service(turn, args: dict) -> dict:
    service_type = args.get("service_type", "cleaning")  # cleaning | accompany
    provider = turn.ctx.resolve("community")
    catalog = await provider.service_catalog(service_type)
    if not catalog:
        return fail("该服务暂时没有可用的服务人员")
    chosen = catalog[0]
    amount = (chosen.get("price_per_hour", 35) * int(args.get("hours", 2))
              if service_type == "cleaning" else chosen.get("price_half_day", 150))
    label = "保洁" if service_type == "cleaning" else "陪诊"
    order = await turn.ctx.repos.insert("orders", {
        "elder_id": turn.user.get("id"),
        "service_type": service_type,
        "items": [{"name": f"{label}服务", "provider": chosen["name"],
                   "date": args.get("date", ""), "hours": args.get("hours", 2)}],
        "amount": amount,
        "status": "pending_confirm",
        "provider_name": chosen["name"],
        "timeline": MockCommunityProvider.initial_timeline(label, chosen["name"]),
    })
    return ok(
        summary=f"已创建{label}服务订单：{chosen['name']}，{args.get('date', '')}，"
                f"预计 {amount} 元（等待家人确认后派单）",
        announce=f"{label}服务帮您约上了，等家人确认后就有师傅联系您。",
        data={"order": order},
    )


async def query_order_status(turn, args: dict) -> dict:
    orders = await turn.ctx.repos.list(
        "orders", where={"elder_id": turn.user.get("id")},
        order="-created_at", limit=5,
    )
    if not orders:
        return fail("暂时没有订单")
    lines = [
        f"{_type_label(o.get('service_type'))}：{o.get('provider_name', '')}，"
        f"{o.get('amount', 0)}元，状态：{_status_label(o.get('status'))}"
        for o in orders
    ]
    return ok(summary="最近的订单：\n" + "\n".join(lines), data={"orders": orders})


async def push_activities(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("community")
    activities = await provider.activities()
    lines = [f"{a['title']}：{a['date']}，{a['place']}" for a in activities]
    return ok(
        summary="最近的社区活动：\n" + "\n".join(lines),
        announce="社区最近有活动：" + "；".join(a["title"] for a in activities[:3]) + "。",
        data={"activities": activities},
    )


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _type_label(t: str | None) -> str:
    return {"canteen": "食堂订餐", "cleaning": "保洁", "accompany": "陪诊"}.get(t or "", t or "订单")


def _status_label(s: str | None) -> str:
    return {
        "pending_confirm": "等家人确认", "dispatching": "派单中",
        "in_progress": "服务中", "done": "已完成", "cancelled": "已取消",
    }.get(s or "", s or "")


def register_community_tools(registry) -> None:
    registry.register(make_tool(
        "canteen_order", "在社区食堂订餐（软食/低糖套餐，送餐上门）。",
        {
            "menu_item": {"type": "string", "description": "套餐名，如 软食套餐A"},
            "count": {"type": "integer", "description": "份数"},
            "deliver_time": {"type": "string", "description": "送达时间，如 11:30"},
        },
        canteen_order, agent="community",
        # 下单即写库、即产生金额 → 独占执行（小额由 PaymentRiskRule 放行，
        # 但"两笔订单并发发出"这种事在任何金额下都不该发生）
        execution_mode=BARRIER, report_key="canteen",
        child_summary=lambda a: f"妈妈想在社区食堂订餐（{a.get('menu_item', '')}）",
    ))
    registry.register(make_tool(
        "order_service", "预约保洁或陪诊服务（费用需家人确认后派单）。",
        {
            "service_type": {"type": "string", "enum": ["cleaning", "accompany"],
                             "description": "cleaning=保洁，accompany=陪诊"},
            "date": {"type": "string", "description": "服务日期"},
            "hours": {"type": "integer", "description": "保洁时长（小时）"},
        },
        order_service, agent="community",
        execution_mode=BARRIER, report_key="service_order",
        child_summary=lambda a: (f"妈妈想预约{'保洁' if a.get('service_type') == 'cleaning' else '陪诊'}服务"
                                 f"（{human_date(a.get('date'))}）"),
    ))
    registry.register(make_tool(
        "query_order_status", "查询最近的社区服务订单状态。",
        {}, query_order_status, agent="community",
    ))
    registry.register(make_tool(
        "push_activities", "查询最近的社区活动信息。",
        {}, push_activities, agent="community", report_key="activities",
    ))
