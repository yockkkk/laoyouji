@echo off
chcp 65001 >nul
echo [1/3] 正在启动本地老友记 Docker 容器集群...
docker compose up -d --build
if errorlevel 1 (
    echo [错误] Docker 启动失败，请检查 Docker Desktop 引擎是否已启动。
    pause
    exit /b 1
)
echo [2/3] 等待容器服务就绪...
timeout /t 3 >nul
echo [3/3] 老友记本地服务已在 Docker 容器中启动完成！
echo.
echo   ================================================
echo   * 前端 H5 应用:    http://localhost:5174
echo   * 后端 API 服务:   http://localhost:8000
echo   * Swagger 接口文档: http://localhost:8000/docs
echo   * 健康状态检查:    http://localhost:8000/api/health
echo   ================================================
echo.
echo 提示：
echo   - 查看实时日志: 双击运行 docker-logs.bat
echo   - 停止所有容器: 双击运行 docker-stop.bat
echo   - 容器内跑测试: 双击运行 docker-test.bat
pause
