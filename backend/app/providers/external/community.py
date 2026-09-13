"""社区 Provider（邻里帮 → 心理·社交线）：线下活动 + 散步环线 + 家常食谱。

康乐收敛后，付费社区服务（食堂订餐 / 保洁陪诊下单 / 订单查询）整条砍掉（orders 表停用），
只留三个读接口，它们对着右翼·心理健康：

- ``activities``  线下活动（棋牌室 / 养老院 / 公园 / 社区义诊）—— 让老人走出家门
- ``walk_loops``  环形散步路线（距离 / 歇脚点 / 好走不好走）—— 出门的身体门槛降到最低
- ``recipes``     家常菜谱 —— 一个人吃饭也要吃得像样

**数据全是合成演示数据**（fixture 里带 ``source`` 字段自陈）：社区公告和菜谱都是编的，
不是任何真实社区发布的通知，也不是营养师开的方子。演示时必须让这层身份看得见。

本域没有 Real 实现：社区公告和菜谱都不存在现成的官方开放 API，先造一个空的
``RealCommunityProvider`` 只会变成死代码，所以本文件只有 Mock 一侧。
"""
from __future__ import annotations

import asyncio
import random

from app.providers.external.base import load_fixture


class CommunityProvider:
    async def activities(self, *, kind: str | None = None) -> list[dict]:
        raise NotImplementedError

    async def walk_loops(self, *, city: str | None = None) -> list[dict]:
        raise NotImplementedError

    async def recipes(self, *, category: str | None = None) -> list[dict]:
        raise NotImplementedError


def _match_kind(item: dict, kind: str) -> bool:
    """活动类型匹配：宽松，但不瞎认。

    ``kind`` 是模型说出口的词（"棋牌室"、"公园"），fixture 里写的是分词（"公园"）。
    两种粒度对不上就没有活动 —— 所以按 ``services._mentions`` 的思路双向包含：
    老人说"想找人打牌"，模型填 ``棋牌室``；说"去公园"，模型可能填 ``公园`` 也可能
    照抄标题里的词。宁可放宽这一头，也不要因为一个字对不上就回一句"没有活动"。
    """
    field = str(item.get("kind") or "")
    return bool(kind) and (kind in field or field in kind
                           or kind in str(item.get("title") or ""))


class MockCommunityProvider(CommunityProvider):
    name = "mock_community"

    async def activities(self, *, kind: str | None = None) -> list[dict]:
        await asyncio.sleep(random.uniform(0.1, 0.3))
        rows = load_fixture("activities")["activities"]
        if kind:
            rows = [a for a in rows if _match_kind(a, str(kind))]
        return rows

    async def walk_loops(self, *, city: str | None = None) -> list[dict]:
        """按城市取环线。**匹配不到就返回空列表，不退回"随便给一条"。**

        同 MockMapProvider 的取向：老人照着一条不在自己城市的路走，比"我这儿没有"
        糟糕得多 —— 前者他会真出门。所以宁可说没有，让他去问社区。
        """
        await asyncio.sleep(random.uniform(0.1, 0.3))
        rows = load_fixture("activities")["walk_loops"]
        if not city:
            return rows
        want = str(city).strip()
        return [r for r in rows
                if want in str(r.get("city") or "")
                or str(r.get("city") or "") in want]

    async def recipes(self, *, category: str | None = None) -> list[dict]:
        await asyncio.sleep(random.uniform(0.1, 0.3))
        rows = load_fixture("recipes")["recipes"]
        if category:
            rows = [r for r in rows if str(category) in str(r.get("category") or "")]
        return rows
