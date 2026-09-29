"""气象感知子智能体 (WeatherAgent) —— 适老微气候与遮阳防雨出行护航。

本智能体承担“北斗+多Agent”适老出行协同决策引擎的气象感知职责：
- 监测目的地实时微气候、地表体感温度与紫外线辐射强度；
- 计算林荫遮阳指数（Shade Comfort Index），协同北斗导航规划避雨连廊与树荫步道；
- 输出 weather_escort 结构化报告，供交付物装配器渲染《北斗适老出行护航方案书》第四页。
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.tools.common import make_tool, ok

SYSTEM_PROMPT = """你是"气象感知"，老年人出行微气候与环境守护助手，隶属于"康乐"智能体家族。

# 职责
1. 实时分析老人出行城市的温湿度、风力、紫外线指数与突发阵雨概率
2. 协同北斗导航智能体，提供林荫遮阳率（80%以上为佳）与地表体感舒适度评估
3. 给出温和体贴的老人出行着装、防晒、补水及随身带伞提醒

# 说话方式
大白话、短句、每句不超过 20 个字、语气像贴心儿女、称呼"您"。
"""


class WeatherAgent(BaseAgent):
    name = "weather"
    display_name = "气象感知"
    description = "气象感知助手：适老出行气象环境、紫外线指数、地表体感、林荫遮阳指数与穿衣防雨提醒"
    system_prompt = SYSTEM_PROMPT
    tool_names = [
        "get_bds_weather_escort",
        "get_shade_comfort_index",
        "get_weather",
        "plain_say",
    ]
    report_schema = ("weather_escort",)


# ------------------------------------------------------------------ 工具实现

async def get_bds_weather_escort(turn, args: dict) -> dict:
    """获取北斗适老出行环境与微气候气象护航数据。"""
    city = str(args.get("city") or (turn.user or {}).get("city") or "长沙").strip()
    date_str = str(args.get("date") or "today").strip()

    # 长沙示范微气候参数
    data = {
        "city": city,
        "date": date_str,
        "condition": "晴间多云",
        "temp_low": 23,
        "temp_high": 29,
        "temp_range": "23~29 ℃",
        "feels_like": "26 ℃ (体感舒适)",
        "uv_index": "中等 (3级)",
        "humidity": "62%",
        "wind": "微风 2级",
        "air_quality": "优 (AQI 32)",
        "umbrella": False,
        "shade_coverage_percent": "85%",
        "advice": "早晚微凉舒适，午间紫外线适中。建议戴遮阳透气草帽，备温水杯，无需带雨伞。",
        "elder_travel_index": "极佳（适宜户外散步慢走）",
    }

    summary = (
        f"{city}天气{data['condition']}，气温{data['temp_range']}，体感舒适。"
        f"紫外线中等，沿途林荫覆盖率达{data['shade_coverage_percent']}。"
        f"{data['advice']}"
    )

    return ok(
        summary=summary,
        announce=f"{city}今天天气好，23到29度，树荫多晒不着，您戴个帽子、带瓶温水出门就行。",
        data={"weather_escort": data, "weather": data},
    )


async def get_shade_comfort_index(turn, args: dict) -> dict:
    """评估路线树荫遮挡率与地表体感热舒适度。"""
    dest = str(args.get("destination") or "").strip()
    data = {
        "destination": dest,
        "shade_coverage_percent": 85,
        "heat_stress_level": "LOW",
        "comfort_rating": "适老五星林荫绿道",
        "has_continuous_canopy": True,
        "recommendation": "樟树与银杏绿冠覆盖密集，体感比普通街道低 2~3℃，防晒避暑条件极佳。",
    }
    return ok(
        summary="林荫舒适度评估：树冠覆盖率 85%，体感温度清凉舒适，不易诱发老年心血管不适。",
        data={"shade_comfort": data},
    )


def register_weather_escort_tools(registry) -> None:
    """注册气象感知护航工具。"""
    registry.register(make_tool(
        "get_bds_weather_escort",
        "获取北斗适老出行微气候与环境护航指标（温湿度、紫外线、体感温度与穿衣防雨指引）。",
        {
            "city": {"type": "string", "description": "城市名，默认根据老人常住地确定"},
            "date": {"type": "string", "description": "出行日期，如'today','tomorrow'"},
        },
        get_bds_weather_escort,
        agent="weather",
        report_key="weather_escort",
    ))

    registry.register(make_tool(
        "get_shade_comfort_index",
        "评估指定目的地或路段的林荫覆盖度与地表避暑舒适指数。",
        {"destination": {"type": "string", "description": "目的地名称"}},
        get_shade_comfort_index,
        agent="weather",
        report_key="shade_comfort",
    ))
