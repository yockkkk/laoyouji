"""老友记后端入口：uvicorn app.main:app --reload"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_asr,
    routes_auth,
    routes_chat,
    routes_child,
    routes_confirm,
    routes_family,
    routes_guardian,
    routes_health,
    routes_misc,
    routes_privacy,
)
from app.api.deps import get_app_context

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动装配 + 退出清理。

    用 lifespan 而不是 @app.on_event：后者在 FastAPI 里已标记废弃，每次起服务和
    每条测试都会打一条 DeprecationWarning。
    """
    ctx = get_app_context()  # 提前装配，启动即暴露配置错误
    logging.getLogger(__name__).info(
        "老友记启动完成：llm=%s asr=%s storage=%s agents=%s",
        ctx.registry.provider_name("llm"),
        ctx.registry.provider_name("asr"),
        ctx.settings.storage_backend,
        list(ctx.agents),
    )
    try:
        yield
    finally:
        # MariaDB 连接池和 SSH 隧道都带着后台线程，不显式关就留在进程里，
        # --reload 反复重启时会一路堆积（隧道还占着本地端口）。
        closer = getattr(getattr(ctx, "repos", None), "close", None)
        if closer is not None:
            try:
                await closer()
            except Exception:
                logging.getLogger(__name__).warning("关闭存储连接时出错", exc_info=True)


def create_app() -> FastAPI:
    app = FastAPI(
        title="老友记 · 老年人多智能体生活助手",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 开发演示：H5 前端跨域
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes_misc.router)
    app.include_router(routes_auth.router)
    app.include_router(routes_family.router)
    app.include_router(routes_chat.router)
    app.include_router(routes_asr.router)
    app.include_router(routes_confirm.router)
    app.include_router(routes_child.router)
    app.include_router(routes_guardian.router)
    app.include_router(routes_privacy.router)
    app.include_router(routes_health.router)

    return app


app = create_app()
