# TODO · 老友记实施任务清单

> 对标蓝图 todo_tasks 模式：任务带编号与依赖，完成打 [x]。每 Phase 末有验证门禁。
>
> **本文件分两段。** 上半段 Phase 0–6 是**初版原型**的实施记录，已全部完成并留档；
> 下半段 Phase R0–R5 是**本次大改**（harness 对齐重构）的任务，2026-09-02 五条门禁全绿收尾。
> 初版的门禁日期与结论保留原样，不因返工而改写 —— 那是当时确实达到过的状态。
>
> **接手先看末尾三节**：门禁记录（跑什么、绿在哪、还有哪些路没走过）· 剩下要做的事 ·
> 新窗口从这里接着做。

---

# 第一段 · 初版原型（已完成，留档）

## Phase 0 文档先行
- [x] T0.1 docs/PRD.md（含功能黑名单红线 R1-R6）
- [x] T0.2 docs/ARCHITECTURE.md（含 ADR-1~6 决策记录）
- [x] T0.3 docs/API.md（端点 + SSE 事件协议）
- [x] T0.4 docs/DATA_MODEL.md
- [x] T0.5 docs/DEMO_SCRIPT.md
- [x] T0.6 docs/QA_ANSWERS.md
- [x] T0.7 docs/TODO.md

## Phase 1 后端内核（初版）
- [x] T1.1 工程脚手架：requirements.txt / .env.example / config.py / main.py
- [x] T1.2 core/registry.py（ServiceDefinition/Provider/Registry）
- [x] T1.3 db/：client.py + schema.sql + repositories.py（SupabaseRepo + LocalFileRepo）+ seed.py
- [x] T1.4 core/events.py（SessionEventLog append-only）
- [x] T1.5 core/tool.py + core/guard.py（ToolRegistry/ToolDispatcher/GuardVerdict）
- [x] T1.6 providers/llm（deepseek.py 流式+function calling+重试 / mock.py）
- [x] T1.7 core/agent_base.py（BaseAgent + AgentLoop）+ core/sse.py
- [x] T1.8 api/routes_chat.py（POST /api/chat/stream SSE）
- 门禁 ✅ 2026-08-31：pytest 27/27 全绿；curl -N SSE 见 delta 流；MockLLM 无 key 全绿

## Phase 2 子智能体 + Mock Provider
- [x] T2.1 data/ fixtures：hospitals/trains/hotels/weather/canteen_menu/scam_corpus.json
- [x] T2.2 providers/external：train_12306 / hospital / payment / hotel / weather / amap / ride / community（各含 Mock+Real 空壳）
- [x] T2.3 shared/plain_language.py（术语词典 + LLM 改写 + 免责声明注入）
- [x] T2.4 tools/：travel_tools / health_tools / community_tools / common_tools
- [x] T2.5 agents/：travel / health / community 三个子智能体
- [x] T2.6 agents/main_agent.py（老友记：路由/澄清/规划/聚合/关键词兜底）
- [x] T2.7 safety/risk_rules.py（PaymentRiskRule/ScamContentRule/HealthDisclaimerGuard）
- 门禁 ✅ 2026-08-31：demo_smoke.py 跑通"去北京看腿"→计划书；pytest mock 确定性

## Phase 3 确认流 + 守护 + 隐私
- [x] T3.1 safety/confirmation.py（状态机 + 冻结重放 + 惰性过期 + audit）
- [x] T3.2 api/routes_confirm.py + routes_child.py
- [x] T3.3 api/routes_guardian.py（行程 + checkpoints 守护判定）
- [x] T3.4 safety/privacy.py + api/routes_privacy.py
- [x] T3.5 api/routes_health.py（用药计划 CRUD + 打卡）
- 门禁 ✅ 2026-08-31：pytest 状态机全路径（重复审批 409 实测）；curl 走通拦截→批准→出票→落库→守护告警→dashboard

