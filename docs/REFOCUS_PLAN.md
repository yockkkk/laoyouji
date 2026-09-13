# 「康乐」重构执行方案

> 从"什么都做一点的养老助手（老友记）"收敛为"**以健康为核心的父母陪伴助手（康乐）**"。
> 本文是重构的**总纲 + 分阶段执行清单**，落到具体的表 / 工具 / 确认逻辑 / 页面 / 文件。
>
> 状态：草案 v2 · **平台已定：原生 Android 壳(仓库 `android/` 目录 + `build_apk.sh`，全屏 WebView 加载云端 H5 + 原生 AlarmManager 提醒层)+ 保留 H5 双输出兜底** · 单人预计 13–20 天
>
> **可行性审计见 `docs/FEASIBILITY.md`(路径级、逐功能评级、三机制拆解)——本文是"做什么",那份是"到底能不能做、做不动退到哪"。两份必须一起读。**

---

## 0.5 平台决策(2026-09-11 已定)

**走原生 Android（`android/` 壳：WebView 装 H5 + 原生提醒层）,把"提醒/守护/问候"尽量做真;保留 H5 作兜底。**

> **⚠️ 修正(2026-09-13):打包**从来不是** uni-app 原生编译 / HBuilderX 云打包 / DCloud appid / uni-push 那条路 —— 它从未走通。实际交付物是仓库内 **`android/` 目录 + `build_apk.sh`**(构建与改动说明见 `android/README.md`，跨文件接口契约见 `android/CONTRACT.md`):一台自包含的 **WebView 壳**工程(`MainActivity.java` 全屏加载云端 H5,**不内嵌 assets**),在服务器上用 aapt+javac+d8+zipalign+apksigner 打包,产出 `com.kangle.app` 已签名 APK(**本地已真编通过**)。**好处**:免 HBuilderX/appid/uni-push,打包链路已跑通,且壳透传权限使**前台语音+定位变真**。**代价**:WebView 壳 app 关闭后**无后台/定时/推送**(服务器一挂即白屏,有离线兜底页可重新加载)。故 C 类真实路径:告警子女=**服务器 SMTP 邮件**(已落地真送达)+ app 内红点;**定时提醒已用原生 `AlarmManager` 补上**(`AlarmScheduler`/`ReminderReceiver`/`NotificationHelper`/`BootReceiver` + H5 侧桥 `src/utils/native.js`);**P4 的后台定位仍未做**;**推送/资质整个不碰**。

关键认知:**"全真"不是一件事,是三种机制**(详见 FEASIBILITY §0):

- **① 时间驱动**(用药提醒、晨间问候)= **原生到点闹钟 + 系统通知**,离线·免服务器·到点弹 —— **已落地(🟢)**:`android/` 的 `AlarmScheduler` 排 `Reminder` → `ReminderReceiver` → `NotificationHelper`,`BootReceiver` 负责开机重建;H5 侧由 `src/utils/native.js` 合成并下发。敌人只剩 Android 保活。
- **② 事件驱动·跨设备**(指标异常告警子女)= **SMTP 邮件(已落地、真送达)** + app 内红点(现状保留);**uni-push 在线推送未实现**(它依赖那条从未走通的 uni-app 原生打包路);离线厂商通道需企业资质,**默认不做**(🟡)。
- **③ 位置驱动**(途中守护)= 前台服务 + 后台定位,**能做但 flaky(🟡)**,**保留"模拟轨迹回放"作主兜底**;**`startLocationUpdateBackground` 真机后台定位仍未做(P4)**。

**默认假设已确认(2026-09-11)**:① 只做 Android;② 无企业资质 → ②离线厂商通道不做,**在线推送(uni-push)也未实现,只落 SMTP 邮件兜底**;③ 演示机=**小米(MIUI)**,保活引导按 MIUI 定制(自启动 + 省电白名单 + 前台常驻服务;MIUI 杀后台最凶)。

---

## 0. 一句话定位

**康乐 = 康（身体健康）+ 乐（心理快乐）。** 一条基线（健康），两片翅膀：

- **左翼 · 身体健康**：指标监测 → 慢病档案 → **智能分诊（日常保健优先）** → 必要时就近就医（本地公交/地铁路线 + **完整知会子女，但不需子女审批**）
- **右翼 · 心理健康**：主动问候陪伴 → 情绪识别 → **一键联系（子女 / 棋友）** → 线下社交·运动·饮食建议（下棋 / 撸猫 / 公园健身 / 散步 / 食谱）

产品名由「老友记」改为「**康乐**」：名字本身编码了两层结构，评委一听即懂。

---

## 1. 现状家底（重构的起点）

当前项目**底子很好**，转型主要是"收敛、重定向、加深"，不是推倒重来。

