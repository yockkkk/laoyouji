# 老友记 · 上下文交接与变更日志

> **目标**：让任何新的智能体 / 开发者在**不读长对话**的情况下，能立刻掌握系统全貌、近期关键改动、踩坑记录与下一步路线。  
> **最新快照时间**：2026-09-05（亚太时间）  
> **当前版本状态**：`origin/main` 与 `origin/xt` 已双向对齐，最新 Commit：`26f28d6`  
> **自动化测试现状**：`pytest tests/ -q` 全量通过（**281 passed in 39.73s**）

---

## 0. 仓库与基础环境

- **Git 仓库根路径**：`C:\Users\29602\Desktop\yoc\laoyouji`
- **主要分支关系**：
  - `main`：稳定主线分支（已推送到 `origin/main`，指向 `26f28d6`）
  - `xt`：日常功能演进分支（已推送到 `origin/xt`，指向 `26f28d6`，与 main 保持同步）
  - `yyy`：同事此前推进功能的分支（已完全合入 `main` 与 `xt`）
- **本机服务启动入口**：
  - **后端 FastAPI**：`laoyouji/backend`
    ```bash
    python -m uvicorn app.main:app --port 8000 --reload
    ```
    （当前默认健康地址：`http://127.0.0.1:8000/api/health`，返回 200）
  - **前端 Uni-app H5**：`laoyouji/frontend/laoyouji-app`
    ```bash
    npm run dev:h5
    ```
    （当前默认访问地址：`http://localhost:5173/#/pages/elder/chat`，返回 200）
- **当前运行依赖**：
  - Python 3.14（`C:\Users\29602\AppData\Local\Programs\Python\Python314\python.exe`）
  - Node.js + npm，前端 `node_modules` 齐全，后端 `requirements.txt` 已安装（包含 `aiomysql`、`paramiko`、`httpx`、`pytest` 等）

---

## 1. 核心变更轨迹（按时间倒序）