## Phase 4–6 前端与演示资产（初版）
- [x] T4.1–T4.5 老人端 4 页 + api 三件套 + 组件五件
- [x] T5.1–T5.4 子女端 4 页
- [x] T6.1–T6.4 DEMO_SCRIPT / QA_ANSWERS / README / 离线兜底演练 + 彩排 ×3
- 门禁 ✅ 2026-08-31：headless Chrome E2E 双端全链路通过

---

# 第二段 · 大改（harness 对齐重构，已完成 · 门禁 ✅ 2026-09-02）

返工的理由不是"分层乱"—— 初版分层是干净的。理由是**方案书里的三个卖点在代码里是布景，不是机制**：子 Agent 共用同一份历史（假多智能体）、工具串行且 `tool_result` 伪装成 assistant 消息（因果链断裂）、进度条由 `tool_call` 启发式推动（与真实任务零绑定）、旗舰交付物由 LLM 自由拼字典（可能缺页或编造）。九条缺陷的完整清单见批准的方案。

## Phase R0 设计基线
依赖：无
- [x] TR0.1 `docs/DESIGN.md` 新建（blueprint 第 2 步产物，前端一切返工的前置）
- [x] TR0.2 token 全集落 `uni.scss`：色板 / 字阶 / 间距阶 / 命中区 / 阴影
- [x] TR0.3 导航模型成文：`switchTab` 切 tab · `navigateTo` 下钻 · `reLaunch` 仅登录换角色 · **禁止 `redirectTo`**
- [x] TR0.4 双角色视觉语言：老人端暖底 + 原生 tabBar；子女端冷色 + 顶部分段控件 + 原生导航栏

## Phase R1 内核重写（对齐 deepseek-harness）
依赖：TR0.*
- [x] TR1.1 `core/events.py` 重写：内存单调 `seq` + write-behind + 真 `derive_messages`（`tool/result` → `role:tool` 配 `tool_call_id`）+ agent 作用域过滤
- [x] TR1.2 `core/session.py` 新建：Turn / Step 分层 + `AgentDriver.run_turn()` + 三级预算
- [x] TR1.3 `core/bus.py` 新建：waterfall / serial / parallel / emit 四种派发
- [x] TR1.4 `core/tool.py` 重写：按 harness 顺序的工具流水线 + 批处理（有序 pre → 并发 execute → 有序 post）+ 挂起不再静默丢调用
- [x] TR1.5 `core/subagents.py` 新建：`spawn` / `fork` 接缝 + 结构化 `AgentReport` + `run_parallel`
- [x] TR1.6 `core/todo.py` 新建：`TodoItem{content,status}` 整表覆盖写
- [x] TR1.7 `core/guards.py` 新建：`timeout_policy`（强制）+ `repeat_tool_reminder`（建议）
- [x] TR1.8 `core/compaction.py` 新建：工具输出裁剪 + `agent/pre-step` 压缩
- [x] TR1.9 `core/context.py`：`dispatcher` 从 `@property` 改为装配期单例
- 门禁 ✅ 2026-09-02（用户在本机执行，见 Phase R5 门禁记录）：`pytest tests/ -q` 全绿，含 `test_kernel.py` / `test_subagents.py` / `test_budget.py` / `test_todo.py`

## Phase R2 Agent 层重建
依赖：TR1.*
- [x] TR2.1 `agents/base.py` 重写为薄壳，委托 `AgentDriver`
- [x] TR2.2 `agents/main_agent.py` 重写为真调度器：`todo_write` 落事件、`delegate` 接列表规格走 `run_parallel`、删掉 `show_card` 的 LLM 自由拼字典
- [x] TR2.3 `agents/plan_builder.py` 新建：确定性交付物渲染管线，三份交付物共用同一份 `AgentReport` 输入
- [x] TR2.4 就医计划书做深（五页、页序写死、可打印）；用药卡与社区卡走轻量模式
- [x] TR2.5 三个子 Agent 改为在隔离作用域运行并声明各自 report schema
- 门禁 ✅ 2026-09-02：`test_plan_builder.py` 全绿；`demo_smoke.py` 六步跑通；E2E 实测五页计划书页名齐全

