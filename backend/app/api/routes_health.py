"""健康 API：用药计划 CRUD + 服药打卡。"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import get_ctx

router = APIRouter(prefix="/api/medications", tags=["health"])


class MedicationIn(BaseModel):
    elder_id: str
    drug_name: str
    dose: str = ""
    times: list[str] = ["08:00"]
    notes: str = ""


@router.get("")
async def list_medications(elder_id: str, with_logs: bool = False):
    ctx = get_ctx()
    plans = await ctx.repos.list(
        "medication_plans", where={"elder_id": elder_id}, order="-created_at")
    if not with_logs:
        return {"items": plans}
    today = date.today().isoformat()
    out = []
    for p in plans:
        logs = await ctx.repos.list(
            "medication_logs",
            where={"plan_id": p["id"], "scheduled_for": today})
        out.append({**p, "logs": logs})
    return {"items": out}


@router.post("")
async def create_medication(body: MedicationIn):
    ctx = get_ctx()
    row = await ctx.repos.insert("medication_plans", {
        "elder_id": body.elder_id, "drug_name": body.drug_name,
        "dose": body.dose, "times": body.times,
        "notes": body.notes or "医生已开，遵医嘱服用", "active": True,
    })
    return row


@router.post("/{plan_id}/taken")
async def mark_taken(plan_id: str, scheduled_time: str = ""):
    ctx = get_ctx()
    plan = await ctx.repos.get("medication_plans", plan_id)
    if not plan:
        raise HTTPException(404, "用药计划不存在")
    today = date.today().isoformat()
    log = await ctx.repos.find_one("medication_logs", {
        "plan_id": plan_id, "scheduled_for": today,
        "scheduled_time": scheduled_time or (plan.get("times") or [""])[0],
    })
    if log:
        return await ctx.repos.update("medication_logs", log["id"], {
            "status": "taken", "taken_at": datetime.now(timezone.utc).isoformat()})
    return await ctx.repos.insert("medication_logs", {
        "plan_id": plan_id, "scheduled_for": today,
        "scheduled_time": scheduled_time or (plan.get("times") or [""])[0],
        "status": "taken", "taken_at": datetime.now(timezone.utc).isoformat(),
    })
