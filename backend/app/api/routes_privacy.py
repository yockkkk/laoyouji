"""隐私分级 API：位置（realtime/city/off）与健康（full/summary/off）权限，老人掌控。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_ctx, get_current_principal
from app.auth.security import Principal
from app.safety.privacy import (
    DEFAULT_HEALTH_LEVEL,
    DEFAULT_LOCATION_LEVEL,
    HEALTH_LEVELS,
    LOCATION_LEVELS,
)

router = APIRouter(prefix="/api/privacy", tags=["privacy"])


class PrivacyIn(BaseModel):
    child_id: str
    location_level: str = DEFAULT_LOCATION_LEVEL   # realtime | city | off
    health_level: str = DEFAULT_HEALTH_LEVEL       # full | summary | off
    actor_id: str | None = None


@router.get("/{elder_id}")
async def get_privacy(elder_id: str, child_id: str,
                      principal: Principal = Depends(get_current_principal)):
    ctx = get_ctx()
    # 仅允许本人（老人）或被授权的家人查询
    if principal.id not in (elder_id, child_id):
        raise HTTPException(403, "无权查看该隐私权限")

    row = await ctx.repos.find_one(
        "privacy_permissions", {"elder_id": elder_id, "child_id": child_id})
    if not row:
        grant = await ctx.privacy.grant_for(elder_id, child_id)
        return {"elder_id": elder_id, "child_id": child_id,
                "location_level": grant.location_level,
                "health_level": grant.health_level,
                "bound": grant.bound, "explicit": False}
    return {**row, "explicit": True}


@router.put("/{elder_id}")
async def put_privacy(elder_id: str, body: PrivacyIn,
                      principal: Principal = Depends(get_current_principal)):
    ctx = get_ctx()
    # 强制校验：只有老人本人能修改
    if principal.id != elder_id or principal.role != "elder":
        raise HTTPException(403, "隐私授权只能由老人本人修改")
    if body.location_level not in LOCATION_LEVELS:
        raise HTTPException(422, f"location_level 取值: {'/'.join(LOCATION_LEVELS)}")
    if body.health_level not in HEALTH_LEVELS:
        raise HTTPException(422, f"health_level 取值: {'/'.join(HEALTH_LEVELS)}")

    row = await ctx.repos.find_one(
        "privacy_permissions", {"elder_id": elder_id, "child_id": body.child_id})
    await ctx.repos.insert("audit_log", {
        "actor_id": principal.id, "action": "privacy_changed",
        "target": body.child_id,
        "detail": {"location_level": body.location_level,
                   "health_level": body.health_level},
    })
    if row:
        updated = await ctx.repos.update("privacy_permissions", row["id"], {
            "location_level": body.location_level,
            "health_level": body.health_level,
        })
        return updated
    return await ctx.repos.insert("privacy_permissions", {
        "elder_id": elder_id, "child_id": body.child_id,
        "location_level": body.location_level, "health_level": body.health_level,
    })