**后端** `backend/`：FastAPI + 多 agent 内核（事件溯源会话日志、工具调度流水线、子 agent 作用域隔离、高危确认状态机）。
- LLM：**DeepSeek**（`backend/app/providers/llm/deepseek.py`，`deepseek-chat`），默认可切 `MockLLMProvider` 离线跑。
- ASR：腾讯云一句话识别（`backend/app/providers/asr/tencent.py`），支持方言。
- 地图：**AMap 真实 API**（`backend/app/providers/external/amap_service.py`，地理编码 + 驾车路线 + 偏航检测），前端 Leaflet + 高德栅格瓦片渲染（`frontend/laoyouji-app/src/utils/amap.js`）。
- 存储：可插拔，默认**本地 JSON**（`backend/local_data/*.json`）；Supabase 已标注"弃用"，仅作数据存储；另有 MariaDB 单表 JSON 模式。
- Agent：`main`（编排）+ `travel` + `health` + `community` 四个（`backend/app/agents/`）。
- 工具：重构前 23 个（收敛后实测 22 个，见 §9.1），分布在 `backend/app/tools/{common,travel,health,community}_tools.py` + `main_agent.py`。

**前端** `frontend/laoyouji-app/`：uni-app（Vue 3）编译 H5。长辈端 `src/pages/elder/*`（大字/语音优先，原生 tabBar）、子女端 `src/pages/child/*`（深色守护面板），登录按 `role` 分流（`src/pages/login/login.vue`）。

**数据表**（**16 张**，`backend/app/db/schema.sql`；与 `backend/app/db/repositories.py` 的 `TABLES` 一致）：`users`、`family_bindings`、`sessions`、`session_events`、`confirmation_tasks`、`trips`、`trip_checkpoints`、`notifications`、`medication_plans`、`medication_logs`、`health_records`、**`health_metrics`**、**`health_conditions`**、`orders`、`privacy_permissions`、`audit_log`。

### ⚠️ 必须先修的硬伤：凭据泄露
- `HANDOFF.md`（仓库根，约 118–138 行）含**明文真实凭据**：`TENCENT_SECRET_ID/KEY`、真实 `SUPABASE_URL`，并引用真实 `DEEPSEEK_API_KEY` / `SUPABASE_SERVICE_KEY`。
- AMap key 硬编码为默认值：`backend/app/config.py`、`frontend/laoyouji-app/src/utils/amap.js`。
- **决策(2026-09-11)**：私有仓库 → **git 历史暂不清、密钥暂不轮换**（force-push 推迟）；工作树已脱敏。零风险的仍顺手做：AMap key 从代码默认值收敛进 `.env`。**⚠️ Tripwire：一旦公开仓库 / 交给评委 / 开源，"轮换密钥 + 清历史（`git filter-repo`/BFG）"立即变必做 —— 现有键仍是活的，公开即泄。**

---

## 2. 目标架构：Agent 映射

现有四 agent 几乎天然对齐新定位，改动集中在工具与话术：

| Agent | 现在 | 重构后 | 改动量 |
|---|---|---|---|
| `main` | 编排 | 不变（编排 + 交付物模板换成"健康日报/就医建议/陪伴卡"） | 小 |
| `health` | 就医/报告/用药/反诈/饮食 | **身体健康线主力**：指标 + 慢病 + 分诊 + 就医 + 用药 + 报告 + 饮食 | 中（加深） |
| `community` | 社区食堂/家政/活动 | **改造为心理·社交线**：一键联系 + 线下活动 + 饮食食谱 | 中（重定向） |
| `travel` | 高铁/机票/酒店/路线 | **收缩为本地出行**：就医/散步的公交·地铁·步行路线 | 大（砍多留一） |

---

## 3. 工具改造清单（23 → 收敛后）

★ = 核心卖点

### 留 & 改

| 工具 | 域 | 动作 | 说明 | 文件 |
|---|---|---|---|---|
| `plain_say` | common | 留 ★ | 医学术语→大白话 | `common_tools.py` |
| `get_user_profile` | common | 留 | 增加慢病/紧急联系人字段 | `common_tools.py` |
| `get_weather` | common | 留 | 出行前天气·穿衣 | `common_tools.py` |
| `interpret_report` | health | 留 ★ | 体检报告解读 | `health_tools.py` |
| `add_medication` | health | 留 ★ | 用药提醒（已有 logs 依从打卡） | `health_tools.py` |
| `search_hospital` | health | 改 | 改**就近排序**，弱化专家号 | `health_tools.py` |
| `register_appointment` | health | 改 ★ | **移出高危、不再子女审批**，改直接执行 + 触发完整知会 | `health_tools.py` + `risk_rules.py` |
| `diet_advice` | health | 改 | 扩成"饮食规划 + 食谱指导" | `health_tools.py` |
| `plan_route` | travel | 改 ★ | 高铁/飞机 → **公交/地铁/步行本地模式**（接 AMap `/v5/direction/transit/integrated`） | `travel_tools.py` + `amap_service.py` |
| `push_activities` | community | 改 ★ | 重定向为**线下社交·运动**：棋牌室/养老院/撸猫/公园健身/散步 | `community_tools.py` |
| `hail_ride` | travel | 留（已定） | 打车去医院，去支付/审批，仅信息展示 + 假数据演示 | `travel_tools.py` |
| `todo_write`/`delegate`/`compose_deliverable`/`ask_user` | main | 留 | 内核保留，只改交付物模板 | `main_agent.py` |

