"""隐私分级 API：位置（realtime/city/off）与健康（full/summary/off）权限，老人掌控。

这里只**存**授权。真正按档裁剪数据的是 ``app/safety/privacy.py``，
接在子女端出库路径上（看板、行程详情）—— 等级词表也从那儿引，只有一份。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import get_ctx
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
    # 谁在改。原型没有登录态，这个字段是**声明**而不是凭证 —— 但它有两个实际作用：
    # ① 非老人本人来改直接 403，"隐私由老人掌控"这句话在接口层有了落点，
    #    而不是只靠"子女端界面上没有那个开关"；
    # ② 审计里记的是真 actor。原来这里把 actor_id 写死成 elder_id，
    #    于是任何一次改动都被记成"老人自己改的" —— 审计说了假话比没有审计更糟。
    # 正式版换成从登录态取 actor，本字段随之下线。
    actor_id: str | None = None


@router.get("/{elder_id}")
async def get_privacy(elder_id: str, child_id: str):
    ctx = get_ctx()
    row = await ctx.repos.find_one(
        "privacy_permissions", {"elder_id": elder_id, "child_id": child_id})
    if not row:
        # 没细调过不等于没关系：把生效中的默认档告诉前端，开关才有初始位置
        grant = await ctx.privacy.grant_for(elder_id, child_id)
        return {"elder_id": elder_id, "child_id": child_id,
                "location_level": grant.location_level,
                "health_level": grant.health_level,
                "bound": grant.bound, "explicit": False}
    return {**row, "explicit": True}


@router.put("/{elder_id}")
async def put_privacy(elder_id: str, body: PrivacyIn):
    ctx = get_ctx()
    if body.location_level not in LOCATION_LEVELS:
        raise HTTPException(422, f"location_level 取值: {'/'.join(LOCATION_LEVELS)}")
    if body.health_level not in HEALTH_LEVELS:
        raise HTTPException(422, f"health_level 取值: {'/'.join(HEALTH_LEVELS)}")
    # R6：授权只由老人本人调。带了 actor 又不是本人 → 403，不静静照改
    if body.actor_id and body.actor_id != elder_id:
        raise HTTPException(403, "隐私授权只能由老人本人修改")
    row = await ctx.repos.find_one(
        "privacy_permissions", {"elder_id": elder_id, "child_id": body.child_id})
    # 授权变更必须留痕：老人日后要能问"我什么时候把这个关掉的"
    await ctx.repos.insert("audit_log", {
        "actor_id": body.actor_id or elder_id, "action": "privacy_changed",
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
