# QA_ANSWERS · 答辩预案

> 对齐竞赛五维评分，逐条给出得分点与证据；含模拟数据披露与合规红线说明。
>
> **规矩：这份稿子只写能当场指出来的东西。** 每个数字后面都有一个文件名或一条命令，
> 说不出来的就删掉。评委追问细节时，最贵的失分不是"没做"，是"说了但一看没有"。

## 一、五维得分点

### ① 任务理解与自主规划
- 模糊生活指令（"我想在南京就近看腿疼的老毛病"）→ 总智能体自主拆成四步：
  **选本地医院挂骨科专家号 / 查这两天天气 / 规划从家怎么去医院 / 出一份就医出行计划书**，
  前端**步骤条**三态推进（`pending / in_progress / completed`）。
- 进度是**后端事实**，不是前端猜的：`todo_write` 工具每一波**整表覆盖写**（last-write-wins，
  照抄 harness 的 todo 语义：无 id、无 priority），落成 `todo/write` 事件推到前端。
  刷新页面不丢，因为它在事件日志里。
- 架构：MainAgent（编排）+ 三个子智能体（域内执行），DeepSeek function-calling 驱动；
  `LLM_PROVIDER=mock` 时走确定性离线剧本，LLM 波动或断网都不中断演示。
- 证据：SSE 里的 `todo` 事件 + `GET /api/sessions/{id}/events` 全程留痕（append-only）。
  > 口径注意：SSE 线格式是 `todo`，持久化类型是 `todo/write` ——
  > 两套词表互为反函数（`core/events.py:_SSE_TO_DURABLE`），被追问时说得清是设计不是笔误。

### ② 工具调用与大模型结合
- **22 个工具**（`GET /api/health` 的 `tools` 数组可当场数）：
  查医院/挂号/叫车/导航（公交·地铁·步行）/用药提醒与打卡/报告大白话解读/分诊/
  饮食建议/社区活动/散步环线/家常菜谱/一键联系家人/天气/大白话改写/待办整表写入/
  派发子智能体/生成交付物…
- 统一工具流水线（`core/tool.py`，顺序照抄 harness 的 tool-execution-pipeline）：
  `tool/call 记账 → pre-execute → 守卫（allow/deny/intercept）→ 审批（fail-closed）
  → execute（超时/重试/指标环绕）→ 工具体 → post-execute（免责声明注入）→ tool/result`。
  **批处理是"有序 pre → 并发 execute → 有序 post"**，所以同一批工具真并发。
- 所有外部能力经 **Provider 接缝**调用（Mock 实现 + Real 空壳），换真实 API 不动业务代码。
- 流式体验：SSE `delta` 逐字输出 + 工具气泡，"大脑在思考、手脚在办事"肉眼可见。

### ③ 结果交付可验收
- 旗舰交付物：**`张桂芳 · 南京就医出行计划书`**，四页可打印：
  ① 挂号信息 ② 怎么去医院（本地公交/步行/打车路线）③ 随身清单（出门前一样一样对）④ 南京天气与穿衣
- **没有"费用明细"这一页**，这是有意的：钱的事都在家人手机上确认，不印在老人这张纸上。
- 关键机制：交付物由 **`agents/plan_builder.py` 确定性渲染**，输入是子智能体的结构化
  `AgentReport`，**模型不参与拼装**。每一格都能追到某个工具结果里的某个键；取不到就
  显式渲染"待补"并回填 `missing`，**绝不编造**。
  三份交付物（四页计划书 + 两张轻量卡片）共用同一套 report → 渲染管线，只换模板。
- 每步落库可查：trips / medication_logs / health_records / notifications / audit_log；
  `GET /api/sessions/{id}/events` 可回放整个决策过程（append-only 唯一事实源）。
  （`confirmation_tasks` 与 `orders` 特意不在这一列：前者只在挂起链路真被调用时才写，
  而旗舰链路上它恒为空；后者随社区付费服务整条砍掉，已停用 —— 列进来等于把"查得到"
  说成了"用得上"。）
