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
        <text class="metric-val tabular-num">{{ activeAgentsCount }} / 3</text>
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


        <!-- ================= 根节点：康乐主调度 (Orchestrator Card) ================= -->
        <view class="root-node-card" :class="{ 'is-thinking': thinking || rootThinking }">
          <view class="node-glass-glow"></view>
          <view class="node-head">
            <view class="node-badge-group">
              <view class="avatar-box orchestrator-avatar">
                <text class="avatar-icon">🎯</text>
              </view>
              <view class="node-meta">
                <view class="node-title-row">
                  <text class="node-title">康乐主调度</text>
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
          <view v-if="displaySteps.length > 0" class="plan-steps-track">
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
          <view class="subagent-branch-card health-branch" :class="{ 'collapsed': collapsedAgents.health, 'is-inactive': !isHealthActive, 'is-active-branch': isHealthActive }">
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

                <!-- 空工具提示 -->
                <view v-if="healthTools.length === 0" class="branch-idle-box">
                  <text class="branch-idle-text">{{ isHealthActive ? '正在分析并准备调用健康工具…' : '本轮未派发健康医疗相关工具' }}</text>
                </view>

                <!-- 工具节点列表：节点、入参、状态全部来自该智能体真实发出的 tool_call / tool_result -->
                <view v-if="healthTools.length > 0" class="tools-flow">
                  <view
                    v-for="tool in healthTools"
                    :key="tool.key"
                    class="tool-node"
                    :class="[tool.isHighRisk ? 'high-risk-node' : '', 'node-' + tool.status]"
                  >
                    <view class="node-connector-dot" :class="{ 'risk-dot': tool.isHighRisk }"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">{{ tool.name }}</text>
                          <text class="tool-cn-name">{{ tool.summary }}</text>
                          <text v-if="tool.isHighRisk" class="risk-badge">🛡️ 家人确认保护</text>
                        </view>
                        <view class="node-tags-group">
                          <view class="node-status-tag" :class="tool.status">
                            {{ formatToolStatus(tool.status, tool.name) }}
                          </view>
                        </view>
                      </view>
                      <!-- 参数 JSON 高亮：解析大模型真实入参，不再有写死的样例参数 -->
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tokIdx) in parseParamsTokens(tool.args)" :key="tokIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <!-- 高危挂起：等家人确权 -->
                      <view v-if="tool.status === 'suspended'" class="suspended-alert-card">
                        <view class="suspend-header">
                          <text class="suspend-icon">⏸️</text>
                          <view class="suspend-title-group">
                            <text class="suspend-title">等待子女确认<text v-if="tool.amount"> (¥{{ tool.amount }})</text></text>
                            <text class="suspend-channel-tag">🔒 已推至子女端待核准</text>
                          </view>
                        </view>
                        <text class="suspend-desc">{{ tool.desc || '高危操作已被安全拦截，已推送子女手机端核准。' }}</text>
                        <view class="demo-channel-block">
                          <view class="demo-link-row" @tap="toggleDemoAction(tool.key)">
                            <text class="demo-link-text">{{ showDemoActions[tool.key] ? '收起演示通道 ▲' : '🛠️ 演示通道快捷模拟 ▼' }}</text>
                          </view>
                          <view v-if="showDemoActions[tool.key]" class="suspend-actions-row">
                            <button class="quick-approve-btn" @tap="triggerApprove(tool.confirmationId, tool.name)">
                              ⚡ 模拟子女审批通过
                            </button>
                            <button class="quick-reject-btn" @tap="triggerReject(tool.confirmationId, tool.name)">
                              🛑 模拟子女拒绝
                            </button>
                          </view>
                        </view>
                      </view>
                      <!-- 家人已放行 -->
                      <view v-else-if="tool.status === 'completed' && tool.isHighRisk" class="executed-alert-card">
                        <text class="executed-icon">✅</text>
                        <text class="executed-text">子女已审批同意 · 操作已放行</text>
                      </view>
                      <!-- 家人已拒绝 -->
                      <view v-else-if="tool.status === 'rejected'" class="rejected-alert-card">
                        <view class="reject-header">
                          <text class="reject-icon">🛑</text>
                          <text class="reject-title">子女已拒绝该操作</text>
                        </view>
                        <text class="reject-desc">已安全拦截并终止本次高危请求，未产生任何扣费。</text>
                      </view>
                      <!-- 工具返回摘要 -->
                      <view v-if="tool.result" class="result-box">
                        <view class="result-summary-row">
                          <text class="result-text">🎯 {{ tool.result }}</text>
                        </view>
                      </view>
                    </view>
                  </view>
                </view>

              </view>
            </view>
          </view>

          <!-- 分支 2：银发导航 (Travel Agent · 银发导航) -->
          <view class="subagent-branch-card travel-branch" :class="{ 'collapsed': collapsedAgents.travel, 'is-inactive': !isTravelActive, 'is-active-branch': isTravelActive }">
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
                  <text class="branch-desc">本地出行路线 · 叫车 · 出行天气</text>
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

                <!-- 空工具提示 -->
                <view v-if="travelTools.length === 0" class="branch-idle-box">
                  <text class="branch-idle-text">{{ isTravelActive ? '正在规划并准备调用出行工具…' : '本轮未派发交通出行相关工具' }}</text>
                </view>

                <!-- 工具节点列表：节点、入参、状态全部来自该智能体真实发出的 tool_call / tool_result -->
                <view v-if="travelTools.length > 0" class="tools-flow">
                  <view
                    v-for="tool in travelTools"
                    :key="tool.key"
                    class="tool-node"
                    :class="[tool.isHighRisk ? 'high-risk-node' : '', 'node-' + tool.status]"
                  >
                    <view class="node-connector-dot" :class="{ 'risk-dot': tool.isHighRisk }"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">{{ tool.name }}</text>
                          <text class="tool-cn-name">{{ tool.summary }}</text>
                          <text v-if="tool.isHighRisk" class="risk-badge">🛡️ 家人确认保护</text>
                        </view>
                        <view class="node-tags-group">
                          <view class="node-status-tag" :class="tool.status">
                            {{ formatToolStatus(tool.status, tool.name) }}
                          </view>
                        </view>
                      </view>
                      <!-- 参数 JSON 高亮：解析大模型真实入参，不再有写死的样例参数 -->
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tokIdx) in parseParamsTokens(tool.args)" :key="tokIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <!-- 高危挂起：等家人确权 -->
                      <view v-if="tool.status === 'suspended'" class="suspended-alert-card">
                        <view class="suspend-header">
                          <text class="suspend-icon">⏸️</text>
                          <view class="suspend-title-group">
                            <text class="suspend-title">等待子女确认<text v-if="tool.amount"> (¥{{ tool.amount }})</text></text>
                            <text class="suspend-channel-tag">🔒 已推至子女端待核准</text>
                          </view>
                        </view>
                        <text class="suspend-desc">{{ tool.desc || '高危操作已被安全拦截，已推送子女手机端核准。' }}</text>
                        <view class="demo-channel-block">
                          <view class="demo-link-row" @tap="toggleDemoAction(tool.key)">
                            <text class="demo-link-text">{{ showDemoActions[tool.key] ? '收起演示通道 ▲' : '🛠️ 演示通道快捷模拟 ▼' }}</text>
                          </view>
                          <view v-if="showDemoActions[tool.key]" class="suspend-actions-row">
                            <button class="quick-approve-btn" @tap="triggerApprove(tool.confirmationId, tool.name)">
                              ⚡ 模拟子女审批通过
                            </button>
                            <button class="quick-reject-btn" @tap="triggerReject(tool.confirmationId, tool.name)">
                              🛑 模拟子女拒绝
                            </button>
                          </view>
                        </view>
                      </view>
                      <!-- 家人已放行 -->
                      <view v-else-if="tool.status === 'completed' && tool.isHighRisk" class="executed-alert-card">
                        <text class="executed-icon">✅</text>
                        <text class="executed-text">子女已审批同意 · 操作已放行</text>
                      </view>
                      <!-- 家人已拒绝 -->
                      <view v-else-if="tool.status === 'rejected'" class="rejected-alert-card">
                        <view class="reject-header">
                          <text class="reject-icon">🛑</text>
                          <text class="reject-title">子女已拒绝该操作</text>
                        </view>
                        <text class="reject-desc">已安全拦截并终止本次高危请求，未产生任何扣费。</text>
                      </view>
                      <!-- 工具返回摘要 -->
                      <view v-if="tool.result" class="result-box">
                        <view class="result-summary-row">
                          <text class="result-text">🎯 {{ tool.result }}</text>
                        </view>
                      </view>
                    </view>
                  </view>
                </view>

              </view>
            </view>
          </view>

          <!-- 分支 3：邻里帮 (Community Agent · 邻里帮) -->
          <view class="subagent-branch-card community-branch" :class="{ 'collapsed': collapsedAgents.community, 'is-inactive': !isCommunityActive, 'is-active-branch': isCommunityActive }">
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
                  <text class="branch-desc">线下活动 · 一键联系家人 · 散步环线 · 家常菜谱</text>
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

                <!-- 空工具提示 -->
                <view v-if="communityTools.length === 0" class="branch-idle-box">
                  <text class="branch-idle-text">{{ isCommunityActive ? '正在对接社区便民资源…' : '本轮未派发社区便民服务相关工具' }}</text>
                </view>

                <!-- 工具节点列表：节点、入参、状态全部来自该智能体真实发出的 tool_call / tool_result -->
                <view v-if="communityTools.length > 0" class="tools-flow">
                  <view
                    v-for="tool in communityTools"
                    :key="tool.key"
                    class="tool-node"
                    :class="[tool.isHighRisk ? 'high-risk-node' : '', 'node-' + tool.status]"
                  >
                    <view class="node-connector-dot" :class="{ 'risk-dot': tool.isHighRisk }"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">{{ tool.name }}</text>
                          <text class="tool-cn-name">{{ tool.summary }}</text>
                          <text v-if="tool.isHighRisk" class="risk-badge">🛡️ 家人确认保护</text>
                        </view>
                        <view class="node-tags-group">
                          <view class="node-status-tag" :class="tool.status">
                            {{ formatToolStatus(tool.status, tool.name) }}
                          </view>
                        </view>
                      </view>
                      <!-- 参数 JSON 高亮：解析大模型真实入参，不再有写死的样例参数 -->
                      <view class="mono-params-box">
                        <view class="params-header-row">
                          <text class="params-lang-label">JSON ARGS</text>
                          <text class="params-copy-hint">入参载荷</text>
                        </view>
                        <view class="mono-code-tokens">
                          <text class="token-brace">{</text>
                          <view v-for="(tok, tokIdx) in parseParamsTokens(tool.args)" :key="tokIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <!-- 高危挂起：等家人确权 -->
                      <view v-if="tool.status === 'suspended'" class="suspended-alert-card">
                        <view class="suspend-header">
                          <text class="suspend-icon">⏸️</text>
                          <view class="suspend-title-group">
                            <text class="suspend-title">等待子女确认<text v-if="tool.amount"> (¥{{ tool.amount }})</text></text>
                            <text class="suspend-channel-tag">🔒 已推至子女端待核准</text>
                          </view>
                        </view>
                        <text class="suspend-desc">{{ tool.desc || '高危操作已被安全拦截，已推送子女手机端核准。' }}</text>
                        <view class="demo-channel-block">
                          <view class="demo-link-row" @tap="toggleDemoAction(tool.key)">
                            <text class="demo-link-text">{{ showDemoActions[tool.key] ? '收起演示通道 ▲' : '🛠️ 演示通道快捷模拟 ▼' }}</text>
                          </view>
                          <view v-if="showDemoActions[tool.key]" class="suspend-actions-row">
                            <button class="quick-approve-btn" @tap="triggerApprove(tool.confirmationId, tool.name)">
                              ⚡ 模拟子女审批通过
                            </button>
                            <button class="quick-reject-btn" @tap="triggerReject(tool.confirmationId, tool.name)">
                              🛑 模拟子女拒绝
                            </button>
                          </view>
                        </view>
                      </view>
                      <!-- 家人已放行 -->
                      <view v-else-if="tool.status === 'completed' && tool.isHighRisk" class="executed-alert-card">
                        <text class="executed-icon">✅</text>
                        <text class="executed-text">子女已审批同意 · 操作已放行</text>
                      </view>
                      <!-- 家人已拒绝 -->
                      <view v-else-if="tool.status === 'rejected'" class="rejected-alert-card">
                        <view class="reject-header">
                          <text class="reject-icon">🛑</text>
                          <text class="reject-title">子女已拒绝该操作</text>
                        </view>
                        <text class="reject-desc">已安全拦截并终止本次高危请求，未产生任何扣费。</text>
                      </view>
                      <!-- 工具返回摘要 -->
                      <view v-if="tool.result" class="result-box">
                        <view class="result-summary-row">
                          <text class="result-text">🎯 {{ tool.result }}</text>
                        </view>
                      </view>
                    </view>
                  </view>
                </view>

              </view>
            </view>
          </view>

          <!-- 分支 4：资金与医疗安全防护网 (Safety Guard Gateway) (R3) -->
          <view class="subagent-branch-card safety-branch" :class="{ 'collapsed': collapsedAgents.safety, 'is-inactive': !isSafetyActive, 'is-active-branch': isSafetyActive }">
            <view class="branch-header" @tap="toggleAgentCollapse('safety')">
              <view class="branch-header-left">
                <view class="avatar-box safety-avatar">
                  <text class="avatar-icon">🛡️</text>
                </view>
                <view class="branch-title-group">
                  <view class="branch-name-row">
                    <text class="branch-name">资金与医疗安全防护网</text>
                    <text class="branch-en-tag">安全网关 · 链路管控环节</text>
                  </view>
                  <text class="branch-desc">支付高危拦截 · 就医知会不审批 · 子女端实时核准</text>
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
                    <view v-if="pendingTasksCount > 0" class="dash-actions-group">
                      <text class="demo-channel-link" @tap="demoModeOpen = !demoModeOpen">
                        {{ demoModeOpen ? '收起演示通道 ▲' : '🛠️ 演示通道 ▼' }}
                      </text>
                      <button
                        v-if="demoModeOpen"
                        class="batch-approve-btn"
                        @tap="approveAllPending"
                      >
                        ⚡ 模拟一键全批
                      </button>
                    </view>
                  </view>
                  <!-- 清单按真实挂起/高危调用渲染，条目数与金额都来自事件流 -->
                  <view class="safety-items-list">
                    <view v-for="task in highRiskTools" :key="task.key" class="safety-item-row">
                      <text class="item-icon">{{ toolIcon(task.name) }}</text>
                      <view class="item-meta">
                        <text class="item-name">{{ task.summary }}</text>
                        <text class="item-sub">{{ task.name }}</text>
                      </view>
                      <text v-if="task.amount" class="item-amount tabular-num">¥{{ task.amount }}</text>
                      <view class="item-status" :class="task.status">
                        {{ formatToolStatus(task.status, task.name) }}
                      </view>
                    </view>
                    <view v-if="highRiskTools.length === 0" class="safety-item-row">
                      <text class="item-icon">🛡️</text>
                      <view class="item-meta">
                        <text class="item-name">本轮暂无高危拦截</text>
                        <text class="item-sub">未触发双向审批回路</text>
                      </view>
                    </view>
                  </view>
                  <view v-if="highRiskTools.length > 0" class="safety-pool-summary">
                    <text class="pool-label">资金拦截池受控总额：</text>
                    <text class="pool-val tabular-num">¥{{ highRiskAmountTotal }}</text>
                    <text class="pool-shield-tag">已通过加密长连接推送子女端</text>
                  </view>
                </view>
              </view>
            </view>
          </view>

          <!-- 分支 5：方案建造师 (PlanBuilder · 方案装配) -->
          <view class="subagent-branch-card planbuilder-branch" :class="{ 'collapsed': collapsedAgents.planBuilder, 'is-inactive': !isPlanBuilderActive, 'is-active-branch': isPlanBuilderActive }">
            <view class="branch-header" @tap="toggleAgentCollapse('planBuilder')">
              <view class="branch-header-left">
                <view class="avatar-box planbuilder-avatar">
                  <text class="avatar-icon">📐</text>
                </view>
                <view class="branch-title-group">
                  <view class="branch-name-row">
                    <text class="branch-name">方案建造师</text>
                    <text class="branch-en-tag">交付装配 · 链路管控环节</text>
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

                <view v-if="planBuilderTools.length > 0" class="tools-flow">
                  <!-- 工具节点: compose_deliverable 等真实调用 -->
                  <view
                    v-for="tool in planBuilderTools"
                    :key="tool.key"
                    class="tool-node"
                    :class="'node-' + tool.status"
                  >
                    <view class="node-connector-dot"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">{{ tool.name }}</text>
                          <text class="tool-cn-name">{{ tool.summary }}</text>
                        </view>
                        <view class="node-tags-group">
                          <view class="node-status-tag" :class="tool.status">
                            {{ formatToolStatus(tool.status, tool.name) }}
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
                          <view v-for="(tok, tIdx) in parseParamsTokens(tool.args)" :key="tIdx" class="token-item">
                            <text class="tok-key">"{{ tok.k }}"</text>
                            <text class="tok-colon">: </text>
                            <text class="tok-val" :class="'val-' + tok.type">{{ tok.v }}</text>
                            <text v-if="!tok.isLast" class="tok-comma">,</text>
                          </view>
                          <text class="token-brace">}</text>
                        </view>
                      </view>
                      <view v-if="tool.result" class="result-box">
                        <text class="result-text">{{ tool.resultText || '✅ 已完成事实提取与交付方案装配' }}</text>
                      </view>
                    </view>
                  </view>
                </view>
                <view v-else-if="!isArtifactReady" class="branch-idle-box">
                  <text class="branch-idle-text">{{ isPlanBuilderActive ? '正在等待提取全部事实数据…' : '待各子智能体完成任务后装配交付方案' }}</text>
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
                        <text class="leaf-title">{{ artifactDisplayTitle }}</text>
                        <text class="leaf-tag">适老大字版</text>
                      </view>
                      <text class="leaf-desc">{{ artifactDisplaySubtitle }}</text>
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
    </scroll-view>

    <!-- 交付物全屏交互弹窗 (Artifact Modal) -->
    <view v-if="showArtifactModal" class="artifact-modal-mask" @tap="showArtifactModal = false">
      <view class="artifact-modal" @tap.stop>
        <view class="artifact-modal-header">
          <view class="header-main-box">
            <text class="modal-title">📄 {{ modalTitleText }}</text>
            <text class="modal-sub">{{ modalSubText }}</text>
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
        health: true,
        travel: true,
        community: true,
        safety: true,
        planBuilder: true,
      },
      showArtifactModal: false,
      expandedToolResults: {},
      _userChangedAllExpanded: false,
      demoModeOpen: false,
      showDemoActions: {},
    }
  },
  watch: {
    messages: {
      deep: true,
      immediate: true,
      handler(newMsgs, oldMsgs) {
        const safeNew = (newMsgs || []).filter((m) => m && typeof m === 'object')
        const safeOld = (oldMsgs || []).filter((m) => m && typeof m === 'object')
        const lastNew = safeNew[safeNew.length - 1]
        const lastOld = safeOld[safeOld.length - 1]
        if (lastNew && lastNew.isUser && (!lastOld || lastOld !== lastNew)) {
          this._userChangedAllExpanded = false
        }
        this.syncActiveBranches()
      },
    },
    thinking() {
      this.syncActiveBranches()
    },
    currentAgent() {
      this.syncActiveBranches()
    },
  },
  mounted() {
    this.syncActiveBranches()
  },
  computed: {
    safeMessages() {
      return (this.messages || []).filter((m) => m && typeof m === 'object')
    },

    dispatchedAgents() {
      const set = new Set()
      if (this.thinking && this.currentAgent) {
        const norm = this.normalizeAgent(this.currentAgent)
        if (norm && norm !== 'main') {
          set.add(norm)
        }
      }
      for (const m of this.safeMessages) {
        if (!m || typeof m !== 'object') continue
        const kind = m.kind || ''
        if (
          kind === 'tool' ||
          kind === 'tool_call' ||
          kind === 'tool_result' ||
          kind === 'status' ||
          kind === 'agent_status' ||
          kind === 'report' ||
          m.reasoning ||
          m.thought
        ) {
          const raw = m.agent || (m.tool_call && m.tool_call.agent) || m.sender || ''
          if (raw) {
            const norm = this.normalizeAgent(raw)
            if (norm && norm !== 'main') {
              set.add(norm)
            }
          }
        }
      }
      return set
    },

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
      return this.safeMessages.some(
        (m) =>
          m.isUser ||
          m.kind === 'tool' ||
          m.kind === 'suspend' ||
          (m.kind === 'todo' && Array.isArray(m.todos) && m.todos.length > 0) ||
          m.kind === 'card',
      )
    },

    hasAnyRejected() {
      if (this.allTools.some((t) => t.status === 'rejected')) return true
      return this.safeMessages.some(
        (m) => m.kind === 'suspend' && m.status === 'rejected',
      )
    },

    // 动态判断子智能体活跃状态（严格由真实派发与工具调用驱动）
    isHealthActive() {
      return (
        this.dispatchedAgents.has('health') ||
        (this.healthTools && this.healthTools.length > 0) ||
        (this.thinking && this.isCurrentAgent('health'))
      )
    },

    isTravelActive() {
      return (
        this.dispatchedAgents.has('travel') ||
        (this.travelTools && this.travelTools.length > 0) ||
        (this.thinking && this.isCurrentAgent('travel'))
      )
    },

    isCommunityActive() {
      return (
        this.dispatchedAgents.has('community') ||
        (this.communityTools && this.communityTools.length > 0) ||
        (this.thinking && this.isCurrentAgent('community'))
      )
    },

    isSafetyActive() {
      return (
        this.highRiskTools.length > 0 ||
        this.pendingTasksCount > 0 ||
        this.hasAnyRejected
      )
    },

    isPlanBuilderActive() {
      return (
        this.isArtifactReady ||
        (this.planBuilderTools && this.planBuilderTools.length > 0)
      )
    },

    // 协同智能体数严格等于当前真实激活的子智能体数量（分母为3，方案建造师与安全网关不计入）
    activeAgentsCount() {
      const DISPATCHABLE_AGENTS = ['health', 'travel', 'community']
      const activeMap = {
        health: this.isHealthActive,
        travel: this.isTravelActive,
        community: this.isCommunityActive,
      }
      return DISPATCHABLE_AGENTS.filter((a) => activeMap[a]).length
    },

    // 执行工具数严格等于当前分支展示的全部工具数量
    totalToolsCount() {
      return this.allTools.length
    },

    // 待批拦截数严格等于真实挂起待确权项目
    pendingTasksCount() {
      const suspendedTools = this.allTools.filter((t) => t.status === 'suspended').length
      const suspendedMsgs = this.safeMessages.filter((m) => m.kind === 'suspend' && m.status === 'pending').length
      return Math.max(suspendedTools, suspendedMsgs)
    },

    globalStatusText() {
      if (this.thinking || this.rootThinking) return 'LLM 正在并行规划推理'
      if (this.pendingTasksCount > 0) return '高危操作等待子女端审批'
      if (this.hasAnyRejected) return '高危操作已被子女拒绝拦截'
      if (this.isArtifactReady) return '执行闭环 · 方案交付完毕'
      if (this.hasTaskStarted) {
        if (this.completedStepsCount === this.totalStepsCount && this.totalStepsCount > 0) {
          return `全部 ${this.totalStepsCount} 阶段已达成 · 随时待命`
        }
        return this.thinking ? (this.displaySteps.length > 0 ? `${this.displaySteps.length} 阶段协同进行中` : '协同处理进行中') : '协同响应已交付 · 随时待命'
      }
      return '协同网络就绪 · 随时待命'
    },

    globalStatusClass() {
      if (this.thinking || this.rootThinking) return 'status-thinking'
      if (this.pendingTasksCount > 0) return 'status-suspended'
      if (this.hasAnyRejected) return 'status-rejected'
      if (this.isArtifactReady) return 'status-completed'
      if (this.hasTaskStarted) {
        if (this.completedStepsCount === this.totalStepsCount && this.totalStepsCount > 0) {
          return 'status-completed'
        }
        return this.thinking ? 'status-thinking' : 'status-ready'
      }
      return 'status-ready'
    },

    isAnyAgentActive() {
      return this.thinking || this.rootThinking || this.pendingTasksCount > 0 || this.hasTaskStarted
    },

    rootStatusClass() {
      if (this.thinking || this.rootThinking) return 'status-thinking'
      if (this.hasAnyRejected) return 'status-rejected'
      if (this.isArtifactReady) return 'status-completed'
      if (this.hasTaskStarted) {
        return this.thinking ? 'status-thinking' : 'status-completed'
      }
      return 'status-ready'
    },

    rootStatusIcon() {
      if (this.thinking || this.rootThinking) return '⚡'
      if (this.hasAnyRejected) return '🛑'
      if (this.isArtifactReady) return '✅'
      if (this.hasTaskStarted && !this.thinking) return '✅'
      return '🎯'
    },

    rootStatusText() {
      if (this.thinking || this.rootThinking) return '意图拆解与全局调度中'
      if (this.hasAnyRejected) return '局部流程已由家人终止'
      if (this.isArtifactReady) return '全链路执行完毕'
      if (this.hasTaskStarted) {
        return this.thinking ? '调度执行中' : '任务调度完成 · 随时待命'
      }
      return '主调度就绪 · 等待长辈诉求'
    },

    // 动态根据真实上下文推导场景标签
    currentScenarioTag() {
      if (!this.hasTaskStarted) return '待命中'

      // 1. 优先从 todo 任务清单推导
      const todoMsgs = this.safeMessages.filter((m) => m.kind === 'todo' && Array.isArray(m.todos) && m.todos.length > 0)
      const todoMsg = todoMsgs.length > 0 ? todoMsgs[todoMsgs.length - 1] : null
      if (todoMsg && todoMsg.todos.length > 0) {
        const validTodos = todoMsg.todos.filter((t) => t && typeof t === 'object')
        const text = validTodos.map((t) => t.content || t.title || t.text || '').join(' ')
        if ((text.includes('挂号') || text.includes('医院') || text.includes('就医')) && (text.includes('路线') || text.includes('怎么去') || text.includes('出行'))) {
          return '就近就医出行协同'
        }
        if (text.includes('挂号') || text.includes('医院') || text.includes('就医') || text.includes('门诊')) {
          return '健康医疗就诊规划'
        }
        if (text.includes('路线') || text.includes('出行') || text.includes('怎么走') || text.includes('散步')) {
          return '本市出行路线规划'
        }
        if (text.includes('用药') || text.includes('配药') || text.includes('服药') || text.includes('慢病')) {
          return '慢病用药管理服务'
        }
        if (text.includes('食堂') || text.includes('便民') || text.includes('助老')) {
          return '邻里助老便民服务'
        }
        if (text.includes('活动') || text.includes('散步') || text.includes('菜谱') || text.includes('陪') || text.includes('社区')) {
          return '社区活动与陪伴'
        }
        return '智能协同任务规划'
      }

      // 2. 从真实调用的工具类型推导
      if (this.allTools.length > 0) {
        const hasHealth = this.healthTools.length > 0
        const hasTravel = this.travelTools.length > 0
        const hasCommunity = this.communityTools.length > 0
        const hasPlan = this.planBuilderTools.length > 0
        if (hasHealth && hasTravel) return '就近就医出行协同'
        if (hasHealth) return '健康医疗导诊服务'
        if (hasTravel) return '本市出行路线规划'
        if (hasCommunity) {
          const isCanteenOrService = this.communityTools.some(
            (t) => t.name && (t.name.includes('canteen') || t.name.includes('order') || t.name.includes('service') || t.name.includes('escort')),
          )
          const lastUser = this.safeMessages.filter((m) => m.isUser && m.text).pop()
          const userText = lastUser ? lastUser.text : ''
          if (isCanteenOrService || userText.includes('食堂') || userText.includes('便民') || userText.includes('助老')) {
            return '邻里助老便民服务'
          }
          return '社区活动与陪伴'
        }
        if (hasPlan) return '适老方案规划装配'
      }

      // 3. 从长辈最近一条提问文本推导
      const userMsgs = this.safeMessages.filter((m) => m.isUser && m.text)
      if (userMsgs.length > 0) {
        const last = userMsgs[userMsgs.length - 1].text
        if (last.includes('看病') || last.includes('医院') || last.includes('挂号') || last.includes('门诊') || last.includes('疼') || last.includes('病')) {
          // 老人提到跨城时，康乐只做本市 —— 标成"超出服务范围"，不是"正在规划"
          const isIntercity =
            last.includes('高铁') ||
            last.includes('火车') ||
            last.includes('车票') ||
            last.includes('外地') ||
            last.includes('跨城') ||
            last.includes('跨市') ||
            last.includes('飞机') ||
            last.includes('机票')
          return isIntercity ? '跨城就医出行规划' : '健康医疗咨询服务'
        }
        if (last.includes('路线') || last.includes('出行') || last.includes('怎么走') || last.includes('怎么去') || last.includes('打车') || last.includes('叫车') || last.includes('散步')) {
          return '本市出行路线规划'
        }
        if (last.includes('药') || last.includes('血压') || last.includes('血糖') || last.includes('慢病') || last.includes('提醒')) {
          return '健康慢病用药管理'
        }
        if (last.includes('报告') || last.includes('体检') || last.includes('解读')) {
          return '健康报告分析解读'
        }
        if (last.includes('诈') || last.includes('骗')) {
          return '防诈预警与安全核验'
        }
        if (last.includes('活动') || last.includes('散步') || last.includes('棋牌') || last.includes('邻里') || last.includes('聊天') || last.includes('闷') || last.includes('菜谱') || last.includes('做什么吃')) {
          return '社区活动与陪伴关怀'
        }
        if (last.includes('你好') || last.includes('您好') || last.includes('早上好') || last.includes('是谁') || last.includes('介绍')) {
          return '日常关怀与问候'
        }
      }

      return '长辈生活智能助理'
    },

    // 动态根据真实诉求与任务推导意图文本
    currentIntentText() {
      const userMsgs = this.safeMessages.filter((m) => m.isUser && m.text)
      if (userMsgs.length > 0) {
        const last = userMsgs[userMsgs.length - 1].text
        if (this.displaySteps.length > 0) {
          const stepsStr = this.displaySteps.map((s) => s.name).join(' ➔ ')
          return `解析长辈诉求：“${last}” ➔ 拆解规划：${stepsStr}`
        }
        if (this.allTools.length > 0) {
          const toolsStr = this.allTools.map((t) => t.summary || t.name).slice(0, 3).join('、')
          return `解析长辈诉求：“${last}” ➔ 实时调度执行：${toolsStr}`
        }
        if (this.thinking || this.rootThinking) {
          return `解析长辈诉求：“${last}” ➔ 主调度正在意图理解与任务规划中…`
        }
        return `解析长辈诉求：“${last}” ➔ 意图理解完成，已协同处理回复。`
      }
      return '等待长辈输入诉求… 可按住说话或打字告诉康乐，主调度将实时理解意图并下发协同网络。'
    },

    // 智能体推理独白：真实模式下完全由会话真实上下文生成
    agentThoughts() {

      const msgs = this.safeMessages
      const userMsgs = msgs.filter((m) => m.isUser && m.text)
      const lastUser = userMsgs.length > 0 ? userMsgs[userMsgs.length - 1].text : ''

      // 1. 主调度独白
      let orchestratorThought = ''
      const mainStatus = msgs.filter(
        (m) =>
          (m.kind === 'status' && (!m.agent || this.matchesAgent(m.agent, 'main'))) ||
          (this.matchesAgent(m.agent, 'main') && (m.reasoning || m.thought)),
      )
      const explicitMainReasoning = mainStatus.slice().reverse().find((m) => m.reasoning || m.thought)
      if (explicitMainReasoning) {
        orchestratorThought = explicitMainReasoning.reasoning || explicitMainReasoning.thought
      } else if (lastUser) {
        if (this.displaySteps.length > 0) {
          const sList = this.displaySteps.map((s) => s.name).join('、')
          orchestratorThought = `接收长辈诉求“${lastUser}”，主调度已建立协同流水线（${sList}），按需调度子智能体并全程护栏监测。`
        } else if (this.allTools.length > 0) {
          const tList = this.allTools.map((t) => t.summary || t.name).slice(0, 3).join('、')
          orchestratorThought = `接收长辈诉求“${lastUser}”，总调度已组织多智能体并行调度（${tList}），落实服务闭环。`
        } else if (this.thinking || this.rootThinking) {
          orchestratorThought = `正在深度理解长辈诉求“${lastUser}”，解析意图与上下文，编排子智能体调度任务…`
        } else {
          orchestratorThought = `长辈问询“${lastUser}”已完成意图解析与响应交付，康乐随时待命。`
        }
      } else {
        orchestratorThought = '康乐主调度处于就绪待命状态，长辈输入诉求后将实时拆解意图并下发专业子智能体。'
      }

      // 2. 健康智能体独白
      let healthThought = ''
      if (!this.isHealthActive) {
        healthThought = '本轮未派发健康医疗相关任务，健康守护助手处于待命状态。'
      } else {
        const hStatus = msgs.filter(
          (m) =>
            (m.kind === 'status' && this.matchesAgent(m.agent, 'health')) ||
            (this.matchesAgent(m.agent, 'health') && (m.reasoning || m.thought)),
        )
        const explicitHealth = hStatus.slice().reverse().find((m) => m.reasoning || m.thought)
        if (explicitHealth) {
          healthThought = explicitHealth.reasoning || explicitHealth.thought
        } else if (this.healthTools.length > 0) {
          const descs = this.healthTools.map((t) => {
            const a = t.args || {}
            if (t.name === 'search_hospital') {
              const d = a.department || a.symptom || '科室'
              const c = a.city ? `${a.city}` : ''
              return `检索${c}${d}号源`
            }
            if (t.name === 'register_appointment') {
              const hosp = a.hospital || ''
              const doc = a.doctor || ''
              const fee = a.fee ? `，诊查费¥${a.fee}` : ''
              return `挂号预约（${hosp} ${doc}${fee}）`
            }
            if (t.name === 'interpret_report') {
              const title = a.title || '体检报告'
              return `解读${title}指标`
            }
            if (t.name === 'add_medication') {
              const drug = a.drug_name || a.medicine || a.name || '药品'
              const dose = a.dose ? `（${a.dose}）` : ''
              return `添加用药提醒（${drug}${dose}）`
            }
            if (t.name === 'diet_advice') {
              const pref = a.preference ? `（${a.preference}）` : ''
              return `提供适老健康饮食建议${pref}`
            }
            return `${t.summary || t.name}`
          })
          healthThought = `健康守护已介入：${descs.join('；')}。严格遵循适老医疗安全规范与免责提示。`
        } else if (this.thinking && this.isCurrentAgent('health')) {
          healthThought = '健康守护助手正在分析健康医疗需求，准备调用适老导诊与号源工具…'
        } else if (hStatus.length > 0) {
          healthThought = hStatus[hStatus.length - 1].text
        } else {
          healthThought = '健康守护助手已就绪，随时提供导医与健康辅助服务。'
        }
      }

      // 3. 银发导航独白（只认现在真挂着的三个工具：plan_route / hail_ride / get_weather）
      let travelThought = ''
      if (!this.isTravelActive) {
        travelThought = '本轮未派发本地出行相关任务，银发导航助手处于待命状态。'
      } else {
        const tStatus = msgs.filter(
          (m) =>
            (m.kind === 'status' && this.matchesAgent(m.agent, 'travel')) ||
            (this.matchesAgent(m.agent, 'travel') && (m.reasoning || m.thought)),
        )
        const explicitTravel = tStatus.slice().reverse().find((m) => m.reasoning || m.thought)
        if (explicitTravel) {
          travelThought = explicitTravel.reasoning || explicitTravel.thought
        } else if (this.travelTools.length > 0) {
          const descs = this.travelTools.map((t) => {
            const a = t.args || {}
            if (t.name === 'plan_route') {
              const r = (a.origin || '') + (a.destination ? `至${a.destination}` : '')
              const mode = a.mode ? `（${a.mode}）` : ''
              return `规划本市出行路线${r ? `：${r}` : ''}${mode}`
            }
            if (t.name === 'hail_ride') {
              const d = a.destination ? `前往${a.destination}` : ''
              return `帮老人叫车${d ? `（${d}）` : ''}`
            }
            if (t.name === 'get_weather') {
              return `查询本市天气（${a.city || ''}）`
            }
            return `${t.summary || t.name}`
          })
          travelThought = `银发导航已介入：${descs.join('；')}。只规划本市公交/地铁/步行的走法，出门前提醒天气。`
        } else if (this.thinking && this.isCurrentAgent('travel')) {
          travelThought = '银发导航助手正在规划本市出行路线…'
        } else if (tStatus.length > 0) {
          travelThought = tStatus[tStatus.length - 1].text
        } else {
          travelThought = '银发导航助手已就绪，提供本市公交/地铁/步行路线与出行天气。'
        }
      }

      // 4. 邻里帮独白（只认现在真挂着的四个工具：
      //    push_activities / suggest_call / suggest_walk / get_recipe）
      let communityThought = ''
      if (!this.isCommunityActive) {
        communityThought = '本轮未派发社区活动或陪伴相关任务，邻里帮处于待命状态。'
      } else {
        const cStatus = msgs.filter(
          (m) =>
            (m.kind === 'status' && this.matchesAgent(m.agent, 'community')) ||
            (this.matchesAgent(m.agent, 'community') && (m.reasoning || m.thought)),
        )
        const explicitComm = cStatus.slice().reverse().find((m) => m.reasoning || m.thought)
        if (explicitComm) {
          communityThought = explicitComm.reasoning || explicitComm.thought
        } else if (this.communityTools.length > 0) {
          const descs = this.communityTools.map((t) => {
            const a = t.args || {}
            if (t.name === 'push_activities') {
              return `查最近的社区活动${a.kind ? `（${a.kind}）` : ''}`
            }
            if (t.name === 'suggest_call') {
              return `把给${a.relation ? a.relation : '家人'}的一键拨号卡放到老人手边`
            }
            if (t.name === 'suggest_walk') {
              return `找一条散步环线${a.city ? `（${a.city}）` : ''}`
            }
            if (t.name === 'get_recipe') {
              return `教一道家常菜${a.dish ? `（${a.dish}）` : ''}`
            }
            return `${t.summary || t.name}`
          })
          communityThought = `邻里帮已介入：${descs.join('；')}。推活动、送拨号卡、给散步环线、教家常菜。`
        } else if (this.thinking && this.isCurrentAgent('community')) {
          communityThought = '邻里帮正在给老人找活动、找人说说话…'
        } else if (cStatus.length > 0) {
          communityThought = cStatus[cStatus.length - 1].text
        } else {
          communityThought = '邻里帮助手随时待命，帮您推活动、找人说话、出门走一走。'
        }
      }

      // 5. 安全网独白
      let safetyThought = ''
      const sStatus = msgs.filter(
        (m) =>
          (m.kind === 'status' && this.matchesAgent(m.agent, 'safety')) ||
          (this.matchesAgent(m.agent, 'safety') && (m.reasoning || m.thought)),
      )
      const explicitSafety = sStatus.slice().reverse().find((m) => m.reasoning || m.thought)
      if (explicitSafety) {
        safetyThought = explicitSafety.reasoning || explicitSafety.thought
      } else if (!this.isSafetyActive) {
        safetyThought = '安全防护网实时监测中：严格实施金融资金与医疗诊断双重防护，当前对话未触发强行挂起风控规则。'
      } else if (this.pendingTasksCount > 0) {
        const items = this.highRiskTools.filter((t) => t.status === 'suspended').map((t) => t.summary || t.name)
        safetyThought = `双向审批回路生效：拦截到 ${this.pendingTasksCount} 项高风险操作（${items.join('、')}），累计管控金额 ¥${this.highRiskAmountTotal}，已通过安全通道推至子女手机端待核准。`
      } else if (this.hasAnyRejected) {
        safetyThought = '安全网关阻断生效：检测到子女端已拒绝高危操作请求，系统已阻断执行链路并撤销相应操作，未发生扣费。'
      } else if (this.highRiskTools.length > 0 && this.highRiskTools.every((t) => t.status === 'completed')) {
        safetyThought = `双向审批回路已成功闭环：全部 ${this.highRiskTools.length} 项受控操作已获子女端授权核准，资金与操作安全验证通过。`
      } else {
        safetyThought = '资金与医疗安全防护网正常运行，全流程合规受控。'
      }

      // 6. 建造师独白
      let planBuilderThought = ''
      const pStatus = msgs.filter(
        (m) =>
          (m.kind === 'status' && this.matchesAgent(m.agent, 'plan_builder')) ||
          (this.matchesAgent(m.agent, 'plan_builder') && (m.reasoning || m.thought)),
      )
      const explicitPlan = pStatus.slice().reverse().find((m) => m.reasoning || m.thought)
      if (explicitPlan) {
        planBuilderThought = explicitPlan.reasoning || explicitPlan.thought
      } else if (this.isArtifactReady) {
        planBuilderThought = '已聚合多智能体协同产生的全部事实与凭证，消除幻觉与冲突，装配成适老大字版交付成果。'
      } else if (this.isPlanBuilderActive) {
        planBuilderThought = '方案建造师正在监听各子智能体执行回报，提取结构化事实数据进行装配准备…'
      } else {
        planBuilderThought = '等待前序子智能体任务达成，将自动对齐多源执行事实并装配成果。'
      }

      return {
        orchestrator: orchestratorThought,
        health: healthThought,
        travel: travelThought,
        community: communityThought,
        safety: safetyThought,
        planBuilder: planBuilderThought,
      }
    },


    safetyStatusClass() {
      if (this.pendingTasksCount > 0) return 'status-suspended'
      if (this.hasAnyRejected) return 'status-rejected'
      if (this.isArtifactReady || (this.hasTaskStarted && this.pendingTasksCount === 0 && this.highRiskTools.length > 0)) {
        return 'status-completed'
      }
      return 'status-ready'
    },
    safetyStatusIcon() {
      if (this.pendingTasksCount > 0) return '⏸️'
      if (this.hasAnyRejected) return '🛑'
      if (this.isArtifactReady || (this.hasTaskStarted && this.pendingTasksCount === 0 && this.highRiskTools.length > 0)) {
        return '✅'
      }
      return '🛡️'
    },
    safetyStatusText() {
      if (this.pendingTasksCount > 0) return `${this.pendingTasksCount}项高危待批`
      if (this.hasAnyRejected) return '已拦截终止'
      if (this.isArtifactReady || (this.hasTaskStarted && this.pendingTasksCount === 0 && this.highRiskTools.length > 0)) {
        return '安全闭环放行'
      }
      return '安全防线待命'
    },

    // 动态推导流水线任务分解步骤（杜绝写死“选医院挂专家号”）
    displaySteps() {
      // 从 messages 中提取最新真实 todo 快照
      const todoMsgs = this.safeMessages.filter(
        (m) => m.kind === 'todo' && Array.isArray(m.todos) && m.todos.length > 0,
      )
      const todoMsg = todoMsgs.length > 0 ? todoMsgs[todoMsgs.length - 1] : null

      if (todoMsg && todoMsg.todos.length > 0) {
        const validTodos = todoMsg.todos.filter((t) => t && typeof t === 'object')
        return validTodos.map((t, idx) => {
          const rawName = (t.content || t.text || t.title || '').trim()
          const name = rawName || `待办事项 ${idx + 1}`
          let st = t.status || 'in_progress'

          // 动态核验工具完成态。工具名必须对得上现在真在册的（见 backend 各 tools 模块
          // 的 register_*：出行只有 plan_route/hail_ride，社区只有 push_activities/
          // suggest_call/suggest_walk/get_recipe）；车票、酒店、陪诊下单、社区食堂
          // 这些工具已经随康乐收敛删掉，别再拿它们核状态 —— 那永远是 pending。
          const lower = name.toLowerCase()
          // 出行那步最优先：todo 里的原话是"规划从家怎么去医院"，含"医院"字样，
          // 若让挂号那条先判会把它错认成挂号步。
          if (lower.includes('怎么去') || lower.includes('怎么走') || lower.includes('路线') || lower.includes('导航')) {
            if (this.statusOf('plan_route') === 'completed' || this.statusOf('hail_ride') === 'completed') st = 'completed'
          } else if (lower.includes('挂号') || lower.includes('医院') || lower.includes('专家') || lower.includes('门诊')) {
            if (this.statusOf('register_appointment') === 'completed') st = 'completed'
            else if (this.statusOf('register_appointment') === 'rejected') st = 'rejected'
            else if (this.statusOf('register_appointment') === 'suspended') st = 'suspended'
            else if (this.statusOf('search_hospital') === 'completed' && !this.thinking) st = 'completed'
          } else if (lower.includes('天气') || lower.includes('穿衣')) {
            if (this.statusOf('get_weather') === 'completed') st = 'completed'
          } else if (lower.includes('计划书') || lower.includes('装配') || lower.includes('聚合') || lower.includes('方案')) {
            if (this.isArtifactReady) st = 'completed'
            else if (this.hasAnyRejected) st = 'rejected'
          } else if (lower.includes('活动') || lower.includes('散步') || lower.includes('菜谱')) {
            if (this.statusOf('push_activities') === 'completed' ||
                this.statusOf('suggest_walk') === 'completed' ||
                this.statusOf('get_recipe') === 'completed') st = 'completed'
          } else if (lower.includes('用药') || lower.includes('服药') || lower.includes('药品')) {
            if (this.statusOf('add_medication') === 'completed') st = 'completed'
          } else if (lower.includes('报告') || lower.includes('体检')) {
            if (this.statusOf('interpret_report') === 'completed') st = 'completed'
          }

          return { name, status: st }
        })
      }

      // 3. 真实对话中若无 todo 快照，但有真实工具调用，按实际执行的工具动态生成步骤
      if (this.allTools.length > 0) {
        return this.allTools.map((t) => ({
          name: t.summary || t.name,
          status: t.status === 'executed' ? 'completed' : t.status,
        }))
      }

      // 4. 正在思考但未发 todo/tool
      if (this.thinking || this.rootThinking) {
        return [{ name: '长辈诉求理解与任务规划', status: 'in_progress' }]
      }

      // 5. 任务未启动或日常对话无分步
      if (this.hasTaskStarted) {
        return [{ name: '意图感知与对话调度', status: 'completed' }]
      }
      return []
    },

    completedStepsCount() {
      return this.displaySteps.filter((s) => s.status === 'completed').length
    },

    totalStepsCount() {
      return this.displaySteps.length
    },

    highRiskToolNames() {
      // 包含后端真会拦截的金融支付与押金动作（pay、pay_deposit）。
      return ['pay', 'pay_deposit']
    },

    healthTools() {
      return this.parseTools(['health', '安康助手'])
    },

    travelTools() {
      return this.parseTools(['travel', '银发导航'])
    },

    communityTools() {
      return this.parseTools(['community', '邻里帮'])
    },

    planBuilderTools() {
      return this.parseTools(['plan_builder', 'planBuilder', '方案建造师'])
    },

    allTools() {
      return this.healthTools.concat(this.travelTools, this.communityTools, this.planBuilderTools)
    },

    highRiskTools() {
      // 一笔挂起的高危操作，会在事件流里同时留下两条来源：①工具节点(tool_call/
      // tool_result)，②挂起卡(suspended)。两者金额口径还不一样——节点读到的常是每晚
      // 单价，挂起卡带的是担保计算的总额。更糟的是真实模型偶尔把同一笔操作换个入参
      // 再下一遍，后端精确入参去重漏网时会冒出第二个确认任务。任凭哪种，对老人和家人
      // 来说都只是"办这一件事"，必须收敛成一张卡、一个金额。
      //
      // 本 App 的业务前提：同一会话对每个高危工具至多一笔在办操作（后端
      // _find_pending_duplicate 已按工具粒度收敛），所以这里也按【工具名】归并最稳，
      // 并优先采用担保总额与家人可读摘要。
      const byName = new Map()
      // 状态择优：completed(已办结) > suspended(等确认) > running > rejected/failed
      const rank = { completed: 4, suspended: 3, running: 2, rejected: 1, failed: 1 }

      const upsert = (card) => {
        const key = card.name || 'high_risk_op'
        const prev = byName.get(key)
        if (!prev) {
          byName.set(key, { ...card, key: card.key || key })
          return
        }
        // 金额：首个非空的胜出（挂起卡先处理，担保总额优先落位；单价节点不再覆盖它）
        if (prev.amount == null && card.amount != null) prev.amount = card.amount
        // 摘要：家人可读的详细说明 > 工具名
        if (card.summary && card.summary !== card.name &&
            (!prev.summary || prev.summary === prev.name)) {
          prev.summary = card.summary
        }
        if (card.desc && !prev.desc) prev.desc = card.desc
        if (card.confirmationId && !prev.confirmationId) prev.confirmationId = card.confirmationId
        if (card.result && !prev.result) prev.result = card.result
        if (card.resultText && !prev.resultText) prev.resultText = card.resultText
        if ((rank[card.status] || 0) > (rank[prev.status] || 0)) prev.status = card.status
      }

      // 1. 先放挂起卡：它带的是担保总额与家人可读摘要，是一笔挂起高危操作最准确的表示
      this.safeMessages
        .filter((m) => m.kind === 'suspend')
        .forEach((s, idx) => {
          const cid = s.confirmationId || ''
          upsert({
            key: cid || `suspend_${s.tool || 'op'}_${idx}`,
            name: s.tool || 'high_risk_op',
            summary: s.summary || s.message || s.tool || 'high_risk_op',
            status:
              s.status === 'executed' || s.status === 'completed'
                ? 'completed'
                : s.status === 'rejected'
                ? 'rejected'
                : 'suspended',
            args: {},
            result: '',
            resultText: '',
            isHighRisk: true,
            amount: s.amount ? Number(s.amount).toFixed(2) : null,
            desc: s.message || s.summary || '',
            confirmationId: cid,
          })
        })

      // 2. 再并入高危工具节点：同名已被挂起卡覆盖的，只做状态/结果融合，不另起一张卡。
      //    金额已在 parseTools 里优先取担保总额，这里首个非空胜出的规则也保证不会被
      //    单价回填。未挂起的高危工具（如无需确认即已执行完成的）独立成卡。
      this.allTools.filter((t) => t.isHighRisk).forEach((t) => upsert({ ...t }))

      return Array.from(byName.values())
    },

    highRiskAmountTotal() {
      const sum = this.highRiskTools.reduce(
        (acc, t) => acc + (t.amount ? Number(t.amount) : 0), 0)
      return sum.toFixed(2)
    },

    healthStatusClass() {
      return this.branchStatus(this.healthTools, 'health', '安康助手')
    },

    healthStatusIcon() {
      return this.branchIcon(this.healthStatusClass, '🏥')
    },

    healthStatusText() {
      const cls = this.healthStatusClass
      if (cls === 'status-suspended') return '待子女确认健康操作'
      if (cls === 'status-rejected') return '子女已拒绝该操作'
      if (cls === 'status-thinking') return '正在调用健康工具'
      if (cls === 'status-completed') return '健康任务已办结'
      return '健康守护待命'
    },

    travelStatusClass() {
      return this.branchStatus(this.travelTools, 'travel', '银发导航')
    },

    travelStatusIcon() {
      return this.branchIcon(this.travelStatusClass, '🧭')
    },

    travelStatusText() {
      const cls = this.travelStatusClass
      // 本地出行（plan_route/hail_ride）都不进高危、不挂起，所以正常走不到
      // status-suspended；万一别的路径让它挂起，也只说"出行安排待家人确认"——
      // 原来的"待子女确认票务/住宿"在票务/住宿整条砍掉后已经没有对应物了。
      if (cls === 'status-suspended') return '待家人确认出行安排'
      if (cls === 'status-rejected') return '子女已拒绝出行操作'
      if (cls === 'status-thinking') return '正在调用出行工具'
      if (cls === 'status-completed') return '出行任务已办结'
      return '银发导航待命'
    },

    communityStatusClass() {
      return this.branchStatus(this.communityTools, 'community', '邻里帮')
    },

    communityStatusIcon() {
      return this.branchIcon(this.communityStatusClass, '🏘️')
    },

    communityStatusText() {
      const cls = this.communityStatusClass
      if (cls === 'status-suspended') return '待子女确认社区服务'
      if (cls === 'status-rejected') return '子女已拒绝该服务'
      if (cls === 'status-thinking') return '正在安排社区服务'
      if (cls === 'status-completed') return '社区服务已安排'
      return '邻里帮待命'
    },

    planBuilderStatusClass() {
      if (this.isArtifactReady) return 'status-completed'
      if (this.planBuilderTools.some((t) => t.status === 'running')) return 'status-thinking'
      if (this.planBuilderTools.some((t) => t.status === 'rejected')) return 'status-rejected'
      if (this.pendingTasksCount > 0) return 'status-suspended'
      return 'status-ready'
    },
    planBuilderStatusIcon() {
      if (this.isArtifactReady) return '✅'
      if (this.planBuilderTools.some((t) => t.status === 'running')) return '⚡'
      if (this.planBuilderTools.some((t) => t.status === 'rejected')) return '🛑'
      if (this.pendingTasksCount > 0) return '⏸️'
      return '📐'
    },
    planBuilderStatusText() {
      if (this.isArtifactReady) return '交付方案装配完成'
      if (this.hasAnyRejected) return '前序审批已拒绝 · 装配终止'
      if (this.thinking && this.isPlanBuilderActive) return '装配方案中'
      if (this.pendingTasksCount > 0) return '等待前序审批解锁'
      return '方案装配待命'
    },

    isArtifactReady() {
      const hasCard = this.safeMessages.some((m) => m.kind === 'card')
      if (hasCard) return true
      const suspends = this.safeMessages.filter((m) => m.kind === 'suspend')
      if (
        suspends.length > 0 &&
        suspends.every((m) => m.status === 'executed' || m.status === 'completed') &&
        !this.hasAnyRejected &&
        !this.thinking
      ) {
        return true
      }
      return false
    },

    artifactDisplayTitle() {
      const msgs = this.safeMessages
      const realCard = msgs.slice().reverse().find((m) => m.kind === 'card')
      if (realCard && realCard.title) {
        return realCard.title.startsWith('《') ? realCard.title : `《${realCard.title}》`
      }
      return this.currentScenarioTag && this.currentScenarioTag !== '待命中'
        ? `《${this.currentScenarioTag}交付方案》`
        : '《智能协同服务交付物》'
    },

    artifactDisplaySubtitle() {
      const msgs = this.safeMessages
      const realCard = msgs.slice().reverse().find((m) => m.kind === 'card')
      if (realCard) {
        if (Array.isArray(realCard.notes) && realCard.notes.length > 0) {
          return realCard.notes.join(' · ')
        }
        if (realCard.sections && realCard.sections.length > 0) {
          return `${realCard.sections.length} 页适老大字版 · 事实对齐与闭环交付`
        }
        return '适老大字版 · 事实对齐与闭环交付'
      }
      return '适老大字版 · 待各协同智能体完成事实聚合后交付'
    },


    modalTitleText() {
      const msgs = this.safeMessages
      const realCard = msgs.slice().reverse().find((m) => m.kind === 'card')
      if (realCard && realCard.title) {
        return `${realCard.title.replace(/^《|》$/g, '')} (适老大字版)`
      }
      return this.currentScenarioTag && this.currentScenarioTag !== '待命中'
        ? `${this.currentScenarioTag}交付方案 (适老大字版)`
        : '智能协同方案交付物 (适老大字版)'
    },

    modalSubText() {
      return '由康乐多智能体协同网络聚合生成 · 事实对齐已闭环'
    },

    artifactPages() {

      const msgs = this.safeMessages
      const realCard = msgs.slice().reverse().find(
        (m) => m.kind === 'card' && (Array.isArray(m.sections || m.pages) || (m.body && typeof m.body === 'object')),
      )
      if (realCard) {
        const pages = realCard.pages || realCard.sections || []
        if (pages.length > 0) {
          return pages.map((p, idx) => ({
            title: (p && (p.title || p.heading)) || `第 ${idx + 1} 页`,
            rows: ((p && p.rows) || []).map((r) => ({
              label: (r && (r.label || r.k)) || '',
              val: (r && (r.val || r.v || r.value)) || '',
            })),
            note: p && Array.isArray(p.notes) ? p.notes.join('；') : ((p && (p.notes || p.note)) || ''),
          }))
        }
        if (realCard.body && typeof realCard.body === 'object') {
          return [
            {
              title: realCard.title || '服务确认凭证',
              rows: Object.entries(realCard.body).map(([label, val]) => ({
                label,
                val: String(val),
              })),
              note: Array.isArray(realCard.notes) ? realCard.notes.join('；') : (realCard.note || '已完成事实对齐，情况已告知家人。'),
            },
          ]
        }
      }

      // 若已达成闭环放行（高危全部批复/执行完毕）但无 card 事件，由真实执行工具动态合成方案页
      if (this.isArtifactReady && this.allTools.length > 0) {
        const pages = []
        const completedHealth = this.healthTools.filter((t) => t.status === 'completed')
        if (completedHealth.length > 0) {
          const rows = []
          completedHealth.forEach((t) => {
            const a = t.args || {}
            if (a.hospital) rows.push({ label: '就诊医院', val: a.hospital })
            if (a.doctor) rows.push({ label: '预约专家', val: a.doctor })
            if (a.date || a.time) rows.push({ label: '门诊时段', val: `${a.date || ''} ${a.time || ''}`.trim() })
            // 「知会不审批」：挂号当场办好，同一个动作里给绑定子女写一条知会。
            // 这里写"已核准"是把康乐说成了审批制产品 —— 家人是**被告知**，不是**核准**。
            // （对照 app/safety/risk_rules.py：register_appointment 在 NON_PAYMENT_TOOLS 里，
            // 只有 pay 那类金融动作才走审批。）
            if (a.fee || t.amount) rows.push({ label: '挂号费用', val: `¥${a.fee || t.amount}（已告知家人）` })
            if (t.result) rows.push({ label: '号源凭证', val: String(t.result) })
          })
          pages.push({
            title: '健康医疗预约凭证',
            rows: rows.length > 0 ? rows : [{ label: '服务状态', val: '专家号源预约成功' }],
            note: '就诊当天请携带老人社保卡与既往病历资料。',
          })
        }

        const completedTravel = this.travelTools.filter((t) => t.status === 'completed')
        if (completedTravel.length > 0) {
          const rows = []
          const hasTrainOrHotel = completedTravel.some(
            (t) => t.name.includes('train') || t.name.includes('ticket') || t.name.includes('hotel'),
          )
          completedTravel.forEach((t) => {
            const a = t.args || {}
            if (a.train_no || a.train) rows.push({ label: '出行车次', val: a.train_no || a.train })
            if (a.from_station || a.to_station) rows.push({ label: '行程区间', val: `${a.from_station || ''} ➔ ${a.to_station || ''}`.trim() })
            if (a.hotel || a.hotel_name) rows.push({ label: '适老酒店', val: a.hotel || a.hotel_name })
            if (a.origin || a.destination) rows.push({ label: '出行区间', val: `${a.origin || ''} ➔ ${a.destination || ''}` })
            if (a.mode) rows.push({ label: '出行方式', val: a.mode })
            if (t.name === 'plan_route' && t.result) rows.push({ label: '路线', val: String(t.result) })
            if (t.name === 'hail_ride' && t.result) rows.push({ label: '叫车信息', val: String(t.result) })
            if (t.result && !rows.some((r) => r.val === String(t.result))) rows.push({ label: '行程凭证', val: String(t.result) })
          })
          pages.push({
            title: hasTrainOrHotel ? '交通住宿出行凭证' : '本市出行路线',
            rows: rows.length > 0 ? rows : [{ label: '出行状态', val: hasTrainOrHotel ? '车次与适老住宿已锁定' : '本市路线已规划' }],
            note: hasTrainOrHotel ? '出行前请核对随身身份证件并关注目的地天气变化。' : '出门前记得带好身份证和医保卡，路上慢慢走、不着急。',
          })
        }

        const completedCommunity = this.communityTools.filter((t) => t.status === 'completed')
        if (completedCommunity.length > 0) {
          const rows = []
          completedCommunity.forEach((t) => {
            const a = t.args || {}
            if (t.name === 'push_activities') rows.push({ label: '社区活动', val: a.kind || '最近的社区活动' })
            if (t.name === 'suggest_call') rows.push({ label: '一键联系', val: `给${a.relation || '家人'}的拨号卡已放到老人手边` })
            if (t.name === 'suggest_walk') rows.push({ label: '散步环线', val: a.city ? `${a.city}的环线` : '附近环线' })
            if (t.name === 'get_recipe') rows.push({ label: '家常菜谱', val: a.dish || '按口味的家常菜' })
            if (t.result) rows.push({ label: '结果', val: String(t.result) })
          })
          pages.push({
            title: '社区活动与陪伴清单',
            rows: rows.length > 0 ? rows : [{ label: '服务状态', val: '活动与陪伴安排已给到老人' }],
            note: '活动以社区通知为准，出门前可以再跟社区确认一下。',
          })
        }

        if (pages.length > 0) return pages
      }

      return []
    },
  },
  methods: {
    matchesAgent(agentVal, targetKey) {
      if (!agentVal) return false
      const a = String(agentVal).toLowerCase()
      if (targetKey === 'health' || targetKey === '安康助手') {
        return a.includes('health') || a.includes('安康') || a.includes('医疗')
      }
      if (targetKey === 'travel' || targetKey === '银发导航') {
        return a.includes('travel') || a.includes('银发') || a.includes('出行') || a.includes('导航')
      }
      if (targetKey === 'community' || targetKey === '邻里帮') {
        return a.includes('community') || a.includes('邻里') || a.includes('便民')
      }
      if (targetKey === 'plan_builder' || targetKey === 'planBuilder' || targetKey === '方案建造师') {
        return a.includes('plan') || a.includes('建造师') || a.includes('方案')
      }
      // 英文键（main / orchestrator）是后端 agent_msg 实际带的键，必须保留；
      // display_name“康乐”那条只是后端没给键时的兜底，别删任何一支。
      if (targetKey === 'main' || targetKey === 'orchestrator' || targetKey === '康乐') {
        return a.includes('main') || a.includes('orchestrator') || a.includes('康乐') || a.includes('主调度')
      }
      if (targetKey === 'safety' || targetKey === '风控') {
        return a.includes('safety') || a.includes('guard') || a.includes('风控') || a.includes('安全') || a.includes('护航')
      }
      return false
    },

    normalizeAgent(agent) {
      if (!agent) return ''
      const a = String(agent).replace(/#\d+$/, '').trim()
      if (this.matchesAgent(a, 'health')) return 'health'
      if (this.matchesAgent(a, 'travel')) return 'travel'
      if (this.matchesAgent(a, 'community')) return 'community'
      if (this.matchesAgent(a, 'plan_builder')) return 'plan_builder'
      if (this.matchesAgent(a, 'safety')) return 'safety'
      if (this.matchesAgent(a, 'main')) return 'main'
      return a.toLowerCase()
    },

    isCurrentAgent(agentKey) {
      return this.matchesAgent(this.currentAgent, agentKey)
    },

    syncActiveBranches() {
      if (!this._userChangedAllExpanded) {
        this.collapsedAgents.health = !this.isHealthActive
        this.collapsedAgents.travel = !this.isTravelActive
        this.collapsedAgents.community = !this.isCommunityActive
        this.collapsedAgents.safety = !this.isSafetyActive
        this.collapsedAgents.planBuilder = !this.isPlanBuilderActive
      }
    },

    getAgentForTool(toolName, explicitAgent) {
      const t = String(toolName || '').toLowerCase()
      // 0. 主调度内部派发与调度工具
      if (
        t === 'delegate' ||
        t === 'todo_write' ||
        t === 'ask_user' ||
        t === 'handshake' ||
        this.matchesAgent(explicitAgent, 'main')
      ) {
        if (t === 'delegate' || t === 'todo_write' || t === 'ask_user' || t === 'handshake') {
          return 'main'
        }
      }

      if (this.matchesAgent(explicitAgent, 'health')) return 'health'
      if (this.matchesAgent(explicitAgent, 'travel')) return 'travel'
      if (this.matchesAgent(explicitAgent, 'community')) return 'community'
      if (this.matchesAgent(explicitAgent, 'plan_builder')) return 'plan_builder'

      // 1. 出行交通类（route/ride/taxi/train/ticket/hotel/weather/travel；route 优先于 plan）
      if (
        t.includes('route') ||
        t.includes('ride') ||
        t.includes('taxi') ||
        t.includes('train') ||
        t.includes('ticket') ||
        t.includes('hotel') ||
        t.includes('weather') ||
        t.includes('travel')
      ) {
        return 'travel'
      }

      // 2. 健康医疗类（hospital/appoint/medic/health/doctor/report/scam/diet/drug）
      if (
        t.includes('hospital') ||
        t.includes('appoint') ||
        t.includes('medic') ||
        t.includes('health') ||
        t.includes('doctor') ||
        t.includes('report') ||
        t.includes('scam') ||
        t.includes('diet') ||
        t.includes('drug')
      ) {
        return 'health'
      }

      // 3. 方案建造师类（compose/deliverable/build_plan/trip_plan）
      if (
        t.includes('compose') ||
        t.includes('deliverable') ||
        t.includes('build_plan') ||
        t.includes('trip_plan') ||
        (t.includes('plan') && !t.includes('route'))
      ) {
        return 'plan_builder'
      }

      // 4. 社区居家便民与生活服务类（显式关键词归属）
      if (
        t.includes('canteen') ||
        t.includes('order') ||
        t.includes('service') ||
        t.includes('clean') ||
        t.includes('accompany') ||
        t.includes('activit') ||
        t.includes('community') ||
        t.includes('pay') ||
        t.includes('plain') ||
        t.includes('profile') ||
        t.includes('help') ||
        t.includes('volunteer') ||
        t.includes('meal')
      ) {
        return 'community'
      }

      // 5. 严格兜底：未归属工具返回空字符串，不盲目点亮任何子分支
      return ''
    },

    parseTools(agentPrefixes) {
      const msgs = this.safeMessages
      const suspends = msgs.filter((m) => m.kind === 'suspend')
      const rawTools = msgs
        .filter(
          (m) =>
            m.kind === 'tool' &&
            agentPrefixes.some((p) => {
              if (p === '') return true
              const explicit = String(m.agent || '')
              const toolName = m.tool || m.name || ''
              const inferred = this.getAgentForTool(toolName, explicit)
              return (
                this.matchesAgent(explicit, p) ||
                explicit.indexOf(p) === 0 ||
                this.matchesAgent(inferred, p) ||
                inferred.indexOf(p) === 0
              )
            }),
        )
        .map((m, idx) => {
          const toolName = m.tool || m.name || 'tool'
          const suspend =
            (m.confirmationId ? suspends.slice().reverse().find((s) => s.confirmationId === m.confirmationId) : null) ||
            suspends.slice().reverse().find((s) => s.tool === toolName)
          let args = m.args
          if (typeof args === 'string') {
            try {
              args = JSON.parse(args)
            } catch (e) {
              args = {}
            }
          }
          if (!args || typeof args !== 'object') args = {}
          // 金额口径：担保计算的总额(price×nights 等，权威，随 suspended 事件下发) 优先，
          // 其次显式总额字段，最后才用 单价×数量 兜底。绝不把"每晚单价"直接当总额显示——
          // 否则订 2 晚 ¥340/晚 会错显成 ¥340（这正是老人看到 ¥340/¥680 两笔的根由）。
          let rawAmount = suspend && suspend.amount ? suspend.amount : null
          if (rawAmount == null) {
            rawAmount = args.total_amount || args.total || args.fee || args.amount || null
          }
          if (rawAmount == null && args.price != null && args.price !== '') {
            const qty = Number(args.nights || args.quantity || args.count || 1)
            rawAmount = Number(args.price) * (qty > 0 ? qty : 1)
          }
          const amount = Number(rawAmount)
          return {
            key: m.callId || `${toolName}#${idx}`,
            callId: m.callId || '',
            name: toolName,
            summary: m.summary || toolName,
            status: this.toolStatus(m, suspend),
            args,
            result: this.toolResultText(m),
            resultText: this.toolResultText(m),
            isHighRisk: this.highRiskToolNames.indexOf(toolName) !== -1 || !!suspend,
            amount: rawAmount != null && rawAmount !== '' && !isNaN(amount) ? amount.toFixed(2) : null,
            desc: (suspend && (suspend.message || suspend.summary)) || '',
            confirmationId: (suspend && suspend.confirmationId) || m.confirmationId || '',
          }
        })

      // 严格去重与状态融合：避免历史会话或多次事件流推送导致的重复工具卡片。
      // 后端不会把"一次调用"发两遍，但同一笔逻辑操作会因三种情况产生多个不同
      // call_id 的事件：①同名读工具挂在两个子智能体上各查一遍；②真实模型在
      // 后续步骤重发同名同参调用（suspended 结果读起来像"没办成"）；③SSE 断线
      // 转轮询时从头回放。因此不能只按 call_id 去重——还要按「工具名+入参」签名
      // 合并，才能把入参完全一致的重复卡收成一张。命中 callId / confirmationId /
      // 签名任一相同即视为同一张卡，终态与详细摘要向已存在的那张融合。
      const deduped = []
      const byKey = new Map()
      for (const item of rawTools) {
        let sig
        try {
          sig = `${item.name}:${JSON.stringify(item.args || {})}`
        } catch (e) {
          sig = `${item.name}:${item.summary || ''}`
        }
        const prev =
          (item.callId && byKey.get('c:' + item.callId)) ||
          (item.confirmationId && byKey.get('f:' + item.confirmationId)) ||
          byKey.get('s:' + sig) ||
          null
        if (prev) {
          // 状态优先级：终态（completed/failed/rejected/suspended）覆盖 running
          if (item.status && item.status !== 'running') prev.status = item.status
          // 摘要优先级：详细中文说明 > 工具名
          if (item.summary && item.summary !== item.name) prev.summary = item.summary
          if (item.result) prev.result = item.result
          if (item.resultText) prev.resultText = item.resultText
          if (item.confirmationId && !prev.confirmationId) prev.confirmationId = item.confirmationId
          if (item.callId && !prev.callId) prev.callId = item.callId
          if (item.amount && !prev.amount) prev.amount = item.amount
          if (item.desc && !prev.desc) prev.desc = item.desc
          // 补登记键：让后续相同 callId / confirmationId / 签名都命中这张已存在的卡
          if (item.callId) byKey.set('c:' + item.callId, prev)
          if (item.confirmationId) byKey.set('f:' + item.confirmationId, prev)
          byKey.set('s:' + sig, prev)
        } else {
          deduped.push(item)
          if (item.callId) byKey.set('c:' + item.callId, item)
          if (item.confirmationId) byKey.set('f:' + item.confirmationId, item)
          byKey.set('s:' + sig, item)
        }
      }
      return deduped
    },

    branchStatus(tools, agentId, displayName) {
      if (tools.some((t) => t.status === 'suspended')) return 'status-suspended'
      if (tools.some((t) => t.status === 'rejected')) return 'status-rejected'
      if (tools.some((t) => t.status === 'running')) return 'status-thinking'
      if (this.thinking && (this.isCurrentAgent(agentId) || this.isCurrentAgent(displayName))) {
        return 'status-thinking'
      }
      if (tools.length > 0 && tools.every((t) => t.status === 'completed' || t.status === 'failed')) {
        return 'status-completed'
      }
      return 'status-ready'
    },

    branchIcon(statusClass, idleIcon) {
      if (statusClass === 'status-suspended') return '⏸️'
      if (statusClass === 'status-rejected') return '🛑'
      if (statusClass === 'status-thinking') return '⚡'
      if (statusClass === 'status-completed') return '✅'
      return idleIcon
    },

    parseParamsTokens(params) {
      if (!params) return []
      let parsed = params
      if (typeof parsed === 'string' && (parsed.trim().startsWith('{') || parsed.trim().startsWith('['))) {
        try {
          parsed = JSON.parse(parsed)
        } catch (e) {
          // fallback to string format
        }
      }
      if (typeof parsed === 'object' && parsed !== null) {
        return Object.entries(parsed).map(([k, v], idx, arr) => {
          let valStr = String(v)
          const type = typeof v === 'number' ? 'number' : (typeof v === 'boolean' ? 'boolean' : 'string')
          if (typeof v === 'string') {
            valStr = `"${v}"`
          } else if (typeof v === 'object' && v !== null) {
            try {
              valStr = JSON.stringify(v)
            } catch (e) {
              valStr = String(v)
            }
          }
          return {
            k,
            v: valStr,
            type,
            isLast: idx === arr.length - 1,
          }
        })
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
            isLast: idx === parts.length - 1,
          }
        }
        return {
          k: 'arg',
          v: part.trim(),
          type: 'string',
          isLast: idx === parts.length - 1,
        }
      })
    },

    toggleToolResultExpand(key) {
      this.expandedToolResults = {
        ...this.expandedToolResults,
        [key]: !this.expandedToolResults[key],
      }
    },

    isToolResultExpanded(key) {
      return !!this.expandedToolResults[key]
    },

    toggleAllExpanded() {
      this._userChangedAllExpanded = true
      this.allExpanded = !this.allExpanded
    },

    toggleAgentCollapse(agentKey) {
      this.collapsedAgents[agentKey] = !this.collapsedAgents[agentKey]
      this._userChangedAllExpanded = true
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
          if (k.includes('route')) return '已规划 ✅'
          if (k.includes('ride')) return '已叫到车 ✅'
          if (k.includes('compose') || k.includes('deliverable')) return '已装配 ✅'
          return '已完成 ✅'
        case 'suspended':
          return '⏸️ 待确认'
        case 'running':
          return '执行中 ⚡'
        case 'pending':
          return '待调度 ⏳'
        case 'failed':
          return '执行失败 ⚠️'
        case 'rejected':
          return '已拦截 🛑'
        default:
          return status
      }
    },

    toolStatus(m, suspend = null) {
      if (suspend) {
        if (suspend.status === 'executed' || suspend.status === 'completed') return 'completed'
        if (suspend.status === 'rejected') return 'rejected'
        if (suspend.status === 'pending') return 'suspended'
      }
      if (m.status === 'suspended') return 'suspended'
      if (m.status === 'rejected' || m.blocked) return 'rejected'
      if (m.status === 'running') return 'running'
      if (m.status === 'executed' || m.status === 'completed') return 'completed'
      if (m.status === 'failed' || m.status === 'error') return 'failed'
      if (m.status === 'pending') return 'pending'
      if (m.result !== undefined || m.ok !== undefined) return m.ok === false ? 'failed' : 'completed'
      return 'running'
    },

    toolResultText(m) {
      const raw = m.result !== undefined && m.result !== null && m.result !== ''
        ? m.result
        : (m.data !== undefined && m.data !== null && m.data !== '' ? m.data : '')
      if (raw === '') return ''
      let text = raw
      if (typeof text === 'object') {
        try {
          text = JSON.stringify(text)
        } catch (e) {
          text = ''
        }
      }
      text = String(text)
      return text.length > 240 ? `${text.slice(0, 240)}…` : text
    },

    statusOf(name) {
      const hit = this.allTools.filter((t) => t.name === name).pop()
      return hit ? hit.status : 'pending'
    },

    stageStatus(riskTool, searchTool, idleStatus) {
      const risk = this.statusOf(riskTool)
      if (risk === 'completed') return 'completed'
      if (risk === 'rejected') return 'rejected'
      if (risk === 'suspended') return 'suspended'
      if (risk === 'running') return 'in_progress'
      if (this.statusOf(searchTool) === 'completed') return this.thinking ? 'in_progress' : 'completed'
      return this.thinking ? 'in_progress' : idleStatus
    },

    toolIcon(name) {
      const n = String(name || '')
      if (n.indexOf('appoint') !== -1 || n.indexOf('hospital') !== -1 || n.indexOf('register') !== -1) return '🏥'
      if (n.indexOf('weather') !== -1) return '🌤️'
      if (n.indexOf('ride') !== -1 || n.indexOf('route') !== -1) return '🚖'
      if (n.indexOf('walk') !== -1) return '🚶'
      if (n.indexOf('activit') !== -1) return '🎲'
      if (n.indexOf('recipe') !== -1 || n.indexOf('diet') !== -1) return '🍲'
      if (n.indexOf('call') !== -1) return '📞'
      if (n.indexOf('medic') !== -1 || n.indexOf('drug') !== -1 || n.indexOf('report') !== -1
          || n.indexOf('vital') !== -1 || n.indexOf('assess') !== -1 || n.indexOf('condition') !== -1) return '💊'
      if (n.indexOf('pay') !== -1 || n.indexOf('deposit') !== -1) return '💰'
      return '🛡️'
    },

    triggerApprove(confirmationId, toolName) {
      this.$emit('resolve-confirmation', {
        confirmationId,
        tool: toolName,
        status: 'executed',
      })
      const isDemo = !confirmationId || confirmationId.startsWith('conf_demo_')
      if (isDemo) {
        uni.showToast({ title: '已模拟子女端审核同意！', icon: 'success' })
      }
    },

    triggerReject(confirmationId, toolName) {
      this.$emit('resolve-confirmation', {
        confirmationId,
        tool: toolName,
        status: 'rejected',
      })
      const isDemo = !confirmationId || confirmationId.startsWith('conf_demo_')
      if (isDemo) {
        uni.showToast({ title: '已模拟子女端拒绝该操作', icon: 'none' })
      }
    },

    approveAllPending() {
      const pending = this.highRiskTools.filter((t) => t.status === 'suspended')
      if (pending.length === 0) {
        uni.showToast({ title: '当前没有待子女确认的高危操作', icon: 'none' })
        return
      }
      pending.forEach((t) => this.triggerApprove(t.confirmationId, t.name))
      uni.showToast({ title: `已模拟子女端一键核准 ${pending.length} 项操作！`, icon: 'success' })
    },

    toggleDemoAction(key) {
      if (!key) return
      const nextVal = !this.showDemoActions[key]
      if (typeof this.$set === 'function') {
        this.$set(this.showDemoActions, key, nextVal)
      } else {
        this.showDemoActions[key] = nextVal
      }
    },

    scrollToSection(id) {
      this._userChangedAllExpanded = true
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
      if (this.artifactPages.length === 0) {
        uni.showToast({ title: '暂未生成可展示的方案页面', icon: 'none' })
        return
      }
      this.showArtifactModal = true
    },

    readAloud() {
      uni.showToast({ title: `正在为您大字朗读${this.artifactDisplayTitle}…`, icon: 'none' })
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
  font-family: $lyj-font-family !important;
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
  white-space: nowrap !important;
  word-break: keep-all !important;
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


/* 智能体推理独白卡片 (R3) */
.agent-monologue-card {
  background: #fffbf5;
  border: 2rpx solid #fde68a;
  border-left: 6rpx solid #2A82E4;
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

.orchestrator-avatar { background: #EBF4FE; }
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
  background: linear-gradient(90deg, #10b981, #2A82E4, #1967C2);
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

.subagent-branch-card.is-inactive {
  opacity: 0.72;
  border-color: #f1f5f9;
  background: #fafafa;
  .branch-header {
    background: #fafafa;
  }
}

.subagent-branch-card.is-active-branch {
  border-color: #cbd5e1;
  box-shadow: 0 6rpx 20rpx rgba(15, 23, 42, 0.08);
}

.branch-idle-box {
  padding: 24rpx;
  text-align: center;
  background: #f8fafc;
  border-radius: 12rpx;
  border: 1rpx dashed #cbd5e1;
  margin: 12rpx 0;
}

.branch-idle-text {
  font-size: 22rpx;
  color: #94a3b8;
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

.tool-node.node-failed {
  border-left: 6rpx solid #f97316;
}

.tool-node.node-pending {
  border-left: 6rpx solid #cbd5e1;
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

.node-status-tag.failed {
  background: #FEE2E2;
  color: #DC2626;
}

.node-status-tag.pending {
  background: #f1f5f9;
  color: #64748b;
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
  align-items: flex-start;
  gap: 8rpx;
}

.suspend-title-group {
  display: flex;
  align-items: center;
  gap: 8rpx;
  flex-wrap: wrap;
  flex: 1;
}

.suspend-channel-tag {
  font-size: 18rpx;
  padding: 2rpx 10rpx;
  background: #fef3c7;
  color: #b45309;
  border-radius: 999rpx;
  font-weight: 600;
  border: 1rpx solid #fde68a;
}

.demo-channel-block {
  margin-top: 6rpx;
  padding-top: 6rpx;
  border-top: 1rpx dashed #fde68a;
}

.demo-link-row {
  display: inline-flex;
  cursor: pointer;
  padding: 4rpx 0;
}

.demo-link-text, .demo-channel-link {
  font-size: 20rpx;
  color: #b45309;
  text-decoration: underline;
  cursor: pointer;
}

.dash-actions-group {
  display: flex;
  align-items: center;
  gap: 12rpx;
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
  background: #2A82E4;
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
  background: #2A82E4;
  color: #ffffff;
  border: none;
}

.footer-btn.secondary {
  background: #f1f5f9;
  color: #334155;
  border: 2rpx solid #cbd5e1;
}


@keyframes lyj-pulse-glow {
  0%, 100% { transform: scale(1); opacity: 0.8; }
  50% { transform: scale(1.2); opacity: 1; }
}
</style>
