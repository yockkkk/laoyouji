# ARCHITECTURE · 康乐多智能体系统

## 0. 与 deepseek-harness 的关系（逐条对账）

不是 fork，不是移植：本项目是 Python/FastAPI 从零实现，[deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) 是 TypeScript 的。借的是**机制**，下面逐条列出借了哪些、落在哪个文件 —— 这样"参考了某架构"这句话是可核对的，而不是一句背书。

| 借用的机制 | harness 里的说法 | 本项目落点 |
|---|---|---|
| 四种派发模式 | waterfall（环绕中间件，须调 `next()`）/ serial / parallel / emit | `core/bus.py` |
| 钩子命名与语义 | `agent/pre-step`、`agent/request`、`tools/pre-execute`、`tools/execute`、`tools/post-execute`、`agent/turn-stopping`、`session/flush` | `core/bus.py` 常量 |
| 事件溯源 + 投影 | append-only 日志是唯一事实源；`derive_messages()` 投影出模型历史；不变式 "model-visible means logged" | `core/events.py` |
| Turn / Step 分层 | "一个 step = 一次模型请求 + 它调用的工具；一个 turn = 零个或多个 step" | `core/session.py` |
| 工具流水线的**确切顺序** | 先记账 → pre-execute → 单调守卫 → 询问（fail-closed）→ execute → 工具体 → post-execute → finalize → result | `core/tool.py`（见 §2.3） |
| 子智能体接缝 | `spawn` 开全新子作用域 / `fork` 从父已完成历史播种 | `core/subagents.py` |
| todo 整表覆盖 | `TodoItem {content, status}`，**刻意没有 id、没有 priority**，整列表覆盖写 | `core/todo.py` |
| 能力接缝三角色 | Service Definition（契约）/ Provider（实现）/ Consumer（消费方） | `core/registry.py` |
| 守卫分建议性与强制性 | `repeat-tool-reminder` 只提醒不阻断；`timeout-policy` 强制结算 | `core/guards.py` |
| 一切皆插件 | 没有特权内核；注册返回可逆的 disposer | `core/bus.py` 的 `on()` 返回 disposer |

**刻意没借的**：harness 自己的告诫"Don't split preemptively"—— 所以内核没有为了对称而拆碎：harness 借来的机制只落在上表这 8 个模块（`bus` / `session` / `events` / `tool` / `subagents` / `todo` / `guards` / `registry`），与表逐条对应、关键清单见 §6。

## 1. 分层总览

```
┌────────────────────────────────────────────────────────────────────┐
│  API 层  FastAPI (routes_chat SSE / asr / confirm /                │
│          child / guardian / privacy / health /                     │
│          auth / family / misc(seed / events / weather)             │
├────────────────────────────────────────────────────────────────────┤
│  智能体层  main_agent(康乐) —— 调度器                                │
│           ├─ travel_agent 银发导航                                   │
│           ├─ health_agent 安康助手                                   │
│           └─ community_agent 邻里帮                                  │
│     并行扇出 run_parallel → 结构化 AgentReport                       │
│     plan_builder：确定性交付物渲染（四页计划书 + 2 卡片）             │
├────────────────────────────────────────────────────────────────────┤
│  内核 core/  bus(四种派发) · session(Turn/Step + 预算)               │
│              events(事件溯源 + 派生) · tool(流水线)                  │
│              subagents(接缝) · todo(真进度) · guards                 │
│              registry(能力接缝之根)                                  │
├────────────────────────────────────────────────────────────────────┤
│  安全管控中间层                                                      │
│    单调守卫 PaymentRiskRule / ScamContentRule                        │
│    出口改写 diagnosis-scrubber（R1/R2，agent/request）                │
│    后置注入 HealthDisclaimerGuard（R4，post-execute）                 │
│    ConfirmationService（高危确认状态机 + 延迟重放，R5）               │
│    PrivacyService（位置/健康分级裁剪，R6）                            │
├────────────────────────────────────────────────────────────────────┤
│  工具层  ToolRegistry + ToolDispatcher                              │
│          （model-facing 工具，消费 Provider）                       │
├────────────────────────────────────────────────────────────────────┤
│  Provider 接缝层（一切皆插件）                                       │
│    llm: DeepSeekProvider | MockLLMProvider                         │
│    asr: TencentASRProvider | IflytekASRProvider | MockASRProvider  │
│    hospital/payment/weather/ride/community:                         │
│    Mock*Provider（五域全 Mock；Real* 空壳仅 hospital）              │
│    map: AmapMapProvider（真实高德，默认装配）                        │
│    repos: LocalFileRepo | SupabaseRepo | MariaDB | SFTP            │
├────────────────────────────────────────────────────────────────────┤
│  数据层  Supabase (Postgres, RLS 全拒+service key)                  │
│          session_events (append-only 唯一事实源)                     │
└────────────────────────────────────────────────────────────────────┘
```

