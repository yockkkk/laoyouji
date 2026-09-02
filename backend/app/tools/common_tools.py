"""公共工具：天气 / 大白话翻译 / 用户信息（所有子智能体可用）。"""
from __future__ import annotations

from app.tools.common import make_tool, ok


async def get_weather(turn, args: dict) -> dict:
    provider = turn.ctx.resolve("weather")
    w = await provider.get(args.get("city", turn.user.get("city", "南京")),
                           args.get("date"))
    return ok(
        summary=f"{w['city']} {w['date']}：{w['condition']}，"
                f"{w['temp_low']}~{w['temp_high']}℃。{w['advice']}",
        announce=f"{w['city']}明天{w['condition']}，{w['temp_low']}到{w['temp_high']}度。"
                 f"{w['advice']}",
        data=w,
    )


async def plain_say(turn, args: dict) -> dict:
    engine = turn.ctx.resolve("plain_language")
    text = args.get("text", "")
    plain = await engine.to_plain(text)
    return ok(summary=f"大白话：{plain}", announce=plain, data={"plain": plain})


async def get_user_profile(turn, args: dict) -> dict:
    return ok(
        summary=f"当前用户：{turn.user.get('name', '')}（{turn.user.get('city', '')}）",
        data={"user": turn.user},
    )


def register_common_tools(registry) -> None:
    registry.register(make_tool(
        "get_weather", "查询指定城市和日期的天气（含穿衣建议）。",
        {
            "city": {"type": "string", "description": "城市名"},
            "date": {"type": "string", "description": "日期：'tomorrow'、'+2' 或 'YYYY-MM-DD'"},
        },
        get_weather, agent="common", report_key="weather",
    ))
    registry.register(make_tool(
        "plain_say", "把专业的话翻译成老人听得懂的大白话。",
        {"text": {"type": "string", "description": "要翻译的原文"}},
        plain_say, agent="common",
    ))
    registry.register(make_tool(
        "get_user_profile", "查询当前老人的基本信息（姓名、城市、方言偏好）。",
        {}, get_user_profile, agent="common",
    ))
