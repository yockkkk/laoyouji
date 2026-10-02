# API · 康乐后端

Base URL: `http://127.0.0.1:8000`（开发）

挂号 / 天气 / 叫车 / 社区 / 支付这些业务外部 API 均为 **Mock Provider**，返回按参数 `md5` 确定性生成 —— 演示可复现。**地图是例外**：走高德开放平台 Web 服务 API（地理编码 / 驾车 / 公交换乘 / 步行），无 key 或断网时回落 `routes.json` 的本地演示线（`providers/external/amap_service.py`）。个人开发者拿不到这些平台的正式接口，正式落地时替换 provider 实现即可，接缝不动。详见 `README.md` 的模拟数据披露。

## 端点总览

下表只覆盖**演示主链路**用到的端点。完整业务路由共 47 条（表外还有鉴权 `/api/auth/*`、家庭成员绑定 `/api/family/*`、会话列表与历史 `/api/chat/sessions`·`/api/chat/history`、子女端计划与通知 `/api/child/*`、行程列表与实时轮询 `/api/trips`、健康指标 `/api/health/*` 等），见 `backend/app/api/routes_*.py`，挂载点见 `backend/app/main.py:68-77`。

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
| GET | `/api/trips/{id}?child_id=` | 行程详情 + 轨迹（**裁剪按 token 身份，不看 `child_id`**） |
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

`session_id` 为 null 时新建会话；带 ID 时**先 hydrate 再 append** —— 不 hydrate 就写，`seq` 会从 1 重新发号、撞掉已有行（`routes_chat.py:131`）。

### SSE 事件协议

后端有**两套事件名**，这是内核的刻意设计（`core/events.py:20`）：落库的持久类型用斜杠词表 `assistant/message`，推给界面的线格式用下划线 `agent_msg`。下表是线格式，即前端契约。

| event | data 结构 | 落库类型 | 说明 |
|---|---|---|---|
| `session` | `{session_id}` | — | 首帧，会话 ID |
| `user_msg` | `{text}` | `user/message` | 老人这句话的回显（前端已本地上屏，通常忽略） |
| `todo` | `{todos:[{content,status}], progress:{total,done,doing}}` | `todo/write` | 真进度快照，**整表覆盖**。`persist=False` |
| `agent_status` | `{agent, text}` | — | "银发导航正在处理…"。`persist=False` |
| `delta` | `{text, agent}` | — | LLM 流式增量，**打字预览**。`persist=False` |
| `agent_thought` | `{thought, agent}` | `assistant/message` | 中间规划 / 工具调用阶段的思考文本，走**链路独白**通道，不推给老人主对话框。`persist=False` |
| `agent_msg` | `{text, agent}` | `assistant/message` | **定稿**，医疗安全改写后的那一份 |
| `tool_call` | `{call_id, tool, agent, args, summary}` | `tool/call` | 工具调用 |
| `tool_result` | `{call_id, tool, ok, summary, content}` + 可选 `suspended`/`confirmation_id`/`denied` | `tool/result` | 工具结果。`summary` 里带 R4 免责声明 |
| `report` | `{agent, ok, summary, data, missing, error, scope, suspended, tools_used}` | `agent/report` | 子智能体的**结构化回报**，交付物渲染的唯一输入 |
| `card` | 见下 | `artifact/card` | 确定性交付物卡片 |
| `suspended` | `{confirmation_id, tool, summary, amount, expires_at, message}` | `confirmation/suspended` | 高危操作已挂起，等子女确认 |
| `confirmation_resolved` | `{confirmation_id, tool, ok, status}` | `confirmation/resolved` | 子女点完了。`status` = `executed`/`rejected`/`failed` |
| `guardian_alert` | `{trip_id, location, note, elder}` | `guardian/alert` | 偏航告警（由 checkpoint 上报侧推入本会话） |
| `peer_message` | `{id, from_agent, to_agent, msg_type, summary, content, data}` | — | 智能体对等通信电文，前端呈现流光心智显像。`persist=False` |
| `final` | `{text}` | `assistant/final` | 本轮结束语 |
| `error` | `{message}` | — | 出错，`message` 是写给老人听的一句话 |

四条契约要点：

1. **`agent_msg` 覆盖 `delta`，不是追加。** 医疗安全改写挂在 `agent/request` 瀑布最外层，而 `delta` 是 provider 内部逐片推的，比改写更早到前端 —— 所以预览可能是未审的原话。`test_medical_safety.py::test_the_streaming_preview_is_not_the_authoritative_text` 钉着这条。
2. **`tool_result.summary` 覆盖 `tool_call.summary`。** R4 免责声明是 `HealthDisclaimerGuard` 注进**结果** summary 的；只渲染调用摘要，那句声明就到不了老人眼前。用 `call_id` 配对（批处理是并发的，回来的顺序和调用顺序不同）。
3. **`persist=False` 的四个事件（`delta`/`agent_status`/`todo`/`agent_thought`）不单独落事件行**，所以轮询兜底链路里没有打字预览和步骤条 —— 它们是活信号，不是事实（`agent_thought` 的正文随那条 `assistant/message` 一起落库，回放时由前端 `rowToEvent` 翻回）。
4. **`confirmation_resolved` 通常到不了那条流。** 它是唯一一个发生在老人**轮次之外**的事件：挂起在轮内，子女是几分钟后在自己手机上点的，那时老人这条 SSE 早已收 `final` 关闭。后端照样广播 + 落库，界面靠回读 `GET /api/sessions/{id}/events` 补上（`chat.vue::_watchConfirmations`，见 `docs/DESIGN.md §6.6`）。`ok=False` 不足以描述结局，所以 `status` 必须单独读：`rejected` 是家人不同意，`failed` 是家人同意了但重放没成功。

