@echo off
chcp 65001 >nul
echo 正在停止老友记 Docker 容器集群...
docker compose down
echo.
echo 已成功停止并清理本地 Docker 容器！
pause
