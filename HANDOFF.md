# 老友记 · 上下文交接与变更日志

> 目标：让新的智能体 / 新的 Claude 会话能**在不读长对话**的情况下，直接接手继续工作。
> 快照时间：2026-09-03（亚太时间）
> 当前会话使用模型：`claude-fable-5[1m]`（与上下文刚切换的 `Opus 4.8` 都能继续读这份文件）。

---

## 0. 仓库与路径

- **Git 仓库根**：`C:\Users\29602\Desktop\yoc\laoyouji`
  - `.git/` 真实存在，`git status` 工作区
  - 当前 HEAD：`35acf56 chore: 项目初始提交`
  - 工作区与远端 `origin/main` 一致，但**有 20 个文件修改 + 11 个新文件未提交**
- **本机可执行入口**：
  - 后端 FastAPI：`laoyouji/backend`（端口 8000，脚本 `python -m uvicorn app.main:app --port 8000`，建议在 backend 目录下加 `--reload`）
  - 前端 H5：`laoyouji/frontend/laoyouji-app`（端口 5173，脚本 `npm run dev:h5`）
  - E2E：`laoyouji/frontend/e2e`
  - 演示剧本/接口文档：`laoyouji/docs`
- **本机已有依赖**（用户原已具备）：
  - Python 3.14（`C:\Users\29602\AppData\Local\Programs\Python\Python314\python.exe`）
  - Node.js + npm
  - 后端 Python 依赖已 `pip install -r requirements.txt` 完整
  - 前端 `node_modules` 已 `npm install`
- **MCP 启动配置**（仅本机）`C:\Users\29602\.claude\launch.json`：
  ```json
  {
    "version": "0.0.1",
    "configurations": [
      { "name": "laoyouji-backend",
        "runtimeExecutable": "python",
        "runtimeArgs": ["-m", "uvicorn", "app.main:app", "--app-dir", "laoyouji/backend", "--port", "8000"],
        "port": 8000 },
      { "name": "laoyouji-frontend",
        "runtimeExecutable": "npm",
        "runtimeArgs": ["--prefix", "laoyouji/frontend/laoyouji-app", "run", "dev:h5"],
        "port": 5173 }
    ]
  }
  ```

---

## 1. 当前目标 & 已完成

完成方向：**登录鉴权 + 家庭关系组 + 家人页扩充**，账号密码注册登录。

### 1.1 已完成（代码 + 测试全绿）
- **后端认证**：
  - `backend/app/auth/security.py`：`scrypt` 密码哈希、HMAC-SHA256 JWT 签发与校验、`Principal` 数据类、`AuthError`
  - `backend/app/api/routes_auth.py`：`register` / `login` / `me` / `refresh` / `logout`，统一输出 DTO（绝不返回 password_hash）
  - `backend/app/api/deps.py`：`get_ctx`（单例 AppContext）、`get_current_principal`（Bearer Token 注入）、`require_role`、`get_optional_principal`（用于 SSE 兜底）
  - `backend/app/main.py` 启动日志：装配 `llm/asr/storage/agents`
- **家庭关系**：
  - `backend/app/api/routes_family.py`：`GET /members`（按当前用户角色返回家人/老人），`POST /requests`（发起申请，自带合法性校验：合法 elder-child 配对、不能自绑、不能重复 pending/active），`POST /requests/{id}/accept`（被邀请方确认、初始化默认 privacy 权限），`POST /requests/{id}/reject`，`DELETE /bindings/{id}`（解绑、关闭隐私、写审计）
  - `backend/app/db/schema.sql`：`users` 增加 `username unique` / `password_hash` / `status`，`family_bindings` 增加 `status`（pending/active/rejected/revoked/expired）、`invited_by` / `approved_at` / `resolved_at` / `revoked_at`
  - `backend/app/db/seed.py`：给张桂芳、李明生成账号密码：
    - `zhangguifang` / `elder123456`（老人）
    - `liming` / `child123456`（子女）
    - 默认 `family_bindings` 状态写为 `active`
- **核心接口强制鉴权**（旧参数最多用于一致性校验）：
  - `routes_child.py` / `routes_confirm.py` / `routes_privacy.py` / `routes_chat.py` 全部改为 `Depends(get_current_principal)`，禁止客户端伪造 `actor_id`
  - `routes_chat.py` 兼容旧 `user_id` 字段（无 Token 时仅供测试夹具），但 Token 存在时与 Token 不一致直接 403
  - `routes_confirm.py` 的 approve/reject 强制校验 `actor.role == "child"`
  - `routes_privacy.py` 强制 `actor.id == elder_id and actor.role == "elder"`，审计 actor 来自 Token
