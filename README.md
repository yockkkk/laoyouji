# 康乐 · 老年人健康生活多智能体助手

> 一条基线（健康）+ 两翼（身体健康 / 心理健康）：一个总智能体「康乐」+ 三个子智能体
> （银发导航 / 安康助手 / 邻里帮）+ 安全管控中间层。
> 语音说话就办事。**看病挂号当场办好、同一步把完整情况知会子女（知会不审批）**；
> 家人确认闸门（`ConfirmationService`）已落地并测试 —— 当前工具集里没有会触发它的动作，
> 这条链路预留给后续支付类工具。

## ⚠️ 模拟数据披露声明

> **本竞赛原型中，挂号、叫车、支付、天气、社区活动等外部业务接口均为模拟数据**
> （个人开发者无法获取官方正式接口）；地图/路线走高德开放平台，未配 key 或断网时
> 回落内置演示库。所有 Mock 均为确定性实现（同输入同输出），
> 并通过 Provider 接缝隔离（`backend/app/providers/external/`）——正式落地对接官方
> 开放 API 时只替换实现类，业务代码零改动。

## 场景

| 子智能体 | 能力 |
|---|---|
| 🧭 银发导航 | 本市公交/地铁/步行路线（就近就医、公园散步）、叫车（只展示不代付）、出行天气 |
| 🏥 安康助手 | 健康指标记录、健康分诊（保健/观察/建议就医/紧急）、慢病登记、用药提醒打卡、报告大白话解读（**不做诊断**，强制免责声明）、挂号引导 |
| 🏘️ 邻里帮 | 社区活动（棋牌/养老院/公园健身）、孤独时的一键拨号卡、环形散步路线、家常菜谱 |
| 🤵 康乐（总） | 语音入口、意图识别、任务规划、调度子智能体、汇总交付《就医出行计划书》（四页） |

安全管控中间层：高危确认状态机（冻结参数 + 确认后重放，当前工具集无触发者，预留给支付类工具）· **就医知会子女（知会不审批）** · 方言 ASR · 大白话翻译 · 隐私分级（老人掌控）。

## 一键启动

### 方式 A：Docker 容器化一键编排（最简开箱即用）
```bash
# Windows 双击或命令行执行
docker-start.bat        # 自动构建并启动前端(5174)与后端(8000)
docker-logs.bat         # 实时查看前后端日志
docker-test.bat         # 容器内运行自动化测试 (147项全绿)
docker-stop.bat         # 平滑停止容器
```
启动后直接访问前端：`http://localhost:5174`，后端健康探针：`http://localhost:8000/api/health`。

### 方式 B：本地命令行启动（Python + Node）
```bash
# 1. 后端（Python 3.12）
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# 2. 前端（Node 20）
cd frontend/laoyouji-app
npm install
npm run dev:h5        # http://127.0.0.1:5174

# 3. 演示数据复位（任何时候）
curl -X POST http://127.0.0.1:8000/api/seed
```

默认 `LLM_PROVIDER=mock`、`STORAGE_BACKEND=local`、`ASR_PROVIDER=mock`——拔网线也能完整演示。

## 接真实服务（正式落地）

复制 `backend/.env.example` 为 `.env`，填入：

```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
ASR_PROVIDER=tencent
TENCENT_SECRET_ID=... / TENCENT_SECRET_KEY=... / TENCENT_REGION=ap-guangzhou
# 备选讯飞：ASR_PROVIDER=iflytek + IFLYTEK_APP_ID / IFLYTEK_API_KEY / IFLYTEK_API_SECRET
STORAGE_BACKEND=supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=...
```

Supabase 建表：执行 `backend/app/db/schema.sql`（所有表已开 RLS 且不建 policy = 前端直连全拒，仅后端 service key 可写）。

## 演示账号

登录页选择身份即可（自动绑定演示家庭）：

- 👵 **张桂芳**（老人，南京，西南官话）— 老人端
- 👨 **李明**（子女，北京）— 子女端

## 验证

```bash
cd backend
.venv\Scripts\python -m pytest tests/ -q            # 后端全量
.venv\Scripts\python scripts/demo_smoke.py          # 无前端全链路冒烟（分诊→挂号→知会子女→0 挂起卡）

cd frontend/e2e
npm install && node elder-flow.mjs                  # headless Chrome 双端 E2E（断言数见 docs/DEMO_SCRIPT.md）
```

> 上面这套跑的是 `LLM_PROVIDER=mock` + `STORAGE_BACKEND=local` 这条离线组合。
> **具体的通过数 / 断言数只在 `docs/DEMO_SCRIPT.md` 的检查单里维护一份** ——
> 工具数、Agent 数、计划书页数这些台上要念的数字，两份稿子对不上就是硬伤，
> 所以这里不再各写一个会过期的数字。
> `MariaDB` / `SSH` 两条存储后端尚未被测试覆盖（`backend/tests/` 里没有 `SQLRepository` / `SSHRepository` 用例）。

## 工程结构

```
laoyouji/
├── docs/                 # PRD / 架构(ADR×6) / API / 数据模型 / 演示剧本 / 答辩预案
├── backend/              # FastAPI：core(harness内核) / agents / tools / safety / providers / api / db
├── android/              # 自包含 Android 壳工程 + AlarmManager 原生提醒层（提醒闭环，见 android/README.md）
└── frontend/
    ├── laoyouji-app/     # uni-app(Vue3) 单工程双角色（老人端+子女端，编译 H5）
    └── e2e/              # puppeteer-core 双端全链路 E2E
```

## 医疗合规边界

本系统**不提供 AI 医疗诊断**：健康域仅做辅助解读、提醒与挂号引导；
所有健康类输出由 `HealthDisclaimerGuard` 强制追加免责声明（措辞见 `backend/app/safety/risk_rules.py`，两版都含"辅助解读/辅助提醒、不是诊断结论、遵医嘱"三要素）。

## 文档索引

- [docs/PRD.md](docs/PRD.md) — 需求与功能黑名单（红线 R1-R6）
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 架构与关键决策（ADR-1~6）
- [docs/API.md](docs/API.md) — 端点与 SSE 事件协议
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) — 数据模型与表清单
- [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) — 答辩演示脚本 + 失败兜底
- [docs/QA_ANSWERS.md](docs/QA_ANSWERS.md) — 答辩预案（五维得分点/披露/红线）
- [docs/TODO.md](docs/TODO.md) — 分阶段任务清单（含各阶段验证门禁记录）
