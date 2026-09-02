# API · 老友记后端

Base URL: `http://127.0.0.1:8000`（开发）

所有业务外部 API（挂号、12306、地图、天气、支付）均为 **Mock Provider**，返回按参数 `md5` 确定性生成 —— 演示可复现。个人开发者拿不到这些平台的正式接口，正式落地时替换 provider 实现即可，接缝不动。详见 `README.md` 的模拟数据披露。

## 端点总览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查：当前装配的 provider / agent / tool 清单 |
| POST | `/api/chat/stream` | 对话主入口，SSE 流式响应 |
| POST | `/api/asr/upload` | 语音文件 → 识别文本（multipart：`file`，可选 `dialect`） |
| GET | `/api/sessions/{sid}` | 会话详情 + 最近 200 条事件 |
| GET | `/api/sessions/{sid}/events?after_seq=N` | 会话事件增量拉取（轮询兜底 / 断线恢复 / 回放） |
| GET | `/api/child/{cid}/dashboard` | 子女端聚合看板（**一次请求拿全部**） |
| GET | `/api/child/{cid}/confirmations?status=` | 确认任务列表（`status` 可省 = 全部状态） |
| POST | `/api/confirmations/{id}/approve?child_id=` | 子女批准并重放执行 |
| POST | `/api/confirmations/{id}/reject?child_id=` | 子女拒绝 |
| GET | `/api/trips/{id}?child_id=` | 行程详情 + 轨迹（**带 `child_id` 才按隐私档裁剪**） |
| POST | `/api/trips/{id}/checkpoints` | 位置上报（演示模拟）→ 偏航判定与告警 |
| GET | `/api/privacy/{elder_id}?child_id=` | 读隐私分级授权 |
| PUT | `/api/privacy/{elder_id}` | 改隐私分级授权（写审计） |
| GET | `/api/medications?elder_id=&with_logs=` | 用药计划列表 |
| POST | `/api/medications` | 新建用药计划 |
| POST | `/api/medications/{id}/taken?scheduled_time=` | 服药打卡 |
| GET | `/api/weather?city=&date_offset=` | 天气（走 Weather Provider 接缝） |
| GET | `/api/demo/family` | 登录页用：演示家庭（老人/子女），无数据时自动 seed |
| POST | `/api/seed` | 演示数据一键复位 |

## POST /api/chat/stream

请求体：
```json
{ "session_id": "uuid|null", "user_id": "uuid", "text": "我想去北京看腿疼的老毛病" }
```

`session_id` 为 null 时新建会话；带 ID 时**先 hydrate 再 append** —— 不 hydrate 就写，`seq` 会从 1 重新发号、撞掉已有行（`routes_chat.py:40`）。

### SSE 事件协议

后端有**两套事件名**，这是内核的刻意设计（`core/events.py:20`）：落库的持久类型用斜杠词表 `assistant/message`，推给界面的线格式用下划线 `agent_msg`。下表是线格式，即前端契约。

| event | data 结构 | 落库类型 | 说明 |
|---|---|---|---|
| `session` | `{session_id}` | — | 首帧，会话 ID |
| `user_msg` | `{text}` | `user/message` | 老人这句话的回显（前端已本地上屏，通常忽略） |
| `todo` | `{todos:[{content,status}], progress:{total,done,doing}}` | `todo/write` | 真进度快照，**整表覆盖**。`persist=False` |
| `agent_status` | `{agent, text}` | — | "银发导航正在处理…"。`persist=False` |
| `delta` | `{text, agent}` | — | LLM 流式增量，**打字预览**。`persist=False` |
| `agent_msg` | `{text, agent}` | `assistant/message` | **定稿**，医疗安全改写后的那一份 |
| `tool_call` | `{call_id, tool, agent, args, summary}` | `tool/call` | 工具调用 |
| `tool_result` | `{call_id, tool, ok, summary, content}` + 可选 `suspended`/`confirmation_id`/`denied` | `tool/result` | 工具结果。`summary` 里带 R4 免责声明 |
| `report` | `{agent, ok, summary, data, missing, error, scope, suspended, tools_used}` | `agent/report` | 子智能体的**结构化回报**，交付物渲染的唯一输入 |
| `card` | 见下 | `artifact/card` | 确定性交付物卡片 |
| `suspended` | `{confirmation_id, tool, summary, amount, expires_at, message}` | `confirmation/suspended` | 高危操作已挂起，等子女确认 |
| `confirmation_resolved` | `{confirmation_id, tool, ok, status}` | `confirmation/resolved` | 子女点完了。`status` = `executed`/`rejected`/`failed` |
| `guardian_alert` | `{trip_id, location, note, elder}` | `guardian/alert` | 偏航告警（由 checkpoint 上报侧推入本会话） |
| `final` | `{text}` | `assistant/final` | 本轮结束语 |
| `error` | `{message}` | — | 出错，`message` 是写给老人听的一句话 |

四条契约要点：