## Phase R3 安全管控中间层升级
依赖：TR2.*
- [x] TR3.1 `safety/confirmation.py` 补 fail-closed：无应答者即 deny，不靠 30 分钟静默过期
- [x] TR3.2 `safety/risk_rules.py` 收紧医疗红线：`install_medical_safety` 挂 `agent/request`（order=-100）拦诊断口吻；`HealthDisclaimerGuard` 挂 `tools/post-execute`
- [x] TR3.3 `safety/privacy.py` 分级裁剪：位置 realtime/city/off、健康 full/summary/off，接在子女端出库路径上
- [x] TR3.4 修正 `allows_location` / `allows_health` 的 need 侧 fail-open（未识别的 need 现在 `return False`）
- 门禁 ✅ 2026-09-02：`test_confirmation.py` / `test_privacy.py` / `test_medical_safety.py` / `test_scam_check.py` 全绿；E2E 实测拦截 3 笔 → 同意 1 笔 → 冻结重放执行

## Phase R4 前端重建（以 `docs/DESIGN.md` 为准）
依赖：TR0.* + TR1-3 契约确定
- [x] TR4.1 `pages.json` 加真 `tabBar`（老人端 4 项）+ 子女端 4 页深色原生导航栏
- [x] TR4.2 **删除 `components/LyjTabBar.vue`** —— 全仓零引用，`grep uni.redirectTo` 与页面级 hex 字面量随之归零
- [x] TR4.3 `components/LyjSegment.vue` 新建（子女端顶部分段控件）
- [x] TR4.4 `components/LyjMic.vue` 新建：120px 麦克风从 chat.vue 抽出，`touchcancel` + `beforeUnmount` 收尾
- [x] TR4.5 `store/handoff.js` 新建：一次性话术交接（`switchTab` 不能带参数，这是绕开它的唯一干净办法）
- [x] TR4.6 `StepTimeline.vue` 契约整体替换：吃 `todo` 快照，删掉 `tool_call` 启发式
- [x] TR4.7 `PlanCard.vue` 契约整体替换：typed 五页 + `missing` 显式占位"待补" + 朗读按钮（文本从卡面合成）
- [x] TR4.8 `ConfirmCard.vue` 契约修正：正文改用 `message`（老人那句话），`summary` 降为次要位
- [x] TR4.9 老人端 4 页 + login 重写：token 化、导航模型归位、麦克风上首屏
- [x] TR4.10 子女端 4 页重写：分段控件、`DENIED` 兜底、`/api/trips` 必带 `child_id`、去掉两处冗余请求
- [x] TR4.11 `api/sse.js` 修三处：`final`/`error` 收流并调 `onDone`（原来是把 `onEvent` 派发两遍）、轮询兜底加**持久类型→线格式**反向翻译表（原来整条降级链路渲染不出任何东西）、轮询拿到 `final` 即收工（原来必须走满 2 分钟）
- [x] TR4.12 `chat.vue` 补两个未处理事件：`error`（后端写给老人的那句话原来被丢掉）、`report`（子智能体回报，界面上唯一看得见的扇出证据）
- 门禁 ✅ 2026-09-02：静态判据 12/12（`docs/DESIGN.md` §7）；实机判据已拆成两组 ——
  **6 条由 E2E 覆盖**（底栏按文字点、confirm-detail 返回、黄卡就地变绿三个数、隐私 6 档位选中 2、
  pytest、E2E 自身），**7 条仍要人手验**（老人端返回键、分段控件三页全走、devtools 量字号、
  两处故障注入、改档位后回看子女端三页、点拒绝那一支）。清单在 §7，别在这里维护第二份

