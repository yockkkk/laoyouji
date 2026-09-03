"""演示种子数据：默认家庭（张桂芳 + 李明）+ 账号密码 + 用药计划 + 隐私默认授权。

幂等：reset 后重新灌入。POST /api/seed 与 scripts/seed_demo.py 共用。
"""
from __future__ import annotations

from typing import Any

from app.auth.security import hash_password
from app.db.repositories import Repository

# 演示环境统一密码（仅供开发测试与演示使用）
DEMO_PASSWORD_ELDER = "elder123456"
DEMO_PASSWORD_CHILD = "child123456"


async def seed_demo(repo: Repository) -> dict[str, Any]:
    await repo.reset()

    elder = await repo.insert("users", {
        "username": "zhangguifang",
        "password_hash": hash_password(DEMO_PASSWORD_ELDER),
        "status": "active",
        "role": "elder", "name": "张桂芳", "phone": "13800000001",
        "dialect": "southwestern", "city": "南京",
    })
    child = await repo.insert("users", {
        "username": "liming",
        "password_hash": hash_password(DEMO_PASSWORD_CHILD),
        "status": "active",
        "role": "child", "name": "李明", "phone": "13900000002",
        "dialect": "mandarin", "city": "北京",
    })
    await repo.insert("family_bindings", {
        "elder_id": elder["id"], "child_id": child["id"], "relation": "儿子",
        "status": "active",
    })
    await repo.insert("privacy_permissions", {
        "elder_id": elder["id"], "child_id": child["id"],
        "location_level": "realtime", "health_level": "summary",
    })
    await repo.insert("medication_plans", {
        "elder_id": elder["id"], "drug_name": "硫酸氨基葡萄糖胶囊",
        "dose": "每次1粒", "times": ["08:00", "20:00"],
        "notes": "饭后温水送服，医生已开", "active": True,
    })
    await repo.insert("medication_plans", {
        "elder_id": elder["id"], "drug_name": "钙片",
        "dose": "每次1片", "times": ["09:00"],
        "notes": "和牛奶隔开一小时", "active": True,
    })
    return {"elder": elder, "child": child}
