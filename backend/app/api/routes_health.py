"""健康 API：用药计划 CRUD + 服药打卡。"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import get_ctx

router = APIRouter(prefix="/api/medications", tags=["health"])

# 打卡记录的 id 由 (计划, 日期, 时段) 直接算出来，同一格永远是同一个 id。
# 这样"重复打卡"在数据库层就撞主键，而不是靠先查后插那道会被并发穿过的缝。
_TAKEN_NS = uuid.UUID("6f9b1e2c-5a47-4d8e-9c31-7b0a2f4d8e10")

# 同进程内的抢跑还是要挡：老人手抖连点，两个请求同时走到"没查到 -> 插入"，
# 主键会让第二个失败，但那会在日志里留一串刺眼的 IntegrityError。锁在前面拦掉。
_taken_locks: dict[str, asyncio.Lock] = {}
_taken_locks_guard = asyncio.Lock()


def _log_id(plan_id: str, day: str, slot: str) -> str:
    return str(uuid.uuid5(_TAKEN_NS, f"{plan_id}|{day}|{slot}"))


async def _lock_for(key: str) -> asyncio.Lock:
    async with _taken_locks_guard:
        lock = _taken_locks.get(key)
        if lock is None:
            # 键里带日期，天然按天增长；到量了把没人拿着的清掉，别无限涨
            if len(_taken_locks) > 512:
                for k in [k for k, v in _taken_locks.items() if not v.locked()]:
                    del _taken_locks[k]
            lock = _taken_locks[key] = asyncio.Lock()
        return lock


def _is_active(plan: dict) -> bool:
    # 没有 active 字段的老数据按"在用"算，别让它凭空消失
    return plan.get("active", True) is not False


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
    plans = [p for p in plans if _is_active(p)]
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
    times = [t.strip() for t in body.times if t and t.strip()]
    if not times:
        raise HTTPException(400, "请至少填一个服药时间，例如 08:00")
    row = await ctx.repos.insert("medication_plans", {
        "elder_id": body.elder_id, "drug_name": body.drug_name.strip(),
        "dose": body.dose, "times": times,
        "notes": body.notes or "医生已开，遵医嘱服用", "active": True,
    })
    return row


@router.delete("/{plan_id}")
async def delete_medication(plan_id: str):
    """停用一条用药计划。

    做的是软删除：病历性质的数据不该真删，子女端和审计还要看得见历史打卡。
    列表接口会把 active=false 的过滤掉，所以老人端看着就是"没了"。
    """
    ctx = get_ctx()
    plan = await ctx.repos.get("medication_plans", plan_id)
    if not plan:
        raise HTTPException(404, "用药计划不存在")
    if not _is_active(plan):
        return plan  # 已经停用过了，重复请求当成功（前端可能点了两下）
    updated = await ctx.repos.update("medication_plans", plan_id, {
        "active": False,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    })
    if updated is None:
        raise HTTPException(404, "用药计划不存在")
    return updated


@router.post("/{plan_id}/taken")
async def mark_taken(plan_id: str, scheduled_time: str = ""):
    ctx = get_ctx()
    plan = await ctx.repos.get("medication_plans", plan_id)
    if not plan:
        raise HTTPException(404, "用药计划不存在")

    today = date.today().isoformat()
    slot = scheduled_time or (plan.get("times") or [""])[0]
    log_id = _log_id(plan_id, today, slot)

    async with await _lock_for(log_id):
        existing = await ctx.repos.get("medication_logs", log_id)
        if existing is None:
            # 兜早期数据：那时的 id 是随机 uuid，按 id 查不到，得按字段找一遍
            existing = await ctx.repos.find_one("medication_logs", {
                "plan_id": plan_id, "scheduled_for": today, "scheduled_time": slot,
            })
        if existing:
            if existing.get("status") == "taken":
                return existing  # 已经吃过了，幂等返回，不再写一条
            return await ctx.repos.update("medication_logs", existing["id"], {
                "status": "taken",
                "taken_at": datetime.now(timezone.utc).isoformat(),
            })
        return await ctx.repos.insert("medication_logs", {
            "id": log_id,
            "plan_id": plan_id, "scheduled_for": today,
            "scheduled_time": slot,
            "status": "taken", "taken_at": datetime.now(timezone.utc).isoformat(),
        })
