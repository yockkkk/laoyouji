# Original User Request

## 2026-09-29T07:58:29Z

全面重构并升级现有“老友记”项目，打造面向“第八届湖南省大学生智能导航科技创新大赛”（科技创意类赛道）的参赛级全套成果——《银发导航智能体：基于多Agent协同的老年人安心出行伴侣》，深度融合“北斗卫星导航系统（BDS）+ 多Agent协同调度”技术，交付高保真可交互的前后端演示原型与严格契合大赛规范的科技创意类作品申报方案套件。

Working directory: c:\Users\lenovo\Desktop\develop\laoyouji
Integrity mode: development

参考赛事背景：
- 赛事全称：第八届湖南省大学生智能导航科技创新大赛（湖南省教育厅主办，国防科技大学、测控与导航技术国家地方联合工程研究中心、湘南学院联合承办）
- 赛道类型：科技创意类
- 核心要求：基于北斗卫星导航技术开展“智能导航+”创新应用性研究，推动北斗产业规模化应用与智能信息产业升级，突出多Agent人工智能与北斗精准时空信息融合创新。

## Requirements

### R1. “北斗+多Agent”适老出行协同决策引擎 (BDS Multi-Agent Escort Engine)
深度集成北斗高精度定位数据与老年人慢病体征、实时气象、无障碍步道信息，由多智能体（主调度智能体、健康体能Agent、北斗导航规划Agent、气象感知Agent、安全守护Agent）协同自主完成适老出行方案规划（避开陡坡/复杂过街天桥/长楼梯）与实时动态护航。

### R2. 适老沉浸式北斗高精度实景导航与极简交互 (Elder BDS Navigation UI)
基于北斗亚米级高精度时空感知与地图服务，打造专为银发群体定制的极简出行交互：大白话语音一键直达、大字号高对比度无障碍实景地图、关键路口地标式实景卡片引导、以及偏航与防迷路即时声控纠偏，杜绝生硬技术参数与多余交互。

### R3. 北斗高精电子围栏与子女端安心守护中枢 (BDS Geofencing & Guardian Hub)
基于北斗高精定位与时空轨迹，构建子女/监护人端双向守护闭环：实现老人实时行程与位置感知、北斗安全电子围栏出入与异常停留预警、一键电话/报平安双向直连，形成“老人放心走、子女安心看”的监护闭环。

### R4. 突发风险主动防御与北斗应急求助联动 (Safety Defense & Emergency Dispatch)
构建出行全场景主动防御与应急响应机制：融合北斗特种定位与应急求助概念，支持老人迷路/摔倒一键求助、陌生偏远目的地防诈行程拦截、以及突发身体不适自动重划切换至就近三甲医院就医导航绿通。

### R5. 大赛科技创意类作品申报书与答辩演示套件 (Competition Artifact Package)
严格对照第八届湖南省大学生智能导航科技创新大赛科技创意类作品格式规范，编制高水准的《参赛作品方案报告与商业/技术创新论证》（含北斗核心技术深度融入、多Agent架构设计、核心痛点、创新亮点、产业前景与社会效益），并配套 3-5 分钟评审演示脚本与答辩要点。

## Acceptance Criteria

### 系统与算法验收 (System & Multi-Agent Criteria)
- [ ] 后端多Agent协同与北斗服务链路可测：针对包含身体状况（如膝关节退行性病变）与目的地（如公园/医院）的语音输入，多Agent能自主协同规划避开台阶/长坡的北斗适老路线并输出结构化方案。
- [ ] 北斗安全围栏与异常滞留预警闭环：触发偏远/高危路线或长时间异常停留时，系统自动生成安全告警事件并推向子女端与审计日志。
- [ ] 自动化测试全量通过：后端针对多Agent出行规划、北斗服务适配与守护风控的自动化测试用例通过率达 100%。

### 前端与体验验收 (Frontend & Presentation Criteria)
- [ ] 老人端导航演示链路流畅稳定：从语音发起“去省人民医院/去烈士公园”到北斗路线生成、适老地图展示、步骤分解指引全流程顺畅无报错。
- [ ] 子女端/监护端数据实时联动：子女端看板能直观查阅老人当前出行计划、北斗实时安全状态与历史轨迹。
- [ ] 项目构建与演示无故障：前端 H5 编译无致命错误（`npm run build:h5` 或本地开发服务器稳定可用）。

### 比赛材料验收 (Competition Proposal Criteria)
- [ ] 参赛方案报告规范完整：按照大赛附件规范完整撰写立项背景、北斗融合技术方案、多Agent协同机理、应用场景设计、社会与经济效益分析。
- [ ] 演示脚本与答辩配套清晰：提供 3-5 分钟现场评审汇报脚本与图文对照演示流程。

## 2026-10-01T14:28:46Z

# Teamwork Project Prompt

全面重构并升华“老友记·银发导航智能体”的整套多 Agent 协作体系与前端高精导航地图体验：
深度吸收 C:\Users\lenovo\Desktop\nanobot 与 E:\claude code\claude-code-源码 两大成熟工业级系统的精髓，彻底根除原有“单向静态脚本派发、缺乏灵性、体感平平无奇”的沉闷现状，建立真正的多智能体对等通信信箱（Teammate Mailbox）、流式实时心智显像（Thinking & Handoff Stream）与长期自适应认知记忆；同时彻底根除 Leaflet 地图在 Uni-app 中的手势冲突、卡顿与抖动，打造达到国家级科技创新大赛最高水准的 60fps 丝滑人机体验。

Working directory: c:\Users\lenovo\Desktop\develop\laoyouji
Integrity mode: development