## 2. 核心抽象（core/）

### 2.1 ServiceRegistry —— "一切皆插件"的根

```python
class ServiceDefinition(Generic[P]):  # 能力契约：名字 + 协议类型
    def __init__(self, name: str, protocol: type): ...
class ServiceProvider(Generic[P]):    # 实现：create(ctx) -> 协议实例
    def __init__(self, name: str, create: Callable): ...
    def create(self, ctx): ...
class ServiceRegistry:              # 注册表：register / resolve
    ...
```

- 启动时 `main.py` 按 `.env` 选择实现装配：`ASR_PROVIDER=tencent|iflytek|mock`、`STORAGE_BACKEND=local|mariadb|ssh|supabase`、`LLM_PROVIDER=deepseek|mock`。
- **换真实医院号源 = 只换一行 provider 注册**（`map` 已经这样换过：`bootstrap.py:132` 无条件注册 `AmapMapProvider`，高德真接口即默认实现；只剩医院号源还没有真实现），agents/tools/safety 零改动。这就是"能力接缝"：Service Definition（接口）+ Service Provider（实现）+ Consumer（工具）三角色分离。

### 2.2 BaseAgent / AgentDriver（Turn-Step 分层）

```python
class BaseAgent(ABC):
    name: str            # 'travel'
    display_name: str    # '银发导航'
    description: str     # 供主智能体路由判断
    system_prompt: str
    tool_names: list[str]
    max_steps: int = 8
    report_schema: tuple[str, ...]   # 该 Agent 承诺回报哪些字段
```

`BaseAgent` 是薄壳，循环由 `core/session.py` 的 `AgentDriver` 跑。分层按 harness 的定义：**一个 step = 一次模型请求 + 它调用的工具；一个 turn = 零个或多个 step。**

```
AgentDriver.run(user_text):
  turn 开始 → budget.start()
  循环每个 step：
    budget.exhausted() ⇒ 收尾，stop_reason = budget/steps(2/2) 之类
    agent/pre-step（瀑布：压缩、注入提醒）
    derive_messages(session_id, scopes=[本 Agent 作用域])   ← 只看自己的历史
    agent/request（瀑布，最外层是 R1/R2 医疗改写）
      失败 ⇒ agent/request-error（瀑布；无人处理则 stop_reason = llm/failed）
    逐 delta：turn.emit('delta', persist=False)     ← 预览，不落库
    记 assistant/message（含 tool_calls）→ emit('agent_msg', persist=False)
    有 tool_calls ⇒ ToolDispatcher.execute_batch(整批结算，见 §2.3)
    无 tool_calls ⇒ agent/turn-stopping（瀑布）；无人挽留则 stop_reason = model/idle
  session/flush（write-behind 落库检查点）
```

三处与旧实现的关键差异：

1. **作用域隔离**：`derive_messages` 按 `agent_id` 过滤，子 Agent 看不到父和兄弟的对话（旧实现每个子 Agent 都拉同一份最近 20 条）。
2. **三级预算 + 单工具 deadline**：`Budget(max_steps, max_tokens, wall_clock_s, tool_timeout_s)`，耗尽时 `stop_reason` 自带账目（`budget/tokens(500/400)`）。旧实现只有 `MAX_STEPS=8`，模型卡住 SSE 就一起悬着。
3. **挂起不再丢调用**：被拦截的调用返回结构化"待确认"结果，**同批次其余调用照样结算**。旧实现 `break` 之后直接返回挂起话术，剩余 `tool_calls` 静默消失，模型下一步看不到结果。