1. **`agent_msg` 覆盖 `delta`，不是追加。** 医疗安全改写挂在 `agent/request` 瀑布最外层，而 `delta` 是 provider 内部逐片推的，比改写更早到前端 —— 所以预览可能是未审的原话。`test_medical_safety.py::test_the_streaming_preview_is_not_the_authoritative_text` 钉着这条。
2. **`tool_result.summary` 覆盖 `tool_call.summary`。** R4 免责声明是 `HealthDisclaimerGuard` 注进**结果** summary 的；只渲染调用摘要，那句声明就到不了老人眼前。用 `call_id` 配对（批处理是并发的，回来的顺序和调用顺序不同）。
3. **`persist=False` 的三个事件（`delta`/`agent_status`/`todo`）不进事件日志**，所以轮询兜底链路里没有打字预览和步骤条 —— 它们是活信号，不是事实。
4. **`confirmation_resolved` 通常到不了那条流。** 它是唯一一个发生在老人**轮次之外**的事件：挂起在轮内，子女是几分钟后在自己手机上点的，那时老人这条 SSE 早已收 `final` 关闭。后端照样广播 + 落库，界面靠回读 `GET /api/sessions/{id}/events` 补上（`chat.vue::_watchConfirmations`，见 `docs/DESIGN.md §6.6`）。`ok=False` 不足以描述结局，所以 `status` 必须单独读：`rejected` 是家人不同意，`failed` 是家人同意了但重放没成功。

### `card` 的 data 结构

```json
{
  "type": "trip_plan | health_card | community_card",
  "title": "张桂芳 · 北京就医出行计划书",
  "subtitle": "共 5 页，可以直接打印带着走",
  "printable": true, "generated_on": "2026-...",
  "pages": [
    { "no": 1, "title": "第一页 · 挂号信息",
      "rows": [{ "label": "医院", "value": "北京积水潭医院", "missing": false }],
      "notes": ["..."], "complete": true }
  ],
  "body": {...}, "missing": ["hotel.address"], "complete": false,
  "disclaimer": "本计划书由老友记根据查询结果自动生成，仅供出行参考。医疗相关内容不构成诊断意见，请以医生面诊结论为准。",
  "footnote": "（竞赛原型：车次、号源、酒店数据来自模拟接口，正式落地对接官方开放 API）"
}
```

标题不带书名号，格式是 `f"{name} · {city}就医出行计划书"`（`agents/plan_builder.py:302`），`name` 取自老人记录（种子数据是 `张桂芳`）。页标题**自带"第一页"**，前端不要再加一层序号。

`footnote` 只有五页计划书有，内容是**模拟数据披露**（`plan_builder.py:52`）。它必须渲染出来 —— 这是合规要求，不是装饰。前端 `_toCard` 把 `subtitle` / `disclaimer` / `footnote` 依次收进 `notes`。

**卡片里没有 `announce` 字段。** 后端把免责声明同时写进工具结果的 `summary` 与 `announce`，但 SSE 只推 `outcome.result["card"]` 这一个子字典（`core/session.py:343`）—— `announce` 是结果的兄弟字段，不随卡片下来。卡片的朗读文本因此由前端从卡面合成（`PlanCard.speech()`），卡面已含脚注里的声明。见 `docs/DESIGN.md` §5.1。

### `tool_result` 上的三个可选标记

`suspended` / `confirmation_id` / `denied` 互斥，代表守卫流水线的三种出口：

| 标记 | 含义 | 界面该做什么 |
|---|---|---|
| `suspended: true` + `confirmation_id` | 高危操作被拦下，已建确认任务 | 黄卡「这一步要家人点头」，等 `confirmation_resolved` 就地改状态 |
| `denied: true` | 守卫**硬拒绝**，不问家人也不执行 | 直接把 `summary` 当结论上屏。**不要**渲染成待确认卡 —— 这条路的全部意义就是不把决定权交出去 |
| 两个都没有 | 正常执行完 | 常规结果气泡 |

`denied` 目前只有一个来源：`ScamContentRule` 在**下单类工具的参数里**发现骗子话术（如"保健品神药根治套餐"）。做成待确认卡片等于替骗子把话传给了家人，所以这里没有"问一下"的出口。

### `check_scam` 的结果形状（反诈判定，三档）

```json
{ "ok": true,
  "summary": "疑似诈骗：…（附 R4 通用版免责声明）",
  "announce": "这个像是骗子！先别转。挂了电话给孙子本人打一个，确认清楚。",
  "data": { "verdict": "high_risk | normal | unknown",
            "reason": "命中的判据", "advice": "一句能照着做的话" } }
```

`verdict` 有**三个**取值，`unknown` 是刻意留的第三态：判定顺序是**语料库命中（二元字组包含度 ≥ 0.34）→ 高信号词命中 → 交给模型且只认它给出的判定词**，三档都说不出话时给 `unknown`，播报是「我拿不准这条是真是假。先别回、也别转钱，把它发给家人看一眼。」