参考架构源代码路径：
1. nanobot: C:\Users\lenovo\Desktop\nanobot
   - 重点参考：nanobot/agent/loop.py（Agent执行流与循环）、nanobot/agent/subagent.py（子智能体管理）、nanobot/agent/memory.py（长短期记忆分层巩固）、nanobot/bus/progress.py（进度与思考流推进）。
2. Claude Code 源码: E:\claude code\claude-code-源码
   - 重点参考：src/utils/teammateMailbox.ts（智能体信箱对等通信通信协议）、src/utils/tasks.ts（共享任务看板）、src/utils/thinking.ts（心智流式协议）、src/utils/teamMemoryOps.ts（团队协同记忆）。

## Requirements

### R1. 多智能体对等通信信箱与协作研讨中枢 (Teammate Swarm & Peer Mailbox)
参考 Claude Code `src/utils/teammateMailbox.ts` 与 nanobot `agent/subagent.py` / `agent/loop.py`，突破主 Agent 机械单向派发的旧局限，构建分布式的多智能体对等协作体系：
- 每个智能体（MainAgent、HealthAgent、BdsNavAgent、WeatherAgent、GuardianAgent）拥有独立的信箱（Inbox / Outbox）与身份标识（角色名、专属主题色、能力卡片）；
- 智能体间可自主相互发起点对点或广播式磋商电文（Peer-to-Peer Messaging），例如健康体能 Agent 将慢病关节受力极限主动推至北斗导航信箱，北斗导航 Agent 就特定路段林荫度与气象 Agent 实时问答确认，形成真正动态闭环的 Multi-Agent Deliberation；
- 维护全局共享任务看板（Shared Task Board，参考 Claude Code `tasks.ts`），各个智能体动态认领、执行与汇报阶段性任务。

### R2. 实时心智思考流与拟人化交接显像 (Real-Time Thinking & Dynamic Agent Handoff)
参考 Claude Code `thinking.ts` / `stream.ts` 与 nanobot `bus/progress.py`，彻底摒弃“长达数秒无响应、突然弹出大卡片”的黑盒体验：
- 后端建立高保真 SSE 流式输出管道，将各智能体的实时思考摘要（Thinking Traces）、信箱通信交互与工具调用进度实时推送至前端；
- 前端对话流原生支持动态拟人化交互动效：老人发起诉求后，界面实时流式呈现智能体思考气泡、智能体流光交接卡（Agent Handoff Card）与状态流转过程，让长辈与评委清晰感知到“多位专业数字秘书正在为自己分工张罗”。

### R3. 自适应分层认知记忆与主动情境关怀 (Adaptive Hierarchical Memory & Proactive Loop)
参考 nanobot `agent/memory.py`（Hierarchical Memory Consolidation）与 Claude Code `teamMemoryOps.ts`：
- 沉淀老人的高频生活地标、下肢慢病体能变化、日常活动节律与异地子女关切偏好；
- 不再局限于“一问一答”的机械被动响应，实现基于情境感知的自然伴随式自适应交互，让系统具备真正懂长辈习惯的“老朋友”温度。

### R4. 适老高精地图手势隔离与 60fps 丝滑渲染重构 (Smooth Map Navigation Engine)
彻底解决 `route-map.vue` 中“一卡一卡、用起来很怪”的性能与交互瓶颈：
- **手势穿透与滚动隔离**：修复 Uni-app 全局页面滚动与 Leaflet 地图拖拽事件冲突，通过 `touch-action: none` 与精确手势拦截，杜绝拖拽卡顿与手势打架；
- **瓦片渲染优化**：消除 `zoomSnap: 0.5` 等非整数缩放引发的栅格瓦片模糊与二次重排重绘，启用硬件加速；
- **丝滑过渡动画**：重构视角跳转逻辑，采用平滑曲线缓动（Smooth FlyTo / PanTo 缓动算法）替代粗暴突变；
- **图层解耦与重绘抑制**：将长辈定位脉冲呼吸动效从主瓦片图层抽离至独立 GPU 硬件加速层，保持地图平移与缩放全程 60fps 稳定流畅。

## Acceptance Criteria

### 多Agent架构与交互验证 (Multi-Agent Swarm Criteria)
- [ ] 跨智能体对等通信可验证：后台日志与事件总线中具备子智能体之间通过信箱直接发送和接收电文的完整记录（如 Health -> BdsNav 约束注入、BdsNav -> Weather 路况校验）。
- [ ] 实时心智流可视化：前端会话流在用户发起诉求后，能够实时呈现智能体思考进度与交接动画，无死寂黑盒等待。
- [ ] 记忆持久与动态提取：在多轮对话中能够自适应调取之前沉淀的长辈体能约束或地标偏好，免于长辈重复输入。

### 导航地图性能与体验验证 (Navigation Map Criteria)
- [ ] 手势拖拽与缩放丝滑流畅：在浏览器及移动端视图下，地图连续拖拽、缩放无卡顿、无顿挫、无页面跟随滚动打架现象（达到 60fps 视效标准）。
- [ ] 视角与定位缓动平滑：点击步骤卡片或长辈定位更新时，视口平移动画自然平滑过渡，无生硬闪跳。

### 系统可靠性与工程指标 (Engineering Stability)
- [ ] 自动化测试全量通过：现有 146 项测试用例保持 100% 通过，且新增多智能体信箱与流式心智单元测试。
- [ ] 前后端构建与运行零报错：前端 H5 编译（npm run build:h5）及开发服务（dev:h5）稳定无警告阻断，后端核心接口响应毫秒级稳定。

