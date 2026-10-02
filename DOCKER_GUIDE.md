# 老友记 (LaoYouJi) · 本地 Docker 容器化运行指南

本项目现已全面支持基于 Docker 与 Docker Compose 的本地一键容器化开发与运行环境。

---

## 快速上手（一键运行）

在项目根目录下，提供了开箱即用的快捷批处理脚本（直接双击即可运行）：

| 脚本文件 | 说明 | 对应命令 |
| :--- | :--- | :--- |
| **`docker-start.bat`** | **启动/热构建本地 Docker 集群** | `docker compose up -d --build` |
| **`docker-stop.bat`** | **停止并清理本地 Docker 容器** | `docker compose down` |
| **`docker-logs.bat`** | **查看容器实时运行日志** | `docker compose logs -f` |
| **`docker-test.bat`** | **在后端容器内运行全量自动化测试** | `docker compose exec backend pytest tests` |

---

## 本地服务访问入口

容器启动成功后，即可直接在宿主机浏览器中访问以下地址：

- **前端适老移动端 H5**：[http://localhost:5174](http://localhost:5174)
- **后端 FastAPI 接口服务**：[http://localhost:8000](http://localhost:8000)
- **Swagger 交互式 API 文档**：[http://localhost:8000/docs](http://localhost:8000/docs)
- **服务健康状态检查**：[http://localhost:8000/api/health](http://localhost:8000/api/health)

---

## 架构与特性

### 1. 双服务容器拓扑
- **`backend` 容器**：
  - 基于 `python:3.12-slim` 构建；
  - 挂载宿主机 `./backend` 源码目录（具备 `--reload` 热重载能力，保存 Python 代码即刻生效）；
  - 自动读取 `backend/.env` 凭据配置；
  - 内置健康检查探针（`HEALTHCHECK`），确保数据源与 Agent 装配就绪。
- **`frontend` 容器**：
  - 基于 `node:20-slim` 构建；
  - 运行 Vite 开发服务器，支持 HMR 热更新；
  - 内网反向代理自动将 `/api` 指向 `http://backend:8000`，杜绝跨域预检与浏览器代理拦截。

### 2. 命令行操作指南

如果你习惯使用 PowerShell 或终端命令行：

```bash
# 1. 启动容器集群（后台运行）
docker compose up -d

# 2. 查看当前容器运行状态
docker compose ps

# 3. 查看实时滚动日志
docker compose logs -f

# 4. 进入后端容器终端排查
docker compose exec backend bash

# 5. 在容器内运行 pytest 测试
docker compose exec backend pytest tests

# 6. 停止并释放容器资源
docker compose down
```

---

## 常见问题与说明

1. **Docker Desktop 启动**：运行前请确保 Windows 的 Docker Desktop 处于运行状态（小鲸鱼图标就绪）。
2. **代码修改即时生效**：前端与后端的源码均已挂载至容器中，日常修改前端 Vue 组件或后端 Agent 提示词、接口逻辑，均无需重新构建镜像，即改即生效。
3. **数据库连接**：后端容器完全继承宿主机 `backend/.env` 中的配置，支持自动建立 SSH 隧道直通远程 MariaDB，体验与宿主机原生运行完全一致。
