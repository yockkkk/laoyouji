# DATA_MODEL · Supabase Schema 说明

DDL 全文见 **`backend/app/db/schema.sql`**（在 Supabase SQL Editor 直接粘贴执行）。
表清单与 `backend/app/db/repositories.py:17` 的 `TABLES` 一一对应 —— 那份列表还兼作 `reset()` 的清空顺序（反依赖序），所以两处必须同时改。

## 表清单（16 张）

| 表 | 用途 | 关键字段 |
|---|---|---|
| `users` | 老人/子女双角色 | `role` (elder/child), `dialect`, `city` |
| `family_bindings` | 家庭绑定 | `elder_id` + `child_id` 唯一 |
| `sessions` | 会话 | `user_id`, `title` |
| `session_events` | **append-only 唯一事实源** | `(session_id, seq)` 全序 · `type` · `payload jsonb` · **`agent_id` / `turn_id` / `step_id`** |
| `confirmation_tasks` | 高危确认状态机 | `tool_name` + `tool_args`（冻结）, `status`, `expires_at`, `summary_for_child` |
| `notifications` | 子女端通知（就医知会 / 待确认 / 结果） | `user_id` + `elder_id`, `type`（如 `appointment_notice`）, `is_read`, `data jsonb` |
| `trips` | 行程 | `plan jsonb`（就医出行计划书全文）, `status` |
| `trip_checkpoints` | 守护轨迹点 | `status`: normal / off_route / long_stay / arrived / **not_moving** |
| `medication_plans` | 用药计划 | `times jsonb`（`["08:00","20:00"]`）, `active` |
| `medication_logs` | 服药打卡 | `scheduled_for`(date) + `scheduled_time`(text), `taken_at`, `status` |
| `health_records` | 健康记录 | `record_type` 约束允许 report / appointment / scam_check / diet，**代码目前只写 `appointment` / `report` 两种**（`scam_check` 随反诈工具下架、`diet_advice` 不落档，见下）· `plain_summary`（大白话解读） |
| `health_metrics` | 健康指标读数（血压/血糖/心率/血氧/体温/体重） | `metric_type` · 血压 `systolic`/`diastolic`、单值 `value` · `level`（当时的**分诊档位** 保健/观察/建议就医/紧急） |
| `health_conditions` | 慢病登记 | `name`（如 原发性高血压）· `diagnosed_at`（老人原话）· `severity` · `active` |
| `orders` | 邻里帮订单 | `service_type`: canteen / cleaning / accompany · `timeline jsonb`（派单进度） |
| `privacy_permissions` | 隐私分级 | `location_level`(realtime/city/off) · `health_level`(full/summary/off) · `(elder_id, child_id)` 唯一 |
| `audit_log` | 审计 | `actor_id`, `action`, `target`, `detail jsonb` |

### `session_events` 是内核的落点，值得单独说

大改后这张表承载的是 harness 式的事件溯源，有三处与旧版不同：

1. **`seq` 由后端内存里的单调计数器发号**（`core/events.py`），`append()` 同步返回、不等 I/O。旧实现是"先读 `max(seq)` 再 +1"，两个并发轮次会拿到同一个号，"append-only 全序"的承诺不成立。`uq_session_events_session_seq` 这条唯一索引是内存计数器的**数据库侧后盾** —— 真撞号了就报错，不会静静写坏。
2. **写库是 write-behind**：`append` 只入内存待刷队列，`session/flush` 检查点才落盘。所以"事件已记录"和"事件已入库"之间有一个窗口；`GET /api/sessions/{sid}/events` 读的是已落库的那一份。
3. **作用域三件套**：`agent_id` 是"谁说的"（三个子智能体各占一个），`derive_messages(session_id, agent_id=…)` 按它过滤，这是"子 Agent 不共用父历史"在存储层的落点；`turn_id` / `step_id` 让"第几轮第几步干了什么"可以精确回放。`idx_session_events_scope` 索引服务这条查询。

`type` 里存的是**持久事件类型**（斜杠词表：`assistant/message`、`tool/result`、`todo/write`…），不是推给前端的线格式（`agent_msg`、`tool_result`、`todo`）。两套词表的翻译点各在一侧：后端 `core/events.py` 的 `_SSE_TO_DURABLE`、前端 `src/api/sse.js` 的 `_DURABLE_TO_SSE`。详见 `docs/API.md`。

另外：`delta` / `agent_status` / `todo` 三个 SSE 事件是 `persist=False` 的活信号，**这张表里没有它们**。轮询兜底因此看不到打字预览和步骤条 —— 事实进表，信号不进。

### `health_records` 的两种写入者

| `record_type` | 谁写 | `plain_summary` 里是什么 |
|---|---|---|
| `appointment` | `register_appointment` 挂号成功后 | 空（挂号信息在 `content` 里） |
| `report` | `interpret_report` 体检解读 | 那份大白话解读 |

