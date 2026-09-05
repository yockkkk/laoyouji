"""数据库装配：按 STORAGE_BACKEND 选实现。

这里只有一条铁律：**认不出来的 backend 必须抛，不许悄悄退回 local**。
之前 .env 写 STORAGE_BACKEND=mysql（而代码认的是 mariadb），启动日志照样打
"启动完成 storage=mysql"，实际却在往本机 JSON 文件里写 —— 数据全落在错的地方，
而且一点报错都没有。宁可起不来，也不能装作连上了。
"""
from __future__ import annotations

from typing import Any

from app.config import Settings

_BACKENDS = ("local", "mariadb", "ssh", "supabase")


def build_repo(settings: Settings) -> Any:
    """Repository 协议实现的组合根。"""
    backend = (settings.storage_backend or "").strip().lower()

    if backend in ("", "local"):
        from app.db.repositories import LocalFileRepo

        return LocalFileRepo(settings.local_data_dir)

    if backend == "mariadb":
        missing = [
            name
            for name, value in (
                ("MARIADB_HOST", settings.mariadb_host),
                ("MARIADB_USER", settings.mariadb_user),
                ("MARIADB_DB", settings.mariadb_db),
            )
            if not value
        ]
        if missing:
            raise ValueError(
                f"STORAGE_BACKEND=mariadb 但缺少 {' / '.join(missing)}，"
                "请补全 backend/.env，或改用 STORAGE_BACKEND=local"
            )
        from app.db.sql_repo import SQLRepository

        return SQLRepository(
            host=settings.mariadb_host,
            port=settings.mariadb_port,
            user=settings.mariadb_user,
            password=settings.mariadb_password,
            db=settings.mariadb_db,
            ssh_tunnel=settings.mariadb_ssh_tunnel,
            ssh_host=settings.mariadb_ssh_host or settings.ssh_host,
            ssh_port=settings.mariadb_ssh_port,
            ssh_user=settings.mariadb_ssh_user or settings.ssh_user,
            ssh_password=settings.mariadb_ssh_password or settings.ssh_password,
        )

    if backend == "ssh":
        if not settings.ssh_host or not settings.ssh_user:
            raise ValueError(
                "STORAGE_BACKEND=ssh 但缺少 SSH_HOST / SSH_USER，"
                "请补全 backend/.env，或改用 STORAGE_BACKEND=local"
            )
        from app.db.ssh_repo import SSHRepository

        return SSHRepository(
            host=settings.ssh_host,
            user=settings.ssh_user,
            password=settings.ssh_password,
            data_dir=settings.ssh_data_dir,
        )

    if backend == "supabase":
        if not settings.supabase_url or not settings.supabase_service_key:
            raise ValueError(
                "STORAGE_BACKEND=supabase 但缺少 SUPABASE_URL / SUPABASE_SERVICE_KEY，"
                "请先在 Supabase 建项目并执行 db/schema.sql，或改用 STORAGE_BACKEND=local"
            )
        from app.db.repositories import SupabaseRepo

        return SupabaseRepo(settings.supabase_url, settings.supabase_service_key)

    raise ValueError(
        f"STORAGE_BACKEND={settings.storage_backend!r} 不认识（可选：{', '.join(_BACKENDS)}）。"
        " 注意别写成 mysql —— MariaDB 请写 mariadb。"
    )