### 砍

| 工具 | 域 | 原因 |
|---|---|---|
| `check_scam` | health | 反诈偏离健康基线；降级为后台安全规则（`ScamContentRule` 仍护 agent），不作卖点 |
| `search_train` / `book_ticket` | travel | 城际铁路，与"本地就医"矛盾 |
| `search_hotel` / `book_hotel` | travel | 住宿 |
| `canteen_order` / `order_service` / `query_order_status` | community | 付费社区服务；`orders` 表停用 |

### 新建

| 新工具 | 域 | 作用 | report_key |
|---|---|---|---|
| `log_vital` ★ | 身体 | 录入血压/血糖/心率/体重/血氧/体温（支持语音录入，复用 ASR） | `vital_logged` |
| `get_health_summary` ★ | 身体 | 近期指标 + 趋势 + 异常标记 | `health_summary` |
| `add_condition` ★ | 身体 | 慢病档案（高血压/糖尿病…） | `condition` |
| `assess_health` ★ | 身体 | **分诊大脑**：指标+慢病+症状 → 保健/观察/建议就医/紧急，默认偏向"日常保健优先" | `assessment` |
| `notify_children` ★ | 身体 | 把完整情况（症状·指标·分诊·推荐医院·预约·路线）推给子女，过隐私分级 | `family_notice` |
| `suggest_call` ★ | 心理 | 生成"打给孩子/棋友"卡片，预填号码，点一下 `uni.makePhoneCall` | `call_action` |
| `suggest_walk` | 心理 | 下棋/撸猫/公园健身/散步路线（落地名，由 `push_activities` 改造承担） | `activity` |
| `get_recipe` | 饮食 | 分步食谱指导自制 | `recipe` |
| `mood_checkin`（可选） | 心理 | 记录情绪，触发 `suggest_call` | `mood` |

> 每个工具的 `report_key` 需在 `backend/app/agents/plan_builder.py` 的交付物渲染器登记；agent 的 `tool_names` allow-list 需同步更新；注册在 `backend/app/bootstrap.py` 的 `register_*_tools`。

---

## 4. 机制级改动：审批 → 知会

**你的明确要求**：本地就医不需子女同意，但要完整知会子女。

- 改造前 `HIGH_RISK_TOOLS = {book_ticket, book_hotel, register_appointment, pay, order_service}`（`backend/app/safety/risk_rules.py`），命中即**挂起等子女审批**。
- 付费类工具全砍 → 高危集合基本清空。
- `register_appointment` **移出高危集合** → 老人自己确认即可就医，不阻塞。
- 改为触发 `notify_children` → 写 `type=health_alert` 完整通知（复用 `notifications` 表 + `backend/app/shared/plan_helpers.py` 幂等去重 + `backend/app/safety/privacy.py` 的 `health_level` 分级）。
- **送达通道(App 路线,②事件驱动跨设备,详见 FEASIBILITY §2.1)**:原设计三层,**目前只有邮件真的落地**——
  1. **SMTP 邮件(已落地、真送达)**:`providers/external/mailer.py`（`MockMailer`/`SmtpMailer` + `build_mailer`），`bootstrap.py` 注册为 `mail` provider，`health_tools.py::_deliver_by_email` 已接进挂号知会主链；正文含指标/分诊/医院/预约/路线,按 `health_level` 脱敏。
  2. **app 内红点 + 轮询**:子女打开 app 即见(现状保留)。
  3. **uni-push 在线推送**:**未实现** —— 它依赖那条从未走通的 uni-app 原生打包路，当前无落点。
  - 想让"子女 app 被杀也秒到"→ 厂商离线通道,**需企业资质,默认不做**,标注"已设计未上线"。
- **高危确认基础设施保留**（状态机是好工程、也是加分项），只是医疗流程不再触发它；日后若接入真实支付可复用。

> 这一步同时命中「不需家人同意」+「完整情况及时通知」，而且是减法，更贴合"小而精"。

---

## 5. 数据模型改动

基于现有 **16 张**表（`health_metrics` / `health_conditions` 已落地），改三处：`backend/app/db/schema.sql` + `backend/local_data/*.json` + `backend/app/db/repositories.py`。

**已建（本节记录其形状）**
- `health_metrics`：`id, elder_id, metric_type, value, systolic, diastolic, unit, measured_at, context, source, level, note, created_at` —— 身体线核心（血压靠 `systolic`/`diastolic` 存两列，分诊档位存 `level`；见 `backend/app/db/schema.sql`）
- `health_conditions`：`id, elder_id, name, diagnosed_at, severity, active, notes, created_at` —— 慢病档案