- 证据：`tests/test_plan_builder.py`（24 个）钉的就是"同输入同输出"和"缺字段不编造"。

### ④ 综合创新（安全管控中间层）
- **高危操作拦截 + 冻结参数重放**（ADR-1）：拦下时把**那一次调用的参数原样冻住**创建
  确认任务，子女批准后凭 `bypass_confirmation_id` 精确比对后重放 —— 改一个字（哪怕
  只改金额）就拒绝执行。"AI 有能力，但没有越权花钱的权力。"
  > **边界（与 README / `docs/API.md` / `docs/ARCHITECTURE.md` 同一口径）**：当前注册表上
  > 这条链路**不可达** —— `HIGH_RISK_TOOLS` 的唯一成员 `pay` 并未注册成工具，金额兜底那条
  > 又豁免了唯一带 `fee` 入参的活工具 `register_appointment`，所以 22 个在册工具里没有一个
  > 能触发 `INTERCEPT`，旗舰链路的挂起卡数恒为 0。它是**已落地、并有单测覆盖的中间层机制**
  > （`tests/test_confirmation.py` 自己现注册一个假 `pay` 来测），**不是今天可演示的产品能力** ——
  > 预留给后续接入真实支付类工具。台上先给这句，再讲机制。
- 拦截口径（`safety/risk_rules.py`）：高危工具集 `{pay}`（`HIGH_RISK_TOOLS`）
  **与金额无关，一律拦**；挂号 `register_appointment` 显式不在集内（`NON_PAYMENT_TOOLS`），
  立即办好、后置知会子女；不在集里的工具，参数金额 **≥ 50 元**也拦。
  金额由守卫从参数里算（单价 × 数量），**不是模型写的一个数** —— 家人按"同意"，
  按的是被算出来的这一笔。
- **三种结局分开表达**：同意办成了 / 家人不同意 / 家人同意了但没办成。
  合成一句"没成功"，等于替家人表了个他没表过的态。
- **行程守护**：命中预期途经点、或落在规划走廊 3.5 公里以内算正常；到目的地 1 公里内（或报出医院名）算到达并结束行程；其余判偏航 → 子女端告警 + 审计。
- **方言 ASR + 大白话引擎**是共享公共服务（`shared/plain_language.py` + `providers/asr/`），
  不是某个页面的功能，所有子 Agent 共用。
- **隐私分级**：位置三档（实时/城市级/关闭）、健康三档（完整/概要/关闭），老人本人掌控。

### ⑤ 市场可行性
- 客群：中国 3 亿 60+ 人口，独居/空巢比例高；付费者是子女（孝心经济），使用者是老人（免费好用）。
- 商业模式：①**子女端年费订阅 199 元/年**（守护 + 确认服务，后者见 §一④ 边界）——"给父母请了个 AI 秘书"
  ②社区养老服务分佣（社区活动 `push_activities` / 散步环线 `suggest_walk` 等社区资源导流）
  ③保险/体检机构合作导流（合规前提下）。
  > 定价口径只留这一个。这份稿子原来写"9.9~29 元/月"、PRD 写"199 元/年"，
  > 两处对不上；被同时问到就是硬伤，所以统一到 PRD 的 199 元/年。
- 获客：社区居委会/养老驿站地推 + 子女端微信家庭群裂变。
- 竞品差异：市面上是"工具 App"，我们是"会办事且守规矩的智能体"——安全确认流是家庭信任的钥匙。

## 二、模拟数据披露（答辩必讲，主动说）

> "竞赛原型中，挂号、叫车、支付、社区活动、天气等外部业务接口均为**模拟数据**
> （个人开发者无法获取官方正式接口）；地图/路线走高德开放平台，未配 key 或断网时
> 回落内置演示库。所有 Mock 均为确定性实现（同输入同输出，可复现可测试），
> 并通过 **Provider 接缝**隔离——每个 Provider 都留有 Real 空壳，正式落地对接官方开放 API 时
> 只替换实现类，业务代码零改动。这一点已在 README、演示剧本、以及计划书自己的脚注里明确披露。"

