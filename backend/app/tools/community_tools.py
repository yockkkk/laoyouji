"""心理·社交线工具（邻里帮）：一键联系 + 线下活动 + 散步环线 + 家常食谱。

康乐的两只翅膀里，右边这只管"心里舒坦"。四件事按老人真实的心理需要排：

1. **一键拨号**（``suggest_call``）—— 老人说"心里闷、一个人没意思"，话术安慰只是半件事，
   另外半件是**让他此刻就能听见家人的声音**。号码从 ``family_bindings`` 读绑定关系
   现取，一个字都不写在代码里：写死的号码会在换人演示时打给一个错的陌生人。
   老人认知负荷已经很高，所以这张卡上只有一个动作 —— 点一下，拨出去。
2. **线下活动**（``push_activities``）—— 棋牌室/养老院/公园/义诊，走出家门才是解闷的正路。
3. **散步环线**（``suggest_walk``）—— 只给现成的环形路线，说清多远、多久、在哪儿歇。
   距离与用时**只有一个出处**（``walk_estimate`` 按慢速算），别处不许手写"约 40 分钟"。
4. **家常菜谱**（``get_recipe``）—— 一个人吃饭也要吃得像样。

红线 R1/R2/R4 的双层把关：
- **代码层**：食谱只谈做法与口感（软烂、少盐、少油），个性化最多到"您有高血压，
  我挑了一道盐少的"这一层；不说"治什么"、不推荐保健品或药物；输出末尾一律拼上
  ``GENERIC_DISCLAIMER``（含"遵医嘱"，与 ``HealthDisclaimerGuard`` 的去重键一致，
  将来把 ``get_recipe`` 登记进 ``HEALTH_TOOLS`` 也不会追加出两遍声明）。
- **数据层**：``data/recipes.json`` 里不出现"治/功效/保健品/药"这类词，由测试钉死
  （见 tests/test_subagents.py 的 ``test_recipe_fixture_makes_no_medical_claim``）。
  靠自觉不如靠断言：食谱极容易滑进"降血压、软化血管"那类话术。
"""
from __future__ import annotations

import math

from app.safety.risk_rules import GENERIC_DISCLAIMER
from app.tools.common import fail, make_tool, ok

# 散步估时：老人慢走的保守速度。真正的步速因人而异，所以这个常量只用来估，
# 并且必须原样告诉老人"是按慢走算的"—— 一个不说明口径的时长会被当成承诺。
WALK_SPEED_KMH = 3.0
REST_MINUTES = 5          # 每个歇脚点留 5 分钟：坐下、喝口水、缓一缓


# ------------------------------------------------------------------ 活动推送


async def push_activities(turn, args: dict) -> dict:
    """推线下活动。**不出 card** —— 交付物那份《社区活动推荐单》由 plan_builder 出，
    这里再吐一张卡，老人屏幕上就会出现两张内容一样的活动卡。"""
    provider = turn.ctx.resolve("community")
    activities = await provider.activities(kind=args.get("kind"))
    lines = [_activity_line(a) for a in activities]
    if not activities:
        return fail("我这儿没找着合适的活动，您换个说法，或者问问社区门口公告栏。")
    return ok(
        summary="最近的社区活动：\n" + "\n".join(lines),
        announce="社区最近有活动：" + "；".join(a["title"] for a in activities[:3]) + "。",
        data={"activities": activities},
    )


def _activity_line(a: dict) -> str:
    """一条活动给模型看的一行：标题、时间、地点、收不收费、怎么走。

    ``fee`` 缺了就按 ``free`` 推。两个都不写就**不猜**，只说地点 —— 编一个"免费"
    会让老人白跑一趟问价，编一个"收费"会让他干脆不去。
    """
    fee = a.get("fee")
    if not fee:
        if a.get("free") is True:
            fee = "免费"
        elif a.get("free") is False:
            fee = "收费"
    parts = [f"{a.get('title', '')}：{a.get('date', '')}"]
    if a.get("time"):
        parts.append(str(a["time"]))
    parts.append(f"{a.get('place', '')}" + (f"（{fee}）" if fee else ""))
    if a.get("how_to"):
        parts.append(f"怎么走：{a['how_to']}")
    return "，".join(p for p in parts if p.strip())


