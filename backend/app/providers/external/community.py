"""社区服务 Provider（食堂订餐 / 保洁陪诊下单 / 活动推送）。"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone

from app.providers.external.base import derive_no, load_fixture


class CommunityProvider:
    async def menu(self) -> list[dict]:
        raise NotImplementedError

    async def activities(self) -> list[dict]:
        raise NotImplementedError

    async def service_catalog(self, service_type: str) -> list[dict]:
        raise NotImplementedError


class MockCommunityProvider(CommunityProvider):
    name = "mock_community"

    async def menu(self) -> list[dict]:
        await asyncio.sleep(random.uniform(0.1, 0.3))
        return load_fixture("canteen_menu")["meals"]

    async def activities(self) -> list[dict]:
        await asyncio.sleep(random.uniform(0.1, 0.3))
        return load_fixture("canteen_menu")["activities"]

    async def service_catalog(self, service_type: str) -> list[dict]:
        await asyncio.sleep(random.uniform(0.1, 0.3))
        return load_fixture("canteen_menu")["providers"].get(service_type, [])

    @staticmethod
    def initial_timeline(service_type: str, provider: str) -> list[dict]:
        now = datetime.now(timezone.utc).isoformat()
        return [
            {"at": now, "text": "订单已创建，等待派单"},
            {"at": now, "text": f"已派单给{provider}，等待接单"},
        ]