- 模拟清单（5 个业务域）：hospital / weather / ride / community / payment
- **地图/路线是例外**：`map` 走真实高德开放平台 Web 服务 API（`AmapMapProvider`，
  `bootstrap.py:132`），未配 key 或断网时回落 `routes.json` 的内置演示线 ——
  与 README、`docs/API.md` 把它标为"例外"的写法一致。
- 另有 4 个非业务接缝：llm / asr / plain_language / mail（共 10 个 `ServiceDefinition`，见 `bootstrap.py:76-82`）
- 确定性保证：编号由 md5(参数) 派生，演示可复现；pytest 断言依赖此性质
  （`tests/test_mock_providers.py`，18 个）。
- **披露落在三处，缺一处都算没披露**：README、`docs/DEMO_SCRIPT.md` 收尾台词、
  四页计划书最后一行脚注（`plan_builder.py:52` 的 `MOCK_NOTE`，经 `chat.vue` / `PlanCard` 渲染）。
  > 口径提醒：这行脚注正文是「号源、**路线**、天气数据来自模拟接口」——「路线」写宽了，
  > 路线走的是真高德（见上一条）。被指着打印纸追问时，按「号源、天气」答，
  > 别顺着脚注把路线也说成模拟。

## 三、合规红线（主动规避）

| 红线 | 我们的边界 |
|---|---|
| R1 不做 AI 医疗诊断 | 只做辅助解读/提醒/挂号引导。报告解读输出**由代码强制追加**：「（以上是把报告上的话换成大白话，属于辅助解读，不是诊断结论。身体的事请听医生的，遵医嘱。）」；其余健康域工具用通用版（不提"报告"）。`HealthDisclaimerGuard` 是后置过滤器，**不靠模型自觉**，绕不过去 |
| R2 不做处方建议 | 用药提醒只登记"医生已开的药"；饮食建议只说家常搭配，不推荐药物或保健品 |
| R3 不扣真实资金 | 支付全 Mock；唯一的高危工具是 `pay`，**当前注册表上没有工具能触发它**（见 §一④ 边界，挂起卡数恒为 0）；挂号不在审批线上，立即办好并知会子女 |
| R4 健康输出必带免责声明 | 见 R1 那一栏。两版措辞都含"辅助""不是诊断结论""遵医嘱"三要素；去重判据是"遵医嘱"，所以换措辞不会叠出两遍 |
| R5 不做无人监护的自动执行 | 高危工具集（`HIGH_RISK_TOOLS = {"pay"}`）拦截等家人点头 —— **但当前注册表上没有工具能触发它**（`pay` 未注册，见 §一④ 边界）；挂号走"知会不审批"，不进这条线 |
| R6 隐私数据不越级 | 前端不直连数据库；后端持 service key；表全部开 RLS 默认全拒；改授权只认老人本人（越权返回 403 并留审计）|

**反诈这一条要讲准，别讲大**（评委最容易在这里追出破绽）：

- 它现在是**后台安全规则**，不是产品卖点：守卫 `ScamContentRule` 对工具参数做一次词表
  匹配（`risk_rules.py:_SCAM_PATTERNS`），命中就 DENY，**不产判定档位、不写老人档案**。
- **DENY 硬拦截**：骗子话术出现在**下单参数**里时（比如"保健品神药根治套餐"），
  守卫直接拒绝执行，**连家人都不问** —— 因为"要不要同意这笔转账"本身就是骗局的下一步，
  做成一张待确认卡片等于替骗子把话传到了。
  证据：`tests/test_confirmation.py::test_a_scam_is_refused_outright_instead_of_asked_about`。
- 不代替公安机关，只做识别与提醒。

## 四、常见追问速答

