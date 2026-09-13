"""出行工具（银发导航）：本地出行路线 + 叫车。

康乐收敛后，城际高铁/酒店整条砍掉（与"就近就医"矛盾），只留本地出行：
``plan_route`` 的结果进 ``route`` 键，是"怎么去医院/去散步"那一段的来源
（渲染器只认这个键，模型不参与拼装，见 agents/plan_builder.py）。
``hail_ride`` 只做信息展示（叫车 ETA），不涉及支付，故不进高危、不冻结。

出行的方式只有公交/地铁/步行三种 —— "打车"走的是 ``hail_ride`` 那条已经存在的
路，不在这张枚举里，免得模型把两种方式混着说。
"""
from __future__ import annotations

from app.tools.common import fail, make_tool, ok

# 模型嘴里蹦出来的说法（"坐地铁""走路过去"）归一到 provider 认的三个词。
# 认不出的（含"打车""高铁"）返回空串 → 走 provider 的推荐方式（公交），
# 不在这里现编一个方式来满足模型。
_MODE_ALIASES = {
    "公交": "公交", "公交车": "公交", "巴士": "公交", "公交车过去": "公交",
    "地铁": "地铁", "轨道交通": "地铁", "轻轨": "地铁",
    "步行": "步行", "走路": "步行", "走": "步行", "散步": "步行",
}


def _normalize_mode(raw) -> str:
    return _MODE_ALIASES.get(str(raw or "").strip(), "")


async def plan_route(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("map")
    route = await provider.plan_route(
        args.get("origin", ""), args.get("destination", ""),
        _normalize_mode(args.get("mode")),
        # 老人档案里的常住城市：出发地常常就一个"家"，看不出在哪个城市走动
        (turn.user or {}).get("city") or "",
    )
    return ok(summary=route["summary"], announce=route.get("announce", ""), data=route)


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


def register_travel_tools(registry) -> None:
    registry.register(make_tool(
        "plan_route",
        "规划同城从出发地到目的地的出行路线（公交/地铁/步行，只做本市，不查跨城）。",
        {"origin": {"type": "string"}, "destination": {"type": "string"},
         "mode": {"type": "string", "enum": ["公交", "地铁", "步行"],
                  "description": "出行方式，默认公交；打车请用 hail_ride"}},
        plan_route, agent="travel", report_key="route",
    ))
    registry.register(make_tool(
        "hail_ride", "为老人叫一辆网约车。",
        {"origin": {"type": "string"}, "destination": {"type": "string"}},
        hail_ride, agent="travel", timeout_s=30.0,
    ))
