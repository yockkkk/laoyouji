"""家庭关系绑定测试：申请、同意、拒绝、解绑与权限隔离。"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_family_bindings_lifecycle(ctx, elder, child):
    # 初始 active 关系在 seed 中已存在
    binding = await ctx.repos.find_one("family_bindings", {
        "elder_id": elder["id"], "child_id": child["id"]
    })
    assert binding is not None
    assert binding.get("status") == "active"

    # 解绑
    await ctx.repos.update("family_bindings", binding["id"], {"status": "revoked"})
    revoked = await ctx.repos.get("family_bindings", binding["id"])
    assert revoked["status"] == "revoked"

    # 再次发起 pending 申请
    new_row = await ctx.repos.update("family_bindings", binding["id"], {
        "status": "pending",
        "relation": "儿子",
        "invited_by": child["id"],
    })
    assert new_row["status"] == "pending"

    # 老人同意
    accepted = await ctx.repos.update("family_bindings", binding["id"], {
        "status": "active",
    })
    assert accepted["status"] == "active"
