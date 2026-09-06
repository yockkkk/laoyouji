"""存储仓储层：Repository 协议 + SupabaseRepo（主）+ LocalFileRepo（JSON 文件兜底）。

ADR-2：不做 SQLite 双 ORM；两个实现共用同一协议，业务代码只依赖协议。
所有方法 async（Supabase 客户端是同步 HTTP，经 asyncio.to_thread 包装）。
"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

# 演示系统的全部业务表（reset 时按序清空）
TABLES = [
    "notifications",
    "audit_log",
    "privacy_permissions",
    "orders",
    "health_records",
    "medication_logs",
    "medication_plans",
    "trip_checkpoints",
    "trips",
    "confirmation_tasks",
    "session_events",
    "sessions",
    "family_bindings",
    "users",
]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository(Protocol):
    """业务代码唯一依赖的存储协议。"""

    async def insert(self, table: str, data: dict) -> dict: ...
    # 批量插入：一轮对话会产生几十条 session_events，逐条 insert 就是几十个
    # 往返。落库在轮次末尾的检查点做，那里一次写完才不拖住下一句话。
    async def insert_many(self, table: str, rows: list[dict]) -> list[dict]: ...
    async def update(self, table: str, row_id: str, data: dict) -> dict | None: ...
    async def get(self, table: str, row_id: str) -> dict | None: ...
    async def find_one(self, table: str, where: dict) -> dict | None: ...
    async def list(self, table: str, where: dict | None = None,
                   order: str | None = None, limit: int | None = None) -> list[dict]: ...
    async def delete(self, table: str, row_id: str) -> bool: ...
    async def reset(self) -> None: ...


class SupabaseRepo:
    """Supabase Postgres 实现（service key 仅后端持有，表 RLS 全拒）。"""

    def __init__(self, url: str, service_key: str):
        from supabase import create_client  # 延迟导入，local 模式无需安装可用性影响

        self._client = create_client(url, service_key)

    async def insert(self, table: str, data: dict) -> dict:
        data = dict(data)
        if table == "session_events":
            data.pop("id", None)
        elif "id" not in data:
            data["id"] = str(uuid.uuid4())
        row = await asyncio.to_thread(
            self._client.table(table).insert(data).execute
        )
        return row.data[0]

    async def insert_many(self, table: str, rows: list[dict]) -> list[dict]:
        if not rows:
            return []
        payload = []
        for data in rows:
            data = dict(data)
            if table == "session_events":
                data.pop("id", None)
            elif "id" not in data:
                data["id"] = str(uuid.uuid4())
            payload.append(data)
        res = await asyncio.to_thread(
            self._client.table(table).insert(payload).execute
        )
        return res.data or []

    async def update(self, table: str, row_id: str, data: dict) -> dict | None:
        row = await asyncio.to_thread(
            self._client.table(table).update(data).eq("id", row_id).execute
        )
        return row.data[0] if row.data else None

    async def get(self, table: str, row_id: str) -> dict | None:
        row = await asyncio.to_thread(
            self._client.table(table).select("*").eq("id", row_id).execute
        )
        return row.data[0] if row.data else None

    async def find_one(self, table: str, where: dict) -> dict | None:
        rows = await self.list(table, where=where, limit=1)
        return rows[0] if rows else None

    async def list(self, table: str, where: dict | None = None,
                   order: str | None = None, limit: int | None = None) -> list[dict]:
        def _run() -> list[dict]:
            q = self._client.table(table).select("*")
            if where:
                for k, v in where.items():
                    q = q.eq(k, v)
            if order:
                desc = order.startswith("-")
                q = q.order(order.lstrip("-"), desc=desc)
            if limit:
                q = q.limit(limit)
            return q.execute().data

        return await asyncio.to_thread(_run)

    async def delete(self, table: str, row_id: str) -> bool:
        row = await asyncio.to_thread(
            self._client.table(table).delete().eq("id", row_id).execute
        )
        return bool(row.data)

    async def reset(self) -> None:
        # 演示复位：按依赖序清空全部业务表
        for table in TABLES:
            def _del():
                if table in ("audit_log", "session_events"):
                    return self._client.table(table).delete().gt("id", -1).execute()
                return self._client.table(table).delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

            await asyncio.to_thread(_del)


class LocalFileRepo:
    """JSON 文件实现（STORAGE_BACKEND=local，断网/无 Supabase 兜底）。

    每表一个 JSON 文件，读写加线程锁，写盘原子（先写临时文件再替换）。
    """

    def __init__(self, data_dir: str | Path):
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cache: dict[str, list[dict]] = {}
        self._load_all()

    def _path(self, table: str) -> Path:
        return self._dir / f"{table}.json"

    def _load_all(self) -> None:
        for table in TABLES:
            p = self._path(table)
            if p.exists():
                try:
                    self._cache[table] = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    self._cache[table] = []
            else:
                self._cache[table] = []

    def _flush(self, table: str) -> None:
        p = self._path(table)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._cache.get(table, []), ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        tmp.replace(p)

    def _rows(self, table: str) -> list[dict]:
        if table not in self._cache:
            self._cache[table] = []
        return self._cache[table]

    @staticmethod
    def _match(row: dict, where: dict) -> bool:
        return all(row.get(k) == v for k, v in where.items())

    async def insert(self, table: str, data: dict) -> dict:
        def _do() -> dict:
            row = dict(data)
            with self._lock:
                if "id" not in row:
                    if table == "session_events":
                        row = {"id": len(self._rows(table)) + 1, **row}
                    else:
                        row = {"id": str(uuid.uuid4()), **row}
                if "created_at" not in row:
                    row = {**row, "created_at": utcnow_iso()}
                self._rows(table).append(row)
                self._flush(table)
                return dict(row)

        return await asyncio.to_thread(_do)

    async def insert_many(self, table: str, rows: list[dict]) -> list[dict]:
        """整批一次锁、一次写盘（逐条 insert 会把同一个文件写 N 遍）。"""
        if not rows:
            return []

        def _do() -> list[dict]:
            out = []
            with self._lock:
                target = self._rows(table)
                for data in rows:
                    row = dict(data)
                    if "id" not in row:
                        if table == "session_events":
                            row = {"id": len(target) + 1, **row}
                        else:
                            row = {"id": str(uuid.uuid4()), **row}
                    if "created_at" not in row:
                        row = {**row, "created_at": utcnow_iso()}
                    target.append(row)
                    out.append(dict(row))
                self._flush(table)
            return out

        return await asyncio.to_thread(_do)

    async def update(self, table: str, row_id: str, data: dict) -> dict | None:
        def _do() -> dict | None:
            with self._lock:
                for row in self._rows(table):
                    if row.get("id") == row_id:
                        row.update(data)
                        self._flush(table)
                        return dict(row)
                return None

        return await asyncio.to_thread(_do)

    async def get(self, table: str, row_id: str) -> dict | None:
        with self._lock:
            for row in self._rows(table):
                if row.get("id") == row_id:
                    return dict(row)
        return None

    async def find_one(self, table: str, where: dict) -> dict | None:
        with self._lock:
            for row in self._rows(table):
                if self._match(row, where):
                    return dict(row)
        return None

    async def list(self, table: str, where: dict | None = None,
                   order: str | None = None, limit: int | None = None) -> list[dict]:
        with self._lock:
            rows = [dict(r) for r in self._rows(table) if self._match(r, where or {})]
        if order:
            key = order.lstrip("-")
            rows.sort(key=lambda r: (r.get(key) is None, r.get(key)),
                      reverse=order.startswith("-"))
        if limit:
            rows = rows[:limit]
        return rows

    async def delete(self, table: str, row_id: str) -> bool:
        def _do() -> bool:
            with self._lock:
                rows = self._rows(table)
                for i, row in enumerate(rows):
                    if row.get("id") == row_id:
                        rows.pop(i)
                        self._flush(table)
                        return True
                return False

        return await asyncio.to_thread(_do)

    async def reset(self) -> None:
        def _do() -> None:
            with self._lock:
                for table in TABLES:
                    self._cache[table] = []
                    self._flush(table)

        await asyncio.to_thread(_do)
