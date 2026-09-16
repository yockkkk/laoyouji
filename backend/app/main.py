"""康乐后端入口：uvicorn app.main:app --reload"""
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
        "康乐启动完成：llm=%s asr=%s storage=%s agents=%s",
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
        title="康乐 · 老年人健康生活多智能体助手",
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

    # 挂载静态分发目录 static_dist，提供 APK 下载与前端 H5 单页应用
    import os
    import json
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi import HTTPException

    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static_dist")

    @app.middleware("http")
    async def add_cache_control_headers(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith(".html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif "/assets/" in path:
            response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
        return response

    @app.get("/api/app/version")
    async def get_app_version():
        version_json_path = os.path.join(static_dir, "version.json")
        if os.path.isfile(version_json_path):
            try:
                with open(version_json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "versionCode": 101,
            "versionName": "1.0.1",
            "apkUrl": "https://sdad.hynu.site/laoyouji.apk",
            "updateTime": "2026-09-16",
            "changelog": "优化卡片布局，修复拨号与全屏退出",
        }

    @app.get("/laoyouji.apk")
    @app.head("/laoyouji.apk")
    async def download_apk():
        apk_path = os.path.join(static_dir, "laoyouji.apk")
        if os.path.isfile(apk_path):
            return FileResponse(
                apk_path,
                media_type="application/vnd.android.package-archive",
                filename="laoyouji.apk",
            )
        raise HTTPException(404, "APK 尚未生成或不存在")

    if os.path.isdir(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static_dist")

    return app


app = create_app()

