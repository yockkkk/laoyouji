@echo off
chcp 65001 >nul
echo 正在老友记后端 Docker 容器内执行全量自动化测试...
docker compose exec backend pytest tests
pause