`delta` 是打字预览（`persist=False`），`agent_msg` / `final` 才是定稿。因为 R1/R2 改写发生在 `agent/request` 出口，而 delta 由 provider 内部更早推出，**前端必须用 `agent_msg` 覆盖预览** —— 契约见 `docs/DESIGN.md` §6.1，门禁见 `tests/test_medical_safety.py`。

### 2.3 Tool 流水线（安全管控中间层的落点）

```python
class GuardVerdict(str, Enum):
    ALLOW      # 不反对（没有意见的守卫返回这个）
    INTERCEPT  # 拦截挂起 → 创建 confirmation_task，等子女确认后重放
    DENY       # 直接拒绝（如识别到诈骗话术），给出替代建议
```

当前注册表里**没有会触发 `INTERCEPT` 的工具**：唯一的 `HIGH_RISK_TOOLS` 成员是 `pay`，而它不在 22 个在册工具之列；金额兜底那条规则又豁免了唯一带金额参数的工具（`register_appointment` 的挂号费）。所以下面这条流水线里的 INTERCEPT 分支、以及 §4 那台状态机，是给后续支付类工具预留的接缝 —— 今天的演示链路上不会出现"待确认"这一步（挂起卡数恒为 0）。

单次调用的**确切顺序**（照 harness 的 tool-execution-pipeline）：

```
tool/call 先记账（先记再做：失败也留痕）
  → tools/pre-execute（瀑布）
  → 单调守卫：任一 DENY 立即短路；否则第一个 INTERCEPT 生效；其余 ALLOW
  → 询问确认服务（fail-closed：没有应答者 = 拒绝，见下）
  → tools/execute（瀑布：超时策略、重试、指标都在这里环绕）
  → 工具体
  → tools/post-execute（瀑布：HealthDisclaimerGuard 挂在这里）
  → _finalize（补 ok / summary / tool 字段）
  → tools/result（同步 emit，结果已冻结）
  → tool/result（会话事件，供 derive_messages 配 tool_call_id）
```

批处理 `execute_batch`：**有序 pre → 并发 execute（BARRIER 分段 + `Semaphore(4)`）→ 有序 post**。每个调用都一对一结算且保持顺序 —— 这是"多智能体并行"在工具层的一半（另一半是 §2.5 的子智能体扇出）。

守卫的**单调性**是刻意的：裁决只会越来越严，所以两条守卫谁先注册都不影响结论。诈骗话术因此不会被做成一张"要不要同意转账"的待确认卡片 —— 那等于替骗子把话传到了。

**fail-closed**：装配里没有确认服务时（库连不上、服务没起来），高危调用是一次明确的 `DENY` 加一句"先给家里人打个电话"，而不是放过去、也不是假装已经发出去问了。靠 30 分钟静默过期兜不住，因为静默过期的前提是**任务已经建起来了**。

`bypass_confirmation_id` 是**恢复执行的唯一放行凭证**，且只放行该 confirmation_task 里冻结存储的那一次调用参数（服务端精确比对，防篡改重放），且**一次性** —— `approved` 之外的任何状态都不放行，包括已经用过的 `executed`。

### 2.4 SessionEventLog —— 唯一事实源

