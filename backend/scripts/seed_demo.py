"""灌入演示数据（等价 POST /api/seed）。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bootstrap import build_context  # noqa: E402
from app.db.seed import seed_demo  # noqa: E402


async def main() -> None:
    ctx = build_context()
    result = await seed_demo(ctx.repos)
    print(f"演示数据已复位：{result['elder']['name']}（{result['elder']['id']}）— "
          f"{result['child']['name']}（{result['child']['id']}）")


if __name__ == "__main__":
    asyncio.run(main())
