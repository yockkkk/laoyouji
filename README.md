# 老友记 · 老年人多智能体生活助手

> 一个总智能体「老友记」+ 三个子智能体（银发导航 / 安康助手 / 邻里帮）+ 安全管控中间层。
> 语音说话就办事；花钱挂号类大事，子女点头才执行。
ss
## ⚠️ 模拟数据披露声明

> **本竞赛原型中，挂号、12306 购票、支付、酒店、地图、天气等外部业务接口均为模拟数据**
> （个人开发者无法获取官方正式接口）。所有 Mock 均为确定性实现（同输入同输出），
> 并通过 Provider 接缝隔离——每个 Provider 均含 Real 空壳，正式落地对接官方开放 API 时
> 只替换实现类，业务代码零改动。

## 场景

| 子智能体 | 能力 |
|---|---|
| 🧭 银发导航 | 查车次订票、订酒店、叫车、行程守护（偏航告警）、天气穿衣 |
| 🏥 安康助手 | 查医院挂号、报告大白话解读（**不做诊断**，强制免责声明）、用药提醒打卡、防诈骗核查 |
| 🏘️ 邻里帮 | 社区食堂订餐（软食/低糖）、保洁/陪诊派单、社区活动 |
| 🤵 老友记（总） | 语音入口、意图识别、任务规划、调度子智能体、汇总交付《就医出行计划书》 |

安全管控中间层：高危操作拦截（子女确认后重放执行）· 方言 ASR · 大白话翻译 · 隐私分级（老人掌控）。

## 一键启动（离线可演，无需任何 API Key）

```bash
# 1. 后端（Python 3.12）
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt   # Windows
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# 2. 前端（Node 20）
cd frontend/laoyouji-app
npm install
npm run dev:h5        # http://localhost:5173

# 3. 演示数据复位（任何时候）
curl -X POST http://127.0.0.1:8000/api/seed
```

默认 `LLM_PROVIDER=mock`、`STORAGE_BACKEND=local`、`ASR_PROVIDER=mock`——拔网线也能完整演示。

## 接真实服务（正式落地）

复制 `backend/.env.example` 为 `.env`，填入：

```ini
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...
ASR_PROVIDER=iflytek
IFLYTEK_APP_ID=... / IFLYTEK_API_KEY=... / IFLYTEK_API_SECRET=...
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
.venv\Scripts\python -m pytest tests/ -q            # 219 passed（12 个文件）
.venv\Scripts\python scripts/demo_smoke.py          # 无前端全链路冒烟（拦截→批准→出票→守护告警）

cd frontend/e2e
npm install && node elder-flow.mjs                  # headless Chrome 双端 E2E，46 条断言
```

> 上面这套 2026-09-02 全绿，跑的是 `LLM_PROVIDER=mock` + `STORAGE_BACKEND=local`
> 这条离线组合。`SupabaseRepo` 与真实 DeepSeek / 讯飞 Key 尚未被覆盖，见 `docs/TODO.md`。

## 工程结构

```
laoyouji/
├── docs/                 # PRD / 架构(ADR×6) / API / 数据模型 / 演示剧本 / 答辩预案
├── backend/              # FastAPI：core(harness内核) / agents / tools / safety / providers / api / db
└── frontend/
    ├── laoyouji-app/     # uni-app(Vue3) 单工程双角色（老人端+子女端，编译 H5）
    └── e2e/              # puppeteer-core 双端全链路 E2E
```

## 医疗合规边界

本系统**不提供 AI 医疗诊断**：健康域仅做辅助解读、提醒与挂号引导；
所有健康类输出由 `HealthDisclaimerGuard` 强制追加"仅供参考，不能替代医生诊断，请遵医嘱"。

## 文档索引

- [docs/PRD.md](docs/PRD.md) — 需求与功能黑名单（红线 R1-R6）
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — 架构与关键决策（ADR-1~6）
- [docs/API.md](docs/API.md) — 端点与 SSE 事件协议
- [docs/DATA_MODEL.md](docs/DATA_MODEL.md) — 13 张表说明
- [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) — 3 分钟演示剧本 + 失败兜底
- [docs/QA_ANSWERS.md](docs/QA_ANSWERS.md) — 答辩预案（五维得分点/披露/红线）
- [docs/TODO.md](docs/TODO.md) — 分阶段任务清单（含各阶段验证门禁记录）
