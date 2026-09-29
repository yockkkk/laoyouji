"""北斗适老多智能体协同出行护航 API 路由 (BDS Escort Engine API Routes).

遵循 PROJECT.md 接口契约：
1. POST /api/bds/escort/route：计算适老微地形低坡度零台阶路线与地标卡片
2. GET /api/bds/telemetry/live：获取当前北斗三号亚米级高精度差分遥测数据与 $BDGGA 报文
3. POST /api/bds/escort/audit-destination：目的地涉诈主动安全防御前置审核
4. POST /api/bds/escort/emergency-sos：突发身体不适/跌倒一键 SOS 三甲医院急救绿色通道极速重划
5. POST /api/bds/escort/plan-book：装配生成 5 页完整版《北斗适老出行护航方案书》
"""
from __future__ import annotations

from typing import Any, Optional, Tuple
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.agents import plan_builder
from app.core.subagents import AgentReport
from app.providers.bds_service import (
    BdsTelemetry,
    bds_service,
)
from app.services.elder_routing_service import (
    ElderEscortRouteRequest,
    ElderEscortRouteResponse,
    elder_routing_service,
)

router = APIRouter(prefix="/api/bds", tags=["bds_escort"])


# ------------------------------------------------------------------ 扩展请求模型

class AuditDestinationRequest(BaseModel):
    destination_name: str = Field(..., description="目的地名称")
    destination_coords: Optional[Tuple[float, float]] = Field(None, description="经纬度坐标 (lng, lat)")


class EmergencySosRequest(BaseModel):
    coords: Tuple[float, float] = Field(..., description="老人触发 SOS 时北斗坐标 (lng, lat)")
    elder_name: str = Field(default="张阿姨", description="老人姓名")
    elder_id: Optional[str] = Field(None, description="老人 ID")
    condition: str = Field(default="突发心慌胸闷/跌倒", description="突发状况描述")


class EscortPlanBookRequest(BaseModel):
    elder_id: str = Field(default="elder_default", description="老人 ID")
    elder_name: str = Field(default="张桂芳", description="老人姓名")
    destination_name: str = Field(..., description="目的地，如'湖南省人民医院'、'烈士公园'")
    origin: Tuple[float, float] = Field(default=(112.9862, 28.2045), description="出发地坐标 (lng, lat)")
    health_conditions: list[str] = Field(default_factory=lambda: ["膝关节退行性病变", "轻度高血压"], description="慢病特征")
    city: str = Field(default="长沙", description="城市")


# ------------------------------------------------------------------ API 端点实现

@router.post("/escort/route", response_model=ElderEscortRouteResponse)
async def plan_escort_route(req: ElderEscortRouteRequest) -> ElderEscortRouteResponse:
    """计算适老微地形低阻力高舒适路线（严格遵守避台阶、避陡坡、优先林荫与长椅）。"""
    try:
        res = elder_routing_service.plan_elder_route(req)
        return res
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"北斗适老路线规划异常: {exc}")


@router.get("/telemetry/live", response_model=BdsTelemetry)
async def get_live_telemetry(
    lat: Optional[float] = Query(None, description="CGCS2000 纬度"),
    lng: Optional[float] = Query(None, description="CGCS2000 经度"),
    elder_id: Optional[str] = Query(None, description="老人 ID"),
) -> BdsTelemetry:
    """获取北斗三号亚米级高精度实时定位与卫星遥测报文 ($BDGGA)。"""
    return bds_service.get_live_telemetry(lat=lat, lng=lng)


@router.post("/escort/audit-destination")
async def audit_destination(req: AuditDestinationRequest) -> dict[str, Any]:
    """主动防御：目的地涉诈话术与偏远高危会销场所前置审查。"""
    return elder_routing_service.audit_destination_safety(
        destination_name=req.destination_name,
        destination_coords=req.destination_coords,
    )


@router.post("/escort/emergency-sos")
async def trigger_emergency_sos(req: EmergencySosRequest) -> dict[str, Any]:
    """突发风险一键 SOS：锁定北斗高精坐标并极速重划就近三甲医院急救绿色通道。"""
    return elder_routing_service.emergency_sos_reroute(
        current_coords=req.coords,
        elder_name=req.elder_name,
        condition=req.condition,
    )


@router.post("/escort/plan-book")
async def generate_escort_plan_book(req: EscortPlanBookRequest) -> dict[str, Any]:
    """装配生成 5 页全套《北斗适老出行护航方案书》（体征适配、北斗路线、微地形长椅、气象防护、安全守护）。"""
    # 1. 计算北斗适老路径
    route_req = ElderEscortRouteRequest(
        elder_id=req.elder_id,
        origin=req.origin,
        destination_name=req.destination_name,
        health_conditions=req.health_conditions,
        avoid_stairs=True,
        max_slope_percent=4.0,
    )
    route_res = elder_routing_service.plan_elder_route(route_req)

    # 2. 模拟多 Agent 汇报数据
    reports = [
        AgentReport(
            agent="health",
            ok=True,
            summary="健康体能与就近就医挂号完成",
            data={
                "appointment": {
                    "hospital": req.destination_name if "医院" in req.destination_name else "湖南省人民医院（天心阁院区）",
                    "department": "老年医学综合门诊 / 骨科",
                    "doctor": "副主任专家团队",
                    "date": "today",
                    "fee": 50,
                    "city": req.city,
                },
                "mobility_profile": {
                    "avoid_stairs": True,
                    "max_slope": 4.0,
                },
            },
        ),
        AgentReport(
            agent="bds_nav",
            ok=True,
            summary="北斗微地形平缓无障碍路线规划完成",
            data={
                "bds_route": route_res.model_dump(),
                "micro_terrain": {
                    "max_gradient_percent": route_res.max_gradient_percent,
                    "stairs_count": route_res.stairs_count,
                    "barrier_free_score": route_res.barrier_free_score,
                },
                "rest_benches": {
                    "total_benches": route_res.rest_benches_count,
                    "average_interval_m": 140,
                },
            },
        ),
        AgentReport(
            agent="weather",
            ok=True,
            summary="适老气象环境与林荫评估完成",
            data={
                "weather_escort": route_res.weather_summary or {
                    "city": req.city,
                    "condition": "晴间多云",
                    "temp_range": "23~29 ℃",
                    "feels_like": "26 ℃",
                    "uv_index": "中等 (3级)",
                    "shade_coverage_percent": "85%",
                    "umbrella": False,
                    "advice": "适宜出行，林荫覆盖率高，随身带好温水杯与折叠伞。",
                },
            },
        ),
    ]

    elder_dict = {
        "id": req.elder_id,
        "name": req.elder_name,
        "city": req.city,
    }

    card = plan_builder.build(
        "bds_escort_plan",
        elder_dict,
        reports,
        city=req.city,
        destination=req.destination_name,
    )
    return card