**Q: 为什么不用现成 Agent 框架（LangChain 等）？**
A: 参考了 deepseek-harness 的具体机制，但从零自研。**借的是七样东西，能逐条指**：
四种派发模式（waterfall/serial/parallel/emit）· 事件溯源 + `derive_messages` 投影 ·
Turn/Step 分层 · 工具流水线顺序 · 子智能体接缝（spawn/fork）· todo 整表覆盖 ·
能力接缝三角色（定义/注册/解析）。
自研的理由：竞赛要的是"看得懂、讲得清、改得动"的架构 —— 后端 `app/` + 前端 `src/`
现在的规模用 `git ls-files | xargs wc -l` 当场就能报，我不背一个记不住的数字上台；
而安全管控中间层（守卫瀑布 + 冻结参数延迟执行）是框架给不了的定制核心。

**Q: 你说"真多智能体"，凭什么不是一个模型自己演？**
A: 三条硬证据，都能当场指：
① 每个子智能体只看到**自己作用域**的派生历史（`derive_messages(session_id, scopes=self.scopes)`，
   `core/session.py:294`；事件上的 `agent_id` 只是作用域标签，不是 `derive_messages` 的形参），
   不是共读一份会话历史 —— 上下文是真隔离的；
② 同一批派发**并发执行**，`tests/test_subagents.py` 断言墙钟小于串行之和；
③ 子→父回报是结构化 `AgentReport(agent, ok, summary, data, missing)`，不是自由文本，
   而且它是交付物渲染的**唯一输入** —— 演示界面上那两条「🏥 安康助手已经查好了」
  「🧭 银发导航已经查好了」就是这两个 report 事件。

**Q: 大模型幻觉怎么办（说成能诊断）？**
A: 三重防御：系统提示词红线 + 输出**后置强制注入**免责声明（代码层，不是提示词层）+
答辩明示边界。且**高风险动作不由 LLM 决定** —— 由确定性规则（高危工具集 + 金额阈值）拦截。
交付物同理：四页计划书由渲染器拼，模型碰不到那些格子。

**Q: 子女不在线怎么办？**
A: （先给边界，别等评委追问：这条链路当前在注册表上**不可达** —— 没有工具能触发
`INTERCEPT`，见 §一④。下面答的是它接上真实支付类工具后的**既定行为**。）
确认任务 30 分钟过期（`config.py:58` 的 `confirm_timeout_min`），温和话术告知老人"晚点再办"，不制造焦虑；
**没有应答者时 fail-closed 直接 deny**（`core/tool.py:338`：确认服务未就绪即 DENY，
不是放行），不靠静默过期蒙过去。
紧急场景**不拦**：`hail_ride`（叫车回家）参数里只有 origin / destination、不含任何金额字段，
也不在高危工具集里，走的是直通（`travel_tools.py` 顶部注释写死了这条：不涉及支付，故不进高危、不冻结）。

**Q: 老人不会用智能手机？**
A: 语音优先（方言 ASR）+ 主按钮 ≥80px + 正文 ≥20px + 麦克风 120px + 高对比暖色；
不认字也能全程语音完成。设计口径成文在 `docs/DESIGN.md`，token 落在 `uni.scss`，
页面只准引用变量。

**Q: 双端如何同步？批准之后老人怎么知道？**
A: （同一条边界先给：当前注册表上没有工具能触发 `INTERCEPT`，挂起卡数恒为 0，见 §一④ ——
下面答的是它接上真实支付类工具后的**既定行为**。）
老人端 SSE 长连接实时推送；子女端 5s 轮询（可靠简单）。
**批准发生在老人那一轮结束之后**，那时流早关了，所以走的是：后端把结果落进事件日志 →
老人端回读日志，把原来那张黄卡**就地改成绿卡**（`chat.vue::_watchConfirmations`，2.5s 轮询，
卡片全部落定就自动停）。不是新推一张卡 —— 老人要看到的是"我刚才那件事成了"，
不是又收到一条不知从哪来的消息。