### 1.1 上下文机制与智能体协同调度重构（Commit `26f28d6`，2026-09-05）
- **背景与痛点**：在多轮对话中，老人明明说了“我现在就在南京”，智能体连续口头说“我这就帮您张罗”，但底层**一次工具都不调**；甚至在后续追问“您今天从哪儿出发去南京”，导致极度反人类的“失忆与假答应”体验。
- **落地修复**：
  1. **全局用户档案置顶锚定（[`backend/app/core/session.py`](file:///c:/Users/29602/Desktop/yoc/laoyouji/backend/app/core/session.py)）**：
     - 在 `AgentDriver._request` 中，动态将老人的基本盘（姓名、常住城市：南京、方言）作为不可变事实置顶注入 `system_prompt`，主智能体与并发子智能体全部继承，杜绝“不知老人在哪、反问老人在哪”；
  2. **行动铁律与场景解耦（[`backend/app/agents/main_agent.py`](file:///c:/Users/29602/Desktop/yoc/laoyouji/backend/app/agents/main_agent.py)）**：
     - **拒绝口头空话**：明确意图后，当前轮次必须立即调用 `delegate` 派活或 `todo_write` 启动清单，禁止纯文本假答应；
     - **解耦“本地就医 vs 跨城就医”**：本地就医只派 health 查本地医院和专家号源，坚决不派 travel 查机票车票和外地酒店，严禁向本地老人索要“出发城市”；
  3. **轮次安全滑动截断与防孤儿 Tool（[`backend/app/core/events.py`](file:///c:/Users/29602/Desktop/yoc/laoyouji/backend/app/core/events.py)）**：
     - 引入 `_slice_turn_safe`，截断时严格对齐到完整的 `role: user` 物理轮次边界，并在此之后二次过滤未配对的 tool，彻底杜绝以 `role: tool` 开头导致的 DeepSeek 400 Bad Request 报错；
  4. **测试与实测**：
     - 新增 `tests/test_context_optimization.py`（3个单元测试全绿）；
     - 真实端到端测试（会话 `7ab49d4b`）：老人说“我现在就在南京，立刻帮我规划”，智能体直接发出 `delegate` 并在南京鼓楼医院骨科（邱勇主任医师）锁定号源，全程 0 废话、0 弱智反问。

---

### 1.2 并入同事 yyy 分支重大升级（Commit `6bc5b39`，2026-09-05）
- **数据库架构扩展**：
  - 新增 MariaDB 单表 JSON 模式（`backend/app/db/sql_repo.py`），通过 `laoyouji_records` 承载全表，免反复 DDL 迁移；
  - 内置 SSH 隧道（`backend/app/db/ssh_tunnel.py`），无需将服务器 3306 暴露到公网；
  - `build_repo` 严格禁止静默降级，参数错误直接 fail-fast 抛错；
- **全流程闭环 Mock 数据**：
  - 补齐南京与北京的 243 行真实科室、号源、双向车次、打车接驳数据；
  - 增加 `test_mock_data_closure.py` 护栏测试，保证子智能体不会查到空数据中断；
- **健康打卡与用药真删除**：
  - 打卡使用 `UUIDv5(plan_id, date, slot)` 复合主键，配合进程内异步锁彻底实现打卡幂等防重；
  - 用药删除接入 `DELETE /api/medications/{id}` 软删除（`active: false, deleted_at: ...`）；
- **音频与返回胶囊**：
  - H5 录音绕过 `webm/opus`，用 `AudioContext` 采原始 PCM 降采样封装 16k WAV，直通腾讯云 ASR；
  - 前端封装 `LyjBack.vue` 全局适老返回导航控件；
  - `messages.js` 统一大白话失败兜底文案，绝不说“没听清您再说一遍”以防老人以为是口音问题。

---

### 1.3 聊天全链路持久化与历史回显（Commit `04223a2` 与 `d1b5726`）
- **核心修复**：
  - 修复了 Supabase `session_events.id` 自增整型主键插入 UUID 被 PostgreSQL 拒绝且静默丢弃的重大 Bug，仓储层适配自增序列；
- **API 与前端**：
  - 增加 `GET /api/chat/sessions`、`GET /api/chat/history`、`POST /api/chat/sessions/new`；
  - 前端 `chat.vue` 支持历史消息反序列化回显与右上角 `[＋ 新对话]` 胶囊按钮。

---

## 2. 核心配置文件说明（`backend/.env`）

本文件的真实凭据受 `.gitignore` 保护，**严禁提交到公共 GitHub**：

```ini
# ===== 大模型（已接入 DeepSeek 官方，实测 deepseek-v4-flash 驱动）=====
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=<真实 sk-f7c3b8... 见本机 backend/.env>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# ===== 语音识别（方言识别支持）=====
ASR_PROVIDER=tencent
TENCENT_SECRET_ID=AKID7JPr8KyQq69xgGhw781t8QYeaIuHPIvJ
TENCENT_SECRET_KEY=BIG7uW5UiiT1LRIvJWXLxNYVDCyXs92Y
TENCENT_REGION=ap-shanghai

# ===== 存储 =====
STORAGE_BACKEND=supabase
SUPABASE_URL=https://fxjjgegtiakrfgeybslu.supabase.co
SUPABASE_SERVICE_KEY=<真实 key 见本机 backend/.env>
LOCAL_DATA_DIR=./local_data

# ===== 安全风控 =====
RISK_AMOUNT_THRESHOLD=50          # 挂号/买票超过50元强制子女审批卡
CONFIRM_TIMEOUT_MIN=30
```

---

## 3. 当前系统架构 Review 与评价

| 架构维度 | 现状与评级 | 说明 |
|---|:---:|---|
| **会话并发与生命周期** | ⭐⭐⭐⭐⭐ (9.8/10) | `SessionTurnGate` 排队防交错；`_detach` 强引用保活落库；404 自动无感建会话自愈； |
| **上下文管理与调度** | ⭐⭐⭐⭐⭐ (9.5/10) | 用户画像置顶锚定；`_slice_turn_safe` 轮次边界截断防孤儿 tool；行动优先铁律避免假答应； |
| **测试完整度** | ⭐⭐⭐⭐⭐ (10/10) | 281 项自动化测试全绿（涵盖鉴权、内核、生命周期、用药、闭环 Mock 数据、上下文截断）； |
| **适老 UI 体验** | ⭐⭐⭐⭐☆ (9.0/10) | 960px 适老宽屏、贴底输入栏、无技术黑话兜底文案、防手抖连按打卡； |

---

## 4. 后续演进建议（迈向真实生产的路线图）

1. **语音交互体验跃升（极高优先级）**：
   - **点按断句（VAD）**：将当前长按说话改造为轻点一下开始、静音 1.5 秒由本地 Web Audio 自动断句切刀，彻底根除高龄老人长按手抖滑出的痛点；
   - **高拟真自动播报（TTS）**：接入自然温和的老年管家音色，智能体回答完毕后主动用语音念给老人听；
2. **移动端真机生产环境支持**：
   - 部署到外网服务器时必须配置 **HTTPS SSL 证书**，否则 iOS Safari 与 Chrome 会强行禁用 `getUserMedia` 麦克风权限；
3. **长期记忆表（Long-term Profile）**：
   - 未来可引入跨 Session 的持久偏好表（如“高血压既往病史”、“习惯下午车次”），在新开会话时同样能长期保留。
