"""Plan helpers: deduplication, upsert, destination extraction, and notification dispatch."""
from __future__ import annotations

import re
from typing import Any

from app.db.repositories import Repository, utcnow_iso


def extract_destination(data: dict[str, Any] | None) -> str:
    """Extract destination city or location from a plan card or trip dict."""
    if not isinstance(data, dict):
        return ""

    def _clean(c: Any) -> str:
        s = str(c).strip()
        return s[:-1] if s.endswith("市") and len(s) > 2 else s

    # 1. Direct city or destination
    city = data.get("city") or data.get("destination")
    if city:
        return _clean(city)
    # 2. Inside plan object
    plan = data.get("plan")
    if isinstance(plan, dict):
        plan_city = plan.get("city") or plan.get("destination")
        if plan_city:
            return _clean(plan_city)
        body = plan.get("body")
        if isinstance(body, dict):
            for k in ("天气与穿衣/城市", "去程车票 + 返程建议/到达"):
                val = body.get(k)
                if val:
                    clean_val = str(val).replace("南站", "").replace("东站", "").replace("西站", "").replace("北站", "").replace("虹桥", "").replace("站", "").strip()
                    return _clean(clean_val)
            for k, val in body.items():
                if "天气与穿衣" in k:
                    m = re.search(r"(.+?)天气与穿衣", k)
                    if m and m.group(1).strip():
                        return _clean(m.group(1).strip())
                    if val and isinstance(val, str) and "城市" in k:
                        return _clean(val)
                if "去程车票" in k and "到达" in k and val:
                    clean_val = str(val).replace("南站", "").replace("东站", "").replace("西站", "").replace("北站", "").replace("虹桥", "").replace("站", "").strip()
                    return _clean(clean_val)
        pages = plan.get("pages")
        if isinstance(pages, list):
            for p in pages:
                if isinstance(p, dict):
                    p_title = p.get("title") or ""
                    if "天气与穿衣" in p_title:
                        m = re.search(r"·\s*(.+?)天气与穿衣", p_title)
                        if m and m.group(1).strip():
                            return _clean(m.group(1).strip())
                    for r in p.get("rows") or []:
                        if isinstance(r, dict) and r.get("label") == "到达" and r.get("value"):
                            v = str(r.get("value")).replace("南站", "").replace("东站", "").replace("西站", "").replace("北站", "").replace("虹桥", "").replace("站", "").strip()
                            if v:
                                return _clean(v)
    # 3. From title or purpose
    title = data.get("title") or data.get("purpose") or ""
    for known in ("北京", "上海", "杭州", "南京", "苏州", "广州", "深圳", "成都", "重庆", "武汉", "西安", "青岛", "黄山"):
        if known in title:
            return known
    scenic_map = {
        "西湖": "杭州",
        "故宫": "北京",
        "长城": "北京",
        "天安门": "北京",
        "外滩": "上海",
        "东方明珠": "上海",
        "迪士尼": "上海",
        "夫子庙": "南京",
        "玄武湖": "南京",
        "中山陵": "南京",
        "鼓楼医院": "南京",
        "兵马俑": "西安",
        "大雁塔": "西安",
        "积水潭": "北京",
        "协和": "北京",
        "同仁": "北京",
        "华西": "成都",
        "湘雅": "长沙",
        "瑞金": "上海",
        "华山医院": "上海",
    }
    for spot, city_name in scenic_map.items():
        if spot in title:
            return city_name
    if "·" in title:
        part = title.split("·")[-1]
        cleaned = (
            part.replace("就医出行计划书", "")
            .replace("出行计划书", "")
            .replace("就医计划", "")
            .replace("出行计划", "")
            .replace("两日游", "")
            .replace("三日游", "")
            .replace("游玩", "")
            .replace("计划书", "")
            .strip()
        )
        if cleaned:
            return _clean(cleaned)
    return ""


def is_same_plan(t1: dict[str, Any], t2: dict[str, Any]) -> bool:
    """Determine if two trips or plans represent the same plan."""
    p1 = (t1.get("purpose") or (t1.get("plan") or {}).get("title") or "").strip()
    p2 = (t2.get("purpose") or (t2.get("plan") or {}).get("title") or "").strip()
    if p1 and p2 and p1 == p2:
        return True
    d1 = extract_destination(t1)
    d2 = extract_destination(t2)
    if d1 and d2 and d1 == d2:
        kind1 = (t1.get("plan") or {}).get("type") or ("medical_plan" if "就医" in p1 else "trip_plan")
        kind2 = (t2.get("plan") or {}).get("type") or ("medical_plan" if "就医" in p2 else "trip_plan")
        if kind1 == kind2:
            return True
    return False


