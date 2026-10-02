param(
    [ValidateSet("start", "stop", "restart", "logs", "test", "build", "status")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"

function Check-Docker {
    try {
        docker info | Out-Null
    } catch {
        Write-Warning "Docker 守护进程未就绪，正在尝试连接 Docker Desktop..."
        Start-Process "C:\Users\lenovo\AppData\Local\Programs\DockerDesktop\Docker Desktop.exe"
        Start-Sleep -Seconds 5
    }
}

Check-Docker

switch ($Action) {
    "start" {
        Write-Host "🚀 正在启动老友记 Docker 集群..." -ForegroundColor Cyan
        docker compose up -d --build
        Write-Host "✅ 服务已启动！" -ForegroundColor Green
        Write-Host "  - 前端 H5:    http://localhost:5174"
        Write-Host "  - 后端 API:   http://localhost:8000"
        Write-Host "  - 文档 Swagger: http://localhost:8000/docs"
        Write-Host "  - 健康检查:   http://localhost:8000/api/health"
    }
    "stop" {
        Write-Host "🛑 正在停止老友记 Docker 容器..." -ForegroundColor Yellow
        docker compose down
        Write-Host "✅ 容器已停止。" -ForegroundColor Green
    }
    "restart" {
        Write-Host "🔄 正在重启老友记 Docker 集群..." -ForegroundColor Cyan
        docker compose restart
        Write-Host "✅ 容器已重启。" -ForegroundColor Green
    }
    "logs" {
        docker compose logs -f
    }
    "test" {
        Write-Host "🧪 正在在容器内运行自动化测试..." -ForegroundColor Cyan
        docker compose exec backend pytest tests
    }
    "build" {
        Write-Host "🔨 正在重新构建 Docker 镜像..." -ForegroundColor Cyan
        docker compose build --no-cache
    }
    "status" {
        docker compose ps
    }
}
