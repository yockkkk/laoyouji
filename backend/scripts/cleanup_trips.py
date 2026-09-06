"""Clean up duplicate trips in MariaDB / database."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bootstrap import build_context
from app.shared.plan_helpers import deduplicate_trips_for_elder


async def main() -> None:
    ctx = build_context()
    try:
        print("Connecting to database and cleaning duplicate trips...")
        elders = await ctx.repos.list("users", where={"role": "elder"})
        total_cleaned = 0
        for elder in elders:
            eid = elder["id"]
            before_trips = await ctx.repos.list("trips", where={"elder_id": eid})
            cleaned_trips = await deduplicate_trips_for_elder(ctx.repos, eid)
            removed = len(before_trips) - len(cleaned_trips)
            if removed > 0:
                print(f"Elder {elder.get('name')} ({eid}): removed {removed} duplicate trips. Remaining: {len(cleaned_trips)}")
                total_cleaned += removed
            else:
                print(f"Elder {elder.get('name')} ({eid}): no duplicates found. Total trips: {len(cleaned_trips)}")
        print(f"Cleanup finished! Total duplicate trips removed: {total_cleaned}")
    finally:
        closer = getattr(ctx.repos, "close", None)
        if closer is not None:
            await closer()


if __name__ == "__main__":
    asyncio.run(main())