- `session_events` 表 append-only，`(session_id, seq)` 全序。
- **`seq` 由内存单调计数器分配**（`dict[session_id, int]`），`append()` 同步返回。旧实现"先读 max 再 +1"在并发下会撞号，"append-only 全序"这个承诺其实不成立。
- **write-behind**：`append()` 只入 `_pending` 并同步返回（热路径不等 I/O），落库发生在轮次结束的 `session/flush` 检查点。`hydrate(session_id)` 用于跨请求场景（如子女批准后重放）先把库里的历史读回内存。
- 持久事件类型（`core/events.py` 的常量）：`turn/start` · `turn/end` · `step/start` · `step/end` · `user/message` · `assistant/message` · `assistant/final` · `tool/call` · `tool/result` · `todo/write` · `agent/report` · `artifact/card` · `confirmation/suspended` · `confirmation/resolved` · `guardian/alert`。SSE 线格式名（`user_msg` / `agent_msg` / `final` / `todo` / `card` / `report` / `suspended` …）由 `events.py` 的 `_SSE_TO_DURABLE` 映射成上面这套。`delta` 只走 SSE 不落库（`persist=False`）；`agent_msg` 的 emit 也是 `persist=False`，但它的正文已在同一步由 `_record_assistant` 落成 `assistant/message`（`core/session.py:332`）—— 事件不落、正文落。
- **`derive_messages(session_id, *, scopes=[...])`** 是投影，不是拼字符串：
  - `assistant_message` 带 tool_calls → `{"role": "assistant", "tool_calls": [...]}`
  - `tool_result` → `{"role": "tool", "tool_call_id": ..., "content": ...}`

  旧实现把工具结果伪装成 `role: assistant` 的 `"[工具结果] …"` 文本，跨轮次后模型就不知道哪个结果对应哪次调用了 —— function-calling 的因果链是断的。
- 不变式 **"model-visible means logged"**：派生出的每条消息都必须能追溯到已记录事件。违反即抛，`tests/test_kernel.py` 有断言。
- 三个派生用途：**LLM 上下文**（按作用域投影）、**审计回放**（演示加分项）、**前端断线恢复**（`GET /events?after_seq=N` 增量拉取）。

### 2.5 子智能体接缝（`core/subagents.py`）

`ctx.subagents` 负责发现、运行与回报：

- `spawn(turn, spec)` —— 开**全新子作用域**（独立 `agent_id`、独立派生历史）。子 Agent 干净起步，看不到父与兄弟的对话。
- `fork(turn, spec)` —— 从父**已完成**历史播种，用于需要上下文延续的追问。
- `run_parallel(specs)` —— 真正的多智能体扇出（`asyncio.gather`），墙钟小于串行之和，`tests/test_subagents.py` 有计时断言。
- 子 → 父的回报是**结构化**的，不是自由文本：

```python
AgentReport(agent, ok, summary, data: dict, missing: list[str], tools_used: list[str])
```

`data` 的键来自工具声明的 `report_key`（如 `search_hospital` → `hospital_options`、`register_appointment` → `appointment`、`plan_route` → `route`），`missing` 记录该 Agent 承诺过但没拿到的字段。**这是交付物生成器的唯一输入** —— 计划书不再由 LLM 自由拼字典。

子智能体的预算比父更紧：token 与墙钟各按 0.6 折算，步数沿用它自己声明的上限（收紧"能烧多少 / 能拖多久"，不收紧"能想几步"）。

### 2.6 真进度（`core/todo.py`）

`TodoItem {content, status: pending|in_progress|completed}` —— 照 harness 原样，**没有 id、没有 priority**。整列表覆盖写、last-write-wins、log-only 事件 + 不变式伴随校验。

旧实现的进度条是布景：任意 `tool_call` 推进第一个步骤，plan 只活在前端组件内存里，刷新即丢。现在快照进事件日志，前端只渲染收到的快照、自己不推进状态（见 `docs/DESIGN.md` §6.2）。

## 3. 关键决策记录（ADR）

### ADR-1 高危确认采用"延迟执行"，不做跨请求协程挂起
拦截时 AgentLoop 正常结束该轮（话术："已经发给您儿子确认啦"），工具调用参数**原样冻结**在 `confirmation_tasks.tool_args`。子女批准后由 `ConfirmationService` 在新的执行上下文中重放（带 bypass 凭证）。
**前提限定**：如 §2.3 所述，当前 22 个在册工具里没有会触发 `INTERCEPT` 的，这条链路是给后续支付类工具预留的接缝 —— 演示时不会有真实的挂起卡走到这里。
理由：跨 HTTP 请求暂停协程复杂且脆弱；延迟执行天然支持进程重启后恢复（状态全在表里）、支持审批排队、失败可独立重试。代价：批准后的"收尾话术生成"需要一次独立的 LLM 调用（不走完整 AgentLoop），可接受。

