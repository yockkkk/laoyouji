"""清理超过保留窗口的会话及其事件（存储治理：默认只留最近 7 天）。

用法::

    python backend/scripts/cleanup_sessions.py                 # 真删 7 天前
    python backend/scripts/cleanup_sessions.py --dry-run        # 只看会删多少
    python backend/scripts/cleanup_sessions.py --days 3         # 自定义窗口

设计上的三条硬约束：

1. **不可恢复**：这里是物理删除，删掉就找不回来。所以默认是"先 --dry-run 看
   一眼"，真的要删再去掉参数。
2. **先删事件再删会话**：session_events 按 session_id 挂在 sessions 上，
   顺序反了会留下孤儿事件， hydrate 时读出一堆无主的事实。
3. **不碰别的表**：行程、计划书、用药方案、确认工单等产物**不在本脚本范围内**
   （它们有自己的生命周期，且是老人真要用的东西），只清会话与会话事件。

真要无人值守跑，用系统定时器::

    # 每天凌晨 3 点
    0 3 * * * cd /path/to/laoyouji && python backend/scripts/cleanup_sessions.py >> /var/log/lyj-cleanup.log 2>&1
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bootstrap import build_context

DEFAULT_KEEP_DAYS = 7


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def main(keep_days: int, dry_run: bool) -> int:
    ctx = build_context()
    cutoff = _cutoff(keep_days)
    try:
        print(f"保留窗口：最近 {keep_days} 天（早于 {cutoff} 的会话将被清理）")
        sessions = await ctx.repos.list("sessions", order="-created_at")
        expired = [s for s in sessions if s.get("created_at", "") < cutoff]

        if not expired:
            print("没有需要清理的过期会话。")
            return 0

        print(f"命中 {len(expired)} 个过期会话（共 {len(sessions)} 个）。")

        if dry_run:
            print("--dry-run：以下会话不会被删除")
            for s in expired[:20]:
                print(f"  - {s.get('id')}  created_at={s.get('created_at')}")
            if len(expired) > 20:
                print(f"  …… 另有 {len(expired) - 20} 个")
            return 0

        deleted_sessions = 0
        deleted_events = 0
        for session in expired:
            sid = session.get("id")
            if not sid:
                continue
            events = await ctx.repos.list("session_events", where={"session_id": sid})
            for event in events:
                eid = event.get("id")
                if eid:
                    await ctx.repos.delete("session_events", eid)
            deleted_events += len(events)
            await ctx.repos.delete("sessions", sid)
            deleted_sessions += 1

        print(f"清理完成：删除 {deleted_sessions} 个会话、{deleted_events} 条会话事件。")
        logging.getLogger(__name__).info(
            "cleanup_sessions: deleted %s sessions / %s events (keep_days=%s)",
            deleted_sessions, deleted_events, keep_days,
        )
        return 0
    finally:
        closer = getattr(ctx.repos, "close", None)
        if closer is not None:
            await closer()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理超过保留窗口的会话与会话事件")
    parser.add_argument("--days", type=int, default=DEFAULT_KEEP_DAYS,
                        help=f"保留最近 N 天的会话（默认 {DEFAULT_KEEP_DAYS}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印将被删除的会话，不执行删除")
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days 必须 >= 1")

    raise SystemExit(asyncio.run(main(args.days, args.dry_run)))