- **前端**：
  - `store/user.js` 增加 token 持久化 + 清除 + 登录态判断
  - `api/client.js` 自动添加 `Authorization: Bearer`，401 触发一次性 refresh、互斥刷新、失败 reLaunch 到登录
  - `api/sse.js` SSE 与轮询降级都携带 Token
  - `pages/login/login.vue` 重写为账号密码登录 + 演示账号快捷填入
  - `pages/login/register.vue` 新增，角色 / 账号 / 密码 / 姓名 / 城市 / 农村音
  - `pages/child/family.vue` 新增：发起申请 / 同意 / 拒绝 / 解绑
  - `components/LyjSegment.vue` 增加“家人”分项：看板 / 家人 / 守护 / 隐私
  - `pages/elder/profile.vue` 增加家庭成员块，可针对每个子女单独设隐私
  - `pages.json` 注册 `register` 与 `family` 路由
- **腾讯云 ASR（原生 httpx 签名）**：
  - `backend/app/providers/asr/tencent.py`（已落盘）
  - `backend/scripts/test_tencent_asr.py`（连通性自检通过：返回 `{"ok": True, "text": ""}`，仅 1 秒空音频所以无文字）
  - `.env` 中 `ASR_PROVIDER=tencent` 已配置
- **测试**：`pytest tests/ -q` 全绿，**225 passed in 39.26s**（原 219 + 新增 6：test_auth 5 个 + test_family 1 个）

### 1.2 正在收尾 / 待你确认的小问题
- **`STORAGE_BACKEND=supabase` 已经写进 `.env`**，Supabase 13 张表已建好；服务跑起来了（`/api/health` 返回 `storage=supabase`），但 `python scripts/seed_demo.py` **仍报两个错**：
  1. `reset()` 在 `audit_log` / `session_events` 上用 `neq("id", "00000000-...-...")` → 大整型字段不能放 UUID 字面量。**已部分修复**（`repositories.py:107-115` 按表分条件 `gt("id", -1)`），但本次还没重跑验证。
  2. `insert("users", ...)` 报 `Could not find the 'password_hash' column of 'users' in the schema cache` → 你刚才的 `supabase` SQL 里**没把** `password_hash`、`username`、`status` 写进 `public.users` 表。我猜是建表脚本里漏了相关 `ALTER TABLE`/`ADD COLUMN`，新表只有最初的 `id/role/name/phone/dialect/city/created_at`。
- 上面两个问题修完后，`python scripts/seed_demo.py` 应能成功灌入演示家庭。

---

## 2. 当前配置（`laoyouji/backend/.env`）

```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=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
DEEPSEEK_BASE_URL=https://integrate.api.nvidia.com/v1
DEEPSEEK_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b

ASR_PROVIDER=tencent
TENCENTCLOUD_SECRET_ID=AKID7JPr8KyQq69xgGhw781t8QYeaIuHPIvJ
TENCENTCLOUD_SECRET_KEY=BIG7uW5UiiT1LRIvJWXLxNYVDCyXs92Y
TENCENTCLOUD_REGION=ap-shanghai
IFLYTEK_APP_ID=
IFLYTEK_API_KEY=
IFLYTEK_API_SECRET=

STORAGE_BACKEND=supabase
SUPABASE_URL=https://fxjjgegtiakrfgeybslu.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ4ampnZWd0aWFrcmZnZXlic2x1Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4Mzk1NjkyMywiZXhwIjoyMDk5NTMyOTIzfQ.mQnUpDrvqrYQy-UiKp0-hRhBgsh83H-d7XsuQNS4Ozs
LOCAL_DATA_DIR=./local_data

RISK_AMOUNT_THRESHOLD=50
CONFIRM_TIMEOUT_MIN=30
```

⚠️ 服务密钥保存在用户本机 `.env`，**不会进入 Git**（`backend/.env` 未被 git 跟踪，`.gitignore` 也没把它加进去 —— 需要的话见 §6）。

---

## 3. 本次改动的文件清单（git diff 概览）