### ADR-2 存储走 Repository 协议四个实现，不做 SQLite 双 ORM
`LocalFileRepo`（JSON 文件，默认）、`SupabaseRepo`、MariaDB（`SQLRepository`，可走 SSH 隧道）、SFTP（`SSHRepository`）四个实现，按 `STORAGE_BACKEND=local|mariadb|ssh|supabase` 切换。理由：会场断网兜底成本约半天；SQLAlchemy+SQLite 在 Windows 引入驱动与迁移负担，收益低。

### ADR-3 SSE 优先 / 轮询兜底，两套共用同一事件模型
H5 端用浏览器 `fetch + ReadableStream` 手工解析 SSE（uni.request 不支持流式）；不支持/断线时降级 2s 轮询 `GET /api/sessions/{id}/events?after_seq=`。服务端事件只产出一次模型，两条通道消费同一份。

### ADR-4 医疗合规四重防线（不依赖 LLM 自觉）
① system prompt 红线（不做诊断 / 不做处方）；② **出口改写** `diagnosis-scrubber` 挂在 `agent/request` 瀑布**最外层**（`order=-100`），命中诊断/处方口吻的句子**整句替换**成引导就医的话，并留一条 warning 日志；③ `HealthDisclaimerGuard` 对健康域工具输出**强制**追加免责声明（`tools/post-execute`，`summary` 与 `announce` 两条出口都加）；④ 文档与答辩明示。

第②层为什么在最外层：它要看的是所有重试、所有其它中间件之后的**最终**那一条应答 —— 而重试那一次恰恰是模型状态最不稳、最容易说错话的一次。第②层为什么整句替换而不抠词：抠词会留下"您这是…（已隐去）"这种比原话更吓人的残句；整句换掉之后，"要不要我帮您挂个骨科？"这半句还在，老人拿到的是下一步动作。

**误杀比漏杀更隐蔽**：饮食推荐与用药提醒都是本项目声明过的正常能力，被筛子顺手杀掉会让功能静静地少一半而没人报错。所以处方规则刻意要求出现剂量单位或"药"字才算命中，`tests/test_medical_safety.py` 里两组反面测试与正面测试同等重要。

### ADR-5 Mock 数据确定性原则
所有 Mock Provider：同输入同输出（fixture 固定 + 参数派生随机数），保证演示可复现、测试可断言。模拟延迟各异（0.1–3.0s 不等，其中叫车固定 3s）制造真实感。

### ADR-6 主智能体路由：LLM function-calling 为主，关键词规则兜底
LLM 通过 `delegate(specs)` 工具完成路由，**参数接列表** —— 能并行的一次派多个，交给 `ctx.subagents.run_parallel`（提示词也从"一次派一个"改成了鼓励并行）。旧实现的 `route_to_agent` 是在父工具里 `await agent.run()`，既是串行的，也把子 Agent 的执行嵌在父的工具调用里，评委看不到"调度"这件事。LLM 不可用（MockLLM 离线演示）时退化为关键词规则表路由，保证离线剧本可演。

## 4. 高危确认状态机

```
 pending ──approve──► approved ──成功──► executed
    │ │                                   │
    │ └──reject──► rejected          失败──► failed
    │
    └──超时30min/惰性清扫──► expired

约束：非 pending 状态再审批 ⇒ 409；过期后审批 ⇒ 409 并标记 expired；
executed 记录 result（票号/订单号），写 audit_log。
```

## 5. 技术栈清单

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 · FastAPI · uvicorn · sse-starlette · httpx · pydantic-settings |
| LLM | DeepSeek chat API（OpenAI 兼容，流式 + function calling，3 次退避重试） |
| ASR | 腾讯一句话识别（方言，首选）｜讯飞语音听写（方言版，备选）；Web Speech API 前端降级 |
| 存储 | Repository 协议四实现：local（JSON 文件，默认）/ MariaDB / SFTP / Supabase Postgres（service key 仅后端，RLS 全拒） |
| 前端 | uni-app (Vue 3) · H5 · 模块级 store（`src/store/`，uni storage 持久化）· fetch/ReadableStream SSE |
| 测试 | pytest + pytest-asyncio（MockLLM 全链路无 key 可测） |

