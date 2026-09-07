<template>
  <view class="agent-tree-container">
    <!-- 头部工具栏与全局状态 -->
    <view class="tree-header">
      <view class="header-left">
        <text class="tree-title-icon">🧠</text>
        <view class="title-group">
          <text class="tree-main-title">智能体规划与执行链路</text>
          <text class="tree-sub-title">Agent Execution Tree · 多智能体协同拓扑</text>
        </view>
      </view>

      <view class="header-right">
        <!-- 实时协同状态药丸 -->
        <view class="global-status-pill" :class="globalStatusClass">
          <view class="status-pulse-dot"></view>
          <text class="status-pill-text">{{ globalStatusText }}</text>
        </view>
        <!-- 控制按钮 -->
        <button class="icon-action-btn" :title="allExpanded ? '全部收起' : '全部展开'" @tap="toggleAllExpanded">
          <text class="icon-action-text">{{ allExpanded ? '收起全部' : '展开全部' }}</text>
        </button>
        <button
          class="icon-action-btn replay-btn"
          :class="{ 'is-active': replay.active }"
          :title="replay.active ? (replay.playing ? '暂停演播' : '继续演播') : '动态演播全链路'"
          @tap="toggleReplayMode"
        >
          <text class="icon-action-text">{{ replay.active ? (replay.playing ? '⏸ 暂停演播' : '▶ 继续演播') : '✨ 动态演播全链路' }}</text>
        </button>
        <button v-if="isDesktop" class="icon-action-btn collapse-pane-btn" title="收起执行树面板" @tap="$emit('close')">
          <text class="icon-action-text">⇤ 收起</text>
        </button>
        <button v-if="!isDesktop" class="close-drawer-btn" @tap="$emit('close')">
          <text class="close-icon">✕</text>
        </button>
      </view>
    </view>

    <!-- 拓扑度量信息栏 -->
    <view class="metrics-bar">
      <view class="metric-item">
        <text class="metric-label">总调度</text>
        <text class="metric-val tabular-num">1</text>
      </view>
      <view class="metric-divider"></view>
      <view class="metric-item">
        <text class="metric-label">协同智能体</text>
        <text class="metric-val tabular-num">{{ activeAgentsCount }} / 4</text>
      </view>
      <view class="metric-divider"></view>
      <view class="metric-item">
        <text class="metric-label">执行工具数</text>
        <text class="metric-val tabular-num">{{ totalToolsCount }}</text>
      </view>
      <view class="metric-divider"></view>
      <view class="metric-item" :class="{ 'has-pending': pendingTasksCount > 0, 'has-rejected': hasAnyRejected }">
        <text class="metric-label">{{ hasAnyRejected ? '高危拦截/拒绝' : '高危安全拦截' }}</text>
        <text class="metric-val tabular-num">{{ pendingTasksCount > 0 ? (pendingTasksCount + ' 项待核准') : (hasAnyRejected ? '已安全拦截' : (isArtifactReady ? '已闭环放行' : '0 风险')) }}</text>
      </view>
    </view>

    <!-- 可滚动树内容区 -->
    <scroll-view class="tree-scroll" scroll-y>
      <view class="tree-canvas">

        <!-- ================= 动态规划 DAG 画布 (Planning Flowchart / DAG Canvas) (R3) ================= -->
        <view class="planning-dag-card">
          <view class="dag-header">
            <view class="dag-header-title-box">
              <text class="dag-sparkle">✨</text>
              <view class="dag-titles">
                <text class="dag-main-title">多智能体动态规划 DAG (Agent Planning Flowchart)</text>
                <text class="dag-sub-title">感知输入 ➔ 意图拆解 ➔ 并行协同 ➔ 安全拦截网 ➔ 方案装配 ➔ 成果闭环</text>
              </view>
            </view>
            <view class="dag-header-actions">
              <button
                class="replay-trigger-btn"
                :class="{ 'is-playing': replay.active }"
                @tap="toggleReplayMode"
              >
                <text class="replay-btn-icon">{{ replay.active ? (replay.playing ? '⏸' : '▶') : '✨' }}</text>
                <text class="replay-btn-text">{{ replay.active ? (replay.playing ? '暂停演播' : '继续演播') : '动态演播全链路' }}</text>
              </button>
            </view>
          </view>

          <!-- 动态演播全链路控制面板 (Replay Controller Bar) -->
          <view v-if="replay.active" class="replay-controller-bar">
            <view class="replay-narrative">
              <view class="narrative-tag">
                <text class="narrative-step-num tabular-num">{{ currentReplayStepInfo.num }}</text>
                <text class="narrative-icon">{{ currentReplayStepInfo.icon }}</text>
              </view>
              <view class="narrative-content">
                <text class="narrative-title">{{ currentReplayStepInfo.title }}</text>
                <text class="narrative-desc">{{ currentReplayStepInfo.desc }}</text>
              </view>
            </view>

            <view class="replay-buttons-row">
              <button class="ctrl-btn" @tap="prevReplayStep" :disabled="replay.step <= 0">
                <text class="ctrl-text">⏮ 上一步</text>
              </button>
              <button class="ctrl-btn primary" @tap="toggleReplayPlay">
                <text class="ctrl-text">{{ replay.playing ? '⏸ 暂停' : '▶ 播放' }}</text>
              </button>
              <button class="ctrl-btn" @tap="nextReplayStep" :disabled="replay.step >= 5">
                <text class="ctrl-text">⏭ 下一步</text>
              </button>
              <button class="ctrl-btn" @tap="resetReplay">
                <text class="ctrl-text">↺ 重置</text>
              </button>
              <button class="ctrl-btn exit" @tap="exitReplay">
                <text class="ctrl-text">✕ 退出</text>
              </button>
            </view>

            <!-- 演播进度指示条 -->
            <view class="replay-progress-track">
              <view
                v-for="s in 6"
                :key="s"
                class="replay-progress-dot"
                :class="{
                  'passed': (s - 1) < replay.step,
                  'current': (s - 1) === replay.step,
                }"
                @tap="seekReplay(s - 1)"
              >
                <text class="dot-num tabular-num">{{ s - 1 }}</text>
              </view>
              <view
                class="replay-progress-bar-fill"
                :style="{ width: (replay.step / 5 * 100) + '%' }"
              ></view>
            </view>
          </view>

          <!-- DAG 拓扑流程图主体 (Visual DAG Hierarchy) -->
          <view class="dag-canvas-container">
            <!-- 节点 1：Root Intent 根意图调度 -->
            <view
              class="dag-node dag-node-root"
              :class="{
                'is-frontier': isRootFrontier,
                'is-completed': isRootDone,
              }"
              @tap="scrollToSection('root')"
            >
              <view class="dag-node-glow"></view>
              <view class="dag-node-avatar orchestrator-avatar">
                <text class="dag-avatar-icon">🎯</text>
              </view>
              <view class="dag-node-text-group">
                <text class="dag-node-title">老友记总调度</text>
                <text class="dag-node-role">Orchestrator · 意图理解与任务派发</text>
              </view>
              <view class="dag-node-state-chip" :class="rootStatusClass">
                {{ rootStatusText }}
              </view>
            </view>

            <!-- 动态能量连接线：总调度 -> 派发主干 -->
            <view class="dag-wire-vertical" :class="{ 'energy-pulse': isAnyAgentActive }">
              <view class="pulse-particle"></view>
            </view>

            <!-- 节点 2：多智能体并发协同总线 -->
            <view class="dag-parallel-trunk-label">
              <text class="trunk-label-text">⚡ 多智能体并发协同总线 (Parallel Dispatch Trunk)</text>
            </view>
            <view class="dag-trunk-bar" :class="{ 'energy-pulse': isAnyAgentActive }"></view>

            <!-- 节点 3：并行子智能体集群 (Subagents Cluster) -->
            <view class="dag-subagents-grid">
              <!-- 健康守护 -->
              <view
                class="dag-node dag-sub-node health-sub-node"
                :class="{
                  'is-frontier': isHealthFrontier,
                  'is-completed': healthStatusClass === 'status-completed',
                  'is-suspended': healthStatusClass === 'status-suspended',
                }"
                @tap="scrollToSection('health')"
              >
                <view class="dag-node-avatar health-avatar">
                  <text class="dag-avatar-icon">🏥</text>
                </view>
                <text class="dag-sub-name">健康守护</text>
                <text class="dag-sub-role">安康助手</text>
                <view class="dag-mini-status" :class="healthStatusClass">
                  {{ healthStatusText }}
                </view>
              </view>

              <!-- 银发导航 -->
              <view
                class="dag-node dag-sub-node travel-sub-node"
                :class="{
                  'is-frontier': isTravelFrontier,
                  'is-completed': travelStatusClass === 'status-completed',
                  'is-suspended': travelStatusClass === 'status-suspended',
                }"
                @tap="scrollToSection('travel')"
              >
                <view class="dag-node-avatar travel-avatar">
                  <text class="dag-avatar-icon">🧭</text>
                </view>
                <text class="dag-sub-name">银发导航</text>
                <text class="dag-sub-role">出行管家</text>
                <view class="dag-mini-status" :class="travelStatusClass">
                  {{ travelStatusText }}
                </view>
              </view>

              <!-- 邻里帮 -->
              <view
                class="dag-node dag-sub-node community-sub-node"
                :class="{
                  'is-frontier': isCommunityFrontier,
                  'is-completed': communityStatusClass === 'status-completed',
                }"
                @tap="scrollToSection('community')"
              >
                <view class="dag-node-avatar community-avatar">
                  <text class="dag-avatar-icon">🏘️</text>
                </view>
                <text class="dag-sub-name">邻里帮</text>
                <text class="dag-sub-role">就医陪诊</text>
                <view class="dag-mini-status" :class="communityStatusClass">
                  {{ communityStatusText }}
                </view>
              </view>
            </view>

            <!-- 动态能量连接线：子智能体 -> 安全防护网 -->
            <view class="dag-trunk-bar" :class="{ 'energy-pulse': isSafetyActive || isArtifactReady }"></view>
            <view class="dag-wire-vertical" :class="{ 'energy-pulse': isSafetyActive || isArtifactReady }">
              <view class="pulse-particle"></view>
            </view>

            <!-- 节点 4：资金与医疗安全防护网 (Safety Guard Gateway) -->
            <view
              class="dag-node dag-node-gateway"
              :class="{
                'is-frontier': isSafetyFrontier,
                'is-suspended': pendingTasksCount > 0,
                'is-completed': pendingTasksCount === 0 && (hasTaskStarted || replay.step >= 4),
                'is-rejected': hasAnyRejected,
              }"
              @tap="scrollToSection('safety')"
            >
              <view class="dag-node-glow"></view>
              <view class="dag-node-avatar safety-avatar">
                <text class="dag-avatar-icon">🛡️</text>
              </view>
              <view class="dag-node-text-group">
                <text class="dag-node-title">资金与医疗安全防护网</text>
                <text class="dag-node-role">Safety Guard Gateway · 双向审批回路 (Loopback)</text>
              </view>
              <view class="dag-node-state-chip" :class="safetyStatusClass">
                {{ safetyStatusText }}
              </view>
            </view>

            <!-- 动态能量连接线：安全网 -> 方案建造师 -->
            <view class="dag-wire-vertical" :class="{ 'energy-pulse': isPlanBuilderActive || isArtifactReady }">
              <view class="pulse-particle"></view>
            </view>

            <!-- 节点 5：方案建造师 (PlanBuilder) -->
            <view
              class="dag-node dag-node-builder"
              :class="{
                'is-frontier': isPlanBuilderFrontier,
                'is-completed': planBuilderStatusClass === 'status-completed',
              }"
              @tap="scrollToSection('planBuilder')"
            >
              <view class="dag-node-glow"></view>
              <view class="dag-node-avatar planbuilder-avatar">
                <text class="dag-avatar-icon">📐</text>
              </view>
              <view class="dag-node-text-group">
                <text class="dag-node-title">方案建造师</text>
                <text class="dag-node-role">PlanBuilder · 事实聚合与去幻觉对齐</text>
              </view>
              <view class="dag-node-state-chip" :class="planBuilderStatusClass">
                {{ planBuilderStatusText }}
              </view>
            </view>

            <!-- 动态能量连接线：方案建造师 -> 终极交付物 -->
            <view class="dag-wire-vertical" :class="{ 'energy-pulse': isArtifactReady }">
              <view class="pulse-particle"></view>
            </view>

            <!-- 节点 6：终极交付物 (Final Deliverable Artifact) -->
            <view
              class="dag-node dag-node-artifact"
              :class="{
                'is-ready': isArtifactReady,
                'is-frontier': isArtifactReady,
              }"
              @tap="openArtifactModal"
            >
              <view class="dag-node-avatar artifact-avatar">
                <text class="dag-avatar-icon">📄</text>
              </view>
              <view class="dag-node-text-group">
                <text class="dag-node-title">《五页就医出行计划书》</text>
                <text class="dag-node-role">五页适老大字版 · 挂号凭证+高铁票+酒店+慢病清单+天气</text>
              </view>
              <view class="dag-node-state-chip" :class="isArtifactReady ? 'status-completed' : 'status-ready'">
                {{ isArtifactReady ? '✅ 已交付 (点击预览)' : '⏳ 待审批后交付' }}
              </view>
            </view>
          </view>
        </view>

        <!-- ================= 根节点：老友记主调度 (Orchestrator Card) ================= -->
        <view class="root-node-card" :class="{ 'is-thinking': thinking || rootThinking }">
          <view class="node-glass-glow"></view>
          <view class="node-head">
            <view class="node-badge-group">
              <view class="avatar-box orchestrator-avatar">
                <text class="avatar-icon">🎯</text>
              </view>
              <view class="node-meta">
                <view class="node-title-row">
                  <text class="node-title">老友记主调度</text>
                  <text class="agent-tag-role">Orchestrator · 总入口</text>
                </view>
                <text class="node-role-desc">意图解析 · 任务规划 · 并行派发 · 交付聚合</text>
              </view>
            </view>
            <!-- 状态标签 -->
            <view class="state-badge" :class="rootStatusClass">
              <text class="state-icon">{{ rootStatusIcon }}</text>
              <text class="state-text">{{ rootStatusText }}</text>
            </view>
          </view>

          <!-- 意图识别结果框 -->
          <view class="intent-box">
            <view class="intent-header">
              <text class="intent-label">🎯 老人诉求意图识别</text>
              <text class="intent-tag">{{ currentScenarioTag }}</text>
            </view>
            <text class="intent-content">{{ currentIntentText }}</text>
          </view>

          <!-- 智能体推理独白 (Orchestrator Monologue) (R3) -->
          <view class="agent-monologue-card">
            <view class="monologue-head">
              <text class="monologue-sparkle">💡</text>
              <text class="monologue-title">主调度规划推理独白 (Orchestrator Thought)</text>
            </view>
            <text class="monologue-text">{{ agentThoughts.orchestrator }}</text>
          </view>

          <!-- 全局规划链路步骤 (阶段动态状态机) (R2) -->
          <view class="plan-steps-track">
            <view class="track-header">
              <text class="track-title">📋 任务分解流水线 (Todo State Machine)</text>
              <text class="track-progress tabular-num">{{ completedStepsCount }}/{{ totalStepsCount }} 已完成</text>
            </view>
            <view class="steps-grid">
              <view
                v-for="(step, sIdx) in displaySteps"
                :key="sIdx"
                class="step-chip"
                :class="'step-' + step.status"
              >
                <view class="step-num tabular-num">{{ sIdx + 1 }}</view>
                <text class="step-name">{{ step.name }}</text>
                <text class="step-status-tag">{{ formatStepStatus(step.status) }}</text>
              </view>
            </view>
          </view>
        </view>

        <!-- 主调度连接向子智能体的分支干线 -->
        <view class="branch-trunk-container">
          <view class="trunk-line-vertical" :class="{ 'flow-active': isAnyAgentActive }"></view>
          <view class="trunk-label-chip">
            <text class="trunk-chip-text">多智能体并行调度分支 (Parallel Dispatch)</text>
          </view>
          <view class="trunk-horizontal-bar" :class="{ 'flow-active': isAnyAgentActive }"></view>
        </view>

        <!-- ================= 子智能体分支网格 ================= -->
        <view class="subagent-branches-container">

          <!-- 分支 1：健康守护 (Health Agent · 安康助手) -->
          <view class="subagent-branch-card health-branch" :class="{ 'collapsed': collapsedAgents.health }">
            <view class="branch-header" @tap="toggleAgentCollapse('health')">
              <view class="branch-header-left">
                <view class="avatar-box health-avatar">
                  <text class="avatar-icon">🏥</text>
                </view>
                <view class="branch-title-group">
                  <view class="branch-name-row">
                    <text class="branch-name">健康守护</text>
                    <text class="branch-en-tag">Health Agent · 安康助手</text>
                  </view>
                  <text class="branch-desc">对症导诊 · 科室号源 · 专家预约</text>
                </view>
              </view>
              <view class="branch-header-right">
                <view class="state-badge" :class="healthStatusClass">
                  <text class="state-icon">{{ healthStatusIcon }}</text>
                  <text class="state-text">{{ healthStatusText }}</text>
                </view>
                <text class="accordion-arrow">{{ collapsedAgents.health ? '▼' : '▲' }}</text>
              </view>
            </view>

            <view class="branch-collapsible" :class="{ 'is-open': !collapsedAgents.health }">
              <view class="branch-body">
                <!-- 智能体推理独白 (R3) -->
                <view class="agent-monologue-card">
                  <view class="monologue-head">
                    <text class="monologue-sparkle">💡</text>
                    <text class="monologue-title">健康智能体推理独白 (Health Agent Thought)</text>
                  </view>
                  <text class="monologue-text">{{ agentThoughts.health }}</text>
                </view>

                <!-- 工具节点列表 -->
                <view class="tools-flow">
                  <!-- 工具节点: search_hospital -->
                  <view class="tool-node" :class="'node-' + healthTools.searchHospital.status">
                    <view class="node-connector-dot"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">search_hospital</text>
                          <text class="tool-cn-name">权威医院专家号源检索</text>
                        </view>
                        <view class="node-tags-group">
                          <text class="latency-badge tabular-num">{{ toolLatencies.searchHospital }}</text>
                          <view class="node-status-tag" :class="healthTools.searchHospital.status">
                            {{ formatToolStatus(healthTools.searchHospital.status, 'searchHospital') }}
                          </view>
                        </view>
                      </view>
                      <!-- 参数 JSON 高亮 (R3) -->
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tIdx) in parseParamsTokens(healthTools.searchHospital.params, 'searchHospital')" :key="tIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <!-- 返回摘要与展开详情 (R3) -->
                      <view v-if="healthTools.searchHospital.result" class="result-box">
                        <view class="result-summary-row">
                          <text class="result-text">🎯 匹配号源：{{ healthTools.searchHospital.result }}</text>
                          <button class="toggle-detail-btn" @tap="toggleToolResultExpand('searchHospital')">
                            {{ isToolResultExpanded('searchHospital') ? '收起详情 ▴' : '展开完整结果 ▾' }}
                          </button>
                        </view>
                        <view v-if="isToolResultExpanded('searchHospital')" class="expanded-tool-detail">
                          <view class="detail-row"><text class="detail-k">执行状态:</text><text class="detail-v text-ok">200 OK (成功返回)</text></view>
                          <view class="detail-row"><text class="detail-k">响应耗时:</text><text class="detail-v tabular-num">{{ toolLatencies.searchHospital }}</text></view>
                          <view class="detail-row"><text class="detail-k">安全合规:</text><text class="detail-v text-ok">经 HealthDisclaimerGuard 免责审查</text></view>
                          <view class="detail-row"><text class="detail-k">返回载荷:</text><text class="detail-v code-block">{"doctor": "田伟", "title": "主任医师", "dept": "关节外科", "hospital": "北京积水潭医院", "slot": "08:30-09:30", "fee": 100.0}</text></view>
                        </view>
                      </view>
                    </view>
                  </view>

                  <!-- 工具节点: register_appointment (高危资金/挂起) -->
                  <view class="tool-node high-risk-node" :class="'node-' + healthTools.registerAppointment.status">
                    <view class="node-connector-dot risk-dot"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">register_appointment</text>
                          <text class="tool-cn-name">门诊挂号 (高危医疗)</text>
                          <text class="risk-badge">🛡️ 家人确认保护</text>
                        </view>
                        <view class="node-tags-group">
                          <text class="latency-badge tabular-num">{{ toolLatencies.registerAppointment }}</text>
                          <view class="node-status-tag" :class="healthTools.registerAppointment.status">
                            {{ formatToolStatus(healthTools.registerAppointment.status, 'registerAppointment') }}
                          </view>
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tIdx) in parseParamsTokens(healthTools.registerAppointment.params, 'registerAppointment')" :key="tIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <!-- 挂起等待子女确认状态卡片 (R2) -->
                      <view v-if="healthTools.registerAppointment.status === 'suspended'" class="suspended-alert-card">
                        <view class="suspend-header">
                          <text class="suspend-icon">⏸️</text>
                          <text class="suspend-title">等待子女确认 (¥{{ healthTools.registerAppointment.amount ? Number(healthTools.registerAppointment.amount).toFixed(2) : '100.00' }})</text>
                        </view>
                        <text class="suspend-desc">{{ healthTools.registerAppointment.desc || '已安全拦截高危挂号请求，需子女手机端核准后方可放行挂号' }}</text>
                        <view class="suspend-actions-row">
                          <button
                            class="quick-approve-btn"
                            @tap="triggerApprove(healthTools.registerAppointment.confirmationId || 'conf_demo_appoint', 'register_appointment')"
                          >
                            ⚡ 模拟子女审批通过 (Loopback)
                          </button>
                          <button
                            class="quick-reject-btn"
                            @tap="triggerReject(healthTools.registerAppointment.confirmationId || 'conf_demo_appoint', 'register_appointment')"
                          >
                            🛑 模拟子女拒绝
                          </button>
                        </view>
                      </view>
                      <!-- 已执行卡片 -->
                      <view v-else-if="healthTools.registerAppointment.status === 'executed'" class="executed-alert-card">
                        <text class="executed-icon">✅</text>
                        <text class="executed-text">子女已审批同意 · 积水潭骨科田伟主任号挂号成功</text>
                      </view>
                      <!-- 已拒绝卡片 -->
                      <view v-else-if="healthTools.registerAppointment.status === 'rejected'" class="rejected-alert-card">
                        <view class="reject-header">
                          <text class="reject-icon">🛑</text>
                          <text class="reject-title">子女已拒绝挂号申请</text>
                        </view>
                        <text class="reject-desc">已安全拦截并终止高危挂号请求，未扣除挂号费用，就诊预约已取消。</text>
                      </view>
                    </view>
                  </view>
                </view>
              </view>
            </view>
          </view>

          <!-- 分支 2：银发导航 (Travel Agent · 银发导航) -->
          <view class="subagent-branch-card travel-branch" :class="{ 'collapsed': collapsedAgents.travel }">
            <view class="branch-header" @tap="toggleAgentCollapse('travel')">
              <view class="branch-header-left">
                <view class="avatar-box travel-avatar">
                  <text class="avatar-icon">🧭</text>
                </view>
                <view class="branch-title-group">
                  <view class="branch-name-row">
                    <text class="branch-name">银发导航</text>
                    <text class="branch-en-tag">Travel Agent · 银发导航</text>
                  </view>
                  <text class="branch-desc">高铁订票 · 适老酒店 · 行程感知与天气</text>
                </view>
              </view>
              <view class="branch-header-right">
                <view class="state-badge" :class="travelStatusClass">
                  <text class="state-icon">{{ travelStatusIcon }}</text>
                  <text class="state-text">{{ travelStatusText }}</text>
                </view>
                <text class="accordion-arrow">{{ collapsedAgents.travel ? '▼' : '▲' }}</text>
              </view>
            </view>

            <view class="branch-collapsible" :class="{ 'is-open': !collapsedAgents.travel }">
              <view class="branch-body">
                <!-- 智能体推理独白 (R3) -->
                <view class="agent-monologue-card">
                  <view class="monologue-head">
                    <text class="monologue-sparkle">💡</text>
                    <text class="monologue-title">出行智能体推理独白 (Travel Agent Thought)</text>
                  </view>
                  <text class="monologue-text">{{ agentThoughts.travel }}</text>
                </view>

                <view class="tools-flow">
                  <!-- 工具节点: search_train -->
                  <view class="tool-node" :class="'node-' + travelTools.searchTrain.status">
                    <view class="node-connector-dot"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">search_train</text>
                          <text class="tool-cn-name">高铁车次检索</text>
                        </view>
                        <view class="node-tags-group">
                          <text class="latency-badge tabular-num">{{ toolLatencies.searchTrain }}</text>
                          <view class="node-status-tag" :class="travelTools.searchTrain.status">
                            {{ formatToolStatus(travelTools.searchTrain.status, 'searchTrain') }}
                          </view>
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tIdx) in parseParamsTokens(travelTools.searchTrain.params, 'searchTrain')" :key="tIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <view v-if="travelTools.searchTrain.result" class="result-box">
                        <text class="result-text">🚅 {{ travelTools.searchTrain.result }}</text>
                      </view>
                    </view>
                  </view>

                  <!-- 工具节点: book_ticket (高危资金/挂起) -->
                  <view class="tool-node high-risk-node" :class="'node-' + travelTools.bookTicket.status">
                    <view class="node-connector-dot risk-dot"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">book_ticket</text>
                          <text class="tool-cn-name">高铁订票出票 (高危支付)</text>
                          <text class="risk-badge">🛡️ 家人确认保护</text>
                        </view>
                        <view class="node-tags-group">
                          <text class="latency-badge tabular-num">{{ toolLatencies.bookTicket }}</text>
                          <view class="node-status-tag" :class="travelTools.bookTicket.status">
                            {{ formatToolStatus(travelTools.bookTicket.status, 'bookTicket') }}
                          </view>
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tIdx) in parseParamsTokens(travelTools.bookTicket.params, 'bookTicket')" :key="tIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <!-- 挂起卡片 -->
                      <view v-if="travelTools.bookTicket.status === 'suspended'" class="suspended-alert-card">
                        <view class="suspend-header">
                          <text class="suspend-icon">⏸️</text>
                          <text class="suspend-title">等待子女确认 (¥{{ travelTools.bookTicket.amount ? Number(travelTools.bookTicket.amount).toFixed(2) : '443.50' }})</text>
                        </view>
                        <text class="suspend-desc">{{ travelTools.bookTicket.desc || '高铁票订购款项，已推送子女端审核放行' }}</text>
                        <view class="suspend-actions-row">
                          <button
                            class="quick-approve-btn"
                            @tap="triggerApprove(travelTools.bookTicket.confirmationId || 'conf_demo_ticket', 'book_ticket')"
                          >
                            ⚡ 模拟子女审批通过 (Loopback)
                          </button>
                          <button
                            class="quick-reject-btn"
                            @tap="triggerReject(travelTools.bookTicket.confirmationId || 'conf_demo_ticket', 'book_ticket')"
                          >
                            🛑 模拟子女拒绝
                          </button>
                        </view>
                      </view>
                      <!-- 已执行卡片 -->
                      <view v-else-if="travelTools.bookTicket.status === 'executed'" class="executed-alert-card">
                        <text class="executed-icon">✅</text>
                        <text class="executed-text">子女已审批同意 · G102二等座已出票，凭身份证直接进站</text>
                      </view>
                      <!-- 已拒绝卡片 -->
                      <view v-else-if="travelTools.bookTicket.status === 'rejected'" class="rejected-alert-card">
                        <view class="reject-header">
                          <text class="reject-icon">🛑</text>
                          <text class="reject-title">子女已拒绝购票申请</text>
                        </view>
                        <text class="reject-desc">已安全终止高铁订票出票操作，未产生 ¥443.50 扣费，资金已保护。</text>
                      </view>
                    </view>
                  </view>

                  <!-- 工具节点: search_hotel -->
                  <view class="tool-node" :class="'node-' + travelTools.searchHotel.status">
                    <view class="node-connector-dot"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">search_hotel</text>
                          <text class="tool-cn-name">适老无障碍酒店检索</text>
                        </view>
                        <view class="node-tags-group">
                          <text class="latency-badge tabular-num">{{ toolLatencies.searchHotel }}</text>
                          <view class="node-status-tag" :class="travelTools.searchHotel.status">
                            {{ formatToolStatus(travelTools.searchHotel.status, 'searchHotel') }}
                          </view>
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tIdx) in parseParamsTokens(travelTools.searchHotel.params, 'searchHotel')" :key="tIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <view v-if="travelTools.searchHotel.result" class="result-box">
                        <text class="result-text">🏨 {{ travelTools.searchHotel.result }}</text>
                      </view>
                    </view>
                  </view>

                  <!-- 工具节点: book_hotel (高危资金/挂起) -->
                  <view class="tool-node high-risk-node" :class="'node-' + travelTools.bookHotel.status">
                    <view class="node-connector-dot risk-dot"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">book_hotel</text>
                          <text class="tool-cn-name">适老酒店预订 (高危支付)</text>
                          <text class="risk-badge">🛡️ 家人确认保护</text>
                        </view>
                        <view class="node-tags-group">
                          <text class="latency-badge tabular-num">{{ toolLatencies.bookHotel }}</text>
                          <view class="node-status-tag" :class="travelTools.bookHotel.status">
                            {{ formatToolStatus(travelTools.bookHotel.status, 'bookHotel') }}
                          </view>
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tIdx) in parseParamsTokens(travelTools.bookHotel.params, 'bookHotel')" :key="tIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <!-- 挂起卡片 -->
                      <view v-if="travelTools.bookHotel.status === 'suspended'" class="suspended-alert-card">
                        <view class="suspend-header">
                          <text class="suspend-icon">⏸️</text>
                          <text class="suspend-title">等待子女确认 (¥{{ travelTools.bookHotel.amount ? Number(travelTools.bookHotel.amount).toFixed(2) : '680.00' }})</text>
                        </view>
                        <text class="suspend-desc">{{ travelTools.bookHotel.desc || '酒店预订2晚费用，已报送子女端确认' }}</text>
                        <view class="suspend-actions-row">
                          <button
                            class="quick-approve-btn"
                            @tap="triggerApprove(travelTools.bookHotel.confirmationId || 'conf_demo_hotel', 'book_hotel')"
                          >
                            ⚡ 模拟子女审批通过 (Loopback)
                          </button>
                          <button
                            class="quick-reject-btn"
                            @tap="triggerReject(travelTools.bookHotel.confirmationId || 'conf_demo_hotel', 'book_hotel')"
                          >
                            🛑 模拟子女拒绝
                          </button>
                        </view>
                      </view>
                      <!-- 已执行卡片 -->
                      <view v-else-if="travelTools.bookHotel.status === 'executed'" class="executed-alert-card">
                        <text class="executed-icon">✅</text>
                        <text class="executed-text">子女已审批同意 · 漫心酒店无障碍双床房已保留成功</text>
                      </view>
                      <!-- 已拒绝卡片 -->
                      <view v-else-if="travelTools.bookHotel.status === 'rejected'" class="rejected-alert-card">
                        <view class="reject-header">
                          <text class="reject-icon">🛑</text>
                          <text class="reject-title">子女已拒绝预订申请</text>
                        </view>
                        <text class="reject-desc">已安全终止酒店预订操作，未产生 ¥680.00 扣费，资金已保护。</text>
                      </view>
                    </view>
                  </view>

                  <!-- 工具节点: get_weather -->
                  <view class="tool-node" :class="'node-' + travelTools.getWeather.status">
                    <view class="node-connector-dot"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">get_weather</text>
                          <text class="tool-cn-name">目的地出行天气感知</text>
                        </view>
                        <view class="node-tags-group">
                          <text class="latency-badge tabular-num">{{ toolLatencies.getWeather }}</text>
                          <view class="node-status-tag" :class="travelTools.getWeather.status">
                            {{ formatToolStatus(travelTools.getWeather.status, 'getWeather') }}
                          </view>
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tIdx) in parseParamsTokens(travelTools.getWeather.params, 'getWeather')" :key="tIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <view v-if="travelTools.getWeather.result" class="result-box">
                        <text class="result-text">🌤️ {{ travelTools.getWeather.result }}</text>
                      </view>
                    </view>
                  </view>
                </view>
              </view>
            </view>
          </view>

          <!-- 分支 3：邻里帮 (Community Agent · 邻里帮) -->
          <view class="subagent-branch-card community-branch" :class="{ 'collapsed': collapsedAgents.community }">
            <view class="branch-header" @tap="toggleAgentCollapse('community')">
              <view class="branch-header-left">
                <view class="avatar-box community-avatar">
                  <text class="avatar-icon">🏘️</text>
                </view>
                <view class="branch-title-group">
                  <view class="branch-name-row">
                    <text class="branch-name">邻里帮</text>
                    <text class="branch-en-tag">Community Agent · 邻里帮</text>
                  </view>
                  <text class="branch-desc">就医陪诊 · 轮椅借用 · 绿色通道引导</text>
                </view>
              </view>
              <view class="branch-header-right">
                <view class="state-badge" :class="communityStatusClass">
                  <text class="state-icon">{{ communityStatusIcon }}</text>
                  <text class="state-text">{{ communityStatusText }}</text>
                </view>
                <text class="accordion-arrow">{{ collapsedAgents.community ? '▼' : '▲' }}</text>
              </view>
            </view>

            <view class="branch-collapsible" :class="{ 'is-open': !collapsedAgents.community }">
              <view class="branch-body">
                <!-- 智能体推理独白 (R3) -->
                <view class="agent-monologue-card">
                  <view class="monologue-head">
                    <text class="monologue-sparkle">💡</text>
                    <text class="monologue-title">邻里智能体推理独白 (Community Agent Thought)</text>
                  </view>
                  <text class="monologue-text">{{ agentThoughts.community }}</text>
                </view>

                <view class="tools-flow">
                  <view class="tool-node" :class="'node-' + communityTools.orderService.status">
                    <view class="node-connector-dot"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">order_service / escort</text>
                          <text class="tool-cn-name">就医全程陪诊服务推荐</text>
                        </view>
                        <view class="node-tags-group">
                          <text class="latency-badge tabular-num">{{ toolLatencies.orderService }}</text>
                          <view class="node-status-tag" :class="communityTools.orderService.status">
                            {{ formatToolStatus(communityTools.orderService.status, 'orderService') }}
                          </view>
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tIdx) in parseParamsTokens(communityTools.orderService.params, 'orderService')" :key="tIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <view class="result-box">
                        <text class="result-text">🤝 匹配三甲护士级持证陪诊员，随时待命协助老人就医跑腿</text>
                      </view>
                    </view>
                  </view>
                </view>
              </view>
            </view>
          </view>

          <!-- 分支 4：资金与医疗安全防护网 (Safety Guard Gateway) (R3) -->
          <view class="subagent-branch-card safety-branch" :class="{ 'collapsed': collapsedAgents.safety }">
            <view class="branch-header" @tap="toggleAgentCollapse('safety')">
              <view class="branch-header-left">
                <view class="avatar-box safety-avatar">
                  <text class="avatar-icon">🛡️</text>
                </view>
                <view class="branch-title-group">
                  <view class="branch-name-row">
                    <text class="branch-name">资金与医疗安全防护网</text>
                    <text class="branch-en-tag">Safety Guard Gateway · 双向审批回路</text>
                  </view>
                  <text class="branch-desc">高危支付拦截 · 医疗操作防护 · 子女端实时核准</text>
                </view>
              </view>
              <view class="branch-header-right">
                <view class="state-badge" :class="safetyStatusClass">
                  <text class="state-icon">{{ safetyStatusIcon }}</text>
                  <text class="state-text">{{ safetyStatusText }}</text>
                </view>
                <text class="accordion-arrow">{{ collapsedAgents.safety ? '▼' : '▲' }}</text>
              </view>
            </view>

            <view class="branch-collapsible" :class="{ 'is-open': !collapsedAgents.safety }">
              <view class="branch-body">
                <!-- 智能体推理独白 -->
                <view class="agent-monologue-card">
                  <view class="monologue-head">
                    <text class="monologue-sparkle">🛡️</text>
                    <text class="monologue-title">安全风控网关推理独白 (Safety Guard Monologue)</text>
                  </view>
                  <text class="monologue-text">{{ agentThoughts.safety }}</text>
                </view>

                <!-- 高危拦截受控清单 -->
                <view class="safety-dashboard-card">
                  <view class="safety-dash-header">
                    <text class="dash-title">🛡️ 受控高危操作清单 (双向审批回路)</text>
                    <button
                      v-if="pendingTasksCount > 0"
                      class="batch-approve-btn"
                      @tap="approveAllPending"
                    >
                      ⚡ 模拟子女一键全批通过
                    </button>
                  </view>
                  <view class="safety-items-list">
                    <view class="safety-item-row">
                      <text class="item-icon">🏥</text>
                      <view class="item-meta">
                        <text class="item-name">北京积水潭医院田伟主任门诊号</text>
                        <text class="item-sub">高危医疗就诊 · 专家号源预约</text>
                      </view>
                      <text class="item-amount tabular-num">¥100.00</text>
                      <view class="item-status" :class="healthTools.registerAppointment.status">
                        {{ formatToolStatus(healthTools.registerAppointment.status, 'registerAppointment') }}
                      </view>
                    </view>
                    <view class="safety-item-row">
                      <text class="item-icon">🧭</text>
                      <view class="item-meta">
                        <text class="item-name">G102 次高铁二等座车票 (南京南-北京南)</text>
                        <text class="item-sub">跨城大额资金支付</text>
                      </view>
                      <text class="item-amount tabular-num">¥443.50</text>
                      <view class="item-status" :class="travelTools.bookTicket.status">
                        {{ formatToolStatus(travelTools.bookTicket.status, 'bookTicket') }}
                      </view>
                    </view>
                    <view class="safety-item-row">
                      <text class="item-icon">🏨</text>
                      <view class="item-meta">
                        <text class="item-name">漫心适老酒店无障碍房 (2晚)</text>
                        <text class="item-sub">大额住宿保证金预授权</text>
                      </view>
                      <text class="item-amount tabular-num">¥680.00</text>
                      <view class="item-status" :class="travelTools.bookHotel.status">
                        {{ formatToolStatus(travelTools.bookHotel.status, 'bookHotel') }}
                      </view>
                    </view>
                  </view>
                  <view class="safety-pool-summary">
                    <text class="pool-label">资金拦截池受控总额：</text>
                    <text class="pool-val tabular-num">¥1,223.50</text>
                    <text class="pool-shield-tag">已通过加密长连接推送子女端</text>
                  </view>
                </view>
              </view>
            </view>
          </view>

          <!-- 分支 5：方案建造师 (PlanBuilder · 方案装配) -->
          <view class="subagent-branch-card planbuilder-branch" :class="{ 'collapsed': collapsedAgents.planBuilder }">
            <view class="branch-header" @tap="toggleAgentCollapse('planBuilder')">
              <view class="branch-header-left">
                <view class="avatar-box planbuilder-avatar">
                  <text class="avatar-icon">📐</text>
                </view>
                <view class="branch-title-group">
                  <view class="branch-name-row">
                    <text class="branch-name">方案建造师</text>
                    <text class="branch-en-tag">PlanBuilder · 方案装配</text>
                  </view>
                  <text class="branch-desc">多智能体事实对齐 · 交付物确定性装配</text>
                </view>
              </view>
              <view class="branch-header-right">
                <view class="state-badge" :class="planBuilderStatusClass">
                  <text class="state-icon">{{ planBuilderStatusIcon }}</text>
                  <text class="state-text">{{ planBuilderStatusText }}</text>
                </view>
                <text class="accordion-arrow">{{ collapsedAgents.planBuilder ? '▼' : '▲' }}</text>
              </view>
            </view>

            <view class="branch-collapsible" :class="{ 'is-open': !collapsedAgents.planBuilder }">
              <view class="branch-body">
                <!-- 智能体推理独白 (R3) -->
                <view class="agent-monologue-card">
                  <view class="monologue-head">
                    <text class="monologue-sparkle">💡</text>
                    <text class="monologue-title">建造师推理独白 (PlanBuilder Agent Thought)</text>
                  </view>
                  <text class="monologue-text">{{ agentThoughts.planBuilder }}</text>
                </view>

                <view class="tools-flow">
                  <!-- 工具节点: compose_deliverable -->
                  <view class="tool-node" :class="'node-' + planBuilderTools.composeDeliverable.status">
                    <view class="node-connector-dot"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">compose_deliverable</text>
                          <text class="tool-cn-name">方案聚合装配</text>
                        </view>
                        <view class="node-tags-group">
                          <text class="latency-badge tabular-num">{{ toolLatencies.composeDeliverable }}</text>
                          <view class="node-status-tag" :class="planBuilderTools.composeDeliverable.status">
                            {{ formatToolStatus(planBuilderTools.composeDeliverable.status, 'composeDeliverable') }}
                          </view>
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tIdx) in parseParamsTokens(planBuilderTools.composeDeliverable.params, 'composeDeliverable')" :key="tIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <view v-if="planBuilderTools.composeDeliverable.result" class="result-box">
                        <text class="result-text">✅ 已成功从多智能体回放提取全部事实，装配成五页大字适老就医计划书</text>
                      </view>
                    </view>
                  </view>

                  <!-- ================= 终极产物叶子节点：可点击计划书 Artifact (R2/R3) ================= -->
                  <view
                    class="artifact-leaf-node"
                    :class="{ 'is-ready': isArtifactReady, 'is-dimmed': !isArtifactReady }"
                    @tap="openArtifactModal"
                  >
                    <view class="leaf-glow"></view>
                    <view class="leaf-head">
                      <view class="leaf-icon-badge">
                        <text class="leaf-icon">📄</text>
                      </view>
                      <view class="leaf-info">
                        <view class="leaf-title-row">
                          <text class="leaf-title">《五页就医出行计划书》</text>
                          <text class="leaf-tag">可打印适老大字版</text>
                        </view>
                        <text class="leaf-desc">挂号凭证 · 高铁车次 · 适老酒店 · 携带清单 · 天气预警</text>
                      </view>
                      <view class="leaf-action-badge" :class="{ 'badge-ready': isArtifactReady }">
                        <text class="leaf-action-text">{{ isArtifactReady ? '点击预览 🔍' : '等待装配 ⏳' }}</text>
                      </view>
                    </view>
                  </view>

                </view>
              </view>
            </view>
          </view>

        </view>

      </view>
    </scroll-view>

    <!-- 交付物全屏交互弹窗 (Artifact Modal) -->
    <view v-if="showArtifactModal" class="artifact-modal-mask" @tap="showArtifactModal = false">
      <view class="artifact-modal" @tap.stop>
        <view class="artifact-modal-header">
          <view class="header-main-box">
            <text class="modal-title">📄 就医出行计划书 (可打印适老大字版)</text>
            <text class="modal-sub">由老友记主调度协同安康助手与银发导航自动生成 · 4/4 阶段全部闭环</text>
          </view>
          <button class="modal-close-btn" @tap="showArtifactModal = false">✕</button>
        </view>
        <scroll-view class="artifact-modal-body" scroll-y>
          <view class="plan-page-card" v-for="(p, pIdx) in artifactPages" :key="pIdx">
            <view class="page-card-head">
              <text class="page-badge tabular-num">第 {{ pIdx + 1 }} 页</text>
              <text class="page-title">{{ p.title }}</text>
            </view>
            <view class="page-rows">
              <view v-for="(row, rIdx) in p.rows" :key="rIdx" class="page-row">
                <text class="row-label">{{ row.label }}</text>
                <text class="row-val tabular-num">{{ row.val }}</text>
              </view>
            </view>
            <view v-if="p.note" class="page-note">
              <text class="note-icon">💡</text>
              <text class="note-text">{{ p.note }}</text>
            </view>
          </view>
        </scroll-view>
        <view class="artifact-modal-footer">
          <button class="footer-btn secondary" @tap="readAloud">🔊 大字朗读</button>
          <button class="footer-btn primary" @tap="simulatePrint">🖨️ 无线打印</button>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