## Phase R5 验收门禁
依赖：TR1-4
- [x] TR5.1 新增测试文件：`test_kernel.py`（19）/ `test_subagents.py`（17）/ `test_budget.py`（18）/ `test_todo.py`（13）/ `test_plan_builder.py`（22）/ `test_privacy.py`（34）/ `test_medical_safety.py`（27 + 5 处 parametrize）；`test_confirmation.py` 扩到 13
- [x] TR5.2 `docs/DESIGN.md` 补全（§5.1 的 `announce` 误述已纠正、§6.3 覆盖规则、§6.5 子女端分级显示契约、§7 静态/实机分栏）
- [x] TR5.3 `docs/API.md` 重写（两套事件名、`card` 无 `announce`、未绑定看板缺字段、`/api/trips` 的 owner 路径）
- [x] TR5.4 `docs/ARCHITECTURE.md` 更新（把无凭据的 harness 对齐声明换成逐条列举真正借用的机制）
- [x] TR5.5 **`pytest tests/ -q` 全绿** ✅ 2026-09-02 —— **219 passed**（12 个文件、203 个测试函数，
  其中 `test_medical_safety.py` 有 5 处 `@pytest.mark.parametrize`，展开成 21 个用例：6+6+4+3+2，
  故 `203 − 5 + 21 = 219`）。**对外一律引 219** —— 那是 pytest 自己打印的数，别人重跑对得上；
  203 是静态点算的函数数，只在解释这个差额时才提。27 是初版红线，只是下界
- [x] TR5.6 `python -m compileall -q app tests scripts` 无报错 ✅ 2026-09-02
- [x] TR5.7 `scripts/demo_smoke.py` 按新契约刷新（`todo` 事件名、`report`/`card` 打印、第 5 步反诈判定 + 自己的 flush、六步编号）—— 六步跑通 ✅ 2026-09-02
- [x] TR5.8 `frontend/e2e/elder-flow.mjs` 按新契约整文重写 —— **46 条断言全绿、EXIT=0** ✅ 2026-09-02
  （44 条无条件 + 看板有行程条目时多跑的 2 条守护断言，本次两条都跑到了）。
  旧脚本已经测不了现在的应用：点 `.tab`（假底栏已删）、断言 2 张挂起卡（真是 3 张）、
  走 `?quick=` 自动发送通道（已改成只填输入框）、拿假底栏第 3 项去子女端隐私页（子女端没有底栏）。
  每条断言都对应 `DEMO_SCRIPT.md` 里会当众念的一句话，**下面这些数字现在是被脚本钉住的**：
  - `/api/health` 的 **23 个工具 / 4 个 Agent**
  - 原生底栏**按文字**点（「聊天」「首页」），不按下标 —— 顺序以后能调，约定不能破
  - 快捷入口跳到聊天页后**输入框有话、`.tool-bubble` 为 0**（只填不发，R5 的界面侧）
  - 步骤条 4 项、两支子智能体各回一条 `.status-bubble`（扇出唯一的可见证据）
  - 挂起卡 **=== 3** 且**逐笔对账 100 / 553.5 / 658、合计 1311.5**（等到 3 张后再稳 3 秒复查，多出第 4 张也要红）
  - 计划书标题带「张桂芳」、`.section-heading` **=== 5** 且五个页标题关键词齐全、脚注含"模拟接口"与"不构成诊断"
  - 子女端 `.seg-item === 3` 且 `.uni-tabbar__item === 0`（子女端不该有底栏）、待确认 3 → 同意 1 → 剩 2、`.result-text.executed`
  - **老人端那张黄卡就地变绿**：`.s-executed === 1` / `.s-pending === 2` / 总数仍 3（是改状态，不是又推一张）
  - 隐私页 6 个档位、**选中态恰好 2 个**（界面不能同时宣称两个权限档）