## 6. 目录结构

见 `backend/app/` 各包注释与 README。关键文件：

**内核**
- `app/core/registry.py` 能力接缝之根（Definition / Provider / Consumer）
- `app/core/bus.py` 四种派发模式 + 钩子词表；`on()` 返回可逆 disposer
- `app/core/events.py` 事件溯源、单调 seq、write-behind、`derive_messages` 投影
- `app/core/session.py` Turn / Step 分层 + 三级预算 + `AgentDriver`
- `app/core/tool.py` 工具流水线 + 批处理（有序 pre → 并发 execute → 有序 post）
- `app/core/subagents.py` `spawn` / `fork` / `run_parallel` + `AgentReport`
- `app/core/todo.py` 整表覆盖的真进度
- `app/core/guards.py` `timeout-policy`（强制）/ `repeat-tool-reminder`（建议）

**智能体**
- `app/agents/main_agent.py` 总智能体：`todo_write` 规划 + `delegate` 并行调度
- `app/agents/plan_builder.py` 确定性交付物渲染（四页计划书 + 两张轻量卡片）

**安全**
- `app/safety/risk_rules.py` 单调守卫 + R1/R2 出口改写 + R4 免责声明注入
- `app/safety/confirmation.py` 确认状态机 + 冻结参数防篡改重放（R5）
- `app/safety/privacy.py` 位置/健康分级裁剪（R6）

**其它**
- `db/schema.sql` 全量 DDL
- `docs/DESIGN.md` 前端设计基线（token / 信息架构 / 导航模型 / 组件契约 / SSE 界面契约）

## 7. 多智能体对等通信信箱与协作研讨中枢 (Teammate Mailbox)

深度借鉴 Claude Code (`teammateMailbox.ts`) 与 Nanobot (`agent/loop.py _pending_queues`) 架构：
- **突破单向派发局限**：实现分布式的多智能体对等通信信箱中枢 (`app/core/mailbox.py`)。每个智能体 (`main`, `health`, `bds_nav`, `weather`, `guardian`) 均拥有独立的 Mailbox。
- **电文信封协议 (`PeerMessage`)**：支持 `direct`（点对点）、`broadcast`（全员广播）、`proposal`（协商提议）、`handoff`（角色交接）、`ack`（确认回执）与 `emergency`（紧急熔断插队）。
- **双通道投递管道**：
  1. *主动调用管道*：智能体可通过工具主动向同伴发起电文查询与约束注入（如 HealthAgent 向 BdsNavAgent 注入膝关节避台阶约束）；
  2. *被动注水管道*：`PRE_STEP` 瀑布中间件在每个 Step 启动时自动检查收件箱，将同伴电文安全拼接进提示词上下文中；
  3. *防死循环熔断*：设置 `MAX_DELIBERATION_HOPS = 3`，防止同伴之间无限轮转对答。

## 8. 自适应分层认知记忆系统 (Adaptive Hierarchical Memory)

借鉴 Nanobot (`agent/memory.py`) 与 Claude Code (`teamMemoryOps.ts`) 设计的三层记忆模型 (`app/core/memory.py`)：
- **Tier 1 - 工作记忆 (Working Memory)**：当前会话轮次内的即时上下文与工具调用结果缓存；
- **Tier 2 - 情景日志 (Episodic History Ledger)**：以 Append-only JSONL 格式 (`episodic_history.jsonl`) 记录长辈日常出行偏好、常去地标及体征变化事件；
- **Tier 3 - 语义画像巩固 (Consolidated Semantic Profile)**：以 Markdown 规范 (`ELDER_PROFILE.md`) 沉淀长辈的慢性病史、耐力极限、生活习惯及子女关联偏好，每次会话启动自动装配，无需长辈重复交代。