### `card` 的 data 结构

```json
{
  "type": "trip_plan | medical_plan | health_card | community_card",
  "title": "张桂芳 · 南京就医出行计划书",
  "subtitle": "共 4 页，可以直接打印带着走",
  "printable": true, "generated_on": "2026-...",
  "pages": [
    { "no": 1, "title": "第一页 · 挂号信息",
      "rows": [{ "label": "医院", "value": "南京鼓楼医院", "missing": false }],
      "notes": ["..."], "complete": true }
  ],
  "body": {...}, "missing": ["appointment.hospital"], "complete": false,
  "disclaimer": "本计划书由康乐根据查询结果自动生成，仅供出行参考。医疗相关内容不构成诊断意见，请以医生面诊结论为准。",
  "footnote": "（竞赛原型：号源、路线、天气数据来自模拟接口，正式落地对接官方开放 API）"
}
```

标题不带书名号，格式是 `f"{name} · {city}就医出行计划书"`（`agents/plan_builder.py:303`），`name` 取自老人记录（种子数据是 `张桂芳`）。页标题**自带"第一页"**，前端不要再加一层序号。

`footnote` 只有四页计划书有，内容是**模拟数据披露**（`plan_builder.py:52`）。它必须渲染出来 —— 这是合规要求，不是装饰。前端 `_toCard` 把 `subtitle` / `disclaimer` / `footnote` 依次收进 `notes`。

**卡片里没有 `announce` 字段。** 后端把免责声明同时写进工具结果的 `summary` 与 `announce`，但 SSE 只推 `outcome.result["card"]` 这一个子字典（`core/session.py:385`）—— `announce` 是结果的兄弟字段，不随卡片下来。卡片的朗读文本因此由前端从卡面合成（`PlanCard.speech()`），卡面已含脚注里的声明。见 `docs/DESIGN.md` §5.1。

### `tool_result` 上的三个可选标记

`suspended` / `confirmation_id` / `denied` 互斥，代表守卫流水线的三种出口：

| 标记 | 含义 | 界面该做什么 |
|---|---|---|
| `suspended: true` + `confirmation_id` | 高危操作被拦下，已建确认任务 | 黄卡「这一步要家人点头」，等 `confirmation_resolved` 就地改状态 |
| `denied: true` | 守卫**硬拒绝**，不问家人也不执行 | 直接把 `summary` 当结论上屏。**不要**渲染成待确认卡 —— 这条路的全部意义就是不把决定权交出去 |
| 两个都没有 | 正常执行完 | 常规结果气泡 |

> **当前注册表上 `suspended` 这条路不可达**：`HIGH_RISK_TOOLS = {"pay"}`（`safety/risk_rules.py:34`），而 `pay` 工具并不存在；金额阈值那条又豁免了唯一带 `fee` 入参的活工具 `register_appointment`（`risk_rules.py:43`、`health_tools.py:691`）。所以 22 个已注册工具里没有一个能触发 `INTERCEPT` —— 黄卡与确认任务要等接入真实支付工具后才生效。

`denied` 有三个来源：`ScamContentRule` 在**任意工具的参数里**发现骗子话术（如"保健品神药根治套餐"），以及内核的两条 fail-closed 兜底 —— 确认服务未就绪（`core/tool.py:338`）、或确认凭证无效 / 参数与审批时不一致（`core/tool.py:353`）。做成待确认卡片等于替骗子把话传给了家人，所以这里没有"问一下"的出口。

### 反诈是后台守卫，不是工具

反诈已从卖点降级为**后台安全规则**：`ScamContentRule`（`safety/risk_rules.py:119`）把调用参数拼成一段文本，命中 `_SCAM_PATTERNS` 里的骗子话术（`risk_rules.py:79`）或出现非白名单链接就返回 `DENY`（`risk_rules.py:124`）。它只有 DENY / ALLOW 两态，没有 `verdict` 字段，也**没有豁免名单** —— 命中即硬拒绝，不问家人。

**没有 `check_scam` 这个工具。** 拦截结果就落在上一节的 `tool_result.denied = true` 上，前端把 `summary` 当结论上屏即可。

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
  "trips": [{"id","purpose","status","created_at"}],
  "plans": [...], "notifications": [...], "alerts": [...] }
```

**未绑定时走提前返回**（`routes_child.py:45`），响应里**没有 `elder`、也没有 `privacy`**：
```json
{ "child": {...}, "elders": [], "pending_confirmations": [],
  "medications": [], "trips": [], "plans": [], "notifications": [], "alerts": [] }