async def upsert_trip_plan(
    repos: Repository, elder_id: str, card: dict[str, Any], status: str = "planned"
) -> tuple[dict[str, Any], bool]:
    """Upsert an active plan for elder_id. If an active plan with same purpose/destination exists,
    update it; otherwise insert a new trip. Also remove any duplicate rows.
    Returns (trip_dict, was_created).
    """
    existing_trips = await repos.list("trips", where={"elder_id": elder_id}, order="-created_at")
    active_matches: list[dict[str, Any]] = []
    target_dummy = {"purpose": card.get("title", ""), "plan": card}

    for t in existing_trips:
        t_status = t.get("status") or "planned"
        if t_status in ("planned", "ongoing") and is_same_plan(t, target_dummy):
            active_matches.append(t)

    if active_matches:
        primary = active_matches[0]
        updated = await repos.update(
            "trips",
            primary["id"],
            {
                "purpose": card.get("title"),
                "plan": card,
                "status": primary.get("status") or status,
                "updated_at": utcnow_iso(),
            },
        )
        for dup in active_matches[1:]:
            await repos.delete("trips", dup["id"])
        return updated or primary, False
    else:
        inserted = await repos.insert(
            "trips",
            {
                "elder_id": elder_id,
                "purpose": card.get("title"),
                "plan": card,
                "status": status,
            },
        )
        return inserted, True


async def deduplicate_trips_for_elder(repos: Repository, elder_id: str) -> list[dict[str, Any]]:
    """Clean up duplicate trips for elder_id in repository, returning unique trips."""
    all_trips = await repos.list("trips", where={"elder_id": elder_id}, order="-created_at")
    unique_trips: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for t in all_trips:
        dest = extract_destination(t)
        p = t.get("purpose") or (t.get("plan") or {}).get("title") or ""
        t_status = t.get("status") or "planned"
        p_type = (t.get("plan") or {}).get("type") or ("medical_plan" if "就医" in p else "trip_plan")
        if t_status in ("planned", "ongoing"):
            key = f"active:{dest}:{p_type}" if dest else f"active:{p}"
        else:
            key = f"terminal:{t.get('id')}"

        if key in seen_keys:
            await repos.delete("trips", t["id"])
        else:
            seen_keys.add(key)
            unique_trips.append(t)
    return unique_trips


async def dispatch_plan_created_notification(
    repos: Repository, elder: dict[str, Any], card: dict[str, Any], trip_id: str, kind: str
) -> list[dict[str, Any]]:
    """Create unread notifications in 'notifications' table for bound family members."""
    elder_id = elder.get("id")
    if not elder_id:
        return []
    elder_name = elder.get("name") or "张桂芳"
    plan_title = card.get("title") or "新计划"
    notification_title = f"老人{elder_name}已规划《{plan_title}》（母亲{elder_name}行程方案）"
    pages_count = len(card.get("pages") or [])
    subtitle = card.get("subtitle") or f"共 {pages_count} 页计划书，随时可在子女看板查看详情与守护行程。"

    bindings = await repos.list("family_bindings", where={"elder_id": elder_id})
    active_bindings = [b for b in bindings if b.get("status") in (None, "active")]

    created_notifs: list[dict[str, Any]] = []
    seen_children: set[str] = set()
    for b in active_bindings:
        child_id = b.get("child_id")
        if not child_id or child_id in seen_children:
            continue
        seen_children.add(child_id)
        notif = await repos.insert(
            "notifications",
            {
                "user_id": child_id,
                "elder_id": elder_id,
                "title": notification_title,
                "summary": subtitle,
                "type": "plan_created",
                "is_read": False,
                "data": {
                    "trip_id": trip_id,
                    "plan_title": plan_title,
                    "kind": kind,
                    "city": extract_destination(card),
                },
                "created_at": utcnow_iso(),
            },
        )
        created_notifs.append(notif)
    return created_notifs