`scam_check` 与 `diet` 留在 `schema.sql:179` 的 check 约束里，但代码里没有写入者：反诈工具（`check_scam`）已随康乐收敛下架，`diet_advice` 也只回一段建议、**不落档**。
约束留着是给后续用的；写文档和答辩稿时不要把"约束允许"说成"已经有这类记录"。

**没有任何出库接口读这张表。** 全仓的读取只在挂号幂等查重（`health_tools.py`）与验证链路
（`scripts/demo_smoke.py`、`tests/test_confirmation.py`）上。子女端看板返回的是
`medications`，不是 `health_records`。所以 `health_level` 的降级
（`filter_medication` / `filter_health_text`）此刻管不到这张表：不是设计上豁免，是这条
出库路径还没接。**要给子女端加"健康档案"视图的话，R6 的第一件事就是在那条路上补裁剪**，
别让"存的是全量"变成"看到的是全量"。

## 访问安全策略

- 前端**绝不**直连 Supabase（不下发 anon key）
- 后端持 service key 读写
- **所有表开启 RLS 且不建任何 policy**（默认全拒，仅 service role 可操作）
- 正式版升级路径：改用 anon key + per-family RLS policy（经 `family_bindings` 关联校验）
- 断网/无 Supabase 时切 `STORAGE_BACKEND=local` → `LocalFileRepo`，每表一个 JSON 文件、写盘原子（临时文件 + `replace`）、读写加线程锁。演示离线可跑，接口不变

## 状态机

**`confirmation_tasks.status`**：`pending → (approved → executing → executed | failed) | rejected | expired`

- 30 分钟未处理 → 惰性清扫为 `expired`（任意读取路径触发）
- 非 `pending` 再审批 → HTTP 409
- **fail-closed**：找不到应答者（没有绑定子女）时直接 deny，**不靠 30 分钟静默过期**。等超时等于"没人管就默认放行一段时间"，那是把 R5 反过来做
- `tool_args` 在挂起那一刻冻结；批准时精确比对后新建 `TurnContext` 重放。参数被改过一个字就拒绝执行

**`orders.status`**：`pending_confirm → dispatching → in_progress → done | cancelled`（DDL 默认值是 `dispatching` —— 走高危拦截的单子由确认流负责把它先摆在 `pending_confirm`）

**`trips.status`**：`planned → ongoing → completed | aborted`

## 隐私分级的存储侧

`privacy_permissions` 的 DDL 默认值是 `location_level='realtime'` / `health_level='summary'`。**这两个默认值只在"已建行"的语义下成立** —— 表示老人建立绑定时默认开放到这一档。

没有行、或压根没有绑定关系时，正确的语义是**全关**，不是默认值。子女端界面的兜底常量因此必须是 `{location_level:'off', health_level:'off', bound:false}`。把 DDL 默认值当兜底，界面就会宣称一份后端 `denied()` 明确拒绝的权限。这条踩过，判据写在 `docs/DESIGN.md` §6.5。

每次 PUT 变更写 `audit_log`（`action: privacy_changed`）—— 老人日后要能问"我什么时候把这个关掉的"。

## 演示数据

分两类，**别混在一起讲**：

**① 落库的种子数据**（`POST /api/seed` / `app/db/seed.py`，幂等，先 `reset()` 再灌）：

- `seed_demo`（基础四表）：`users` 张桂芳（elder，南京，`dialect=southwestern`）+ 李明（child，北京）· `family_bindings` 儿子 · `privacy_permissions` `realtime` / `summary` · `medication_plans` ×2（硫酸氨基葡萄糖胶囊 08:00 / 20:00、钙片 09:00）
- `seed_kangle_persona`（`/api/seed` 默认 `with_persona=true` 时叠加，`days=30`）：`health_conditions` ×2（原发性高血压、2 型糖尿病）· `medication_plans` ×2（苯磺酸氨氯地平片、二甲双胍缓释片）· `health_metrics`（30 天合成读数，四个剧本对应四个分诊档位；只追加、不 reset）

**老人的名字是「张桂芳」** —— 交付物标题 `f"{name} · {city}就医出行计划书"` 直接取它，文档和 PPT 里别写成别的字。

**② 不落库的业务夹具**（`backend/app/data/*.json`，由 Mock Provider 读取）：

`hospitals.json`（医院 × 医生 × 一周号源）· `routes.json` · `rides.json` · `activities.json` · `recipes.json` · `weather.json` · `scam_corpus.json`（"保健品神药""冒充孙子借钱""冒充医保局短信"等）

这些**不是表**，也不进 Supabase。Mock Provider 按参数 `md5` 确定性取值，所以同一句话两次演示结果一致。正式落地时替换 provider 实现，夹具随之退场 —— 表结构不动。