- [x] TR5.9 前端 `npm run build:h5` 编译通过 ✅ 2026-09-02
- [x] TR5.10 同步 `docs/PRD.md` / `DATA_MODEL.md` / `DEMO_SCRIPT.md` / `QA_ANSWERS.md`
  - `DEMO_SCRIPT.md` 全文重写：三张挂起卡（100 / 553.5 / 658，合计 1311.5 元，原稿写"两张"）、
    计划书真标题与五页真页名（原稿有一页"费用明细"，代码里不存在）、待确认 3 条、
    日期按 `human_date` 渲染而非 `tomorrow`、子女端真实结果文案、黄卡**就地变绿**（原稿写"广播卡片"）、
    反诈那一步换成语料库对得上的原文并**删掉"DENY 拦截演示"**（那是另一条线）、
    用药计数改成按计划分别算、R4 免责声明用真实原文、23 个工具、`/api/health` 实际返回什么
  - `QA_ANSWERS.md` 全文重写：22 → 23 个工具、"27 个测试" → 12 文件 219 用例、
    删掉"约 N 千行代码"这个从未填上的占位符、定价统一到 PRD 的 199 元/年（原稿 9.9~29 元/月）、
    反诈口径拆成"判定三档"与"DENY 硬拦截"两条线、E2E 那一行如实记录 46 条断言的实跑结果
  - `API.md` 补两节：`tool_result` 上 `suspended`/`denied` 的互斥语义、`check_scam` 的三档结果形状
  - `DESIGN.md` 补 §6.7（反诈三档的显示契约，`unknown` 不许折叠）、改掉 §6.5 那个界面上不存在的"2/3"

## 门禁记录 · 2026-09-02 五条全绿

大改的代码/测试/文档任务（TR0.1 – TR5.10）到此**全部完成并且验证过了**。
五条按顺序跑，前一条不绿不跑下一条，这次一路跑到底：

```bash
cd backend
.venv/Scripts/python.exe -m compileall -q app tests scripts   # ① 能被解析  → EXIT=0
.venv/Scripts/python.exe -m pytest tests/ -q                  # ② 后端用例  → 219 passed in 28.78s
.venv/Scripts/python.exe scripts/demo_smoke.py                # ③ 六步冒烟  → 全链路走完
cd ../frontend/laoyouji-app && npm run build:h5               # ④ 前端编译  → DONE Build complete.
node ../e2e/elder-flow.mjs                                    # ⑤ 双端 E2E  → 46 条断言全绿，EXIT=0
```

第 ⑤ 条要前后端都起着；`LLM_PROVIDER=mock` + `STORAGE_BACKEND=local` 整条离线可跑。

**这一跑钉住的数字**（台上会念，改代码后必须回来重跑）：
23 个工具 · 4 个 Agent · **219 个用例**（12 个文件）· 步骤条 4 项 · 挂起卡 3 张 ·
100 / 553.5 / 658 逐笔对账、合计 **1311.5 元** · 计划书 5 页 · 待确认 3 → 同意 1 → 剩 2 ·
黄卡就地变绿（`.s-executed`=1 / `.s-pending`=2 / 总数仍 3）· 隐私 6 档位选中恰好 2。

**门禁绿 ≠ 全部验证过**，两处要说清楚：

- **Supabase 这条路一次都没跑过**。全绿是在 `STORAGE_BACKEND=local`（`LocalFileRepo`）上跑出来的，
  `backend/tests/` 里没有任何一个用例碰 `SupabaseRepo`（grep 可证）。演示走离线没问题，
  但只要打算连真库，`SupabaseRepo` 的每个方法都属于**首次执行**。
- **DeepSeek / 讯飞同理**：跑的是 `MockLLM` 和 mock ASR。真 Key 下的重试、超时、
  function-calling 返回形状都还没被真实响应打过。

---

## 剩下要做的事

### A. 只有你能做的（需要人、真机、真 Key）

- [ ] **A1 真人语音试音**：普通话 + 方言口音各一遍。麦克风权限被拒时的兜底（打字/快捷入口）也顺手看一眼
- [ ] **A2 接真实 Key 后回归一轮**：`DEEPSEEK_API_KEY` / 讯飞 / Supabase 各填上，重跑上面第 ②③⑤ 条。
      重点盯三处：`SupabaseRepo` 首次执行、真 LLM 会不会不按 `delegate` 的列表规格调用、
      真 ASR 的方言识别质量
