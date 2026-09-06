"""子女确认流 API：待确认列表 / 批准 / 拒绝。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_ctx, get_current_principal
from app.auth.security import Principal
from app.core.context import AppContext
from app.safety.confirmation import ConfirmationError

router = APIRouter(prefix="/api", tags=["confirmation"])


async def _ensure_task_in_family(ctx, task_id: str, child_id: str) -> None:
    """审批者与被审批老人必须存在 active 家庭关系。

    只查 role=="child" 挡不住横向越权：任何子女账号拿别人家的 task_id 就能
    替人家批钱。任务不存在时不在这里 404 —— 留给 service 层报，语义一致。
    """
    task = await ctx.repos.get("confirmation_tasks", task_id)
    if not task:
        return
    binding = await ctx.repos.find_one("family_bindings", {
        "elder_id": task.get("elder_id"), "child_id": child_id, "status": "active",
    })
    if not binding:
        raise HTTPException(403, "该确认任务不属于您绑定的家人")


@router.get("/child/{child_id}/confirmations")
async def list_confirmations(
    child_id: str,
    status: str | None = None,
    principal: Principal = Depends(get_current_principal),
    ctx: AppContext = Depends(get_ctx),
):
    if principal.id != child_id or principal.role != "child":
        raise HTTPException(403, "无权查看其他子女确认任务")
    rows = await ctx.confirmation.list_for_child(child_id, status)
    return {"items": rows}


@router.post("/confirmations/{task_id}/approve")
async def approve(
    task_id: str,
    child_id: str | None = None,
    principal: Principal = Depends(get_current_principal),
    ctx: AppContext = Depends(get_ctx),
):
    actor_id = principal.id
    if child_id and child_id != actor_id:
        raise HTTPException(403, "认证身份与请求参数不一致")
    if principal.role != "child":
        raise HTTPException(403, "仅家人角色可审批高危操作")
    await _ensure_task_in_family(ctx, task_id, actor_id)
    try:
        return await ctx.confirmation.approve_and_execute(task_id, ctx, actor_id)
    except ConfirmationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/confirmations/{task_id}/reject")
async def reject(
    task_id: str,
    child_id: str | None = None,
    principal: Principal = Depends(get_current_principal),
    ctx: AppContext = Depends(get_ctx),
):
    actor_id = principal.id
    if child_id and child_id != actor_id:
        raise HTTPException(403, "认证身份与请求参数不一致")
    if principal.role != "child":
        raise HTTPException(403, "仅家人角色可拒绝高危操作")
    await _ensure_task_in_family(ctx, task_id, actor_id)
    try:
        return await ctx.confirmation.reject(task_id, ctx, actor_id)
    except ConfirmationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