**复用（扩字段）**
- `medication_plans` / `medication_logs`：用药提醒 + 依从打卡（已具备）
- `health_records`：`record_type` 增加 `vital` / `condition`
- `notifications`：`type` 增加 `health_alert` / `greeting`
- `trips` / `trip_checkpoints`：**重定向为"就医/散步途中守护"**
- `privacy_permissions`：`health_level`（full/summary/off）直接用于知会分级

**停用**
- `orders`（付费社区服务砍掉）

**静态数据**（`backend/app/data/`）
- 新增 `recipes.json`（食谱）、`activities.json`（棋牌室/养老院/公园等）
- 保留 `hospitals.json`、`routes.json`、`weather.json`
- 停用 `trains.json`、`hotels.json`、`rides.json`（除非留 `hail_ride`）、`canteen_menu.json`、`scam_corpus.json`

---

## 6. 假数据可信度方案（演示重点）

**指标全用合成数据，核心是"可信"—— 不是随机数，而是有临床逻辑 + 有剧本 + 可复现。**

### 6.1 人物档案驱动
Demo 老人 **张桂芳（72 岁，南京）**，档案自洽、贯穿全线：
- 慢病：原发性高血压（5 年）、2 型糖尿病（轻度，3 年）
- 用药：苯磺酸氨氯地平（降压）、二甲双胍（降糖）
- 子女：李明（儿子），已绑定，手机号入库（供一键拨号 + 知会）
- 所有指标、分诊、通知都围绕这一档案，**不自相矛盾**。

### 6.2 生理合理的确定性生成
复用现有 mock 哲学（md5 种子，`seed = f"{elder_id}|{metric}|{date}"`），但让数值符合真实规律：
- **血压**：有昼夜节律（晨峰偏高）、收缩压/舒张压相关（不出现 180/60 这种不合理组合）、符合高血压人群区间（平日 135–150 / 85–95）
- **血糖**：分餐前/餐后（`context` 字段），餐后高于餐前，轻度糖尿病区间（空腹 6–7.5，餐后 8–11 mmol/L）
- **心率/体重**：合理范围，体重缓慢波动
- 确定性伪随机 → 每次演示数据**完全一致、可复现**，不翻车

### 6.3 剧本化趋势（可信的关键）
数据要讲一个故事：
- 过去 30 天：血压平稳（依从用药）
- 最近 5 天：血压逐步走高（埋"最近漏服/天气转冷"诱因）
- 第 30 天早晨：测出 **178/105** → 自然触发 `assess_health` 的"建议就医"档 → 演示就医闭环
- 趋势图上一眼看到"平稳 → 抬头"曲线，评委立刻理解系统为何建议就医

### 6.4 时间真实感
- 测量时间落在合理时段（晨起/睡前），非整点均匀分布
- 故意留 1–2 天缺测 → 系统提示"您已 2 天没测血压"（更真实）
- 时间戳显示"今早 7:12""2 小时前"，绝不出现未来时间

### 6.5 交叉一致
指标 ↔ 慢病 ↔ 用药 ↔ 分诊结论 ↔ 子女通知 全部引用同一组事实。子女收到的通知（"血压 178/105、连续 5 天走高、建议 XX 医院心内科、已预约、路线附上"）与老人端趋势图、分诊卡片完全对得上。

### 6.6 视觉可信
- 趋势图带**参考区间底纹**（正常/警戒/高危三色带，走 `dataviz` 规范）
- 每条记录带来源标签（手动/语音）、相对时间、单位与正常范围（mmHg、mmol/L）

### 6.7 一键复现的种子
扩展 `backend/scripts/seed_demo.py`，加 `seed_kangle_persona()`：一条命令重置张桂芳的完整 30 天档案 + 慢病 + 用药 + 家庭绑定。
- 支持 `--scenario=hypertension_spike` 直接把数据推到触发点，演示就医闭环前一键就位。
- 每次演示前跑一次，状态一致。

### 6.8 诚实边界
README/演示注明"数据为合成演示数据"（现有 README 已有 mock 披露传统）—— 反而体现工程严谨，避免评委质疑造假。

---

## 7. 心理健康层落地

