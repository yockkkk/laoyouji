"""数据库装配：按 STORAGE_BACKEND 选择 SupabaseRepo 或 LocalFileRepo。"""
from __future__ import annotations

from typing import Any

from app.config import Settings


def build_repo(settings: Settings) -> Any:
    """Repository 协议实现的组合根。"""
    if settings.storage_backend == "supabase":
        if not settings.supabase_url or not settings.supabase_service_key:
            raise ValueError(
                "STORAGE_BACKEND=supabase 但缺少 SUPABASE_URL / SUPABASE_SERVICE_KEY，"
                "请先在 Supabase 建项目并执行 db/schema.sql，或改用 STORAGE_BACKEND=local"
            )
        from app.db.repositories import SupabaseRepo

        return SupabaseRepo(settings.supabase_url, settings.supabase_service_key)
    from app.db.repositories import LocalFileRepo

    return LocalFileRepo(settings.local_data_dir)