# ------------------------------------------------------------------ 一键拨号


async def suggest_contact(repos, elder_id: str, *, relation: str | None = None) -> list[dict]:
    """读绑定关系 + 用户表，得出"现在能打给谁"。**号码从库里取，绝不写死。**

    两条纪律：
    - **没存号码的人不进这张卡**（``phone`` 为空就丢掉）。给老人一个点了没反应的
      按钮，比不给他按钮更伤 —— 他会以为是自己按错了。
    - 排序是确定的（按绑定关系的 ``created_at``），所以"第一条"每次都同一个人。
      挑不中 ``relation`` 时退回第一条，而不是随机挑一个，否则同一个问题问两遍
      拨给两个人。

    返回 ``[{id, name, relation, phone, city}]``；挑中的那位排在最前面。
    """
    bindings = await repos.list("family_bindings", where={"elder_id": elder_id})
    contacts: list[dict] = []
    for b in sorted(bindings, key=lambda r: str(r.get("created_at") or "")):
        if b.get("status") not in (None, "active"):
            continue
        child = await repos.get("users", b.get("child_id"))
        if not child:
            continue
        phone = str(child.get("phone") or "").strip()
        if not phone:
            continue
        contacts.append({
            "id": child.get("id"),
            "name": str(child.get("name") or ""),
            "relation": str(b.get("relation")
                            or child.get("relation_to_elder") or "家里人"),
            "phone": phone,
            "city": str(child.get("city") or ""),
        })
    want = str(relation or "").strip()
    if want:
        for i, c in enumerate(contacts):
            if want in c["relation"] or c["relation"] in want:
                return [contacts[i]] + contacts[:i] + contacts[i + 1:]
    return contacts


async def suggest_call(turn, args: dict) -> dict:
    """老人流露孤独/想孩子 → 给一张**点一下就能通话**的卡。

    这不是"推个联系方式"，是"把话接通"：卡片上只有一个大按钮，号码预填家人的，
    老人不需要翻通讯录、不需要记号码、不需要选。所以号码由系统从绑定关系里取，
    连模型都不许在话里报出来（报错了老人照着拨，或者记混了更麻烦）。
    """
    contacts = await suggest_contact(turn.ctx.repos, turn.user.get("id"),
                                    relation=args.get("relation"))
    if not contacts:
        # 没绑定就不编号码：宁可让他把号报给我记上，也不能给一张拨不出去的卡。
        return ok(
            summary="我这儿还没存上家里人的电话号码。您把孩子的号告诉我，"
                    "我给您记上，下回点一下就通。",
            announce="家里人的电话我这儿还没存上，您把号报给我，我给您记着。",
            data={"contacts": []},
        )
    c = contacts[0]
    reason = str(args.get("reason") or "").strip() or "想说话的时候，随时找得着人"
    card = {
        "type": "call",
        "title": f"给{c['relation']}{c['name']}打个电话",
        "name": c["name"],
        "relation": c["relation"],
        "phone": c["phone"],
        "reason": reason,
        "note": "点一下就能拨出去，不用翻通讯录",
    }
    return ok(
        summary=f"给{c['relation']}{c['name']}的拨号卡片放在下面了，点一下就能通话。",
        announce=f"想{c['name']}了就打个电话，按钮我给您放下面了。",
        data={"contacts": contacts, "call": card},
        card=card,
    )


# ------------------------------------------------------------------ 散步环线


def walk_estimate(distance_km: float, rest_stops: int = 0, *,
                  speed_kmh: float = WALK_SPEED_KMH) -> dict:
    """距离 → 走多久。**全项目时长的唯一出处。**

    向上取整到 5 分钟：老人要的是"大概多久"，"36 分钟"这种精度反而逼着他去算。
    取整方向一律往上 —— 报少了会让人以为来得及，报多了最多是提前到。
    """
    raw = max(0.0, float(distance_km)) / speed_kmh * 60
    walking_min = int(math.ceil(raw / 5.0) * 5)
    rest_min = int(max(0, rest_stops)) * REST_MINUTES
    return {
        "distance_km": distance_km,
        "walking_min": walking_min,
        "rest_min": rest_min,
        "total_min": walking_min + rest_min,
        "pace": f"按慢走 {speed_kmh:g} 公里/小时算的",
    }


