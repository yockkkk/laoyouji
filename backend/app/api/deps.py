"""FastAPI 依赖：全局唯一的 AppContext（进程内单例）。"""
from __future__ import annotations

from functools import lru_cache

from app.bootstrap import build_context
from app.core.context import AppContext


@lru_cache(maxsize=1)
def get_app_context() -> AppContext:
    return build_context()


def get_ctx() -> AppContext:
    return get_app_context()
