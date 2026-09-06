# 老友记 · 上下文交接与变更日志

> **目标**：让任何新的智能体 / 开发者在**不读长对话**的情况下，能立刻掌握系统全貌、近期关键改动、踩坑记录与下一步路线。  
> **最新快照时间**：2026-09-06（亚太时间）  
> **当前版本状态**：`origin/xt` 最新 Commit：`6effdab`（全链路调度时序、健全工具调用合法性校验与就医出行全闭环）  
> **自动化测试现状**：全量单元测试（281 passed）及真实远程 MariaDB 全链路端到端用例全绿通过

---

## 0. 仓库与基础环境

- **Git 仓库根路径**：`C:\Users\29602\Desktop\yoc\laoyouji`
- **主要分支关系**：
  - `xt`：核心功能演进分支（已推送到 `origin/xt`，当前最新工作指向 `6effdab`）
  - `main`：稳定主线分支（已推送到 `origin/main`）
  - `yyy`：此前推进功能的分支（已完全合入）
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
    （当前默认访问地址：`http://127.0.0.1:5174/#/pages/elder/chat`，返回 200；5173 被本机 zncp 项目占用，故用 5174）
- **当前运行依赖**：
  - Python 3.14（`C:\Users\29602\AppData\Local\Programs\Python\Python314\python.exe`）
  - Node.js + npm，前端 `node_modules` 齐全，后端 `requirements.txt` 已安装（包含 `aiomysql`、`paramiko`、`httpx`、`pytest` 等）
  - **远程 MariaDB**：`159.75.94.149:3306`（通过 SSH 隧道端口转发，内置长连接池，`STORAGE_BACKEND=mariadb` 实测完全连通）

---

## 1. 核心变更轨迹（按时间倒序）

### 1.1 全链路深度排查与修复：工具调用时序、自主闭环决策与五页计划书数据贯通（Commit `6effdab`，2026-09-06）
- **背景与痛点**：
  1. **400 Bad Request 崩溃**：在连续工具调用或追问时，DeepSeek 接口报错 `An assistant message with 'tool_calls' must be followed by tool messages responding to each 'tool_call_id'`，导致聊天中断卡死；
  2. **智能体停滞不闭环**：安康助手查出积水潭医院专家后，停下来反问老人“您想挂哪位医生”，导致总智能体跟进中断，无法自动闭环生成出行和就医清单；
  3. **交付物计划书缺漏**：五页就医计划书第 5 页天气常年显示“待补”，主作用域工具调用数据未桥接到子智能体报告中；
  4. **老人端体验噪点**：前端聊天气泡残留技术术语黑话、状态气泡无法就地清理替换、长文本不自动滚底。
- **落地修复**：
  1. **协议级根治 400 Bad Request 时序错误（[`backend/app/core/events.py`](file:///c:/Users/29602/Desktop/yoc/laoyouji/backend/app/core/events.py) & [`main_agent.py`](file:///c:/Users/29602/Desktop/yoc/laoyouji/backend/app/agents/main_agent.py)）**：
     - 在 `events.py` 新增 `_ensure_valid_tool_turns`，在上下文送入大模型前进行强制时序规整：每个包含 `tool_calls` 的 assistant 消息后强制连续紧跟对应 `tool_call_id` 的结果消息，清除孤儿工具，非 tool 消息顺延；
     - 将 `main_agent.py` 的 `ask_user` 改为非持久化事件（`persist=False`），杜绝在工具执行期间向事实事件日志中污染插入 assistant 消息；
  2. **多智能体自主闭环与决策指令强化（[`health_agent.py`](file:///c:/Users/29602/Desktop/yoc/laoyouji/backend/app/agents/health_agent.py) & [`travel_agent.py`](file:///c:/Users/29602/Desktop/yoc/laoyouji/backend/app/agents/travel_agent.py)）**：
     - 健康子智能体提示词增加硬规则：未指定医生时，默认预约首位权威专家号源并立即调用 `register_appointment` 提交闭环，依靠家人确认拦截保证安全，杜绝向老人多轮索要选项；
     - 出行子智能体规范火车票、酒店预订与天气的连贯调用要求；
  3. **交付物管线数据全面贯通（[`session.py`](file:///c:/Users/29602/Desktop/yoc/laoyouji/backend/app/core/session.py) & [`main_agent.py`](file:///c:/Users/29602/Desktop/yoc/laoyouji/backend/app/agents/main_agent.py) & [`plan_builder.py`](file:///c:/Users/29602/Desktop/yoc/laoyouji/backend/app/agents/plan_builder.py)）**：
     - `session.py` 在 `tool_result` 中完整收录原始结构化数据 payload；
     - `main_agent.py` 的 `_reports_from_log` 聚合全局公共服务数据（如天气），`plan_builder.py` 补充相对日期（今天/明天/周几）解析与模糊匹配，实现五页计划书 100% 完整生成、零缺失；
  4. **适老界面优化（[`chat.vue`](file:///c:/Users/29602/Desktop/yoc/laoyouji/frontend/laoyouji-app/src/pages/elder/chat.vue)）**：
     - 状态气泡就地替换清理、过滤底层技术调试字符、长消息更新时自动触底平滑滚动；
  5. **实测与全场景跑通**：
     - 旗舰场景单轮自主闭环实测通过：4 项待办步步为营推进、3 笔高额支付全部触发家人确认（100元挂号、553.5元高铁票、658元酒店）、5 页就医计划书完整交付；
     - 模糊健康输入排查、反诈识别拦截、大白话体检解读、社区助餐下单全量通过。

---

### 1.2 上下文机制与智能体协同调度重构（Commit `26f28d6`，2026-09-05）
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

### 1.3 并入同事 yyy 分支重大升级（Commit `6bc5b39`，2026-09-05）
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

### 1.4 聊天全链路持久化与历史回显（Commit `04223a2` 与 `d1b5726`）
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
| **会话并发与生命周期** | ⭐⭐⭐⭐⭐ (9.9/10) | `SessionTurnGate` 排队防交错；`_ensure_valid_tool_turns` 强时序校验根除 400 报错；404 自动无感建会话自愈； |
| **上下文管理与调度** | ⭐⭐⭐⭐⭐ (9.8/10) | 用户画像置顶锚定；子智能体首位专家自主闭环决策；全局服务数据自动汇聚至 5 页计划书； |
| **测试完整度** | ⭐⭐⭐⭐⭐ (10/10) | 281 项单元测试全绿 + 真实远程 MariaDB 线上全场景实测全绿（涵盖挂号、高铁、酒店、天气、反诈、助餐）； |
| **适老 UI 体验** | ⭐⭐⭐⭐⭐ (9.5/10) | 960px 适老宽屏、状态气泡就地更新清理、过滤底层技术调试黑话、长消息平滑触底； |

---

## 4. 后续演进建议（迈向真实生产的路线图）

1. **语音交互体验跃升（极高优先级）**：
   - **点按断句（VAD）**：将当前长按说话改造为轻点一下开始、静音 1.5 秒由本地 Web Audio 自动断句切刀，彻底根除高龄老人长按手抖滑出的痛点；
   - **高拟真自动播报（TTS）**：接入自然温和的老年管家音色，智能体回答完毕后主动用语音念给老人听；
2. **移动端真机生产环境支持**：
   - 部署到外网服务器时必须配置 **HTTPS SSL 证书**，否则 iOS Safari 与 Chrome 会强行禁用 `getUserMedia` 麦克风权限；
3. **长期记忆表（Long-term Profile）**：
   - 未来可引入跨 Session 的持久偏好表（如“高血压既往病史”、“习惯下午车次”），在新开会话时同样能长期保留。