```

所以前端的兜底常量必须是"全关"（`{location_level:'off', health_level:'off', bound:false}`），**不能是 `PrivacyGrant` 的数据默认值** `city`/`summary`（`safety/privacy.py:37`） —— 否则界面会宣称一份后端明确拒绝的权限。这条踩过，见 `docs/DESIGN.md` §6.5。

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

可见范围**由 token 里的身份决定，不看 `child_id`**（`routes_guardian.py:439`）：本人 `precision: "owner"` 全量、绑定子女按档裁剪（`realtime`/`city`/`off`）、其余一律 403。`child_id` 只用来拒绝"身份与 `child_id` 不匹配"的调用（`routes_guardian.py:444`）。

带 `child_id`：`{trip, checkpoints (已按档裁剪), precision, privacy}`，`precision ∈ realtime | city | off`。`city` 档会丢掉 `lng`/`lat` 并把 `location` 粗化成城市级前缀。

## POST /api/trips/{id}/checkpoints（演示模拟位置）

```json
{ "location": "南京南站", "lng": 118.79, "lat": 31.97 }
```
返回 `{checkpoint, status: "normal"|"off_route"|"arrived", alert_sent: bool}`。

判定规则（演示，`routes_guardian.py:638-691`）：与目的地直线距离 ≤ 1000m → `arrived` 并把行程置 `completed`；距离够不着但目的地核心词出现在上报地点里，同样算 `arrived`。未到达时，命中预期途经点 → `normal`；否则算点到高德航迹走廊的最近距离，≤ 3500m → `normal`，超出 → `off_route`。没有经纬度时走防抖：定位中的占位文案算 `normal`，其余按 `off_route`。`off_route` 会向老人会话推 `guardian_alert` + 写审计。

## GET / PUT /api/privacy/{elder_id}

GET 需要 `child_id` query 参数。没细调过时返回**生效中的默认档** + `explicit: false`，让开关有初始位置。

PUT body：`{child_id, location_level, health_level}`。取值不在词表内返回 422。每次变更写 `audit_log`（`action: privacy_changed`）—— 老人日后要能问"我什么时候把这个关掉的"。

- `location_level`: `realtime` | `city` | `off`
- `health_level`: `full` | `summary` | `off`

---

## 北斗适老多智能体协同出行护航 API (/api/bds)

### POST /api/bds/escort/route
计算适老微地形低坡度零台阶路线与生活化地标指引。

- **请求体 (`ElderEscortRouteRequest`)**：
  ```json
  {
    "origin": [112.9862, 28.2045],
    "destination": [112.9945, 28.2120],
    "elder_id": "elder_123",
    "elder_profile": {
      "name": "张桂芳",
      "chronic_conditions": ["膝关节退行性病变", "轻度高血压"],
      "mobility_level": "medium",
      "max_walk_distance_m": 800
    },
    "weather_condition": "slight_rain"
  }
  ```
- **响应体 (`ElderEscortRouteResponse`)**：
  包含 `points` (CGCS2000坐标序列)、`steps` (地标生活化指引)、`summary` (总距离、预计步行时间、平缓指数、避开台阶数、沿途长椅数)、`corridor_polygon` (25米安全走廊多边形坐标)。

### GET /api/bds/telemetry/live
获取当前北斗三号亚米级高精度差分遥测数据。

- **响应格式**：
  ```json
  {
    "timestamp": "2026-10-02T18:30:00Z",
    "lat": 28.204512,
    "lng": 112.986234,
    "alt_m": 45.2,
    "speed_mps": 0.72,
    "satellites_in_use": 19,
    "hdop": 0.68,
    "fix_quality": 4,
    "nmea_raw": "$BDGGA,103000.00,2812.2707,N,11259.1740,E,4,19,0.68,45.2,M,0.0,M,,*47",
    "coordinate_system": "CGCS2000"
  }
  ```

### POST /api/bds/escort/audit-destination
目的地涉诈主动安全防御前置审核。

- **请求体**：`{"destination_name": "某保健品免费体验馆", "destination_coords": [112.98, 28.20]}`
- **响应体**：`{"passed": false, "risk_level": "high", "reason": "命中古法养生会销涉诈黑灰产高危特征库", "safe_alternatives": ["湖南烈士公园老年活动中心"]}`

### POST /api/bds/escort/emergency-sos
突发身体不适或跌倒，一键触发三甲医院急救绿色通道毫秒级重划。

- **请求体**：
  ```json
  {
    "coords": [112.9862, 28.2045],
    "elder_name": "张桂芳",
    "condition": "突发心慌胸闷"
  }
  ```
- **响应体**：毫秒级锁定就近三甲医院（中南大学湘雅医院 / 湖南省人民医院），重划平缓避障急救通道，并返回一键呼叫 120 预填文本与子女强提醒电文。

### POST /api/bds/escort/plan-book
装配生成 5 页完整版《北斗适老出行护航方案书》。
包含：第一联（慢病体能适配）、第二联（北斗微地形平缓路线）、第三联（气象防跌穿戴指引）、第四联（子女守护动态走廊）、第五联（三甲急诊就医备用联）。