界面按 `verdict` 分档显示时**必须处理 `unknown`**，不能按二值折叠成"安全/危险"——两头猜错各有代价：说"没事"会让老人把钱转出去，说"是骗子"会让老人不敢接自己孩子的电话。

这个工具是 `ScamContentRule` 的**唯一豁免**（`safety/risk_rules.py:_JUDGES_CONTENT`）：它的入参就是那条可疑短信，不豁免的话守卫每次都命中，反诈在最该生效的一刻返回 `denied`。豁免前提写死在那份注释里 —— 它不动钱、不下单、不锁号源，只产出一个判断。

三档都会往 `health_records` 写一行（`record_type: "scam_check"`，`plain_summary` 是给子女看的那句话）。子女事后问"我妈那天到底收到了什么"要翻得出来。

示例（curl）：
```bash
curl -N -X POST http://127.0.0.1:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"session_id": null, "user_id": "<elder_uuid>", "text": "我想去北京看腿疼的老毛病"}'
```

## GET /api/sessions/{sid}/events

```json
{ "items": [{ "seq": 12, "type": "assistant/message", "payload": {...},
              "agent_id": "main", "turn_id": "...", "step_id": "...",
              "created_at": "..." }],
  "latest_seq": 12 }
```

`type` 是**持久类型**（斜杠那一套）。前端消费前必须翻回线格式，翻译表在 `src/api/sse.js` 的 `_DURABLE_TO_SSE`。直接把 `row.type` 丢给界面是不行的 —— 一个 case 都不会匹配。

## GET /api/child/{cid}/dashboard

已绑定：
```json
{ "child": {"id","name"}, "elder": {"id","name","city"},
  "privacy": {"elder_id","child_id","location_level","health_level","bound"},
  "pending_confirmations": [...], "medications": [...],
  "trips": [{"id","purpose","status","created_at"}], "alerts": [...] }
```

**未绑定时走提前返回**（`routes_child.py:34`），响应里**没有 `elder`、也没有 `privacy`**：
```json
{ "child": {...}, "elders": [], "pending_confirmations": [],
  "medications": [], "trips": [], "alerts": [] }
```

所以前端的兜底常量必须是"全关"（`{location_level:'off', health_level:'off', bound:false}`），**不能是 `PrivacyGrant` 的数据默认值** `realtime`/`summary` —— 否则界面会宣称一份后端明确拒绝的权限。这条踩过，见 `docs/DESIGN.md` §6.5。

`pending_confirmations` 就是 `/confirmations?status=pending` 的同一个查询，看板轮询**不要**再单独拉一遍。

降级后的数据形状：`medications[].precision === "summary"` 时药名是 MASKED；`alerts[].precision === "off"` 时地点是 MASKED 而告警本身照发（隐私档位管"看得多细"，不管"要不要通知"）。

## GET /api/child/{cid}/confirmations

`status` **可省**，省略即全部状态。返回 `{items: [...]}`，每项含 `summary_for_child = {title, summary, reason, risk_level, amount, relation}` —— 大白话确认卡的数据源。

## POST /api/confirmations/{id}/approve

`child_id` 为可选 query 参数，用作审计日志的 `actor_id`（子女端应当一律带上）。

成功：`{ok: bool, status: "executed"|"failed", result: {...}}`
失败：HTTP 409 `{detail: "已过期/已处理"}`

批准走的是**冻结参数重放**：挂起时冻结 `tool_args`，批准时精确比对后新建 `TurnContext` 重放。参数被改过一个字就拒绝执行。

## GET /api/trips/{id}

**不带 `child_id` 是"老人看自己行程"的路径**，原样返回全量未降级轨迹（`precision: "owner"`）。子女端必须带 `child_id`，否则 R6 的分级在后端做对了、被前端一个缺参绕过去。

带 `child_id`：`{trip, checkpoints (已按档裁剪), precision, privacy}`，`precision ∈ realtime | city | off`。`city` 档会丢掉 `lng`/`lat` 并把 `location` 粗化成城市级前缀。

## POST /api/trips/{id}/checkpoints（演示模拟位置）

```json
{ "location": "南京南站", "lng": 118.79, "lat": 31.97 }
```
返回 `{checkpoint, status: "normal"|"off_route"|"arrived", alert_sent: bool}`。

判定规则（演示）：地点命中预期途经点 → `normal`，含"医院" → `arrived` 并结束行程；否则 `off_route` 并向老人会话推 `guardian_alert` + 写审计。

## GET / PUT /api/privacy/{elder_id}

GET 需要 `child_id` query 参数。没细调过时返回**生效中的默认档** + `explicit: false`，让开关有初始位置。

PUT body：`{child_id, location_level, health_level}`。取值不在词表内返回 422。每次变更写 `audit_log`（`action: privacy_changed`）—— 老人日后要能问"我什么时候把这个关掉的"。

- `location_level`: `realtime` | `city` | `off`
- `health_level`: `full` | `summary` | `off`