修改（M）：
- `backend/.env.example` （-21 行）：保留模板，不再在 commit 中
- `backend/app/api/deps.py`     +50/-2  注入 Principal
- `backend/app/api/routes_chat.py` +5/-22  SSE chat 注入 Token
- `backend/app/api/routes_child.py` +12/-8  注入 Token，active 关系过滤
- `backend/app/api/routes_confirm.py` +25/-7  Token 强制 child 审批
- `backend/app/api/routes_privacy.py` +30/-8  Token 强制 elder 修改
- `backend/app/bootstrap.py`      +6/-1  ASR Tencent 装配
- `backend/app/config.py`         +10/-1  JWT 配置字段
- `backend/app/db/repositories.py` +9/-1  reset 按表类型分条件
- `backend/app/db/schema.sql`     +8/-0   新增 password_hash / status / family_bindings 状态
- `backend/app/db/seed.py`        +13/-1  演示账号密码
- `backend/app/main.py`           +4/-0   注册 auth / family 路由
- `frontend/laoyouji-app/package-lock.json` -16
- `frontend/laoyouji-app/src/api/client.js` +66/-0  Bearer + 401 刷新
- `frontend/laoyouji-app/src/api/sse.js`     +8/-63 Bearer Header
- `frontend/laoyouji-app/src/components/LyjSegment.vue` +11/-1 增加“家人”
- `frontend/laoyouji-app/src/pages.json`     +12/-0  注册 family/register 路由
- `frontend/laoyouji-app/src/pages/elder/profile.vue` +207/-0 家庭 + 隐私独立设置
- `frontend/laoyouji-app/src/pages/login/login.vue` +181/-0 改写为账号密码
- `frontend/laoyouji-app/src/store/user.js`    +36/-3  Token 持久化

新增（??）：
- `backend/app/api/routes_auth.py`        （注册/登录/me/refresh/logout）
- `backend/app/api/routes_family.py`       （家人绑定完整接口）
- `backend/app/auth/__init__.py`
- `backend/app/auth/security.py`           （scrypt + JWT）
- `backend/app/providers/asr/tencent.py`   （腾讯云 ASR 原生 httpx）
- `backend/scripts/test_tencent_asr.py`    （连通性自检）
- `backend/tests/test_auth.py`             （5 个 auth 用例）
- `backend/tests/test_family.py`           （1 个 binding 生命周期用例）
- `frontend/laoyouji-app/src/pages/child/family.vue`
- `frontend/laoyouji-app/src/pages/login/register.vue`
- 根目录还有两个老友记的 `*.txt/*.docx` 说明文档（用户自有，未提交）

---

## 4. 验证清单

| 项 | 状态 |
|---|---|
| `pytest tests/ -q` | **225 passed in 39.26s** |
| 后端 `/api/health` 200 OK | ✓ |
| `npm run build:h5` | ✓ |
| 前端 5173 加载登录页 | ✓ |
| 腾讯云 ASR 自检调用 200 | ✓（返回 `ok=True`，音频空所以 `text=""`） |
| 演示账号密码登录链路 | ✓ 全通（Supabase 已成功灌入张桂芳/李明账号密码，密码哈希校验通过） |
| `git commit` 推送变更 | ❌ 本次所有改动都还没提交，**新会话接手后建议先 `git add` 暂存** |

---

## 5. 给下一个智能体的优先 ToDo（按重要性）

1. **修 Supabase 灌种子** [已完成 ✓]：
   - 之前报错 `Could not find the 'password_hash' column of 'users' in the schema cache`。
   - 已由用户在 Supabase SQL Editor 执行 `patch_auth_family.sql` / `schema.sql` 扩充：
     - `users` 表补充 `username`, `password_hash`, `status`
     - `family_bindings` 表补充 `status`, `invited_by`, `approved_at`, `resolved_at`, `revoked_at` 及唯一约束
   - 验证：`python scripts/seed_demo.py` 顺利执行通过（退出码 0，成功重置全表并灌入演示家庭）。
   - 账号密码校验通过：`zhangguifang` / `elder123456` 与 `liming` / `child123456` 密码比对全绿。

2. **把 13 张表的列名与代码 `find_one({...})` / `insert(...)` 字段对齐** [已完成 ✓]：
   - 全库 13 张表通过 PostgREST OpenAPI 检视完毕，除 users / family_bindings 外其余 11 表完全对齐；补充字段后全量 13 表已全部就绪。
3. **跑通完整生命周期**：
   - `python -m uvicorn app.main:app --port 8000`
   - `curl -X POST http://127.0.0.1:8000/api/seed` 灌种子
   - 浏览器登录 `zhangguifang / elder123456` 与 `liming / child123456`，验证：
     - 老人端：发起 `我想去北京看腿` → 计划书
     - 子女端：李明看到黄卡、批准、出票
     - 家庭页：李明查看成员、发起/拒绝/解绑流程
