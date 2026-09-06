"""家庭绑定关系 API：成员列表、发起绑定申请、同意/拒绝、解绑。"""
from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_ctx, get_current_principal
from app.auth.security import Principal
from app.safety.privacy import DEFAULT_HEALTH_LEVEL, DEFAULT_LOCATION_LEVEL

router = APIRouter(prefix="/api/family", tags=["family"])


class BindRequestIn(BaseModel):
    target_username: str = Field(min_length=3, max_length=64)
    relation: str = Field(min_length=1, max_length=32)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/members")
async def list_members(principal: Principal = Depends(get_current_principal)):
    ctx = get_ctx()
    me = principal.user
    if me.get("role") == "elder":
        rows = await ctx.repos.list("family_bindings", where={"elder_id": me["id"]})
        result = []
        for r in rows:
            child = await ctx.repos.get("users", r["child_id"])
            if child:
                result.append({
                    "id": r["id"], "binding_id": r["id"],
                    "user": {"id": child["id"], "name": child["name"], "role": child.get("role"),
                             "username": child.get("username")},
                    "relation": r.get("relation") or "家人",
                    "status": r.get("status", "active"),
                    "invited_by": r.get("invited_by"),
                    "created_at": r.get("created_at"),
                })
        return {"items": result}
    rows = await ctx.repos.list("family_bindings", where={"child_id": me["id"]})
    result = []
    for r in rows:
        elder = await ctx.repos.get("users", r["elder_id"])
        if elder:
            result.append({
                "id": r["id"], "binding_id": r["id"],
                "user": {"id": elder["id"], "name": elder["name"], "role": elder.get("role"),
                         "username": elder.get("username"), "city": elder.get("city")},
                "relation": r.get("relation") or "家人",
                "status": r.get("status", "active"),
                "invited_by": r.get("invited_by"),
                "created_at": r.get("created_at"),
            })
    return {"items": result}


@router.post("/requests")
async def create_bind_request(body: BindRequestIn, principal: Principal = Depends(get_current_principal)):
    ctx = get_ctx()
    me = principal.user
    target = await ctx.repos.find_one("users", {"username": body.target_username})
    if not target or target.get("status", "active") != "active":
        raise HTTPException(404, "目标用户不存在")
    if target["id"] == me["id"]:
        raise HTTPException(422, "不能绑定自己")

    if me.get("role") == "elder":
        if target.get("role") != "child":
            raise HTTPException(422, "老人只能绑定家人账号")
        elder_id, child_id = me["id"], target["id"]
    else:
        if target.get("role") != "elder":
            raise HTTPException(422, "家人只能绑定老人账号")
        elder_id, child_id = target["id"], me["id"]

    existing = await ctx.repos.find_one("family_bindings", {"elder_id": elder_id, "child_id": child_id})
    if existing and existing.get("status") in ("active", "pending"):
        raise HTTPException(409, "已存在绑定或正在审核中")

    payload = {
        "elder_id": elder_id,
        "child_id": child_id,
        "relation": body.relation,
        "status": "pending",
        "invited_by": me["id"],
        "created_at": _now(),
    }
    if existing:
        row = await ctx.repos.update("family_bindings", existing["id"], payload)
    else:
        row = await ctx.repos.insert("family_bindings", payload)

    await ctx.repos.insert("audit_log", {
        "actor_id": me["id"], "action": "family_bind_request", "target": target["id"],
        "detail": {"relation": body.relation, "binding_id": row["id"]},
    })
    return {"ok": True, "binding": row}


@router.post("/requests/{binding_id}/accept")
async def accept_bind_request(binding_id: str, principal: Principal = Depends(get_current_principal)):
    ctx = get_ctx()
    me = principal.user
    binding = await ctx.repos.get("family_bindings", binding_id)
    if not binding:
        raise HTTPException(404, "绑定申请不存在")
    if binding.get("status") != "pending":
        raise HTTPException(409, "该申请已处理或已失效")
    # 只能由被邀请人（接收方）确认
    if binding.get("invited_by") == me["id"]:
        raise HTTPException(403, "不能确认自己发起的申请")
    if me["id"] not in (binding["elder_id"], binding["child_id"]):
        raise HTTPException(403, "无权处理该申请")

    row = await ctx.repos.update("family_bindings", binding_id, {
        "status": "active", "approved_at": _now(),
    })
    # 初始化默认隐私权限：活跃家庭绑定默认全透明（realtime, full）
    perm = await ctx.repos.find_one("privacy_permissions", {
        "elder_id": binding["elder_id"], "child_id": binding["child_id"],
    })
    if not perm:
        await ctx.repos.insert("privacy_permissions", {
            "elder_id": binding["elder_id"], "child_id": binding["child_id"],
            "location_level": "realtime",
            "health_level": "full",
        })
    await ctx.repos.insert("audit_log", {
        "actor_id": me["id"], "action": "family_bind_accept", "target": binding_id,
        "detail": {"elder_id": binding["elder_id"], "child_id": binding["child_id"]},
    })
    return {"ok": True, "binding": row}


@router.post("/requests/{binding_id}/reject")
async def reject_bind_request(binding_id: str, principal: Principal = Depends(get_current_principal)):
    ctx = get_ctx()
    me = principal.user
    binding = await ctx.repos.get("family_bindings", binding_id)
    if not binding or binding.get("status") != "pending":
        raise HTTPException(404, "申请不存在或已处理")
    if me["id"] not in (binding["elder_id"], binding["child_id"]):
        raise HTTPException(403, "无权处理该申请")
    row = await ctx.repos.update("family_bindings", binding_id, {
        "status": "rejected", "resolved_at": _now(),
    })
    await ctx.repos.insert("audit_log", {
        "actor_id": me["id"], "action": "family_bind_reject", "target": binding_id,
    })
    return {"ok": True, "binding": row}


@router.delete("/bindings/{binding_id}")
async def unbind(binding_id: str, principal: Principal = Depends(get_current_principal)):
    ctx = get_ctx()
    me = principal.user
    binding = await ctx.repos.get("family_bindings", binding_id)
    if not binding or binding.get("status") != "active":
        raise HTTPException(404, "有效绑定不存在")
    if me["id"] not in (binding["elder_id"], binding["child_id"]):
        raise HTTPException(403, "无权解除该绑定")

    row = await ctx.repos.update("family_bindings", binding_id, {
        "status": "revoked", "revoked_at": _now(),
    })
    # 解绑后关闭对应权限并留痕
    perm = await ctx.repos.find_one("privacy_permissions", {
        "elder_id": binding["elder_id"], "child_id": binding["child_id"],
    })
    if perm:
        await ctx.repos.update("privacy_permissions", perm["id"], {
            "location_level": "off", "health_level": "off",
        })
    await ctx.repos.insert("audit_log", {
        "actor_id": me["id"], "action": "family_unbind", "target": binding_id,
        "detail": {"elder_id": binding["elder_id"], "child_id": binding["child_id"]},
    })
    return {"ok": True, "binding": row}