1. **一键拨号**（重点）：**不直接跳转**。聊天中识别到孤独/情绪信号 → 主 agent 吐一张 `CallCard` → 老人**点一下**才 `uni.makePhoneCall` 拨号，号码从 `family_bindings`/联系人预填（子女、棋友均可）。**App 里比 H5 更稳**(直接拉起系统拨号盘)。
2. **主动问候（App 路线,①时间驱动）**：**App 本地到点提醒（原生 `AlarmManager` + 系统通知，见 `android/` + `src/utils/native.js`）**每早 8 点弹问候卡 —— **离线、真到点、免服务器**(不再是"mock 定时"占位)。想触达**完全没开 app 的老人**仍只有**真 SMS**（腾讯云/阿里云，新增 `SmsProvider` 插件位，注册在 `bootstrap.py`）——需签名报备(企业主体、1–3 天、计费)，写入 `docs/SMS_DESIGN.md` 作生产方案,即"方案要有、不强上线"。**敌人=保活**(见 FEASIBILITY §1#6)：前台服务 + 白名单引导页兜底。
3. **线下建议**：`suggest_walk` 出棋牌室/养老院活动/撸猫店/公园健身（原设想名 `suggest_activity`，落地为 `suggest_walk`，见 `community_tools.py`）；散步路线复用 `plan_route` 步行模式（预置环线,FEASIBILITY §2.2）。
4. **饮食**：`get_recipe` 分步食谱（可录制）+ `diet_advice` 饮食规划；前端 `RecipeCard` 展示。

---

## 8. 前端页面改动（`frontend/laoyouji-app/src/`）

**长辈端**
- tabBar（`pages.json`）：首页 / 聊天 / **健康（指标+用药）** / 我的 —— 原"吃药"tab 升级为健康中心（**未做**：tabBar 现仍为 首页/聊天/吃药/我的，即 `pages/elder/medications`；`health.vue` 已存在但未进 tabBar，健康页暂由首页按钮进入 `navigateTo('/pages/elder/health')`，口径同 `docs/DEMO_SCRIPT.md`）
- 新增 `pages/elder/health.vue`：指标录入（表单 + 语音，复用 `components/LyjMic.vue`）+ 趋势图
- `pages/elder/home.vue`：改健康概览（今日指标/用药/问候）
- `pages/elder/route-map.vue`：改本地就医/散步路线
- `pages/elder/profile.vue`：加慢病档案编辑 + 紧急联系人

**子女端**
- `pages/child/dashboard.vue`：从"审批中心"改为"**健康概览**"（最新指标/趋势/用药依从/就医通知）
- `pages/child/guardian.vue`：保留（途中守护）
- `pages/child/notification.vue`：保留（`health_alert` 通知）
- `pages/child/confirm-detail.vue`：改为只读"就医事件详情"

**新组件**（`src/components/`）
- `CallCard.vue`（一键拨号卡）
- `VitalTrend.vue`（趋势图，走 `dataviz` 规范）
- `RecipeCard.vue`（食谱分步）

**App 路线（已交付 `android/` 壳 + H5 侧桥；不再走 `app-plus` / HBuilderX / uni-push 那条路）**
- **交付物 = 仓库 `android/` 目录 + `build_apk.sh`**（怎么构建/怎么改见 `android/README.md`，冻结的接口契约见 `android/CONTRACT.md`）：Java 源码在 `android/src/com/kangle/app/`（`MainActivity` / `NativeBridge` / 提醒四件套），WebView 壳加载云端 H5，原生侧排 `AlarmManager` 到点闹钟。
- `src/utils/native.js`：**H5 侧唯一的原生桥适配层** —— 封装 `window.KangleNative`（`syncReminders`/`buildMedicationReminders`/`buildGreetingReminder`/`openKeepAliveGuide`…）；拿不到桥时静默降级、页面照常渲染，不抛异常。
- 录音适配层：**已落地在 `src/api/asr.js`**（按平台分支：H5 走 WebAudio PCM→WAV，App 走 `uni.getRecorderManager()` mp3 直传），不是独立的 `utils/recorder.js`。
- 保活引导：**已落地在 `pages/elder/profile.vue`**（自启动 / 省电白名单 / 通知 / 精确闹钟四步弹层，事件名 `kangle:keepalive-guide`）。
- `pages/common/permissions.vue`（独立首启权限引导页）：**未建**。
- `manifest.json`：**不加 `app-plus`**（那条路已弃用；APK 由 `build_apk.sh` 直接产出，无需 appid/SDK 配置）。

---

## 9. 分阶段执行计划

> **重排原则**:把最大未知（这套 alpha 版 uni-app 能不能打出能用的 APK）**前移到 P0 去证伪**。别等做完功能才发现打不出包。详细风险标注见 `docs/FEASIBILITY.md §4`。

| 阶段 | 目标 | 关键任务（涉及文件） | 可演示产出 |
|---|---|---|---|
| **P0 收敛 & 硬伤 & APK 打通 spike**<br>~1.5 天 | 聚焦骨架 + **去 App 风险** | 改名康乐（README/PRD/manifest）；**AMap key 收敛进 env**（私有仓库→git 历史不清、密钥暂不轮换，见 §1 tripwire）；砍工具（`travel_tools`/`community_tools`/`check_scam`）、更新 agent `tool_names`、`HIGH_RISK_TOOLS`、`plan_builder` report_key。**APK spike(先做)**:**已证伪并弃用 uni-app 原生路（`manifest.json` 加 `app-plus` + DCloud appid + HBuilderX 云打包）**，改为服务器上 aapt+d8 手打 **WebView 壳**（`android/` + `build_apk.sh`），加载云端 H5 装真机点一遍（验 Leaflet 渲染 + 录音）。**本机已真编通过。** | 干净骨架 + **能装机的 APK 壳(证明路线可行)** |
| **P1 身体核心**<br>2–4 天 | 指标闭环 | 新表 `health_metrics`/`health_conditions`（schema+local+repo）；新工具 `log_vital`/`get_health_summary`/`add_condition`/`assess_health`（新增 `backend/app/safety/health_rules.py` 参考区间+保健优先）；**抽 `recorder` 适配层(H5 WebAudio / App getRecorderManager)**；`elder/health.vue` + `VitalTrend`；扩 `seed_demo.py` 张桂芳 30 天档案 | **录指标 → 趋势 → 分诊** |
| **P2 就医闭环 + 真通知(②)**<br>3–4 天 | 就医+知会 | `register_appointment` 去审批 + `notify_children`（`health_alert`）；**送达:SMTP 邮件兜底（已落地）+ app 内红点；uni-push 在线推送未实现**（§4）；`search_hospital` 高德 POI 就近排序；`plan_route` 接 AMap 公交/地铁（`amap_service.py` 加 transit）；子女端 dashboard/notification 重构 | **异常 → 建议就医 → 本地路线 → 子女邮件+红点收到** |
| **P3 心理层 + 真·本地提醒(①)**<br>3–4 天 | 陪伴+社交+到点提醒 | `suggest_call` + `CallCard`（**已验证**）；**用药到点提醒 / 晨间问候 = `android/` 原生 `AlarmManager` 到点闹钟 + 系统通知（已落地）**；`push_activities`→`suggest_walk` + `activities.json`；散步**预置环线**；`get_recipe` + `recipes.json` + `RecipeCard`；`SmsProvider` 方案文档 | **到点弹用药/问候(真离线) + 孤独→一键拨号 + 活动/食谱** |
| **P4 App 生产化 · 三机制健壮 + 保活**<br>3–5 天 | 让真的稳 | **①本地定时**:原生 `AlarmManager`(已落地)+ 各机型**保活/自启动/电池白名单引导弹层**(已落地于 `pages/elder/profile.vue`);**②跨设备推送**:uni-push 在线**未做**,(有资质才做)厂商离线通道 filing;**③后台守护**:`startLocationUpdateBackground` 真机跑通(**未做**)+ **保留模拟回放主兜底**;独立首启权限引导页 | **真机上提醒不被杀、告警跨设备到、途中能看位置(带兜底)** |
| **P5 打磨演示(真机)**<br>1–2 天 | 参赛就绪 | 端到端脚本；重写 `docs/DEMO_SCRIPT.md`；评委叙事(标注"模拟/演示数据")；**真机走查 + H5 兜底扫码**；更新 `frontend/e2e` + `tests/*.mjs`；`seed_demo --scenario` 预设 | 全链路可复现演示(真机为主、H5 兜底) |

> **工期不确定性集中在 P0(能否打包)和 P4(保活/推送)** —— 这两处"可能超预期",已单列。比纯 H5 版 +5~6 天。

### 9.1 进度核对（2026-09-13，逐条去代码里核实过）

> 只记**核实过的事实**，不照抄描述。每条后面是核实的落点。未核实的一律留在"未做"。

| 阶段 | 完成度 | 已核实做了的 | 核实为**未做**的 |
|---|---|---|---|
| **P0** | 部分 | 工具已砍：`check_scam`/`search_train`/`book_ticket`/`search_hotel`/`book_hotel`/`canteen_order` 均已不在册（实测 `/api/health` 报 **22** 个工具，非原 23）；`HIGH_RISK_TOOLS` 已收敛为 `{pay}`；`travel.json` 类的数据文件（trains/hotels/canteen_menu）已删；**改名康乐已完成**：前端 UI 与后端 display name 已同步为"康乐"（`pages.json`/`manifest.json`/页面标题、`MainAgent.display_name = "康乐"`，`frontend/laoyouji-app/src/` 下 `grep 老友记` 无命中）；**APK 打通已完成**：交付物是 `android/` 目录 + `build_apk.sh`（不走 `manifest.json` 加 `app-plus`/HBuilderX 云打包那条路），本机已真编通过 | **AMap key 收敛进 `.env` 未核实** |
| **P1** | 大体done | `health_metrics`/`health_conditions` 表与 repo 落地；新工具 `log_vital`/`get_health_summary`/`add_condition`/`assess_health` 全部注册可用；`app/safety/health_rules.py`（四档阈值 + 症状红旗 + 趋势，纯函数）已落地并被 `test_health_metrics`/`test_demo_scenarios` 钉住；`seed_kangle_persona` 四剧本（stable/observation/hypertension_spike/emergency）齐备；**录音适配层已落地**：真实现在 `src/api/asr.js`（H5 走 WebAudio PCM→WAV、App 走 `uni.getRecorderManager()` mp3，按 `#ifdef` 分支），不在 `utils/` 下（`src/utils/` 现为 `amap.js` + `native.js`，没有独立的 `recorder.js`） | —— |
| **P2** | 部分 | `register_appointment` 去审批、立即执行 + 办完 `_notify_children_of_appointment` 写 `appointment_notice` 知会全部子女（无 `task_id`）；**送达已落地邮件层**：`providers/external/mailer.py` 的 `MockMailer`/`SmtpMailer`（`build_mailer`），`bootstrap.py:140` 注册为 `mail` provider，`health_tools.py` 的 `_deliver_by_email` 已在挂号知会主链里真发；`search_hospital` 同城硬过滤 + haversine 离家距离排序 + `distance_text`；`plan_route` 的 **transit/walking 已在 `amap_service.py` 实现**（`/v5/direction/transit/integrated`、`/v5/direction/walking`），跨城诚实拒答（`_LOCAL_MODES`）；子女端 `dashboard.vue` **已改成"健康概览"看板**（就医知会不审批） | **送达只做了邮件这一层**：**uni-push 在线推送未做、厂商离线通道未做**（app 内红点保留）；`search_hospital` 仍是 `hospitals.json` 内置库 + haversine，**不是高德 POI 实时周边搜索** |
| **P3** | 部分 | 右翼四张卡全部落地：`suggest_call`(+`CallCard`)、`push_activities`、`suggest_walk`(+环线卡)、`get_recipe`(+`RecipeCard`)，`activities.json`/`recipes.json` 内置数据齐备；**用药到点提醒 / 晨间问候已实现**（不再是"未做"）：`android/` 原生提醒层 `AlarmScheduler` 排 `Reminder` → `ReminderReceiver` → `NotificationHelper`，`BootReceiver` 开机重建，H5 侧经 `src/utils/native.js`（`syncReminders`/`buildMedicationReminders`/`buildGreetingReminder`）桥接，挂在 `pages/elder/home.vue`/`medications.vue`/`profile.vue` | **`SmsProvider` 与 `docs/SMS_DESIGN.md` 未建**；`manifest.json` 仍无 `app-plus`（因为不走那条路，非缺陷） |
| **P4** | 部分 | 保活引导弹层已落地（`pages/elder/profile.vue` 的自启动/省电白名单/通知/精确闹钟四步，事件名 `kangle:keepalive-guide`，`native.js` 的 `openKeepAliveGuide`）；定时提醒靠原生 `AlarmManager` 常驻 | **uni-push 在线推送未做**；**`startLocationUpdateBackground` 后台定位未做**（`src/` 下无落点）；独立的 `pages/common/permissions.vue` 未建 |
| **P5** | 部分 | `docs/DEMO_SCRIPT.md` 已重写为三条链 + 四档切档 + 诚实边界（本文配套）；`tests/test_demo_scenarios.py` 为演示数据可信度单独把关；**`scripts/demo_smoke.py` 与 `frontend/e2e/elder-flow.mjs` 已升级**：旗舰指令改本地就近就医，计划书断言为四页（不再有"去北京"/车票酒店） | ——（本轮未单列其余打磨项） |

**基线测试（2026-09-13 实跑）**：`pytest tests/ -q` → **601 passed, 0 failed**（29 个 `test_*.py` / 494 个 `def test_`）。
上一版本文里的"**512 passed, 1 failed**"与"唯一失败 `test_amap_guardian.py::test_guardian_direct_and_quick_endpoints`，本机无网必然
EOFError、属环境问题"两处说法**均作废**：512/1 是过期数字，而那条用例的"必然 EOFError"判断本身是错的 ——
本轮实跑**全绿**，该用例也通过。（该用例 docstring（`backend/tests/test_amap_guardian.py:810`）仍留着一句
"本机没网会 EOFError —— 那不是本工作流要修的东西，如实留着"，与实测不符，是测试自身文案待清理，不影响结果。）

---

## 10. 端到端演示脚本（两条主线）

**主线 A · 身体健康（张桂芳，触发就医）**
1. 老人早晨语音："帮我记一下血压，高压 178 低压 105" → `log_vital`
2. 系统 `get_health_summary` + `assess_health`：结合高血压史 + 连续 5 天走高 → "建议就医"档（非"保健"档）
3. 老人主对话框：大白话解释 + 就近医院（`search_hospital`）+ 公交/地铁路线（`plan_route`）+ 已挂号（`register_appointment`，无需子女同意）
4. `notify_children`：子女端收到完整通知（**邮件 + app 内红点**两层；在线推送未实现）（指标/趋势/分诊/医院/预约/路线）
5. 老人出门 → guardian 途中守护，子女端看位置/到达（**后台定位尚未实现(P4)，演示走模拟轨迹回放兜底**，FEASIBILITY §3）

**主线 B · 心理健康（孤独 → 陪伴）**
1. 晨间问候卡："张阿姨早，今天想做点什么？"
2. 老人聊天流露孤独 → 主 agent 出 `CallCard`："要不要给儿子李明打个电话？" → 点一下拨号
3. 或 `suggest_walk`（原设想名 `suggest_activity`，落地为 `suggest_walk`）："社区棋牌室今天有活动 / 附近有撸猫店 / 给您规划一条公园散步路线"
4. `get_recipe`："教您做一道清淡的番茄鸡蛋面" → `RecipeCard` 分步

**对比主线 C · 日常保健优先（不去医院）**
- 老人血压 138/86（平稳区）→ `assess_health` 出"保健"档：不建议就医，给饮食/散步/按时服药建议 → 体现"不是什么情况都让老人去医院"。

---

## 11. 需要新建/更新的文档

| 文档 | 动作 |
|---|---|
| `docs/REFOCUS_PLAN.md` | 本文（新建） |
| `docs/PRD.md` | 重写定位为康乐·健康基线两层 |
| `docs/DATA_MODEL.md` | 加 `health_metrics`/`health_conditions`，标注 `orders` 停用 |
| `docs/ARCHITECTURE.md` | 加 ADR：审批→知会、travel 收缩、SmsProvider 插件位 |
| `docs/DEMO_SCRIPT.md` | 重写为上面三条主线 + seed 预设 |
| `README.md` / `HANDOFF.md` | 改名、删明文凭据、更新跑通步骤 |
| `docs/SMS_DESIGN.md` | 新建：真 SMS 生产方案（"方案要有"） |
| `docs/APK_BUILD.md` | **不新建（原设想作废）**：APK 交付物是仓库 `android/` 目录 + `build_apk.sh`，构建步骤/权限清单都在 **`android/README.md`**，接口契约在 **`android/CONTRACT.md`**；不再有 DCloud appid / HBuilderX 云打包 / `app-plus` 配置 |
| `docs/PUSH_DESIGN.md` | **待建**：②跨设备推送现状是 **SMTP 邮件(已落地) + app 内红点**；uni-push 在线推送、离线厂商通道(需资质)filing 均为**未做**的方案部分 |

---

## 12. 风险与取舍

**App 路线新增风险(详见 FEASIBILITY §1、§4):**
- **打包路线已定型（旧的 HBuilderX/DCloud 云打包设想已弃用）**:`uni build` 出不了 APK，改为服务器上 aapt+javac+d8+zipalign+apksigner 手打 **WebView 壳**（仓库 `android/` + `build_apk.sh`），**本机已真编通过**。风险因此从"能不能打包"转为"壳的边界"：app 关闭后无后台/定时/推送（**定时提醒已用原生 `AlarmManager` 补上**），服务器一挂壳即白屏（有离线兜底页）。
- **保活不可根治**:华为/小米/OPPO/vivo 各家杀后台 → 本地提醒/后台定位可能失效。只能白名单引导 + 前台服务兜底 + 演示机预配。**演示时坦白,不假装 100% 可靠。**
- **②跨设备推送**:离线厂商通道要企业资质 → 默认不做;**在线推送(uni-push)也未实现**,当前只落 **SMTP 邮件兜底(已落地、真送达)**;有资质再上厂商通道。
- **③后台定位 flaky**:真机能演但不稳 → **保留模拟轨迹回放作主兜底**。
- **录音双路径**:H5 WebAudio / App getRecorderManager 两套,抽适配层维护。

**沿用的取舍:**
- **审批基础设施保留但闲置**：可接受；是加分工程，且为未来真实支付留口。
- **AMap 公交路线**：**geocode + driving + transit + walking 均已在 `amap_service.py` 实现**（`/v3/geocode/geo`、`/v5/direction/driving`、`/v5/direction/transit/integrated`、`/v5/direction/walking`），跨城诚实拒答（`_LOCAL_MODES`）；offline fallback 仍走 `routes.json`。
- **真挂号/真短信不上线**：作模拟 + 文档方案(`SMS_DESIGN.md`),演示诚实标注。
- **假数据边界**：务必注明"合成演示数据"，把"造假风险"转成"工程严谨"。
- **改名波及面**：康乐品牌串已全局替换完毕（`manifest.json`、页面标题、`MainAgent` display name 等），P0 一次性做完。
- **保留 H5 双输出**:开发期在浏览器调,演示期作真机 APK 的零摩擦兜底,几乎零成本。

---

## 13. 待你确认

平台已定(§0.5)。**三子决策已确认(2026-09-11):只做 Android、无企业资质(→②离线厂商通道不做,uni-push 在线推送也未实现,跨设备送达只落 SMTP 邮件 + app 内红点)、演示机小米(MIUI,保活引导按 MIUI 定制)。** 末两小决策也已定:

1. `hail_ride`（打车去医院）**留** —— 仅信息展示、假数据演示,不代付。
2. 泄露凭据:**私有仓库 → 暂不清历史、不轮换**;仅在**公开/交付/开源前**处理(tripwire,见 §1)。