**Q: 如果 DeepSeek 挂了 / 会场断网？**
A: Provider 内置退避重试；`LLM_PROVIDER=mock` + `STORAGE_BACKEND=local` 一键全离线，
旗舰场景和反诈守卫都走得通，演示台词不变。
SSE 断了 `chatStream` 自动降级为 2s 轮询事件日志（最多 2 分钟，读到 `final` 收工）——
但轮询链路里丢了**打字预览**（`delta` 是 `persist=False` 的活信号，不落库）；
步骤条不丢 —— 它另有 `todo/write` 持久事件（`core/todo.py:70`），轮询回读时由
`_DURABLE_TO_SSE` 的 `'todo/write' → 'todo'` 还原，只是少了实时 payload 里的 `progress` 摘要
（持久 payload 只有 `todos`）。
这句要主动说：说"完全等价"会被一眼看穿。

## 五、代码/资产索引（评委追问时快速定位）

| 关注点 | 位置 |
|---|---|
| 工具流水线 + 批处理并发 | `backend/app/core/tool.py` |
| 事件溯源 + 消息投影 | `backend/app/core/events.py`（`derive_messages` / `_SSE_TO_DURABLE`） |
| 子智能体接缝（spawn/fork/并行） | `backend/app/core/subagents.py` |
| 真进度（整表覆盖写） | `backend/app/core/todo.py` |
| 冻结参数延迟执行 | `backend/app/safety/confirmation.py` |
| 拦截口径 + 免责声明注入 | `backend/app/safety/risk_rules.py`（`HIGH_RISK_TOOLS` / `HealthDisclaimerGuard`） |
| 确定性交付物渲染 | `backend/app/agents/plan_builder.py` |
| 大白话引擎 | `backend/app/shared/plain_language.py` |
| 方言 ASR 接缝 | `backend/app/providers/asr/`（tencent / iflytek / mock 三实现，腾讯优先） |
| Mock 确定性 | `backend/app/providers/external/base.py`（derive_no / md5） |
| 设计系统与导航模型 | `docs/DESIGN.md`、`frontend/laoyouji-app/src/uni.scss` |
| 测试 | `backend/tests/`（**601 passed，实测**；29 个 `test_*.py` 文件：内核/子智能体/预算/待办/交付物渲染/守卫/确认状态机/隐私/医疗安全/Mock 确定性/全链路） |
| 离线冒烟 | `backend/scripts/demo_smoke.py`（八步、53 条断言走完同一条剧本，终端可见） |
| E2E | `frontend/e2e/elder-flow.mjs` —— 按新导航模型重写，**62 条断言全绿、EXIT=0（实测）**：底栏按文字点、旗舰链 **0 张挂起卡**、计划书 **4 页**、子女端只有「就医知会」没有同意/拒绝按钮、反向链 138/86 不去医院 |

> **被问"跑得过吗"就照上面答，但要主动补一句边界**：这一套全绿是在
> `LLM_PROVIDER=mock` + `STORAGE_BACKEND=local` 上跑出来的。
> **`SupabaseRepo` 一次都没跑过**（`backend/tests/` 里没有任何用例碰它，grep 可证），
> 真 Key 下的 DeepSeek 与腾讯/讯飞 ASR 也还没被真实响应打过 —— 演示走离线没问题，
> 连真库那天，那些方法属于首次执行。
> 这句要自己说出来：一个被当场戳破的绿勾，比一个坦白的边界贵得多。
>
> **另备一个数字的口径**：仓库里 `def test_` 数出来是 **494 个函数**，pytest 报 **601 passed（实测）** ——
> 差额来自各处 `@pytest.mark.parametrize` 的展开（`test_medical_safety.py` 一处就展开出 21 个用例，
> 6 种诊断说法 + 6 种处方说法 + 4 条饮食 + 3 条用药提醒 + 2 个空正文）。
> **对外只说实测的那个 passed 数**，那是可复现的那个数；被追问再解释差额。
