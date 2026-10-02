@echo off
chcp 65001 >nul
echo 正在查看老友记 Docker 容器实时日志 (按 Ctrl+C 退出)...
docker compose logs -f
