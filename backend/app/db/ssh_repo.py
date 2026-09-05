import asyncio
import json
import threading
import uuid
import paramiko

from .repositories import TABLES, utcnow_iso

class SSHRepository:
    """基于 SSH SFTP 的 JSON 存储，完全兼容 Repository 协议"""

    def __init__(self, host: str, user: str, password: str, data_dir: str):
        self._host = host
        self._user = user
        self._password = password
        self._data_dir = data_dir
        
        self._cache: dict[str, list[dict]] = {}
        self._lock = threading.RLock()
        
        self._init_sftp()
        self._load_all()

    def _init_sftp(self):
        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self._ssh.connect(
                self._host,
                username=self._user,
                password=self._password,
                timeout=10,
                banner_timeout=15,
                auth_timeout=15
            )
            self._sftp = self._ssh.open_sftp()
            
            try:
                self._sftp.stat(self._data_dir)
            except IOError:
                self._ssh.exec_command(f"mkdir -p {self._data_dir}")
        except Exception as exc:
            # 不能静默降级：_sftp=None 之后所有 _flush 都变成空操作，
            # 数据全丢在内存里，接口却一路 200 —— 那比起不来难查一百倍。
            raise RuntimeError(
                f"SSH 存储连不上 {self._user}@{self._host}：{type(exc).__name__}: {exc}。"
                " 检查主机/账号/密码，或改用 STORAGE_BACKEND=local"
            ) from exc

    def _path(self, table: str) -> str:
        return f"{self._data_dir}/{table}.json"

    def _load_all(self) -> None:
        for table in TABLES:
            p = self._path(table)
            try:
                with self._sftp.open(p, "r") as f:
                    content = f.read().decode("utf-8")
                    self._cache[table] = json.loads(content)
            except IOError:
                self._cache[table] = []
            except json.JSONDecodeError:
                self._cache[table] = []


    def _flush(self, table: str) -> None:
        p = self._path(table)
        tmp = f"{p}.tmp"
        content = json.dumps(self._cache.get(table, []), ensure_ascii=False, indent=1)
        try:
            with self._sftp.open(tmp, "w") as f:
                f.write(content.encode("utf-8"))
            self._sftp.posix_rename(tmp, p)
        except Exception as exc:
            # 写盘失败必须让调用方知道，不然内存和服务器上的 JSON 就悄悄分叉了
            raise RuntimeError(f"SSH 存储写入 {table} 失败：{exc}") from exc

    def _rows(self, table: str) -> list[dict]:
        if table not in self._cache:
            self._cache[table] = []
        return self._cache[table]

    @staticmethod
    def _match(row: dict, where: dict) -> bool:
        for k, v in where.items():
            if row.get(k) != v:
                return False
        return True

    async def insert(self, table: str, data: dict) -> dict:
        return await asyncio.to_thread(self._insert_sync, table, data)

    def _insert_sync(self, table: str, data: dict) -> dict:
        row = data.copy()
        if "id" not in row:
            row["id"] = str(uuid.uuid4())
        if "created_at" not in row:
            row["created_at"] = utcnow_iso()
        with self._lock:
            self._rows(table).append(row)
            self._flush(table)
        return row

    async def insert_many(self, table: str, rows: list[dict]) -> list[dict]:
        return await asyncio.to_thread(self._insert_many_sync, table, rows)

    def _insert_many_sync(self, table: str, rows: list[dict]) -> list[dict]:
        out = []
        now = utcnow_iso()
        with self._lock:
            target = self._rows(table)
            for r in rows:
                new_r = r.copy()
                if "id" not in new_r:
                    new_r["id"] = str(uuid.uuid4())
                if "created_at" not in new_r:
                    new_r["created_at"] = now
                target.append(new_r)
                out.append(new_r)
            self._flush(table)
        return out

    async def update(self, table: str, row_id: str, data: dict) -> dict | None:
        return await asyncio.to_thread(self._update_sync, table, row_id, data)

    def _update_sync(self, table: str, row_id: str, data: dict) -> dict | None:
        with self._lock:
            for row in self._rows(table):
                if row.get("id") == row_id:
                    row.update(data)
                    self._flush(table)
                    return row
        return None

    async def get(self, table: str, row_id: str) -> dict | None:
        return await asyncio.to_thread(self._get_sync, table, row_id)

    def _get_sync(self, table: str, row_id: str) -> dict | None:
        with self._lock:
            for row in self._rows(table):
                if row.get("id") == row_id:
                    return row
        return None

    async def find_one(self, table: str, where: dict) -> dict | None:
        return await asyncio.to_thread(self._find_one_sync, table, where)

    def _find_one_sync(self, table: str, where: dict) -> dict | None:
        with self._lock:
            for row in self._rows(table):
                if self._match(row, where):
                    return row
        return None

    async def list(
        self,
        table: str,
        where: dict | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        return await asyncio.to_thread(self._list_sync, table, where, order, limit)

    def _list_sync(
        self,
        table: str,
        where: dict | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        with self._lock:
            rs = self._rows(table)
            if where:
                rs = [r for r in rs if self._match(r, where)]
            
            if order:
                parts = order.split(".")
                field = parts[0]
                desc = len(parts) > 1 and parts[1] == "desc"
                rs.sort(key=lambda x: x.get(field, ""), reverse=desc)
                
            if limit:
                rs = rs[:limit]
            return rs

    async def delete(self, table: str, row_id: str) -> bool:
        return await asyncio.to_thread(self._delete_sync, table, row_id)

    def _delete_sync(self, table: str, row_id: str) -> bool:
        with self._lock:
            rs = self._rows(table)
            for i, row in enumerate(rs):
                if row.get("id") == row_id:
                    del rs[i]
                    self._flush(table)
                    return True
        return False

    async def reset(self) -> None:
        await asyncio.to_thread(self._reset_sync)

    def _reset_sync(self) -> None:
        with self._lock:
            self._cache.clear()
            for t in TABLES:
                self._flush(t)
            self._load_all()

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        try:
            if getattr(self, "_sftp", None):
                self._sftp.close()
            if getattr(self, "_ssh", None):
                self._ssh.close()
        except Exception:
            pass

    def __del__(self):
        try:
            if hasattr(self, '_sftp') and self._sftp:
                self._sftp.close()
            if hasattr(self, '_ssh') and self._ssh:
                self._ssh.close()
        except Exception:
            pass
