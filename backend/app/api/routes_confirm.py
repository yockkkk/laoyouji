"""子女确认流 API：待确认列表 / 批准 / 拒绝。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_ctx, get_current_principal
from app.auth.security import Principal
from app.safety.confirmation import ConfirmationError

router = APIRouter(prefix="/api", tags=["confirmation"])


@router.get("/child/{child_id}/confirmations")
async def list_confirmations(child_id: str, status: str | None = None,
                             principal: Principal = Depends(get_current_principal)):
    ctx = get_ctx()
    if principal.id != child_id and principal.role != "child":
        raise HTTPException(403, "无权查看其他子女确认任务")
    rows = await ctx.confirmation.list_for_child(child_id, status)
    return {"items": rows}


@router.post("/confirmations/{task_id}/approve")
async def approve(task_id: str, child_id: str | None = None,
                  principal: Principal = Depends(get_current_principal)):
    ctx = get_ctx()
    actor_id = principal.id
    if child_id and child_id != actor_id:
        raise HTTPException(403, "认证身份与请求参数不一致")
    if principal.role != "child":
        raise HTTPException(403, "仅家人角色可审批高危操作")
    try:
        return await ctx.confirmation.approve_and_execute(task_id, ctx, actor_id)
    except ConfirmationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/confirmations/{task_id}/reject")
async def reject(task_id: str, child_id: str | None = None,
                 principal: Principal = Depends(get_current_principal)):
    ctx = get_ctx()
    actor_id = principal.id
    if child_id and child_id != actor_id:
        raise HTTPException(403, "认证身份与请求参数不一致")
    if principal.role != "child":
        raise HTTPException(403, "仅家人角色可拒绝高危操作")
    try:
        return await ctx.confirmation.reject(task_id, ctx, actor_id)
    except ConfirmationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