async def suggest_walk(turn, args: dict) -> dict:
    """给一条老人走得动的**环形**路线：走回出发点，就不存在"走远了回不来"。"""
    provider = turn.ctx.resolve("community")
    city = str(args.get("city") or turn.user.get("city") or "").strip()
    loops = await provider.walk_loops(city=city) if city else []
    if not loops:
        loops = await provider.walk_loops(city="长沙")
    if not loops:
        loops = await provider.walk_loops(city="南京")
    if not loops:
        loops = await provider.walk_loops()
    if not loops:
        return fail("这条线路我这儿没有现成的环线，别照着瞎走，出门前问一下社区。")

    scored = [(loop, walk_estimate(loop["distance_km"],
                                   len(loop.get("rest_stops") or [])))
              for loop in loops]
    minutes = _as_float(args.get("minutes"))
    if minutes is not None:
        loop, est = min(scored, key=lambda p: abs(p[1]["total_min"] - minutes))
    else:
        loop, est = scored[0]

    summary_note = (f"全程 {est['distance_km']} 公里，{est['pace']}，"
                    f"路上歇 {len(loop.get('rest_stops') or [])} 回，"
                    f"连歇脚大约 {est['total_min']} 分钟。")
    body = {
        "路线": loop["name"],
        "全程": f"{est['distance_km']} 公里",
        "用时": f"走 {est['walking_min']} 分钟，歇脚 {est['rest_min']} 分钟，"
                f"加起来约 {est['total_min']} 分钟",
        "好走吗": loop.get("surface") or "路面平整",
        "在哪儿歇": "、".join(loop.get("rest_stops") or []) or "路边找地方坐",
        "几点去": loop.get("best_time") or "上午或傍晚，避开日头",
        "怎么走": " → ".join(loop.get("steps") or []),
        # 走不动怎么办，和"怎么走"一样是出门前就得知道的事，所以它是卡上的一行，
        # 不是一句印在脚注里、老人到了半路才想起来的叮嘱。
        "走不动了": "原路返回，别硬撑；路线是环的，往回走也是回家的路",
    }
    card = {
        "type": "walk_card",
        "title": f"{loop['name']}（{est['distance_km']} 公里）",
        "body": body,
        # 走 PlanCard 的紧凑模式渲染，所以脚注要落在这两个键上：
        # 前端 _toCard 只把 subtitle / disclaimer / footnote 收进卡脚，
        # 另起一个 notes 键会被静默丢掉 —— 披露模拟数据是硬要求，不能丢在半路上。
        "subtitle": summary_note,
        "footnote": "（路线是竞赛原型内置的演示数据，正式落地对接社区与地图开放接口）",
    }
    return ok(
        summary=f"{loop['name']}：全程 {est['distance_km']} 公里，"
                f"约 {est['total_min']} 分钟（{est['pace']}）。"
                f"路线：{' → '.join(loop.get('steps') or [])}",
        announce=f"给您找了条{loop['name']}，"
                 f"{est['distance_km']} 公里，连走带歇大概 {est['total_min']} 分钟。"
                 f"走累了就原路回来。",
        data={"loop": loop, "estimate": est, "city": city},
        card=card,
    )


# ------------------------------------------------------------------ 家常菜谱


def pick_recipe(recipes: list[dict], dish: str | None = None,
                condition: str | None = None) -> dict | None:
    """挑一道菜。**挑不中就说没有，绝不现编一个菜谱。**

    挑选顺序（确定性、事后能解释给老人听）：
    ① 点名了菜名/别名 → 就用它；
    ② 没点名，但知道他的慢病 → 在 ``suitable_for`` 里找对得上的（"高血压"能对上
       "原发性高血压"，双向包含）；
    ③ 都没有 → 头一道。
    """
    if not recipes:
        return None
    want = str(dish or "").strip()
    if want:
        for r in recipes:
            names = [r.get("name") or "", *(r.get("alias") or [])]
            if any(want in str(n) or str(n) in want for n in names if n):
                return r
        # 点了名却查不到：不拿别的菜顶替，让调用方去说"这道我这儿没有"。
        return None
    cond = str(condition or "").strip()
    if cond:
        for r in recipes:
            for s in (r.get("suitable_for") or []):
                if cond in str(s) or str(s) in cond:
                    return r
    return recipes[0]


