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

    # 生产部署：如果存在前端构建物目录 static_dist，提供 APK 下载与 SPA 静态页面
    import os
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static_dist")

    @app.get("/laoyouji.apk")
    async def download_apk():
        apk_path = os.path.join(static_dir, "laoyouji.apk")
        if os.path.isfile(apk_path):
            return FileResponse(
                apk_path,
                media_type="application/vnd.android.package-archive",
                filename="laoyouji.apk",
            )
        raise HTTPException(404, "APK 尚未生成或正在编译中")

    from fastapi.responses import HTMLResponse

    @app.get("/download", response_class=HTMLResponse)
    async def download_page():
        return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>老友记 App 官方下载</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", sans-serif; background: #f1f5f9; color: #1e293b; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px 16px; }
        .card { background: white; border-radius: 24px; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.07), 0 8px 10px -6px rgba(0,0,0,0.04); max-width: 440px; width: 100%; padding: 36px 28px; text-align: center; }
        .logo { width: 88px; height: 88px; background: linear-gradient(135deg, #2563eb, #1d4ed8); border-radius: 20px; margin: 0 auto 20px; display: flex; align-items: center; justify-content: center; font-size: 40px; box-shadow: 0 10px 15px -3px rgba(37,99,235,0.3); }
        h1 { font-size: 26px; font-weight: 700; color: #0f172a; margin-bottom: 8px; }
        .subtitle { font-size: 15px; color: #64748b; margin-bottom: 28px; line-height: 1.5; }
        .btn-download { display: block; width: 100%; background: #2563eb; color: white; text-decoration: none; padding: 16px 20px; border-radius: 16px; font-size: 18px; font-weight: 600; box-shadow: 0 10px 20px -5px rgba(37,99,235,0.4); transition: all 0.2s; margin-bottom: 16px; }
        .btn-download:hover { background: #1d4ed8; transform: translateY(-1px); }
        .btn-web { display: block; width: 100%; background: #f8fafc; color: #334155; text-decoration: none; padding: 14px 20px; border-radius: 16px; font-size: 16px; font-weight: 500; border: 1px solid #e2e8f0; transition: all 0.2s; margin-bottom: 28px; }
        .btn-web:hover { background: #f1f5f9; }
        .info-box { background: #f8fafc; border-radius: 16px; padding: 18px; text-align: left; font-size: 14px; color: #475569; border: 1px solid #e2e8f0; }
        .info-box h3 { font-size: 14px; font-weight: 600; color: #0f172a; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }
        .account-row { display: flex; justify-content: space-between; margin-bottom: 8px; padding-bottom: 8px; border-bottom: 1px dashed #cbd5e1; }
        .account-row:last-child { margin-bottom: 0; padding-bottom: 0; border-bottom: none; }
    </style>
</head>
<body>
    <div class="card">
        <div class="logo">👵</div>
        <h1>老友记</h1>
        <p class="subtitle">老年人多智能体生活助手<br>原生长辈大字界面 · 智能问诊规划 · 家人实时守护</p>
        <a href="/laoyouji.apk" class="btn-download">📱 立即下载安卓版 (APK)</a>
        <a href="/" class="btn-web">🌐 在浏览器中直接打开</a>
        <div class="info-box">
            <h3>🔑 演示预设账号</h3>
            <div class="account-row">
                <span><strong>长辈端：</strong>张桂芳</span>
                <span>账号 <code>zhangguifang</code> / 密码 <code>123456</code></span>
            </div>
            <div class="account-row">
                <span><strong>子女端：</strong>李明</span>
                <span>账号 <code>liming</code> / 密码 <code>123456</code></span>
            </div>
        </div>
    </div>
</body>
</html>"""

    if os.path.isdir(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static_dist")

    return app


app = create_app()