- [ ] **A3 彩排 ×3**：照 `docs/DEMO_SCRIPT.md` 末尾的检查单走，演示机字号调大 + 关无关通知
- [ ] **A4 竞赛提交物本身**：PPT / 演示视频 / 报名材料。**这一项我不知道你们赛事的要求**
      （页数、模板、是否要录屏、截止时间），你给我要求我就能做；`docs/shots/` 里已经有三张
      现成截图：`elder-chat.png`（三张黄卡 + 五页计划书）、`child-confirm.png`（子女端同意）、
      `elder-card-green.png`（黄卡变绿）
- [ ] **A5 走一遍 `docs/DESIGN.md` §7 的"仍要人手验"7 条**：老人端返回键 · 分段控件三页全走 ·
      devtools 量字号命中区 · 两处故障注入（只发一次 `todo` 快照 / 抽掉酒店 report 看"待补"）·
      改档位后回看子女端三页 · **点拒绝那一支**。
      最后一条最值得补：三种结局（同意成了 / 家人不同意 / 同意了但没办成）里，脚本只走过第一种

### B. 明确记账的欠账（正式落地才做，**不是**竞赛阻塞）

这三条都已经写在文档里了，列在这里是防止新窗口把它们当成"漏掉的 bug"又改一遍：

- **R6 的边界**：`health_records` 目前**没有任何出库接口**，所以 `health_level` 的降级
  （`filter_medication` / `filter_health_text`）管不到它。不是豁免，是这条路还没接。
  **要给子女端加"健康档案"视图，第一件事就是在那条出库路径上补裁剪** —— 见 `DATA_MODEL.md`
- **没有登录鉴权**：`actor_id` 是前端声明的，这一层现在挡的是"越权路径存不存在"，
  不是"身份伪造不了"。已在 `DEMO_SCRIPT.md` 第 3 幕主动说明，别偷偷藏起来
- **`plan_builder._human_date` 与 `tools/common.human_date` 重复**：两者空值契约不同
  （`None` vs `""`），**有意不合并**。别当成重复代码顺手删一个

### C. 正式落地才谈的（方案层面，不写代码）

真实业务 API 全部走 Mock（12306 / 挂号 / 支付 / 地图 / 天气 / 酒店），Provider 接缝已留 Real 空壳。
披露落在三处：README、`DEMO_SCRIPT.md` 收尾台词、五页计划书最后一行脚注。**缺一处都算没披露。**

---

## 新窗口从这里接着做

换窗口后先读这一段，就够接手了：

**路径**：项目根 `C:\Users\lenovo\Desktop\develop\laoyouji`，后端 `backend/app`，测试 `backend/tests`，
前端 `frontend/laoyouji-app/src`，E2E `frontend/e2e/elder-flow.mjs`，DDL `backend/app/db/schema.sql`。
`Glob` / `Grep` 一定要给绝对路径并把 `path` 收窄到上面这几个目录 —— 否则 `.venv/` 和
`node_modules/` 会把结果冲掉。

**当前状态**：大改全部完成，五条门禁 2026-09-02 全绿。没有已知的红。

**接手前必读**：`docs/DESIGN.md` §7（前端判据）· `docs/API.md`（两套事件名互为反函数）·
本文件的 B 节（三条别重复改的欠账）。

**改代码时的两条硬约束**：

1. **改了数字就回来改稿子。** `DEMO_SCRIPT.md` / `QA_ANSWERS.md` 里每个数字都会当众念出来，
   E2E 的 46 条断言把它们钉住了 —— 数字漂了是**门禁红**，不是文档过期
2. **六条红线不许松**：R1 不做诊断 · R2 不做处方 · R3 不碰真钱 · R4 免责声明由代码注入
   （`HealthDisclaimerGuard`，不靠模型自觉）· R5 高危工具一律拦 · R6 隐私不越级