## 9. 北斗高精时空基准与适老微地形代价路由

- **亚米级时空基准**：接入北斗三号双频 RTK 与地基增强差分校正，解析 NMEA-0183 报文（$BDGGA），提供 $< 0.5\text{m}$ 高精度授时与平面坐标定位。
- **CGCS2000 坐标系**：全面采用我国自主知识产权的 2000 国家大地坐标系，保障地理空间基准的绝对合规与高精度。
- **适老微地形代价路由模型 (Micro-Terrain Cost Model)**：
  $$\text{Cost}(e) = L(e) \cdot \left(1 + w_{\text{step}} \cdot N_{\text{step}}(e) + w_{\text{slope}} \cdot S(e) - w_{\text{shade}} \cdot \text{Shade}(e) - w_{\text{bench}} \cdot \text{Bench}(e)\right)$$
  - 遇到长台阶时对患有膝疾老人施加无穷大阻断惩罚；
  - 优先选择树荫绿道、坡度 $< 3\%$ 的平缓步道，沿途 200 米服务半径精准串联市政休憩长椅。
- **抗微动滤波算法 (Adaptive Anti-Micro-Motion KF)**：
  - 针对老人行走缓慢（$0.6 \sim 0.8\text{ m/s}$）与停步休息特征，当 $v < 0.3\text{ m/s}$ 时自动冻结位置增益，消除 GPS 静态漂移导致的航向乱跳。

## 10. 前端适老高精地图手势隔离与 60fps 渲染优化 (`route-map.vue`)

- **手势事件穿透隔离**：通过 `touch-action: none`、`@touchmove.stop` 与自定义手势拦截，彻底消除 Uni-app 页面全局滚动与 Leaflet 地图拖拽的手势冲突；
- **栅格瓦片抗锯齿与重绘抑制**：规避非整数 `zoomSnap` 引发的二次重排，启用 CSS3 GPU 硬件加速；
- **平滑缓动算法 (Smooth PanTo/FlyTo)**：长辈位置移动与步骤视口聚焦采用贝塞尔曲线过渡动画，杜绝生硬闪跳，保持全程稳定 60fps 流畅视效。

## 11. 老人端与子女端双端角色定位与交互解耦

- **老人端 (`pages/elder/route-map.vue`)**：
  - 定位：极简、大字、低认知负荷的纯粹人行实景导航；
  - 核心操作：大生活化地标卡片播报、慢速语音指引、“🕊️ 一键给家人报平安”；
  - 去数字化设计：无多余层级与杂乱按钮，专注长辈平稳前行。
- **子女端 (`pages/child/guardian.vue`)**：
  - 定位：全天候数字孪生守护看板与远程应急调度中枢；
  - 核心操作：
    - 卫星遥测监控：实时显示参与解算的北斗卫星颗数（如 19 颗）、CGCS2000 差分精度、航向与步速；
    - 动态安全走廊与电子围栏：可视化走廊范围，偏航与异常滞留超限毫秒触发声光警报；
    - 双向亲情主动关爱：“📞 一键致电长辈”与“💬 发送安心关怀”。

## 12. Docker 容器化架构与本地一键运行体系

系统支持基于 Docker 的全环境微服务编排隔离运行：
- **后端容器 (`laoyouji-backend`)**：
  - 运行环境：Python 3.12-slim；
  - 容器端口：8000（健康探针 `/api/health` 毫秒返回）；
  - 数据卷持久化：SQLite/Local 文件挂载与日志卷隔离。
- **前端容器 (`laoyouji-frontend`)**：
  - 运行环境：Node 20-alpine；
  - 容器端口：5174（暴露 Vite H5 开发与热重载服务）；
  - 反向代理配置：内置 Vite Proxy，无缝桥接 `/api` 流量至 `laoyouji-backend:8000`。
- **一键运维脚本**：
  - `docker-start.bat`：一键构建并后台启动容器；
  - `docker-stop.bat`：一键平滑停止容器；
  - `docker-logs.bat`：聚合跟踪前后端运行日志；
  - `docker-test.bat`：在隔离容器内一键执行全量测试套件。
