"""子女确认流 API：待确认列表 / 批准 / 拒绝。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import get_ctx
from app.safety.confirmation import ConfirmationError

router = APIRouter(prefix="/api", tags=["confirmation"])


@router.get("/child/{child_id}/confirmations")
async def list_confirmations(child_id: str, status: str | None = None):
    ctx = get_ctx()
    if not await ctx.repos.get("users", child_id):
        raise HTTPException(404, "用户不存在")
    rows = await ctx.confirmation.list_for_child(child_id, status)
    return {"items": rows}


@router.post("/confirmations/{task_id}/approve")
async def approve(task_id: str, child_id: str | None = None):
    ctx = get_ctx()
    try:
        return await ctx.confirmation.approve_and_execute(task_id, ctx, child_id)
    except ConfirmationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc


@router.post("/confirmations/{task_id}/reject")
async def reject(task_id: str, child_id: str | None = None):
    ctx = get_ctx()
    try:
        return await ctx.confirmation.reject(task_id, ctx, child_id)
    except ConfirmationError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