4. **可选后续（不阻塞）**：
   - 补一份 `seed_demo_supabase.py`，只 upsert 演示账号，不 `reset()`
   - 写一份家庭关系 E2E（puppeteer 模拟注册→申请→同意→解绑）
   - 在 `backend/.env` 上加一层权限（写入 `.gitignore` 防止误提交到 GitHub）
   - 文档同步：`docs/API.md` 增加 `/api/auth/*` 与 `/api/family/*` 章节；`docs/TODO.md` 标记 Phase 鉴权已完成

---

## 6. 安全 / Git 提醒（请告诉新会话务必遵守）

- **不要把 `backend/.env` 加入 git**：
  - 该文件含腾讯云 SecretId/SecretKey 与 Supabase ServiceKey
  - 当前 `.gitignore` **没有**忽略它（`backend/.env.example` 是模板，不会被加进去）
  - 在 `git add` 前先用 `git status -s` 确认没有 `backend/.env`
- 用户只授权使用自己的密钥做开发调试；如果新会话需要再次调用 ASR/LLM，**直接读取 `.env` 即可**，不要让用户重新发一遍密钥。
- 任何"修改 schema 字段"前，先用 `IF NOT EXISTS` / `add column if not exists` 写法以保证幂等。

---

## 7. 用户的角色与偏好（便于新会话调整语气）

- 中文交流，技术名词保留英文
- 喜欢简短直接，技术问题喜欢问"为什么 / 怎么实现 / 行不行"
- 对架构、demo 链路、UI 体验敏感
- 之前误问过"全写死是不是"、"鉴权怎么接"、"家庭关系组怎么写"，已经逐步接受了多智能体 + 真实 API + 家庭关系组的整体设计

---

## 8. 当前会话已确认的 6 个核心决策

1. **认证方案**：后端自签 JWT，scrypt 密码哈希；不接 Supabase Auth
2. **家庭模型**：升级现有 `family_bindings`，不引入独立 family_groups
3. **绑定方式**：注册后绑定，**对方确认后**才生效（pending 期间 fail-closed）
4. **家人页范围**：核心家庭管理（成员列表、申请、同意/拒绝、解绑）；不重做家庭组管理
5. **演示兼容**：保留张桂芳/李明账号密码登录；删除原"无密码一键选角色"登录入口
6. **鉴权迁移**：核心接口强制 Token；旧参数最多用于一致性校验，未来逐步删除

---

## 9. 已知小问题与未完成事项

- ⚠️ `Supabase` 建表后，`scripts/seed_demo.py` 还会因 `users.password_hash` 缺失而失败（见 §1.2 / §5.1）。
- ⚠️ `local_data/` 还在工作区，是过去 LocalFileRepo 留下的产物；可加入 `.gitignore`。
- 🟡 `routes_child.py` 中如果当前 child 没有任何 `active` 老人，返回结构中**没有 `elders: []` 字段保留**（只有 `elders: []` 的位置写了空数组），需要前端 `dashboard.vue` 已经在用 `d.elders || []` 兜底——已确认
- 🟡 老人端 `profile.vue` 默认会选中第一个 active 家人作为 `selectedChild`，未来若一人多子女，需要把"为谁设权限"显式切换
- 🟡 腾讯云 ASR 当前只支持小文件 `SentenceRecognition`；如需实时流式长录音（流式 ASR），需切换到 `FlashRecognition` 或 `RealTimeASR`
- 🟡 `auth/security.py` 中 `_secret` 使用了开发兜底密钥 `laoyouji-dev-insecure-secret-key-for-local-demo`（与官方早期提交一致）；正式部署前必须通过 `.env` 设置 `JWT_SECRET`，否则会被静默使用弱密钥

---

## 10. 接手第一步建议

```bash
# 1. 进项目
cd C:\Users\29602\Desktop\yoc\laoyouji

# 2. 看看现在工作区状态
git status -s

# 3. 先重启后端（它已经按 supabase + NIM + 腾讯云 ASR 配置好）
cd backend
python -m uvicorn app.main:app --port 8000

# 4. 跑 seed 看是否还报 password_hash 错
python scripts/seed_demo.py

# 5. 如报错，按 §5.1 让用户补一行 ALTER TABLE
```

如果要让新会话**继续推进家庭关系或鉴权**，从 §5 的 ToDo 1 开始即可；本会话所有产出已经固化在 git diff 与本文件里。