export default {
  name: 'AgentExecutionTree',
  props: {
    messages: { type: Array, default: () => [] },
    thinking: { type: Boolean, default: false },
    currentAgent: { type: String, default: '' },
    sessionId: { type: String, default: '' },
    user: { type: Object, default: () => null },
    isDesktop: { type: Boolean, default: true },
  },
  emits: ['close', 'resolve-confirmation', 'preview-card'],
  data() {
    return {
      rootThinking: false,
      collapsedAgents: {
        health: false,
        travel: false,
        community: false,
        safety: false,
        planBuilder: false,
      },
      showArtifactModal: false,
      // 演示覆盖状态
      demoModeActive: false,
      demoApprovals: {
        appointment: false,
        ticket: false,
        hotel: false,
      },
      // 动态演播全链路状态 (R3)
      replay: {
        active: false,
        playing: false,
        step: 0, // 0 到 5 阶段
        timer: null,
      },
      expandedToolResults: {},
    }
  },
  mounted() {
    if (typeof document !== 'undefined') {
      this._onVisChange = () => {
        if (document.hidden && this.replay && this.replay.playing) {
          this.pauseReplay()
        }
      }
      document.addEventListener('visibilitychange', this._onVisChange)
    }
  },
  beforeUnmount() {
    if (this.replay.timer) {
      clearInterval(this.replay.timer)
      this.replay.timer = null
    }
    if (typeof document !== 'undefined' && this._onVisChange) {
      document.removeEventListener('visibilitychange', this._onVisChange)
    }
  },
  computed: {
    allExpanded: {
      get() {
        return (
          !this.collapsedAgents.health &&
          !this.collapsedAgents.travel &&
          !this.collapsedAgents.community &&
          !this.collapsedAgents.safety &&
          !this.collapsedAgents.planBuilder
        )
      },
      set(val) {
        this.collapsedAgents.health = !val
        this.collapsedAgents.travel = !val
        this.collapsedAgents.community = !val
        this.collapsedAgents.safety = !val
        this.collapsedAgents.planBuilder = !val
      },
    },

    hasTaskStarted() {
      if (this.replay.active || this.demoModeActive) return true
      const msgs = this.messages || []
      return msgs.some(
        (m) =>
          m.isUser ||
          m.kind === 'tool' ||
          m.kind === 'suspend' ||
          (m.kind === 'todo' && Array.isArray(m.todos) && m.todos.length > 0) ||
          m.kind === 'card',
      )
    },

    hasAnyRejected() {
      if (this.replay.active) return false
      if (
        this.demoApprovals.appointment === 'rejected' ||
        this.demoApprovals.ticket === 'rejected' ||
        this.demoApprovals.hotel === 'rejected'
      ) {
        return true
      }
      return (this.messages || []).some(
        (m) => m.kind === 'suspend' && m.status === 'rejected',
      )
    },

    pendingTasksCount() {
      if (this.replay.active) {
        if (this.replay.step === 3) return 3
        return 0
      }
      let count = 0
      if (this.healthTools.registerAppointment.status === 'suspended') count++
      if (this.travelTools.bookTicket.status === 'suspended') count++
      if (this.travelTools.bookHotel.status === 'suspended') count++
      return count
    },

    activeAgentsCount() {
      if (!this.hasTaskStarted) return 0
      return 4
    },

    totalToolsCount() {
      if (!this.hasTaskStarted) return 0
      return 8
    },

    globalStatusText() {
      if (this.replay.active) {
        return `演播全链路中 · 第 ${this.replay.step}/5 阶段`
      }
      if (this.thinking || this.rootThinking) return 'LLM 正在并行规划推理'
      if (this.pendingTasksCount > 0) return '高危操作等待子女端审批'
      if (this.hasAnyRejected) return '高危操作已被子女拒绝拦截'
      if (this.isArtifactReady) return '执行闭环 · 计划书交付完毕'
      if (this.hasTaskStarted) return '四阶段流水线协同进行中'
      return '协同网络就绪 · 随时待命'
    },

    globalStatusClass() {
      if (this.replay.active) return 'status-thinking'
      if (this.thinking || this.rootThinking) return 'status-thinking'
      if (this.pendingTasksCount > 0) return 'status-suspended'
      if (this.hasAnyRejected) return 'status-rejected'
      if (this.isArtifactReady) return 'status-completed'
      if (this.hasTaskStarted) return 'status-thinking'
      return 'status-ready'
    },

    isAnyAgentActive() {
      return this.replay.active || this.thinking || this.rootThinking || this.pendingTasksCount > 0 || this.hasTaskStarted
    },

    rootStatusClass() {
      if (this.replay.active) {
        return this.replay.step === 0 ? 'status-thinking' : 'status-completed'
      }
      if (this.thinking || this.rootThinking) return 'status-thinking'
      if (this.hasAnyRejected) return 'status-rejected'
      if (this.isArtifactReady) return 'status-completed'
      if (this.hasTaskStarted) return 'status-thinking'
      return 'status-ready'
    },

    rootStatusIcon() {
      if (this.replay.active) {
        return this.replay.step === 0 ? '⚡' : '✅'
      }
      if (this.thinking || this.rootThinking) return '⚡'
      if (this.hasAnyRejected) return '🛑'
      if (this.isArtifactReady) return '✅'
      return '🎯'
    },

    rootStatusText() {
      if (this.replay.active) {
        return this.replay.step === 0 ? '意图分析与全局编排中' : '全局任务规划完成'
      }
      if (this.thinking || this.rootThinking) return '意图拆解与全局调度中'
      if (this.hasAnyRejected) return '局部流程已由家人终止'
      if (this.isArtifactReady) return '全链路执行完毕'
      if (this.hasTaskStarted) return '调度执行中'
      return '主调度就绪 · 等待老人诉求'
    },

    currentScenarioTag() {
      if (!this.hasTaskStarted) return '待命中'
      return '跨城异地就医全闭环'
    },

    currentIntentText() {
      const userMsgs = (this.messages || []).filter((m) => m.isUser && m.text)
      if (userMsgs.length > 0) {
        const last = userMsgs[userMsgs.length - 1].text
        return `解析老人诉求："${last}" · 编排拆解三甲挂号、往返高铁、适老酒店及交付大字计划书`
      }
      if (this.replay.active || this.demoModeActive) {
        return '老人诉求："我想去北京看腿疼的老毛病" ➔ 拆解为权威骨科挂号、G102高铁订票、积水潭适老酒店及五页就医出行方案'
      }
      return '等待长辈输入诉求… 可按住说话或打字告诉老友记，主调度将实时理解意图并下发协同网络。'
    },

    // 演播当前步骤说明 (R3)
    currentReplayStepInfo() {
      const steps = [
        {
          num: '0/5',
          title: '老友记总调度：意图拆解与全局任务编排',
          desc: '总调度 Orchestrator 感知老人诉求，分解为医院挂号、高铁、适老酒店及计划书 4 阶段流水线',
          icon: '🎯'
        },
        {
          num: '1/5',
          title: '安康助手：权威专家号源智能匹配',
          desc: '健康智能体启动 search_hospital，锁定北京积水潭医院骨科田伟主任医师号源',
          icon: '🏥'
        },
        {
          num: '2/5',
          title: '银发导航：高铁车次与适老无障碍酒店检索',
          desc: '并发执行 search_train 与 search_hotel，锁定 G102 次适老车厢与漫心无障碍酒店',
          icon: '🧭'
        },
        {
          num: '3/5',
          title: '安全防护网：高危拦截与强行挂起保护',
          desc: '触发资金医疗安全防线（挂号¥100 + 高铁¥443.50 + 酒店¥680），已向子女端发送审批请求',
          icon: '🛡️'
        },
        {
          num: '4/5',
          title: '双向回路：子女端审批放行 (Loopback)',
          desc: '模拟子女手机端通过 3 项核准，工具状态立即转为已完成/已出票/已预约，闭环放行',
          icon: '⚡'
        },
        {
          num: '5/5',
          title: '方案建造师：五页大字就医出行计划书装配',
          desc: '汇总挂号凭证、车次、酒店及携带清单，成功生成《就医出行计划书》，流水线 4/4 阶段全部达成！',
          icon: '📄'
        },
      ]
      return steps[this.replay.step] || steps[0]
    },

    // 智能体推理独白文本 (R3)
    agentThoughts() {
      return {
        orchestrator: '针对长辈主诉"去北京看腿疼老毛病"，总调度启动跨城异地就医多智能体并行编排：分发骨科名医筛查至安康助手，往返高铁与适老住宿派发至银发导航，全流程注入安全护栏防线。',
        health: '老人腿痛初筛为膝关节退行性病变。锁定全国骨科标杆北京积水潭医院（国家骨科医学中心），优选关节外科田伟主任医师周二上午专家号，提示携带既往病历与X光片。',
        travel: '配合田主任上午就诊时序，优选南京南站始发 G102 次清晨高铁（08:15开，12:30到，配置无障碍设施）。选定距门诊450米的漫心适老酒店无障碍房，配备应急呼叫与安全扶手。',
        community: '考虑到老人异地就医独行困难，主动匹配三甲医院持证陪诊员，预约北京南站轮椅接站进出站服务，提供全流程代取药与就医引导。',
        safety: '依据金融与医疗双重风控机制，门诊挂号费(¥100.00)、高铁票款(¥443.50)及酒店住宿费(¥680.00)单次超额，触发强行挂起保护，已将工单推至子女手机端待批。',
        planBuilder: '汇总各子智能体返回的凭证号源与执行事实，经过去重与交叉校验，最终组装输出五页大字可读、可打印、可语音播报的《异地就医出行全套方案》。',
      }
    },

    toolLatencies() {
      return {
        searchHospital: '⚡ 240ms',
        registerAppointment: '⚡ 380ms',
        searchTrain: '⚡ 190ms',
        bookTicket: '⚡ 420ms',
        searchHotel: '⚡ 210ms',
        bookHotel: '⚡ 350ms',
        getWeather: '⚡ 120ms',
        orderService: '⚡ 160ms',
        composeDeliverable: '⚡ 310ms',
      }
    },

    // DAG 前沿活跃判断 (R3)
    isRootFrontier() {
      if (this.replay.active) return this.replay.step === 0
      return this.thinking || this.rootThinking
    },
    isRootDone() {
      if (this.replay.active) return this.replay.step >= 1
      return this.hasTaskStarted && !this.thinking
    },
    isHealthFrontier() {
      if (this.replay.active) return this.replay.step === 1
      return this.healthStatusClass === 'status-thinking' || this.healthStatusClass === 'status-suspended'
    },
    isTravelFrontier() {
      if (this.replay.active) return this.replay.step === 2
      return this.travelStatusClass === 'status-thinking' || this.travelStatusClass === 'status-suspended'
    },
    isCommunityFrontier() {
      if (this.replay.active) return this.replay.step === 2
      return this.communityStatusClass === 'status-thinking'
    },
    isSafetyFrontier() {
      if (this.replay.active) return this.replay.step === 3
      return this.pendingTasksCount > 0
    },
    isSafetyActive() {
      if (this.replay.active) return this.replay.step >= 3
      return this.pendingTasksCount > 0 || this.hasAnyRejected
    },
    isPlanBuilderFrontier() {
      if (this.replay.active) return this.replay.step === 4
      return this.planBuilderStatusClass === 'status-thinking'
    },
    isPlanBuilderActive() {
      if (this.replay.active) return this.replay.step >= 4
      return this.planBuilderStatusClass === 'status-thinking' || this.planBuilderStatusClass === 'status-completed'
    },

    safetyStatusClass() {
      if (this.replay.active) {
        if (this.replay.step === 3) return 'status-suspended'
        if (this.replay.step >= 4) return 'status-completed'
        return 'status-ready'
      }
      if (this.pendingTasksCount > 0) return 'status-suspended'
      if (this.hasAnyRejected) return 'status-rejected'
      if (this.isArtifactReady || (this.hasTaskStarted && this.pendingTasksCount === 0)) return 'status-completed'
      return 'status-ready'
    },
    safetyStatusIcon() {
      if (this.replay.active) {
        if (this.replay.step === 3) return '⏸️'
        if (this.replay.step >= 4) return '✅'
        return '🛡️'
      }
      if (this.pendingTasksCount > 0) return '⏸️'
      if (this.hasAnyRejected) return '🛑'
      if (this.isArtifactReady) return '✅'
      return '🛡️'
    },
    safetyStatusText() {
      if (this.replay.active) {
        if (this.replay.step === 3) return '3项高危拦截待批'
        if (this.replay.step >= 4) return '双向回路放行完成'
        return '安全防线待命'
      }
      if (this.pendingTasksCount > 0) return `${this.pendingTasksCount}项高危待批`
      if (this.hasAnyRejected) return '已拦截终止'
      if (this.isArtifactReady || (this.hasTaskStarted && this.pendingTasksCount === 0)) return '安全闭环放行'
      return '安全防线待命'
    },

    // 任务流水线 4 个阶段：解决“阶段3-4”Bug与动态状态机同步 (R2)
    displaySteps() {
      // 1. 演播模式
      if (this.replay && this.replay.active) {
        const step = this.replay.step
        return [
          {
            name: '选医院挂专家号',
            status: step >= 4 ? 'completed' : (step === 3 ? 'suspended' : (step >= 1 ? 'in_progress' : 'pending')),
          },
          {
            name: '查高铁车次及订票',
            status: step >= 4 ? 'completed' : (step === 3 ? 'suspended' : (step >= 2 ? 'in_progress' : 'pending')),
          },
          {
            name: '订适老无障碍酒店',
            status: step >= 4 ? 'completed' : (step === 3 ? 'suspended' : (step >= 2 ? 'in_progress' : 'pending')),
          },
          {
            name: '聚合装配计划书',
            status: step >= 5 ? 'completed' : (step >= 4 ? 'in_progress' : 'pending'),
          },
        ]
      }

      // 2. 解析最新 todo 快照（取 messages 中最后一个 kind === 'todo'） (R2)
      const todoMsgs = (this.messages || []).filter((m) => m.kind === 'todo' && Array.isArray(m.todos) && m.todos.length > 0)
      const todoMsg = todoMsgs.length > 0 ? todoMsgs[todoMsgs.length - 1] : null

      const fallbackTitles = [
        '选医院挂专家号',
        '查高铁车次及订票',
        '订适老无障碍酒店',
        '聚合装配计划书',
      ]

      if (todoMsg && todoMsg.todos.length > 0) {
        return todoMsg.todos.map((t, idx) => {
          let st = t.status || 'in_progress'
          // 读取 t.content || t.text || t.title，杜绝“阶段 3/4”占位 (R2)
          const rawName = (t.content || t.text || t.title || '').trim()
          const name = rawName || fallbackTitles[idx] || `阶段 ${idx + 1}`

          // 动态同步里程碑状态
          const isStage1 = idx === 0 || name.includes('挂号') || name.includes('医院') || name.includes('专家')
          const isStage2 = idx === 1 || name.includes('车次') || name.includes('车票') || name.includes('高铁') || name.includes('订票')
          const isStage3 = idx === 2 || name.includes('酒店') || name.includes('住宿')
          const isStage4 = idx === 3 || name.includes('计划书') || name.includes('装配') || name.includes('聚合') || name.includes('出行方案')

          if (isStage1) {
            if (this.healthTools.registerAppointment.status === 'executed') st = 'completed'
            else if (this.healthTools.registerAppointment.status === 'rejected') st = 'rejected'
            else if (this.healthTools.registerAppointment.status === 'suspended') st = 'suspended'
            else if (this.healthTools.searchHospital.status === 'completed' && !this.thinking) st = 'completed'
          } else if (isStage2) {
            if (this.travelTools.bookTicket.status === 'executed') st = 'completed'
            else if (this.travelTools.bookTicket.status === 'rejected') st = 'rejected'
            else if (this.travelTools.bookTicket.status === 'suspended') st = 'suspended'
            else if (this.travelTools.searchTrain.status === 'completed' && this.travelTools.bookTicket.status !== 'suspended' && !this.thinking) st = 'completed'
          } else if (isStage3) {
            if (this.travelTools.bookHotel.status === 'executed') st = 'completed'
            else if (this.travelTools.bookHotel.status === 'rejected') st = 'rejected'
            else if (this.travelTools.bookHotel.status === 'suspended') st = 'suspended'
            else if (this.travelTools.searchHotel.status === 'completed' && this.travelTools.bookHotel.status !== 'suspended' && !this.thinking) st = 'completed'
          } else if (isStage4) {
            if (this.isArtifactReady) st = 'completed'
            else if (this.hasAnyRejected) st = 'rejected'
            else if (this.healthTools.registerAppointment.status === 'executed' && this.travelTools.bookTicket.status === 'executed' && this.travelTools.bookHotel.status === 'executed') st = 'completed'
          }

          return {
            name,
            status: st,
          }
        })
      }

      // 3. 演示模式
      if (this.demoModeActive) {
        const hEx = this.demoApprovals.appointment === true
        const tEx = this.demoApprovals.ticket === true
        const hoEx = this.demoApprovals.hotel === true
        return [
          {
            name: '选医院挂专家号',
            status: hEx ? 'completed' : (this.demoApprovals.appointment === 'rejected' ? 'rejected' : 'suspended'),
          },
          {
            name: '查高铁车次及订票',
            status: tEx ? 'completed' : (this.demoApprovals.ticket === 'rejected' ? 'rejected' : 'suspended'),
          },
          {
            name: '订适老无障碍酒店',
            status: hoEx ? 'completed' : (this.demoApprovals.hotel === 'rejected' ? 'rejected' : 'suspended'),
          },
          {
            name: '聚合装配计划书',
            status: (hEx && tEx && hoEx) || this.isArtifactReady ? 'completed' : (this.hasAnyRejected ? 'rejected' : 'pending'),
          },
        ]
      }

      // 4. 任务未启动时的默认状态
      if (!this.hasTaskStarted) {
        return [
          { name: '选医院挂专家号', status: 'pending' },
          { name: '查高铁车次及订票', status: 'pending' },
          { name: '订适老无障碍酒店', status: 'pending' },
          { name: '聚合装配计划书', status: 'pending' },
        ]
      }

      // 5. 任务进行中动态推导
      const step1Status = this.healthTools.registerAppointment.status === 'executed'
        ? 'completed'
        : (this.healthTools.registerAppointment.status === 'rejected'
          ? 'rejected'
          : (this.healthTools.registerAppointment.status === 'suspended'
            ? 'suspended'
            : (this.thinking ? 'in_progress' : (this.healthTools.searchHospital.status === 'completed' ? 'completed' : 'in_progress'))))

      const step2Status = this.travelTools.bookTicket.status === 'executed'
        ? 'completed'
        : (this.travelTools.bookTicket.status === 'rejected'
          ? 'rejected'
          : (this.travelTools.bookTicket.status === 'suspended'
            ? 'suspended'
            : (this.thinking ? 'in_progress' : (this.travelTools.searchTrain.status === 'completed' ? 'completed' : 'in_progress'))))

      const step3Status = this.travelTools.bookHotel.status === 'executed'
        ? 'completed'
        : (this.travelTools.bookHotel.status === 'rejected'
          ? 'rejected'
          : (this.travelTools.bookHotel.status === 'suspended'
            ? 'suspended'
            : (this.thinking ? 'pending' : (this.travelTools.searchHotel.status === 'completed' ? 'completed' : 'pending'))))

      const step4Status = (this.isArtifactReady || (step1Status === 'completed' && step2Status === 'completed' && step3Status === 'completed'))
        ? 'completed'
        : (this.hasAnyRejected
          ? 'rejected'
          : (this.thinking ? 'in_progress' : 'pending'))

      return [
        { name: '选医院挂专家号', status: step1Status },
        { name: '查高铁车次及订票', status: step2Status },
        { name: '订适老无障碍酒店', status: step3Status },
        { name: '聚合装配计划书', status: step4Status },
      ]
    },

    completedStepsCount() {
      return this.displaySteps.filter((s) => s.status === 'completed').length
    },

    totalStepsCount() {
      return this.displaySteps.length
    },

    // 健康助手工具状态响应
    healthTools() {
      if (this.replay.active) {
        const step = this.replay.step
        let sStatus = step >= 1 ? 'completed' : (step === 0 ? 'running' : 'pending')
        let aStatus = step >= 4 ? 'executed' : (step === 3 ? 'suspended' : (step >= 1 ? 'running' : 'pending'))
        return {
          searchHospital: {
            status: sStatus,
            params: 'hospital: "北京积水潭医院", symptom: "骨科/腿疼", grade: "三甲专科"',
            result: '北京积水潭医院骨科 · 田伟主任医师（国家骨科医学中心）',
          },
          registerAppointment: {
            status: aStatus,
            confirmationId: 'conf_demo_appoint',
            params: 'doctor: "田伟主任医师", dept: "骨科", fee: 100.0, time: "08:30-09:30"',
            amount: 100.0,
            desc: '已安全拦截高危挂号请求，需子女手机端核准后方可放行挂号',
          },
        }
      }

      const msgs = this.messages || []
      const suspends = msgs.filter((m) => m.kind === 'suspend')
      const appointSuspend = suspends.slice().reverse().find(
        (m) =>
          m.tool === 'register_appointment' ||
          (m.summary && (m.summary.includes('挂号') || m.summary.includes('医院'))) ||
          m.amount === 100,
      )

      const searchHospTool = msgs.slice().reverse().find(
        (m) => m.kind === 'tool' && (m.tool === 'search_hospital' || (m.summary && m.summary.includes('医院'))),
      )
      const appointTool = msgs.slice().reverse().find(
        (m) => m.kind === 'tool' && (m.tool === 'register_appointment' || (m.summary && m.summary.includes('挂号'))),
      )

      let searchStatus = 'pending'
      let searchParams = searchHospTool && searchHospTool.args ? this.formatParams(searchHospTool.args) : ''
      let searchResult = ''

      if (searchHospTool) {
        searchStatus = searchHospTool.status === 'running' ? 'running' : 'completed'
        searchResult = searchHospTool.result || searchHospTool.summary || '北京积水潭医院骨科 · 田伟主任医师'
      } else if (this.demoModeActive) {
        searchStatus = 'completed'
        searchResult = '北京积水潭医院骨科 · 田伟主任医师（国家骨科医学中心）'
      } else if (this.thinking && (this.currentAgent === '安康助手' || this.currentAgent === 'health')) {
        searchStatus = 'running'
      } else if (this.hasTaskStarted && !this.thinking) {
        searchStatus = 'completed'
        searchResult = '北京积水潭医院骨科 · 田伟主任医师（国家骨科医学中心）'
      }

      let appointStatus = 'pending'
      let confId = appointSuspend ? appointSuspend.confirmationId : ''
      let appointParams = appointTool && appointTool.args ? this.formatParams(appointTool.args) : ''
      let appointAmount = appointSuspend ? appointSuspend.amount : 100.0
      let appointDesc = appointSuspend && appointSuspend.message ? appointSuspend.message : ''

      if (appointSuspend) {
        appointStatus = appointSuspend.status || 'pending'
        if (appointStatus === 'pending') {
          if (this.demoApprovals.appointment === true) appointStatus = 'executed'
          else if (this.demoApprovals.appointment === 'rejected') appointStatus = 'rejected'
          else appointStatus = 'suspended'
        }
      } else if (this.demoApprovals.appointment === true) {
        appointStatus = 'executed'
      } else if (this.demoApprovals.appointment === 'rejected') {
        appointStatus = 'rejected'
      } else if (this.demoModeActive) {
        appointStatus = 'suspended'
        confId = 'conf_demo_appoint'
      } else if (this.thinking && (this.currentAgent === '安康助手' || this.currentAgent === 'health')) {
        appointStatus = 'running'
      }

      return {
        searchHospital: {
          status: searchStatus,
          params: searchParams,
          result: searchResult,
        },
        registerAppointment: {
          status: appointStatus,
          confirmationId: confId,
          params: appointParams,
          amount: appointAmount,
          desc: appointDesc,
        },
      }
    },

    healthStatusClass() {
      if (this.replay.active) {
        if (this.replay.step === 1) return 'status-thinking'
        if (this.replay.step === 3) return 'status-suspended'
        if (this.replay.step >= 4) return 'status-completed'
        return 'status-ready'
      }
      if (this.healthTools.registerAppointment.status === 'suspended') return 'status-suspended'
      if (this.healthTools.registerAppointment.status === 'rejected') return 'status-rejected'
      if (this.healthTools.registerAppointment.status === 'executed') return 'status-completed'
      if (this.healthTools.searchHospital.status === 'running' || this.healthTools.registerAppointment.status === 'running') return 'status-thinking'
      if (this.healthTools.searchHospital.status === 'completed') return 'status-completed'
      return 'status-ready'
    },

    healthStatusIcon() {
      if (this.replay.active) {
        if (this.replay.step === 1) return '⚡'
        if (this.replay.step === 3) return '⏸️'
        if (this.replay.step >= 4) return '✅'
        return '🏥'
      }
      if (this.healthTools.registerAppointment.status === 'suspended') return '⏸️'
      if (this.healthTools.registerAppointment.status === 'rejected') return '🛑'
      if (this.healthTools.registerAppointment.status === 'executed' || this.healthTools.searchHospital.status === 'completed') return '✅'
      if (this.healthTools.searchHospital.status === 'running') return '⚡'
      return '🏥'
    },

    healthStatusText() {
      if (this.replay.active) {
        if (this.replay.step === 1) return '积水潭号源检索中'
        if (this.replay.step === 3) return '待子女确认挂号'
        if (this.replay.step >= 4) return '挂号成功 · 已确认'
        return '安康助手待命'
      }
      if (this.healthTools.registerAppointment.status === 'suspended') return '待子女确认挂号'
      if (this.healthTools.registerAppointment.status === 'rejected') return '子女已拒绝挂号'
      if (this.healthTools.registerAppointment.status === 'executed') return '挂号成功 · 已确认'
      if (this.healthTools.searchHospital.status === 'running') return '检索号源中'
      if (this.healthTools.searchHospital.status === 'completed') return '号源检索完成'
      return '健康守护待命'
    },

    // 银发导航工具状态响应
    travelTools() {
      if (this.replay.active) {
        const step = this.replay.step
        let tSearch = step >= 2 ? 'completed' : 'pending'
        let hSearch = step >= 2 ? 'completed' : 'pending'
        let tBook = step >= 4 ? 'executed' : (step === 3 ? 'suspended' : (step === 2 ? 'running' : 'pending'))
        let hBook = step >= 4 ? 'executed' : (step === 3 ? 'suspended' : (step === 2 ? 'running' : 'pending'))
        return {
          searchTrain: {
            status: tSearch,
            params: 'from: "南京南", to: "北京南", date: "明天", seat: "二等座"',
            result: '优选 G102 次 (08:15 - 12:30, 历时4时15分, 余票充裕)',
          },
          bookTicket: {
            status: tBook,
            confirmationId: 'conf_demo_ticket',
            params: 'train: "G102", from: "南京南", to: "北京南", price: 443.50',
            amount: 443.50,
            desc: '高铁票订购款项，已推送子女端审核放行',
          },
          searchHotel: {
            status: hSearch,
            params: 'poi: "北京积水潭医院周边0.5km", barrier_free: true',
            result: '匹配：漫心酒店积水潭店 · 适老无障碍标间 (配备浴室扶手/电梯)',
          },
          bookHotel: {
            status: hBook,
            confirmationId: 'conf_demo_hotel',
            params: 'hotel: "漫心酒店积水潭店", nights: 2, total_amount: 680.0',
            amount: 680.0,
            desc: '酒店预订2晚费用，已报送子女端确认',
          },
          getWeather: {
            status: 'completed',
            params: 'city: "北京", days: 3, elder_comfort_index: true',
            result: '北京晴转多云，18℃~26℃，舒适度优，早晚温差大建议备外套',
          },
        }
      }

      const msgs = this.messages || []
      const suspends = msgs.filter((m) => m.kind === 'suspend')
      const ticketSuspend = suspends.slice().reverse().find(
        (m) =>
          m.tool === 'book_ticket' ||
          (m.summary && (m.summary.includes('车票') || m.summary.includes('高铁') || m.summary.includes('票'))) ||
          m.amount === 443.5,
      )
      const hotelSuspend = suspends.slice().reverse().find(
        (m) =>
          m.tool === 'book_hotel' ||
          (m.summary && (m.summary.includes('酒店') || m.summary.includes('房'))) ||
          m.amount === 680,
      )

      const searchTrainTool = msgs.slice().reverse().find(
        (m) => m.kind === 'tool' && (m.tool === 'search_train' || (m.summary && m.summary.includes('车次'))),
      )
      const bookTicketTool = msgs.slice().reverse().find(
        (m) => m.kind === 'tool' && (m.tool === 'book_ticket' || (m.summary && m.summary.includes('订票'))),
      )
      const searchHotelTool = msgs.slice().reverse().find(
        (m) => m.kind === 'tool' && (m.tool === 'search_hotel' || (m.summary && m.summary.includes('酒店'))),
      )
      const bookHotelTool = msgs.slice().reverse().find(
        (m) => m.kind === 'tool' && (m.tool === 'book_hotel' || (m.summary && m.summary.includes('预订'))),
      )
      const weatherTool = msgs.slice().reverse().find(
        (m) => m.kind === 'tool' && (m.tool === 'get_weather' || (m.summary && m.summary.includes('天气'))),
      )

      let trainStatus = 'pending'
      let trainParams = searchTrainTool && searchTrainTool.args ? this.formatParams(searchTrainTool.args) : ''
      let trainResult = ''
      if (searchTrainTool) {
        trainStatus = searchTrainTool.status === 'running' ? 'running' : 'completed'
        trainResult = searchTrainTool.result || searchTrainTool.summary || '优选 G102 次 (08:15 - 12:30)'
      } else if (this.demoModeActive || (this.hasTaskStarted && !this.thinking)) {
        trainStatus = 'completed'
        trainResult = '优选 G102 次 (08:15 - 12:30, 历时4时15分, 余票充裕)'
      } else if (this.thinking && (this.currentAgent === '银发导航' || this.currentAgent === 'travel')) {
        trainStatus = 'running'
      }

      let ticketStatus = 'pending'
      let ticketConfId = ticketSuspend ? ticketSuspend.confirmationId : ''
      let ticketParams = bookTicketTool && bookTicketTool.args ? this.formatParams(bookTicketTool.args) : ''
      let ticketAmount = ticketSuspend ? ticketSuspend.amount : 443.5
      let ticketDesc = ticketSuspend && ticketSuspend.message ? ticketSuspend.message : ''

      if (ticketSuspend) {
        ticketStatus = ticketSuspend.status || 'pending'
        if (ticketStatus === 'pending') {
          if (this.demoApprovals.ticket === true) ticketStatus = 'executed'
          else if (this.demoApprovals.ticket === 'rejected') ticketStatus = 'rejected'
          else ticketStatus = 'suspended'
        }
      } else if (this.demoApprovals.ticket === true) {
        ticketStatus = 'executed'
      } else if (this.demoApprovals.ticket === 'rejected') {
        ticketStatus = 'rejected'
      } else if (this.demoModeActive) {
        ticketStatus = 'suspended'
        ticketConfId = 'conf_demo_ticket'
      } else if (this.thinking && (this.currentAgent === '银发导航' || this.currentAgent === 'travel')) {
        ticketStatus = 'running'
      }

      let hotelSearchStatus = 'pending'
      let hotelSearchParams = searchHotelTool && searchHotelTool.args ? this.formatParams(searchHotelTool.args) : ''
      let hotelSearchResult = ''
      if (searchHotelTool) {
        hotelSearchStatus = searchHotelTool.status === 'running' ? 'running' : 'completed'
        hotelSearchResult = searchHotelTool.result || searchHotelTool.summary || '匹配漫心酒店积水潭店'
      } else if (this.demoModeActive || (this.hasTaskStarted && !this.thinking)) {
        hotelSearchStatus = 'completed'
        hotelSearchResult = '匹配：漫心酒店积水潭店 · 适老无障碍标间 (配备浴室扶手/电梯)'
      }

      let hotelStatus = 'pending'
      let hotelConfId = hotelSuspend ? hotelSuspend.confirmationId : ''
      let hotelParams = bookHotelTool && bookHotelTool.args ? this.formatParams(bookHotelTool.args) : ''
      let hotelAmount = hotelSuspend ? hotelSuspend.amount : 680.0
      let hotelDesc = hotelSuspend && hotelSuspend.message ? hotelSuspend.message : ''

      if (hotelSuspend) {
        hotelStatus = hotelSuspend.status || 'pending'
        if (hotelStatus === 'pending') {
          if (this.demoApprovals.hotel === true) hotelStatus = 'executed'
          else if (this.demoApprovals.hotel === 'rejected') hotelStatus = 'rejected'
          else hotelStatus = 'suspended'
        }
      } else if (this.demoApprovals.hotel === true) {
        hotelStatus = 'executed'
      } else if (this.demoApprovals.hotel === 'rejected') {
        hotelStatus = 'rejected'
      } else if (this.demoModeActive) {
        hotelStatus = 'suspended'
        hotelConfId = 'conf_demo_hotel'
      }

      let weatherStatus = 'pending'
      let weatherParams = weatherTool && weatherTool.args ? this.formatParams(weatherTool.args) : ''
      let weatherResult = ''
      if (weatherTool) {
        weatherStatus = 'completed'
        weatherResult = weatherTool.result || weatherTool.summary || '北京天气晴好，18~26℃'
      } else if (this.demoModeActive || (this.hasTaskStarted && !this.thinking)) {
        weatherStatus = 'completed'
        weatherResult = '北京晴间多云，气温 18℃~26℃，适老出行指数：优秀'
      }

      return {
        searchTrain: {
          status: trainStatus,
          params: trainParams,
          result: trainResult,
        },
        bookTicket: {
          status: ticketStatus,
          confirmationId: ticketConfId,
          params: ticketParams,
          amount: ticketAmount,
          desc: ticketDesc,
        },
        searchHotel: {
          status: hotelSearchStatus,
          params: hotelSearchParams,
          result: hotelSearchResult,
        },
        bookHotel: {
          status: hotelStatus,
          confirmationId: hotelConfId,
          params: hotelParams,
          amount: hotelAmount,
          desc: hotelDesc,
        },
        getWeather: {
          status: weatherStatus,
          params: weatherParams,
          result: weatherResult,
        },
      }
    },

    travelStatusClass() {
      if (this.replay.active) {
        if (this.replay.step === 2) return 'status-thinking'
        if (this.replay.step === 3) return 'status-suspended'
        if (this.replay.step >= 4) return 'status-completed'
        return 'status-ready'
      }
      if (this.travelTools.bookTicket.status === 'suspended' || this.travelTools.bookHotel.status === 'suspended') {
        return 'status-suspended'
      }
      if (this.travelTools.bookTicket.status === 'rejected' || this.travelTools.bookHotel.status === 'rejected') {
        return 'status-rejected'
      }
      if (this.travelTools.bookTicket.status === 'executed' && this.travelTools.bookHotel.status === 'executed') {
        return 'status-completed'
      }
      if (this.thinking && (this.currentAgent === '银发导航' || this.currentAgent === 'travel')) {
        return 'status-thinking'
      }
      if (this.travelTools.searchTrain.status === 'completed') {
        return 'status-completed'
      }
      return 'status-ready'
    },

    travelStatusIcon() {
      if (this.replay.active) {
        if (this.replay.step === 2) return '⚡'
        if (this.replay.step === 3) return '⏸️'
        if (this.replay.step >= 4) return '✅'
        return '🧭'
      }
      if (this.travelTools.bookTicket.status === 'suspended' || this.travelTools.bookHotel.status === 'suspended') {
        return '⏸️'
      }
      if (this.travelTools.bookTicket.status === 'rejected' || this.travelTools.bookHotel.status === 'rejected') {
        return '🛑'
      }
      if (this.travelTools.bookTicket.status === 'executed' || this.travelTools.searchTrain.status === 'completed') {
        return '✅'
      }
      if (this.thinking) return '⚡'
      return '🧭'
    },

    travelStatusText() {
      if (this.replay.active) {
        if (this.replay.step === 2) return '高铁与酒店规划中'
        if (this.replay.step === 3) return '待子女确认票务酒店'
        if (this.replay.step >= 4) return '车次与酒店均已出票'
        return '银发导航待命'
      }
      if (this.travelTools.bookTicket.status === 'suspended' || this.travelTools.bookHotel.status === 'suspended') {
        return '待子女确认票务酒店'
      }
      if (this.travelTools.bookTicket.status === 'rejected' || this.travelTools.bookHotel.status === 'rejected') {
        return '子女已拒绝出票'
      }
      if (this.travelTools.bookTicket.status === 'executed' && this.travelTools.bookHotel.status === 'executed') {
        return '车次与酒店均已出票'
      }
      if (this.thinking) return '规划路线与车次中'
      if (this.travelTools.searchTrain.status === 'completed') return '行程车次已规划'
      return '银发导航待命'
    },

    // 邻里帮
    communityTools() {
      const msgs = this.messages || []
      const orderTool = msgs.slice().reverse().find(
        (m) => m.kind === 'tool' && (m.tool === 'order_service' || (m.summary && m.summary.includes('陪诊'))),
      )
      let status = 'pending'
      let params = orderTool && orderTool.args ? this.formatParams(orderTool.args) : ''
      if (orderTool) {
        status = orderTool.status === 'running' ? 'running' : 'completed'
      } else if (this.replay.active || this.demoModeActive || (this.hasTaskStarted && !this.thinking)) {
        status = 'completed'
      }
      return {
        orderService: { status, params, result: true },
      }
    },

    communityStatusClass() {
      if (this.communityTools.orderService.status === 'completed') return 'status-completed'
      if (this.communityTools.orderService.status === 'running') return 'status-thinking'
      return 'status-ready'
    },
    communityStatusIcon() {
      if (this.communityTools.orderService.status === 'completed') return '✅'
      if (this.communityTools.orderService.status === 'running') return '⚡'
      return '🏘️'
    },
    communityStatusText() {
      if (this.communityTools.orderService.status === 'completed') return '陪诊服务已待命'
      return '邻里帮待命'
    },

    // 规划建造师
    planBuilderTools() {
      if (this.replay.active) {
        const step = this.replay.step
        let status = step >= 5 ? 'completed' : (step === 4 ? 'running' : 'pending')
        return {
          composeDeliverable: { status, params: 'kind: "trip_plan", sources: ["health", "travel", "community"]', result: status === 'completed' },
        }
      }

      const msgs = this.messages || []
      const hasCard = msgs.some((m) => m.kind === 'card')
      const composeTool = msgs.slice().reverse().find((m) => m.kind === 'tool' && m.tool === 'compose_deliverable')
      let params = composeTool && composeTool.args ? this.formatParams(composeTool.args) : ''

      let status = 'pending'
      if (this.hasAnyRejected) {
        status = 'rejected'
      } else if (hasCard || this.isArtifactReady) {
        status = 'completed'
      } else if (composeTool) {
        status = composeTool.status === 'running' ? 'running' : 'completed'
      } else if (this.demoModeActive) {
        if (this.isArtifactReady) status = 'completed'
        else status = 'pending'
      } else if (this.pendingTasksCount > 0) {
        status = 'pending'
      } else if (this.thinking) {
        status = 'running'
      }

      return {
        composeDeliverable: { status, params, result: status === 'completed' },
      }
    },

    planBuilderStatusClass() {
      if (this.replay.active) {
        if (this.replay.step === 4) return 'status-thinking'
        if (this.replay.step >= 5) return 'status-completed'
        return 'status-ready'
      }
      if (this.planBuilderTools.composeDeliverable.status === 'running') return 'status-thinking'
      if (this.planBuilderTools.composeDeliverable.status === 'rejected') return 'status-rejected'
      if (this.planBuilderTools.composeDeliverable.status === 'completed') return 'status-completed'
      if (this.pendingTasksCount > 0) return 'status-suspended'
      return 'status-ready'
    },
    planBuilderStatusIcon() {
      if (this.replay.active) {
        if (this.replay.step === 4) return '⚡'
        if (this.replay.step >= 5) return '✅'
        return '📐'
      }
      if (this.planBuilderTools.composeDeliverable.status === 'running') return '⚡'
      if (this.planBuilderTools.composeDeliverable.status === 'rejected') return '🛑'
      if (this.planBuilderTools.composeDeliverable.status === 'completed') return '✅'
      if (this.pendingTasksCount > 0) return '⏸️'
      return '📐'
    },
    planBuilderStatusText() {
      if (this.replay.active) {
        if (this.replay.step === 4) return '装配计划书中'
        if (this.replay.step >= 5) return '五页计划书装配完成'
        return '方案装配待命'
      }
      if (this.planBuilderTools.composeDeliverable.status === 'running') return '装配计划书中'
      if (this.planBuilderTools.composeDeliverable.status === 'rejected') return '前序审批已拒绝 · 装配终止'
      if (this.planBuilderTools.composeDeliverable.status === 'completed') return '五页计划书装配完成'
      if (this.pendingTasksCount > 0) return '等待前序审批解锁'
      return '方案装配待命'
    },

    isArtifactReady() {
      if (this.replay.active) {
        return this.replay.step >= 5
      }
      const hasCard = (this.messages || []).some((m) => m.kind === 'card')
      if (hasCard) return true
      if (
        this.demoApprovals.appointment === true &&
        this.demoApprovals.ticket === true &&
        this.demoApprovals.hotel === true
      ) {
        return true
      }
      const msgs = this.messages || []
      const suspends = msgs.filter((m) => m.kind === 'suspend')
      if (suspends.length > 0 && suspends.every((m) => m.status === 'executed') && !this.hasAnyRejected && !this.thinking) {
        return true
      }
      if (this.healthTools.registerAppointment.status === 'executed' &&
          this.travelTools.bookTicket.status === 'executed' &&
          this.travelTools.bookHotel.status === 'executed') {
        return true
      }
      return false
    },

    artifactPages() {
      const realCard = (this.messages || []).slice().reverse().find(
        (m) => m.kind === 'card' && Array.isArray(m.sections || m.pages),
      )
      if (realCard) {
        const pages = realCard.pages || realCard.sections || []
        if (pages.length > 0) {
          return pages.map((p, idx) => ({
            title: p.title || p.heading || `第 ${idx + 1} 页`,
            rows: (p.rows || []).map((r) => ({
              label: r.label || r.k || '',
              val: r.val || r.v || r.value || '',
            })),
            note: Array.isArray(p.notes) ? p.notes.join('；') : (p.notes || p.note || ''),
          }))
        }
      }

      return [
        {
          title: '北京积水潭医院专家挂号凭证',
          rows: [
            { label: '就诊医院', val: '北京积水潭医院（新街口院区）' },
            { label: '科室医生', val: '骨科专家门诊 · 田伟 主任医师' },
            { label: '门诊时段', val: '明天上午 08:30 - 09:30' },
            { label: '诊查费用', val: '¥100.00（家人已代付确认）' },
          ],
          note: '就诊当天请携带老人医保卡及既往腿部关节 X 光片。',
        },
        {
          title: '往返高铁车次出行凭证',
          rows: [
            { label: '去程车次', val: 'G102 次 高铁二等座' },
            { label: '发到站点', val: '南京南站 (08:15) ➔ 北京南站 (12:30)' },
            { label: '乘车证件', val: '刷居民身份证直接刷闸进出站' },
            { label: '票价金额', val: '¥443.50（家人已代付确认）' },
          ],
          note: '已申请重点旅客无障碍轮椅进站引导服务，候车室 A12 专区。',
        },
        {
          title: '积水潭漫心适老无障碍酒店',
          rows: [
            { label: '预订酒店', val: '漫心酒店（北京积水潭医院店）' },
            { label: '入住房型', val: '适老无障碍双床房（2晚）' },
            { label: '适老设施', val: '卫浴防滑扶手、紧急呼叫铃、电梯直达' },
            { label: '到院距离', val: '步行 450 米，出南门即达积水潭门诊' },
          ],
          note: '酒店前台已登记老人优先入住及无障碍轮椅借用。',
        },
        {
          title: '随身物品与就医携带清单',
          rows: [
            { label: '必带证件', val: '二代身份证原件、全国医保电子凭证 / 社保卡' },
            { label: '健康病历', val: '既往关节拍片底片、日常用药盒 / 慢病处方本' },
            { label: '常备药品', val: '降压药、硝酸甘油、关节止痛膏贴' },
          ],
          note: '随身小包放随身证件与药盒，大件衣物由家属或陪诊人员协助。',
        },
        {
          title: '目的地出行天气与健康叮嘱',
          rows: [
            { label: '北京天气', val: '晴间多云，气温 18℃ ~ 26℃，微风' },
            { label: '空气质量', val: '优良 (AQI 42)，体感舒适适宜出行' },
            { label: '穿衣建议', val: '轻薄透气棉质长袖，早晚可加一件防风薄外套' },
          ],
          note: '候车室与车厢内冷气较足，上车前请先备好披肩或外套保暖。',
        },
      ]
    },
  },
  methods: {
    formatParams(args, fallback) {
      if (args && typeof args === 'object' && Object.keys(args).length > 0) {
        return Object.entries(args)
          .map(([k, v]) => `${k}: ${typeof v === 'string' ? JSON.stringify(v) : JSON.stringify(v)}`)
          .join(', ')
      }
      return fallback || ''
    },

    parseParamsTokens(params, defaultKey) {
      const DEFAULT_TOOL_PARAMS = {
        searchHospital: 'hospital: "北京积水潭医院", symptom: "骨科/腿疼", grade: "三甲专科"',
        registerAppointment: 'doctor: "田伟主任医师", dept: "骨科", fee: 100.0, time: "08:30-09:30"',
        searchTrain: 'from: "南京南", to: "北京南", date: "明天", seat: "二等座"',
        bookTicket: 'train: "G102", from: "南京南", to: "北京南", price: 443.50',
        searchHotel: 'poi: "北京积水潭医院周边0.5km", barrier_free: true',
        bookHotel: 'hotel: "漫心酒店积水潭店", nights: 2, total_amount: 680.0',
        getWeather: 'city: "北京", days: 3, elder_comfort_index: true',
        orderService: 'service: "异地就医火车站接站+医院全程陪诊", city: "北京"',
        composeDeliverable: 'kind: "trip_plan", sources: ["health", "travel", "community"]',
      }
      if (!params && defaultKey && DEFAULT_TOOL_PARAMS[defaultKey]) {
        params = DEFAULT_TOOL_PARAMS[defaultKey]
      }
      if (!params) return []
      if (typeof params === 'object') {
        return Object.entries(params).map(([k, v], idx, arr) => ({
          k,
          v: typeof v === 'string' ? `"${v}"` : String(v),
          type: typeof v === 'number' ? 'number' : (typeof v === 'boolean' ? 'boolean' : 'string'),
          isLast: idx === arr.length - 1
        }))
      }
      const parts = String(params).split(/,\s*(?=[a-zA-Z0-9_]+\s*:)/)
      return parts.map((part, idx) => {
        const colonIdx = part.indexOf(':')
        if (colonIdx !== -1) {
          const k = part.slice(0, colonIdx).trim().replace(/^['"]|['"]$/g, '')
          const rawV = part.slice(colonIdx + 1).trim()
          let type = 'string'
          if (/^-?\d+(\.\d+)?$/.test(rawV)) type = 'number'
          else if (rawV === 'true' || rawV === 'false') type = 'boolean'
          return {
            k,
            v: rawV,
            type,
            isLast: idx === parts.length - 1
          }
        }
        return {
          k: 'arg',
          v: part.trim(),
          type: 'string',
          isLast: idx === parts.length - 1
        }
      })
    },

    toggleToolResultExpand(key) {
      this.expandedToolResults = {
        ...this.expandedToolResults,
        [key]: !this.expandedToolResults[key]
      }
    },

    isToolResultExpanded(key) {
      return !!this.expandedToolResults[key]
    },

    toggleAllExpanded() {
      this.allExpanded = !this.allExpanded
    },

    toggleAgentCollapse(agentKey) {
      this.collapsedAgents[agentKey] = !this.collapsedAgents[agentKey]
    },

    formatStepStatus(status) {
      switch (status) {
        case 'completed':
        case 'executed':
          return '✅ 已完成'
        case 'suspended':
          return '⏸️ 待审批'
        case 'in_progress':
        case 'running':
          return '⚡ 执行中'
        case 'rejected':
          return '🛑 已拦截'
        case 'pending':
        default:
          return '⏳ 待启动'
      }
    },

    formatToolStatus(status, toolKey = '') {
      const k = String(toolKey || '').toLowerCase()
      switch (status) {
        case 'completed':
        case 'executed':
          if (k.includes('appoint') || k.includes('register')) return '已预约 ✅'
          if (k.includes('ticket')) return '已出票 ✅'
          if (k.includes('hotel') && (k.includes('book') || status === 'executed')) return '已预订 ✅'
          if (k.includes('compose') || k.includes('deliverable')) return '已装配 ✅'
          return '已完成 ✅'
        case 'suspended':
          return '⏸️ 待确认'
        case 'running':
          return '执行中 ⚡'
        case 'pending':
          return '待调度 ⏳'
        case 'rejected':
          return '已拦截 🛑'
        default:
          return status
      }
    },

    triggerApprove(confirmationId, toolName) {
      // 本地"模拟通过"的状态只对演示卡片（conf_demo_）生效。
      // 真实任务必须等服务端确认（由父组件 await 后才翻卡片），
      // 否则这里先把界面翻绿、服务端却 403，界面就在替家人撒谎。
      const isDemo = !confirmationId || confirmationId.startsWith('conf_demo_')
      if (isDemo) {
        if ((confirmationId && (confirmationId.includes('appoint') || confirmationId.includes('health'))) || toolName === 'register_appointment') {
          this.demoApprovals.appointment = true
        } else if ((confirmationId && confirmationId.includes('ticket')) || toolName === 'book_ticket') {
          this.demoApprovals.ticket = true
        } else if ((confirmationId && confirmationId.includes('hotel')) || toolName === 'book_hotel') {
          this.demoApprovals.hotel = true
        }
      }
      this.$emit('resolve-confirmation', {
        confirmationId,
        tool: toolName,
        status: 'executed',
      })
      if (isDemo) {
        uni.showToast({ title: '已模拟子女端审核同意！', icon: 'success' })
      }
    },

    triggerReject(confirmationId, toolName) {
      const isDemo = !confirmationId || confirmationId.startsWith('conf_demo_')
      if (isDemo) {
        if ((confirmationId && (confirmationId.includes('appoint') || confirmationId.includes('health'))) || toolName === 'register_appointment') {
          this.demoApprovals.appointment = 'rejected'
        } else if ((confirmationId && confirmationId.includes('ticket')) || toolName === 'book_ticket') {
          this.demoApprovals.ticket = 'rejected'
        } else if ((confirmationId && confirmationId.includes('hotel')) || toolName === 'book_hotel') {
          this.demoApprovals.hotel = 'rejected'
        }
      }
      this.$emit('resolve-confirmation', {
        confirmationId,
        tool: toolName,
        status: 'rejected',
      })
      if (isDemo) {
        uni.showToast({ title: '已模拟子女端拒绝该操作', icon: 'none' })
      }
    },

    approveAllPending() {
      if (this.replay.active) {
        this.seekReplay(4)
      }
      this.triggerApprove(this.healthTools.registerAppointment.confirmationId || 'conf_demo_appoint', 'register_appointment')
      this.triggerApprove(this.travelTools.bookTicket.confirmationId || 'conf_demo_ticket', 'book_ticket')
      this.triggerApprove(this.travelTools.bookHotel.confirmationId || 'conf_demo_hotel', 'book_hotel')
      uni.showToast({ title: '已模拟子女端一键核准全部 3 项操作！', icon: 'success' })
    },

    // 动态演播全链路机制 (R3)
    toggleReplayMode() {
      if (!this.replay.active) {
        this.startReplay()
      } else {
        this.toggleReplayPlay()
      }
    },

    startReplay() {
      this.replay.active = true
      this.replay.playing = true
      this.replay.step = 0
      this.allExpanded = true
      if (this.replay.timer) clearInterval(this.replay.timer)
      this.replay.timer = setInterval(() => {
        if (this.replay.step < 5) {
          this.replay.step++
        } else {
          this.pauseReplay()
        }
      }, 2200)
      uni.showToast({ title: '已开启动态演播全链路 ✨', icon: 'none' })
    },

    pauseReplay() {
      this.replay.playing = false
      if (this.replay.timer) {
        clearInterval(this.replay.timer)
        this.replay.timer = null
      }
    },

    resumeReplay() {
      if (this.replay.step >= 5) this.replay.step = 0
      this.replay.playing = true
      if (this.replay.timer) clearInterval(this.replay.timer)
      this.replay.timer = setInterval(() => {
        if (this.replay.step < 5) {
          this.replay.step++
        } else {
          this.pauseReplay()
        }
      }, 2200)
    },

    toggleReplayPlay() {
      if (this.replay.playing) {
        this.pauseReplay()
      } else {
        this.resumeReplay()
      }
    },

    nextReplayStep() {
      this.pauseReplay()
      if (this.replay.step < 5) this.replay.step++
    },

    prevReplayStep() {
      this.pauseReplay()
      if (this.replay.step > 0) this.replay.step--
    },

    resetReplay() {
      this.replay.step = 0
      this.pauseReplay()
      uni.showToast({ title: '演播已重置至阶段 0', icon: 'none' })
    },

    seekReplay(step) {
      this.pauseReplay()
      this.replay.step = step
    },

    exitReplay() {
      this.pauseReplay()
      this.replay.active = false
      this.replay.step = 0
      uni.showToast({ title: '已退出演播，切回实时状态', icon: 'none' })
    },

    scrollToSection(id) {
      if (id === 'health') this.collapsedAgents.health = false
      if (id === 'travel') this.collapsedAgents.travel = false
      if (id === 'community') this.collapsedAgents.community = false
      if (id === 'safety') this.collapsedAgents.safety = false
      if (id === 'planBuilder') this.collapsedAgents.planBuilder = false
      uni.showToast({ title: `已定位至智能体：${id}`, icon: 'none' })
    },

    openArtifactModal() {
      if (!this.isArtifactReady) {
        uni.showToast({ title: '多智能体尚未完成方案装配，请稍候…', icon: 'none' })
        return
      }
      this.showArtifactModal = true
    },

    readAloud() {
      uni.showToast({ title: '正在为您大字朗读《就医出行计划书》…', icon: 'none' })
    },

    simulatePrint() {
      uni.showToast({ title: '已发送至大字无线打印机！', icon: 'success' })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.agent-tree-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  flex: 1;
  min-height: 0;
  background: #f8fafc;
  color: #0f172a;
  border-left: 2rpx solid #e2e8f0;
  box-sizing: border-box;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}

/* 顶部工作台标题栏 */
.tree-header {
  padding: 22rpx 26rpx;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  row-gap: 12rpx;
  column-gap: 16rpx;
  box-shadow: 0 4rpx 16rpx rgba(15, 23, 42, 0.12);
  flex-shrink: 0;
  z-index: 5;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.tree-title-icon {
  font-size: 40rpx;
  line-height: 1;
}

.title-group {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.tree-main-title {
  font-size: 34rpx;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #ffffff;
}

.tree-sub-title {
  font-size: 22rpx;
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.header-right {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10rpx;
}

.global-status-pill {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  padding: 8rpx 20rpx;
  border-radius: 999rpx;
  font-size: 22rpx;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.1);
  border: 1rpx solid rgba(255, 255, 255, 0.2);
}

.status-pulse-dot {
  width: 14rpx;
  height: 14rpx;
  border-radius: 50%;
  background: #10b981;
}

.global-status-pill.status-thinking {
  background: rgba(59, 130, 246, 0.2);
  border-color: #3b82f6;
  color: #93c5fd;
  .status-pulse-dot {
    background: #3b82f6;
    animation: lyj-pulse-glow 1.5s infinite;
  }
}

.global-status-pill.status-suspended {
  background: rgba(245, 158, 11, 0.25);
  border-color: #f59e0b;
  color: #fcd34d;
  .status-pulse-dot {
    background: #f59e0b;
    animation: lyj-pulse-glow 1.2s infinite;
  }
}

.global-status-pill.status-rejected {
  background: rgba(239, 68, 68, 0.2);
  border-color: #ef4444;
  color: #fca5a5;
  .status-pulse-dot {
    background: #ef4444;
  }
}

.global-status-pill.status-completed {
  background: rgba(16, 185, 129, 0.2);
  border-color: #10b981;
  color: #6ee7b7;
  .status-pulse-dot {
    background: #10b981;
  }
}

.global-status-pill.status-ready {
  background: rgba(255, 255, 255, 0.12);
  color: #e2e8f0;
  .status-pulse-dot {
    background: #10b981;
  }
}

.icon-action-btn {
  min-height: 44px;
  padding: 0 20rpx;
  background: rgba(255, 255, 255, 0.12);
  border: 1rpx solid rgba(255, 255, 255, 0.25);
  border-radius: 12rpx;
  color: #f1f5f9;
  font-size: 24rpx;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  touch-action: manipulation;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  margin: 0;
}

.icon-action-btn:active {
  transform: translateY(1px) scale(0.99);
  background: rgba(255, 255, 255, 0.22);
}

.replay-btn {
  background: #FF6B35;
  border-color: #ff8252;
  color: #ffffff;
  font-weight: 700;
  box-shadow: 0 4rpx 12rpx rgba(255, 107, 53, 0.3);
}

.replay-btn.is-active {
  background: #10b981;
  border-color: #34d399;
}

.close-drawer-btn {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  margin: 0;
  color: #ffffff;
  touch-action: manipulation;
}

.close-icon {
  font-size: 28rpx;
  line-height: 1;
}

/* 拓扑度量信息栏 */
.metrics-bar {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 18rpx 24rpx;
  background: #ffffff;
  border-bottom: 2rpx solid #e2e8f0;
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.02);
  flex-shrink: 0;
}

.metric-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4rpx;
}

.metric-label {
  font-size: 20rpx;
  color: #64748b;
  font-weight: 600;
}

.metric-val {
  font-size: 28rpx;
  font-weight: 800;
  color: #0f172a;
}

.metric-item.has-pending .metric-val {
  color: #d97706;
}

.metric-item.has-rejected .metric-val {
  color: #dc2626;
}

.metric-divider {
  width: 2rpx;
  height: 36rpx;
  background: #e2e8f0;
}

/* 滚动容器 */
.tree-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.tree-canvas {
  padding: 24rpx;
  display: flex;
  flex-direction: column;
  gap: 24rpx;
}

/* ================= 规划 DAG 卡片 (R3) ================= */
.planning-dag-card {
  background: #ffffff;
  border: 2rpx solid #e2e8f0;
  border-radius: 24rpx;
  padding: 24rpx;
  box-shadow: 0 6rpx 20rpx rgba(15, 23, 42, 0.04);
}

.dag-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 20rpx;
  border-bottom: 2rpx solid #f1f5f9;
  flex-wrap: wrap;
  gap: 16rpx;
}

.dag-header-title-box {
  display: flex;
  align-items: flex-start;
  gap: 12rpx;
}

.dag-sparkle {
  font-size: 32rpx;
  line-height: 1.2;
}

.dag-titles {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.dag-main-title {
  font-size: 28rpx;
  font-weight: 800;
  color: #0f172a;
}

.dag-sub-title {
  font-size: 20rpx;
  color: #64748b;
}

.replay-trigger-btn {
  min-height: 44px;
  padding: 0 24rpx;
  background: #FF6B35;
  border: none;
  border-radius: 16rpx;
  color: #ffffff;
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  font-size: 24rpx;
  font-weight: 700;
  cursor: pointer;
  touch-action: manipulation;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 4rpx 14rpx rgba(255, 107, 53, 0.3);
}

.replay-trigger-btn.is-playing {
  background: #10b981;
  box-shadow: 0 4rpx 14rpx rgba(16, 185, 129, 0.3);
}

.replay-trigger-btn:active {
  transform: translateY(1px) scale(0.99);
}

/* 演播控制条 */
.replay-controller-bar {
  margin-top: 20rpx;
  background: #f8fafc;
  border: 2rpx solid #cbd5e1;
  border-radius: 20rpx;
  padding: 20rpx;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  animation: fadeIn 0.3s ease;
}

.replay-narrative {
  display: flex;
  align-items: flex-start;
  gap: 16rpx;
  background: #ffffff;
  padding: 16rpx 20rpx;
  border-radius: 16rpx;
  border: 1rpx solid #e2e8f0;
}

.narrative-tag {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: #FF6B35;
  color: #ffffff;
  padding: 6rpx 14rpx;
  border-radius: 12rpx;
  font-weight: 800;
  flex-shrink: 0;
}

.narrative-step-num {
  font-size: 20rpx;
  line-height: 1.2;
}

.narrative-icon {
  font-size: 26rpx;
  line-height: 1;
}

.narrative-content {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
  flex: 1;
}

.narrative-title {
  font-size: 26rpx;
  font-weight: 800;
  color: #0f172a;
}

.narrative-desc {
  font-size: 22rpx;
  color: #475569;
  line-height: 1.4;
}

.replay-buttons-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12rpx;
}

.ctrl-btn {
  min-height: 44px;
  padding: 0 20rpx;
  background: #ffffff;
  border: 2rpx solid #cbd5e1;
  border-radius: 12rpx;
  color: #334155;
  font-size: 22rpx;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  touch-action: manipulation;
  transition: all 0.15s;
}

.ctrl-btn:active {
  transform: translateY(1px) scale(0.99);
  background: #f1f5f9;
}

.ctrl-btn.primary {
  background: #2563eb;
  border-color: #1d4ed8;
  color: #ffffff;
}

.ctrl-btn.exit {
  background: #f1f5f9;
  color: #64748b;
  margin-left: auto;
}

.replay-progress-track {
  position: relative;
  height: 12rpx;
  background: #e2e8f0;
  border-radius: 999rpx;
  margin: 12rpx 10rpx;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.replay-progress-bar-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  background: #FF6B35;
  border-radius: 999rpx;
  transition: width 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.replay-progress-dot {
  width: 32rpx;
  height: 32rpx;
  border-radius: 50%;
  background: #ffffff;
  border: 4rpx solid #cbd5e1;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2;
  cursor: pointer;
  transition: all 0.2s;
}

.replay-progress-dot .dot-num {
  font-size: 16rpx;
  font-weight: 800;
  color: #64748b;
}

.replay-progress-dot.passed {
  border-color: #FF6B35;
  background: #FF6B35;
  .dot-num { color: #ffffff; }
}

.replay-progress-dot.current {
  border-color: #2563eb;
  background: #2563eb;
  transform: scale(1.2);
  box-shadow: 0 0 12rpx rgba(37, 99, 235, 0.5);
  .dot-num { color: #ffffff; }
}

/* DAG 拓扑节点可视化 */
.dag-canvas-container {
  margin-top: 24rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
}

.dag-node {
  width: 100%;
  box-sizing: border-box;
  padding: 16rpx 20rpx;
  background: #ffffff;
  border: 2rpx solid #cbd5e1;
  border-radius: 18rpx;
  display: flex;
  align-items: center;
  gap: 16rpx;
  cursor: pointer;
  position: relative;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.dag-node:active {
  transform: translateY(1px) scale(0.99);
}

.dag-node.is-frontier {
  border-color: #FF6B35;
  box-shadow: 0 0 18rpx rgba(255, 107, 53, 0.35);
  animation: dag-frontier-pulse 2s infinite;
}

.dag-node.is-completed {
  border-color: #10b981;
}

.dag-node.is-suspended {
  border-color: #f59e0b;
  background: #fffbeb;
}

.dag-node.is-rejected {
  border-color: #ef4444;
  background: #fef2f2;
}

.dag-node-avatar {
  width: 52rpx;
  height: 52rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.dag-avatar-icon {
  font-size: 30rpx;
  line-height: 1;
}

.dag-node-text-group {
  display: flex;
  flex-direction: column;
  gap: 2rpx;
  flex: 1;
}

.dag-node-title {
  font-size: 26rpx;
  font-weight: 800;
  color: #0f172a;
}

.dag-node-role {
  font-size: 20rpx;
  color: #64748b;
}

.dag-node-state-chip {
  padding: 6rpx 14rpx;
  border-radius: 999rpx;
  font-size: 20rpx;
  font-weight: 700;
  background: #f1f5f9;
  color: #475569;
  flex-shrink: 0;
}

.dag-wire-vertical {
  width: 4rpx;
  height: 28rpx;
  background: #cbd5e1;
  position: relative;
}

.dag-wire-vertical.energy-pulse {
  background: linear-gradient(180deg, #FF6B35 0%, #10b981 100%);
  box-shadow: 0 0 8rpx rgba(255, 107, 53, 0.5);
}

.dag-parallel-trunk-label {
  padding: 4rpx 16rpx;
  background: #f1f5f9;
  border: 1rpx solid #e2e8f0;
  border-radius: 999rpx;
  font-size: 18rpx;
  font-weight: 700;
  color: #64748b;
  margin: 4rpx 0;
}

.dag-trunk-bar {
  width: 90%;
  height: 4rpx;
  background: #cbd5e1;
}

.dag-trunk-bar.energy-pulse {
  background: linear-gradient(90deg, #10b981, #FF6B35, #2563eb);
  box-shadow: 0 0 8rpx rgba(255, 107, 53, 0.4);
}

.dag-subagents-grid {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12rpx;
  margin: 12rpx 0;
}

.dag-sub-node {
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 16rpx 8rpx;
  gap: 6rpx;
}

.dag-sub-name {
  font-size: 22rpx;
  font-weight: 800;
  color: #0f172a;
}

.dag-sub-role {
  font-size: 18rpx;
  color: #64748b;
}

.dag-mini-status {
  font-size: 18rpx;
  font-weight: 700;
  padding: 2rpx 10rpx;
  border-radius: 999rpx;
  background: #f1f5f9;
  color: #64748b;
  white-space: nowrap;
}

/* 智能体推理独白卡片 (R3) */
.agent-monologue-card {
  background: #fffbf5;
  border: 2rpx solid #fde68a;
  border-left: 6rpx solid #FF6B35;
  border-radius: 16rpx;
  padding: 16rpx 20rpx;
  margin-top: 16rpx;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}

.monologue-head {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.monologue-sparkle {
  font-size: 24rpx;
}

.monologue-title {
  font-size: 22rpx;
  font-weight: 800;
  color: #92400e;
}

.monologue-text {
  font-size: 22rpx;
  color: #78350f;
  line-height: 1.5;
}

/* 根节点卡片 */
.root-node-card {
  background: #ffffff;
  border: 2rpx solid #e2e8f0;
  border-radius: 24rpx;
  padding: 24rpx;
  box-shadow: 0 4rpx 16rpx rgba(15, 23, 42, 0.04);
  position: relative;
}

.node-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12rpx;
}

.node-badge-group {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.avatar-box {
  width: 64rpx;
  height: 64rpx;
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.avatar-icon {
  font-size: 36rpx;
  line-height: 1;
}

.orchestrator-avatar { background: #ffe4d6; }
.health-avatar { background: #dcfce7; }
.travel-avatar { background: #e0f2fe; }
.community-avatar { background: #ede9fe; }
.safety-avatar { background: #fef3c7; }
.planbuilder-avatar { background: #fce7f3; }
.artifact-avatar { background: #e0e7ff; }

.node-meta {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.node-title-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.node-title {
  font-size: 30rpx;
  font-weight: 800;
  color: #0f172a;
}

.agent-tag-role {
  font-size: 20rpx;
  color: #64748b;
  background: #f1f5f9;
  padding: 2rpx 12rpx;
  border-radius: 999rpx;
}

.node-role-desc {
  font-size: 22rpx;
  color: #64748b;
}

.state-badge {
  display: inline-flex;
  align-items: center;
  gap: 6rpx;
  padding: 6rpx 16rpx;
  border-radius: 999rpx;
  font-size: 22rpx;
  font-weight: 700;
  background: #f1f5f9;
  color: #475569;
}

.state-badge.status-completed {
  background: #dcfce7;
  color: #15803d;
}

.state-badge.status-thinking {
  background: #dbeafe;
  color: #1d4ed8;
}

.state-badge.status-suspended {
  background: #fef3c7;
  color: #b45309;
}

.state-badge.status-rejected {
  background: #fee2e2;
  color: #b91c1c;
}

/* 意图识别框 */
.intent-box {
  margin-top: 20rpx;
  background: #f8fafc;
  border: 2rpx solid #e2e8f0;
  border-radius: 16rpx;
  padding: 16rpx 20rpx;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.intent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.intent-label {
  font-size: 22rpx;
  font-weight: 800;
  color: #0f172a;
}

.intent-tag {
  font-size: 20rpx;
  font-weight: 700;
  background: #fee2e2;
  color: #b91c1c;
  padding: 2rpx 10rpx;
  border-radius: 999rpx;
}

.intent-content {
  font-size: 24rpx;
  color: #334155;
  line-height: 1.5;
}

/* 任务分解流水线 (Todo State Machine) (R2) */
.plan-steps-track {
  margin-top: 20rpx;
  background: #f8fafc;
  border: 2rpx solid #e2e8f0;
  border-radius: 16rpx;
  padding: 16rpx 20rpx;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.track-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.track-title {
  font-size: 24rpx;
  font-weight: 800;
  color: #0f172a;
}

.track-progress {
  font-size: 22rpx;
  font-weight: 800;
  color: #10b981;
}

.steps-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12rpx;
}

.step-chip {
  display: flex;
  align-items: center;
  gap: 10rpx;
  padding: 12rpx 16rpx;
  background: #ffffff;
  border: 2rpx solid #e2e8f0;
  border-radius: 12rpx;
  transition: all 0.2s;
}

.step-chip.step-completed {
  border-color: #10b981;
  background: #f0fdf4;
}

.step-chip.step-suspended {
  border-color: #f59e0b;
  background: #fffbeb;
}

.step-chip.step-rejected {
  border-color: #ef4444;
  background: #fef2f2;
}

.step-chip.step-in_progress {
  border-color: #3b82f6;
  background: #eff6ff;
}

.step-num {
  width: 36rpx;
  height: 36rpx;
  border-radius: 50%;
  background: #e2e8f0;
  color: #475569;
  font-size: 20rpx;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.step-completed .step-num {
  background: #10b981;
  color: #ffffff;
}

.step-name {
  font-size: 22rpx;
  font-weight: 700;
  color: #1e293b;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-status-tag {
  font-size: 20rpx;
  font-weight: 700;
  color: #64748b;
  flex-shrink: 0;
}

.step-completed .step-status-tag { color: #15803d; }
.step-suspended .step-status-tag { color: #b45309; }
.step-rejected .step-status-tag { color: #b91c1c; }
.step-in_progress .step-status-tag { color: #1d4ed8; }

/* 分支干线容器 */
.branch-trunk-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin: 8rpx 0;
}

.trunk-line-vertical {
  width: 4rpx;
  height: 32rpx;
  background: #cbd5e1;
}

.trunk-label-chip {
  padding: 4rpx 20rpx;
  background: #ffffff;
  border: 2rpx solid #e2e8f0;
  border-radius: 999rpx;
  box-shadow: 0 2rpx 6rpx rgba(0,0,0,0.04);
}

.trunk-chip-text {
  font-size: 20rpx;
  font-weight: 700;
  color: #64748b;
}

.trunk-horizontal-bar {
  width: 80%;
  height: 4rpx;
  background: #cbd5e1;
  margin-top: 8rpx;
}

.trunk-line-vertical.flow-active,
.trunk-horizontal-bar.flow-active {
  background: linear-gradient(90deg, #10b981, #FF6B35, #2563eb);
}

/* 子智能体分支容器 */
.subagent-branches-container {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.subagent-branch-card {
  background: #ffffff;
  border: 2rpx solid #e2e8f0;
  border-radius: 20rpx;
  overflow: hidden;
  box-shadow: 0 4rpx 16rpx rgba(15, 23, 42, 0.04);
  transition: all 0.25s;
}

.branch-header {
  padding: 18rpx 24rpx;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  background: #ffffff;
  border-bottom: 2rpx solid #f1f5f9;
}

.branch-header:active {
  background: #f8fafc;
}

.branch-header-left {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.branch-title-group {
  display: flex;
  flex-direction: column;
  gap: 2rpx;
}

.branch-name-row {
  display: flex;
  align-items: baseline;
  gap: 8rpx;
}

.branch-name {
  font-size: 28rpx;
  font-weight: 800;
  color: #0f172a;
}

.branch-en-tag {
  font-size: 20rpx;
  color: #64748b;
}

.branch-desc {
  font-size: 20rpx;
  color: #94a3b8;
}

.branch-header-right {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.accordion-arrow {
  font-size: 22rpx;
  color: #94a3b8;
}

.branch-collapsible {
  max-height: 0;
  overflow: hidden;
  transition: max-height 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.branch-collapsible.is-open {
  max-height: 3000px;
}

.branch-body {
  padding: 20rpx 24rpx;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  background: #f8fafc;
}

/* 工具流水线 */
.tools-flow {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.tool-node {
  background: #ffffff;
  border: 2rpx solid #e2e8f0;
  border-radius: 16rpx;
  padding: 18rpx 20rpx;
  box-shadow: 0 2rpx 8rpx rgba(15, 23, 42, 0.03);
}

.tool-node.node-completed {
  border-left: 6rpx solid #10b981;
}

.tool-node.node-suspended {
  border-left: 6rpx solid #f59e0b;
}

.tool-node.node-rejected {
  border-left: 6rpx solid #ef4444;
}

.tool-node.node-running {
  border-left: 6rpx solid #3b82f6;
}

.node-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12rpx;
}

.node-name-box {
  display: flex;
  align-items: baseline;
  gap: 10rpx;
  flex-wrap: wrap;
}

.tool-fn-name {
  font-size: 24rpx;
  font-weight: 800;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  color: #0f172a;
}

.tool-cn-name {
  font-size: 20rpx;
  color: #64748b;
}

.risk-badge {
  font-size: 18rpx;
  font-weight: 700;
  background: #fef3c7;
  color: #b45309;
  padding: 2rpx 10rpx;
  border-radius: 999rpx;
}

.node-tags-group {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.latency-badge {
  font-size: 20rpx;
  font-weight: 700;
  color: #2563eb;
  background: #eff6ff;
  padding: 2rpx 10rpx;
  border-radius: 8rpx;
}

.node-status-tag {
  font-size: 20rpx;
  font-weight: 700;
  padding: 2rpx 12rpx;
  border-radius: 999rpx;
  background: #f1f5f9;
  color: #64748b;
}

.node-status-tag.completed, .node-status-tag.executed {
  background: #dcfce7;
  color: #15803d;
}

.node-status-tag.suspended {
  background: #fef3c7;
  color: #b45309;
}

.node-status-tag.rejected {
  background: #fee2e2;
  color: #b91c1c;
}

.node-status-tag.running {
  background: #dbeafe;
  color: #1d4ed8;
}

/* 参数 JSON 高亮 (R3) */
.mono-params-box {
  background: #0f172a;
  border-radius: 12rpx;
  padding: 12rpx 16rpx;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}

.params-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1rpx solid rgba(255, 255, 255, 0.1);
  padding-bottom: 4rpx;
}

.params-lang-label {
  font-size: 18rpx;
  font-weight: 700;
  color: #94a3b8;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.params-copy-hint {
  font-size: 18rpx;
  color: #64748b;
}

.mono-code-tokens {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 22rpx;
  line-height: 1.4;
  color: #f8fafc;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  column-gap: 8rpx;
  row-gap: 2rpx;
}

.token-brace {
  color: #94a3b8;
}

.token-item {
  display: inline-flex;
  align-items: center;
}

.tok-key {
  color: #60a5fa;
}

.tok-colon {
  color: #94a3b8;
}

.tok-val.val-string {
  color: #34d399;
}

.tok-val.val-number {
  color: #fbbf24;
}

.tok-val.val-boolean {
  color: #f472b6;
}

.tok-comma {
  color: #94a3b8;
}

/* 返回结果框 */
.result-box {
  margin-top: 10rpx;
  background: #f1f5f9;
  border-radius: 10rpx;
  padding: 10rpx 14rpx;
}

.result-summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8rpx;
}

.result-text {
  font-size: 22rpx;
  color: #334155;
  font-weight: 600;
}

.toggle-detail-btn {
  min-height: 44px;
  padding: 0 16rpx;
  background: #ffffff;
  border: 1rpx solid #cbd5e1;
  border-radius: 8rpx;
  font-size: 20rpx;
  color: #2563eb;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  touch-action: manipulation;
  margin: 0;
}

.expanded-tool-detail {
  margin-top: 10rpx;
  padding-top: 10rpx;
  border-top: 1rpx solid #e2e8f0;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}

.detail-row {
  display: flex;
  align-items: flex-start;
  gap: 10rpx;
}

.detail-k {
  font-size: 20rpx;
  font-weight: 700;
  color: #64748b;
  width: 110rpx;
  flex-shrink: 0;
}

.detail-v {
  font-size: 20rpx;
  color: #1e293b;
}

.detail-v.text-ok { color: #15803d; font-weight: 700; }
.detail-v.code-block {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  background: #e2e8f0;
  padding: 4rpx 10rpx;
  border-radius: 6rpx;
  font-size: 18rpx;
  word-break: break-all;
}

/* 挂起警告卡片 */
.suspended-alert-card {
  margin-top: 12rpx;
  background: #fffbeb;
  border: 2rpx solid #fcd34d;
  border-radius: 14rpx;
  padding: 14rpx 16rpx;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.suspend-header {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.suspend-icon { font-size: 26rpx; }
.suspend-title { font-size: 24rpx; font-weight: 800; color: #b45309; }
.suspend-desc { font-size: 20rpx; color: #78350f; line-height: 1.4; }

.suspend-actions-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-top: 4rpx;
  flex-wrap: wrap;
}

.quick-approve-btn {
  min-height: 44px;
  padding: 0 20rpx;
  background: #10b981;
  border: none;
  border-radius: 10rpx;
  color: #ffffff;
  font-size: 22rpx;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  touch-action: manipulation;
  box-shadow: 0 2rpx 8rpx rgba(16, 185, 129, 0.3);
}

.quick-reject-btn {
  min-height: 44px;
  padding: 0 20rpx;
  background: #f1f5f9;
  border: 2rpx solid #cbd5e1;
  border-radius: 10rpx;
  color: #64748b;
  font-size: 22rpx;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  touch-action: manipulation;
}

.quick-approve-btn:active, .quick-reject-btn:active {
  transform: translateY(1px) scale(0.99);
}

/* 已执行/已拒绝状态卡 */
.executed-alert-card {
  margin-top: 10rpx;
  background: #f0fdf4;
  border: 2rpx solid #86efac;
  border-radius: 12rpx;
  padding: 10rpx 14rpx;
  display: flex;
  align-items: center;
  gap: 10rpx;
}

.executed-icon { font-size: 24rpx; }
.executed-text { font-size: 22rpx; font-weight: 700; color: #15803d; }

.rejected-alert-card {
  margin-top: 10rpx;
  background: #fef2f2;
  border: 2rpx solid #fca5a5;
  border-radius: 12rpx;
  padding: 10rpx 14rpx;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.reject-header { display: flex; align-items: center; gap: 8rpx; }
.reject-icon { font-size: 24rpx; }
.reject-title { font-size: 22rpx; font-weight: 800; color: #b91c1c; }
.reject-desc { font-size: 20rpx; color: #991b1b; }

/* 安全防线网关面板 */
.safety-dashboard-card {
  background: #ffffff;
  border: 2rpx solid #fcd34d;
  border-radius: 16rpx;
  padding: 16rpx 20rpx;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.safety-dash-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8rpx;
}

.dash-title {
  font-size: 24rpx;
  font-weight: 800;
  color: #92400e;
}

.batch-approve-btn {
  min-height: 44px;
  padding: 0 20rpx;
  background: #10b981;
  border: none;
  border-radius: 12rpx;
  color: #ffffff;
  font-size: 22rpx;
  font-weight: 800;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  touch-action: manipulation;
  box-shadow: 0 4rpx 12rpx rgba(16, 185, 129, 0.3);
}

.batch-approve-btn:active {
  transform: translateY(1px) scale(0.99);
}

.safety-items-list {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.safety-item-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 10rpx 12rpx;
  background: #f8fafc;
  border: 1rpx solid #e2e8f0;
  border-radius: 10rpx;
}

.item-icon { font-size: 28rpx; }
.item-meta { display: flex; flex-direction: column; flex: 1; }
.item-name { font-size: 22rpx; font-weight: 700; color: #0f172a; }
.item-sub { font-size: 18rpx; color: #64748b; }
.item-amount { font-size: 24rpx; font-weight: 800; color: #dc2626; }
.item-status { font-size: 20rpx; font-weight: 700; padding: 2rpx 10rpx; border-radius: 999rpx; background: #f1f5f9; color: #64748b; }
.item-status.executed, .item-status.completed { background: #dcfce7; color: #15803d; }
.item-status.suspended { background: #fef3c7; color: #b45309; }

.safety-pool-summary {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding-top: 8rpx;
  border-top: 1rpx dashed #e2e8f0;
  font-size: 20rpx;
}

.pool-label { color: #64748b; }
.pool-val { font-size: 26rpx; font-weight: 800; color: #dc2626; }
.pool-shield-tag { margin-left: auto; font-size: 18rpx; color: #10b981; font-weight: 700; }

/* 交付物叶子节点卡片 */
.artifact-leaf-node {
  margin-top: 16rpx;
  background: #ffffff;
  border: 2rpx solid #cbd5e1;
  border-radius: 18rpx;
  padding: 18rpx 20rpx;
  box-shadow: 0 4rpx 12rpx rgba(15, 23, 42, 0.04);
  cursor: pointer;
  transition: all 0.25s;
}

.artifact-leaf-node.is-ready {
  border-color: #10b981;
  background: #f0fdf4;
  box-shadow: 0 6rpx 20rpx rgba(16, 185, 129, 0.15);
}

.artifact-leaf-node:active {
  transform: translateY(1px) scale(0.99);
}

.leaf-head {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.leaf-icon-badge {
  width: 56rpx;
  height: 56rpx;
  border-radius: 14rpx;
  background: #e0e7ff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.leaf-icon { font-size: 32rpx; }
.leaf-info { display: flex; flex-direction: column; gap: 4rpx; flex: 1; }
.leaf-title-row { display: flex; align-items: center; gap: 8rpx; }
.leaf-title { font-size: 26rpx; font-weight: 800; color: #0f172a; }
.leaf-tag { font-size: 18rpx; background: #e0e7ff; color: #4338ca; padding: 2rpx 10rpx; border-radius: 999rpx; font-weight: 700; }
.leaf-desc { font-size: 20rpx; color: #64748b; }

.leaf-action-badge {
  padding: 8rpx 16rpx;
  border-radius: 999rpx;
  font-size: 20rpx;
  font-weight: 700;
  background: #f1f5f9;
  color: #64748b;
}

.leaf-action-badge.badge-ready {
  background: #10b981;
  color: #ffffff;
}

/* 交付物弹窗 */
.artifact-modal-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(4px);
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24rpx;
}

.artifact-modal {
  width: 100%;
  max-width: 680px;
  max-height: 85vh;
  background: #ffffff;
  border-radius: 24rpx;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 20rpx 50rpx rgba(15, 23, 42, 0.25);
}

.artifact-modal-header {
  padding: 20rpx 24rpx;
  background: linear-gradient(135deg, #1e293b, #0f172a);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.modal-title { font-size: 28rpx; font-weight: 800; color: #ffffff; }
.modal-sub { font-size: 20rpx; color: #94a3b8; }
.modal-close-btn {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  border: none;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28rpx;
  cursor: pointer;
  touch-action: manipulation;
}

.artifact-modal-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20rpx;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  background: #f8fafc;
}

.plan-page-card {
  background: #ffffff;
  border: 2rpx solid #e2e8f0;
  border-radius: 18rpx;
  padding: 20rpx;
  margin-bottom: 16rpx;
  box-shadow: 0 2rpx 8rpx rgba(15, 23, 42, 0.04);
}

.page-card-head {
  display: flex;
  align-items: center;
  gap: 10rpx;
  padding-bottom: 12rpx;
  border-bottom: 2rpx solid #f1f5f9;
  margin-bottom: 12rpx;
}

.page-badge {
  font-size: 20rpx;
  font-weight: 800;
  background: #FF6B35;
  color: #ffffff;
  padding: 2rpx 12rpx;
  border-radius: 999rpx;
}

.page-title {
  font-size: 26rpx;
  font-weight: 800;
  color: #0f172a;
}

.page-rows {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.page-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding: 4rpx 0;
}

.row-label { font-size: 22rpx; color: #64748b; width: 150rpx; flex-shrink: 0; }
.row-val { font-size: 24rpx; font-weight: 700; color: #0f172a; text-align: right; flex: 1; }

.page-note {
  margin-top: 10rpx;
  padding-top: 8rpx;
  border-top: 1rpx dashed #e2e8f0;
  display: flex;
  align-items: flex-start;
  gap: 8rpx;
}

.note-icon { font-size: 20rpx; }
.note-text { font-size: 20rpx; color: #64748b; line-height: 1.4; }

.artifact-modal-footer {
  padding: 16rpx 20rpx;
  background: #ffffff;
  border-top: 2rpx solid #e2e8f0;
  display: flex;
  gap: 12rpx;
}

.footer-btn {
  flex: 1;
  min-height: 44px;
  border-radius: 12rpx;
  font-size: 24rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  touch-action: manipulation;
}

.footer-btn.primary {
  background: #FF6B35;
  color: #ffffff;
  border: none;
}

.footer-btn.secondary {
  background: #f1f5f9;
  color: #334155;
  border: 2rpx solid #cbd5e1;
}

@keyframes dag-frontier-pulse {
  0%, 100% {
    box-shadow: 0 0 10rpx rgba(255, 107, 53, 0.25);
  }
  50% {
    box-shadow: 0 0 24rpx rgba(255, 107, 53, 0.55);
  }
}

@keyframes lyj-pulse-glow {
  0%, 100% { transform: scale(1); opacity: 0.8; }
  50% { transform: scale(1.2); opacity: 1; }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-8rpx); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