async def get_recipe(turn, args: dict) -> dict:
    """家常做法，不是营养处方（红线 R1/R2）。

    个性化只到"您有高血压，我挑了一道盐少的"这一层 —— 说出**挑的理由**，
    不声称**吃了会怎样**。后者是疗效话术，前者只是把选择讲清楚。
    """
    provider = turn.ctx.resolve("community")
    rows = await provider.recipes()
    dish = args.get("dish")
    condition = str(args.get("condition") or "").strip()
    if not condition:
        # 老人自己登记过的慢病（health 线 add_condition 写的那张表）——
        # 两边读的是同一份事实，所以在健康页登记过的高血压，这儿挑菜也认。
        conds = await turn.ctx.repos.list("health_conditions",
                                          where={"elder_id": turn.user.get("id")})
        active = [c for c in conds if c.get("active", True)]
        condition = str(active[0].get("name") or "") if active else ""

    r = pick_recipe(rows, dish=dish, condition=condition)
    if not r:
        return fail("这道菜我这儿没有，您换个家常的，我再给您找。")

    steps = list(r.get("steps") or [])
    note = GENERIC_DISCLAIMER
    why = f"您说过有{condition}，我挑了一道口味偏淡的。" if condition else ""
    summary = (f"今天教您做{r['name']}，{len(steps)} 步，{r['minutes']} 分钟。{why}"
               + "".join(steps) + note)
    return ok(
        summary=summary,
        announce=f"今天教您做{r['name']}，{len(steps)} 步，{r['minutes']} 分钟，"
                 f"软烂少油，做起来不难。{note}",
        data={"recipe": r, "dish": r["name"], "picked_for": condition},
        card={
            "type": "recipe",
            "title": f"今日家常菜 · {r['name']}",
            "dish": r["name"],
            "minutes": r["minutes"],
            "tags": list(r.get("tags") or []),
            "ingredients": list(r.get("ingredients") or []),
            "steps": steps,
            "tips": list(r.get("tips") or []),
            "note": note,
        },
    )


def _as_float(value) -> float | None:
    """``minutes`` 可能是模型填的字符串（"30"）。取不到就返回 None，不当成 0。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ 注册


def register_community_tools(registry) -> None:
    registry.register(make_tool(
        "push_activities", "查询最近的社区活动（棋牌室/养老院/公园/义诊）。",
        {"kind": {"type": "string",
                  "description": "活动类型，如 棋牌室/养老院/公园/义诊/社区活动；不填就是全部"}},
        push_activities, agent="community", report_key="activities",
    ))
    registry.register(make_tool(
        "suggest_call",
        "老人流露孤独、想孩子、想找人说说话时，出一张一键拨号卡片"
        "（号码由系统从家人绑定关系里取，你不需要、也不许在话里报号码）。",
        {
            "relation": {"type": "string", "description": "想打给谁，如 儿子/女儿；不填就是默认联系人"},
            "reason": {"type": "string", "description": "为什么想打这通电话（用老人的原话）"},
        },
        suggest_call, agent="community", report_key="call_action",
    ))
    registry.register(make_tool(
        "suggest_walk",
        "给一条环形散步路线：说清多远、走多久、在哪儿歇。只给现成的环线，查不到就说没有。",
        {
            "city": {"type": "string", "description": "城市，如 长沙；不填按老人所在城市"},
            "minutes": {"type": "number", "description": "老人想走多久（分钟）"},
        },
        suggest_walk, agent="community", report_key="walk_route",
    ))
    registry.register(make_tool(
        "get_recipe",
        "教一道家常菜（食材 + 短步骤）。只讲做法与口感，不谈疗效、不推荐保健品或药物。",
        {
            "dish": {"type": "string", "description": "菜名，如 番茄鸡蛋面；不填就按老人口味挑"},
            "condition": {"type": "string", "description": "需要照顾的情况，如 高血压"},
        },
        get_recipe, agent="community", report_key="recipe",
    ))
