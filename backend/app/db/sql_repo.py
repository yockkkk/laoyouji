"""MariaDB/MySQL 存储实现（单表 JSON 模式，兼容 Repository 协议）。

为什么是单表：业务侧只用 insert/update/get/find_one/list/delete 这几把，没有
JOIN、没有报表。一张 laoyouji_records(table_name, id, data JSON) 就能承住全部
14 张逻辑表，schema 不用跟着业务字段来回改。

为什么可以走 SSH 隧道：MariaDB 默认 bind-address = 127.0.0.1，公网连不上。要么
改服务器配置 + 放行 3306（等于把库暴露到公网），要么本地拉一条 SSH 隧道连回环
端口。默认走后者：服务器一行配置都不用动。

排序的坑：JSON 取出来的值是文本，ORDER BY 会按字符串比，seq 到 10 之后就成了
1,10,11,2 —— 聊天记录会乱序。所以除了真列 created_at，其余字段一律取回 Python
里按类型排（本项目数据量是演示级，几百行以内）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
import warnings
from datetime import datetime, timezone

import aiomysql

from .repositories import utcnow_iso

logger = logging.getLogger(__name__)

# JSON 路径里的字段名要拼进 SQL，只放行标识符，别的一概拒掉
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_DDL = """
CREATE TABLE IF NOT EXISTS laoyouji_records (
    table_name VARCHAR(64)  NOT NULL,
    id         VARCHAR(64)  NOT NULL,
    data       JSON         NOT NULL,
    created_at DATETIME(6)  NOT NULL,
    PRIMARY KEY (table_name, id),
    KEY idx_table_created (table_name, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def _field(name: str) -> str:
    if not _FIELD_RE.match(name or ""):
        raise ValueError(f"非法字段名：{name!r}")
    return name


def _to_dt(value: object) -> datetime:
    """把 ISO 字符串收敛成 datetime，垃圾值退回当前时间（宁可时间不准，别丢数据）。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _sort_key(value: object) -> tuple:
    """类型感知排序键：数字按数字比，其余按字符串比，None 垫底。

    返回 (类型档位, 数值, 文本)，同档位内才真正比较 —— 免得 int 和 str 撞在一起
    抛 TypeError（LocalFileRepo 用 x.get(field, "") 也是同一个意思）。
    """
    if value is None:
        return (0, 0.0, "")
    if isinstance(value, bool):
        return (1, float(value), "")
    if isinstance(value, (int, float)):
        return (1, float(value), "")
    return (2, 0.0, str(value))


class SQLRepository:
    """MariaDB 版仓储。连接是懒初始化的：第一次真用到时才建池。

    不在 __init__ 里 create_task：装配 AppContext 的地方不一定有事件循环
    （tests/conftest.py 就是同步调 build_context 的），那样会直接 RuntimeError。
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        db: str,
        *,
        ssh_tunnel: bool = False,
        ssh_host: str = "",
        ssh_port: int = 22,
        ssh_user: str = "",
        ssh_password: str = "",
    ) -> None:
        self._host = host
        self._port = int(port)
        self._user = user
        self._password = password
        self._db = db

        self._ssh_tunnel = bool(ssh_tunnel)
        self._ssh_host = ssh_host or host
        self._ssh_port = int(ssh_port)
        self._ssh_user = ssh_user
        self._ssh_password = ssh_password

        self._pool: aiomysql.Pool | None = None
        self._tunnel = None
        # 3.10+ 的 Lock 不在构造时绑事件循环，放这儿安全
        self._init_lock = asyncio.Lock()

    # ---------- 连接生命周期 ----------

    def _start_tunnel_sync(self) -> int:
        from .ssh_tunnel import SSHPortForwarder

        if not self._ssh_user:
            raise RuntimeError(
                "MARIADB_SSH_TUNNEL=true 但没给 SSH 账号：请在 .env 填 "
                "MARIADB_SSH_USER / MARIADB_SSH_PASSWORD（或复用 SSH_USER / SSH_PASSWORD）"
            )
        tunnel = SSHPortForwarder(
            ssh_host=self._ssh_host,
            ssh_port=self._ssh_port,
            username=self._ssh_user,
            password=self._ssh_password,
            # 服务器视角的库地址：MariaDB 绑在回环上，所以这里固定 127.0.0.1
            remote_host="127.0.0.1",
            remote_port=self._port,
        )
        local_port = tunnel.start()
        self._tunnel = tunnel
        return local_port

    async def _connect(self) -> None:
        host, port = self._host, self._port
        if self._ssh_tunnel:
            port = await asyncio.to_thread(self._start_tunnel_sync)
            host = "127.0.0.1"
            logger.info(
                "MariaDB 走 SSH 隧道：127.0.0.1:%s -> %s 上的 127.0.0.1:%s",
                port, self._ssh_host, self._port,
            )

        self._pool = await aiomysql.create_pool(
            host=host,
            port=port,
            user=self._user,
            password=self._password,
            db=self._db,
            autocommit=True,
            charset="utf8mb4",
            minsize=1,
            maxsize=10,
            pool_recycle=3600,
            connect_timeout=10,
        )
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                # CREATE TABLE IF NOT EXISTS 在表已存在时会回一条 warning，
                # aiomysql 把它抬成 Python Warning 打在 stderr 上 —— 每次启动一条，
                # 看着像出错其实完全正常。这里就地吞掉，别的 warning 照常冒。
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore", message=r".*laoyouji_records' already exists.*")
                    await cur.execute(_DDL)

    async def _ensure_pool(self) -> aiomysql.Pool:
        """建池；失败就抛人话，并且不把失败状态缓存住（下次请求还能重试）。"""
        if self._healthy():
            assert self._pool is not None
            return self._pool
        async with self._init_lock:
            if self._healthy():
                assert self._pool is not None
                return self._pool
            # 隧道掉线时池子看着还开着，底下的 socket 全废了；先拆干净再重建
            await self._teardown()
            try:
                await self._connect()
            except Exception as exc:
                await self._teardown()
                how = "SSH 隧道" if self._ssh_tunnel else f"直连 {self._host}:{self._port}"
                raise RuntimeError(
                    f"连不上 MariaDB（{how}，库 {self._db!r}）：{type(exc).__name__}: {exc}。"
                    " 排查顺序：① 服务器上 systemctl is-active mariadb；"
                    "② 库和账号是否存在、密码对不对；"
                    "③ 直连模式还要看 bind-address 是否放开、3306 是否放行安全组"
                    "（不想放公网就把 MARIADB_SSH_TUNNEL 设成 true）"
                ) from exc
            assert self._pool is not None
            return self._pool

    def _healthy(self) -> bool:
        if self._pool is None or self._pool._closed:
            return False
        if self._tunnel is not None and not self._tunnel.is_alive():
            logger.warning("SSH 隧道已断开，下一次请求会重连")
            return False
        return True

    async def _teardown(self) -> None:
        if self._pool is not None:
            try:
                self._pool.close()
                await self._pool.wait_closed()
            except Exception:
                pass
            self._pool = None
        if self._tunnel is not None:
            try:
                await asyncio.to_thread(self._tunnel.stop)
            except Exception:
                pass
            self._tunnel = None

    async def close(self) -> None:
        await self._teardown()

    # ---------- 内部工具 ----------

    @staticmethod
    def _loads(raw: object) -> dict:
        # MariaDB 的 JSON 其实是 LONGTEXT，取回来是 str；MySQL 8 会给 dict
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        return json.loads(raw) if isinstance(raw, str) else raw

    async def _insert_raw(self, cur, table: str, row: dict) -> None:
        await cur.execute(
            "INSERT INTO laoyouji_records (table_name, id, data, created_at)"
            " VALUES (%s, %s, %s, %s)",
            (table, row["id"], json.dumps(row, ensure_ascii=False), _to_dt(row.get("created_at"))),
        )

    def _build_where(self, where: dict | None) -> tuple[str, list]:
        """JSON 字段等值匹配。

        COLLATE utf8mb4_bin 不能省：utf8mb4 默认排序规则不区分大小写，不加的话
        username='LiMing' 会匹配到 liming，跟 LocalFileRepo 的 Python == 语义就
        不一致了。
        """
        if not where:
            return "", []
        clauses: list[str] = []
        params: list = []
        for key, value in where.items():
            path = f"$.{_field(key)}"
            if value is None:
                clauses.append(f"JSON_EXTRACT(data, '{path}') IS NULL")
                continue
            if isinstance(value, bool):
                literal = "true" if value else "false"
            else:
                literal = str(value)
            clauses.append(
                f"JSON_UNQUOTE(JSON_EXTRACT(data, '{path}')) COLLATE utf8mb4_bin = %s"
            )
            params.append(literal)
        return " AND " + " AND ".join(clauses), params

    # ---------- Repository 协议 ----------

    async def insert(self, table: str, data: dict) -> dict:
        pool = await self._ensure_pool()
        row = dict(data)
        row.setdefault("id", str(uuid.uuid4()))
        row.setdefault("created_at", utcnow_iso())
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await self._insert_raw(cur, table, row)
        return row

    async def insert_many(self, table: str, rows: list[dict]) -> list[dict]:
        pool = await self._ensure_pool()
        now = utcnow_iso()
        out: list[dict] = []
        for r in rows:
            row = dict(r)
            row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("created_at", now)
            out.append(row)
        if not out:
            return []
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO laoyouji_records (table_name, id, data, created_at)"
                    " VALUES (%s, %s, %s, %s)",
                    [
                        (table, r["id"], json.dumps(r, ensure_ascii=False),
                         _to_dt(r.get("created_at")))
                        for r in out
                    ],
                )
        return out

    async def update(self, table: str, row_id: str, data: dict) -> dict | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            # 读-改-写必须在一个事务里并把行锁住，否则两个并发 update 会互相覆盖字段
            await conn.begin()
            try:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT data FROM laoyouji_records"
                        " WHERE table_name=%s AND id=%s FOR UPDATE",
                        (table, row_id),
                    )
                    res = await cur.fetchone()
                    if not res:
                        await conn.rollback()
                        return None
                    row = self._loads(res[0])
                    row.update(data)
                    await cur.execute(
                        "UPDATE laoyouji_records SET data=%s WHERE table_name=%s AND id=%s",
                        (json.dumps(row, ensure_ascii=False), table, row_id),
                    )
                await conn.commit()
                return row
            except Exception:
                await conn.rollback()
                raise

    async def get(self, table: str, row_id: str) -> dict | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT data FROM laoyouji_records WHERE table_name=%s AND id=%s",
                    (table, row_id),
                )
                res = await cur.fetchone()
        return self._loads(res[0]) if res else None

    async def find_one(self, table: str, where: dict) -> dict | None:
        rows = await self.list(table, where=where, limit=1)
        return rows[0] if rows else None

    async def list(
        self,
        table: str,
        where: dict | None = None,
        order: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        pool = await self._ensure_pool()
        where_sql, params = self._build_where(where)

        field, desc = None, False
        if order:
            head, _, tail = order.partition(".")
            desc = tail == "desc"
            if head.startswith("-"):
                head, desc = head[1:], True
            field = _field(head)

        # created_at 是真列，交给 SQL 排 + SQL LIMIT；其余字段藏在 JSON 里，SQL 只会
        # 按文本比大小，得取回来在 Python 里按类型排完再截断。
        sql_sorted = field in (None, "created_at")
        sql = f"SELECT data FROM laoyouji_records WHERE table_name=%s{where_sql}"
        args: list = [table, *params]
        if field == "created_at":
            sql += " ORDER BY created_at DESC" if desc else " ORDER BY created_at ASC"
        if sql_sorted and limit:
            sql += " LIMIT %s"
            args.append(int(limit))

        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, args)
                rows = [self._loads(r[0]) for r in await cur.fetchall()]

        if not sql_sorted:
            rows.sort(key=lambda r: _sort_key(r.get(field)), reverse=desc)
            if limit:
                rows = rows[: int(limit)]
        return rows

    async def delete(self, table: str, row_id: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM laoyouji_records WHERE table_name=%s AND id=%s",
                    (table, row_id),
                )
                return cur.rowcount > 0

    async def reset(self) -> None:
        """清空全部业务数据。种子数据由 seed_demo / POST /api/seed 负责，这里不管。"""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("TRUNCATE TABLE laoyouji_records")
