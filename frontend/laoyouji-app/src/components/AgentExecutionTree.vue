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
        <button v-if="!demoModeActive" class="icon-action-btn demo-btn" title="载入异地就医全链路演示" @tap="loadDemoScenario">
          <text class="icon-action-text">⚡ 演示全链路</text>
        </button>
        <button v-else class="icon-action-btn reset-demo-btn" title="切回实时会话跟踪" @tap="exitDemoMode">
          <text class="icon-action-text">↺ 退出演示</text>
        </button>
        <button v-if="isDesktop" class="icon-action-btn collapse-pane-btn" title="收起执行树面板" @tap="$emit('close')">
          <text class="icon-action-text">⇥ 收起</text>
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
        <text class="metric-val">1</text>
      </view>
      <view class="metric-divider"></view>
      <view class="metric-item">
        <text class="metric-label">协同智能体</text>
        <text class="metric-val">{{ activeAgentsCount }} / 4</text>
      </view>
      <view class="metric-divider"></view>
      <view class="metric-item">
        <text class="metric-label">执行工具数</text>
        <text class="metric-val">{{ totalToolsCount }}</text>
      </view>
      <view class="metric-divider"></view>
      <view class="metric-item" :class="{ 'has-pending': pendingTasksCount > 0, 'has-rejected': hasAnyRejected }">
        <text class="metric-label">{{ hasAnyRejected ? '高危拦截/拒绝' : '高危拦截' }}</text>
        <text class="metric-val">{{ pendingTasksCount > 0 ? (pendingTasksCount + ' 待确认') : (hasAnyRejected ? '已安全拦截' : '0 风险') }}</text>
      </view>
    </view>

    <!-- 可滚动树内容区 -->
    <scroll-view class="tree-scroll" scroll-y>
      <view class="tree-canvas">

        <!-- ================= 根节点：老友记主调度 (Orchestrator) ================= -->
        <view class="root-node-card" :class="{ 'is-thinking': thinking || rootThinking }">
          <view class="node-glass-glow"></view>
          <view class="node-head">
            <view class="node-badge-group">
              <view class="avatar-box orchestrator-avatar">
                <text class="avatar-icon">🤵</text>
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

          <!-- 全局规划链路步骤（4阶段动态状态机） -->
          <view class="plan-steps-track">
            <view class="track-header">
              <text class="track-title">📋 任务分解流水线 (Todo State Machine)</text>
              <text class="track-progress">{{ completedStepsCount }}/{{ totalStepsCount }} 已完成</text>
            </view>
            <view class="steps-grid">
              <view
                v-for="(step, sIdx) in displaySteps"
                :key="sIdx"
                class="step-chip"
                :class="'step-' + step.status"
              >
                <view class="step-num">{{ sIdx + 1 }}</view>
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
                        <view class="node-status-tag" :class="healthTools.searchHospital.status">
                          {{ formatToolStatus(healthTools.searchHospital.status) }}
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <text class="mono-code">{{ healthTools.searchHospital.params || 'hospital: "北京积水潭医院", symptom: "骨科/腿疼", grade: "三甲专科"' }}</text>
                      </view>
                      <view v-if="healthTools.searchHospital.result" class="result-box">
                        <text class="result-text">🎯 匹配号源：{{ healthTools.searchHospital.result }}</text>
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
                        <view class="node-status-tag" :class="healthTools.registerAppointment.status">
                          {{ formatToolStatus(healthTools.registerAppointment.status) }}
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <text class="mono-code">{{ healthTools.registerAppointment.params || 'doctor: "田伟主任医师", dept: "骨科", fee: 100.0, time: "08:30-09:30"' }}</text>
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
                            🚫 模拟子女拒绝
                          </button>
                        </view>
                      </view>
                      <!-- 已执行/已同意成功卡片 -->
                      <view v-else-if="healthTools.registerAppointment.status === 'executed'" class="executed-alert-card">
                        <text class="executed-icon">🟢</text>
                        <text class="executed-text">子女已审批同意 · 积水潭骨科田伟主任号挂号成功</text>
                      </view>
                      <!-- 已拒绝卡片 (R2) -->
                      <view v-else-if="healthTools.registerAppointment.status === 'rejected'" class="rejected-alert-card">
                        <view class="reject-header">
                          <text class="reject-icon">🔴</text>
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
                        <view class="node-status-tag" :class="travelTools.searchTrain.status">
                          {{ formatToolStatus(travelTools.searchTrain.status) }}
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <text class="mono-code">{{ travelTools.searchTrain.params || 'from: "南京南", to: "北京南", date: "明天", seat: "二等座"' }}</text>
                      </view>
                      <view v-if="travelTools.searchTrain.result" class="result-box">
                        <text class="result-text">🚄 {{ travelTools.searchTrain.result }}</text>
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
                        <view class="node-status-tag" :class="travelTools.bookTicket.status">
                          {{ formatToolStatus(travelTools.bookTicket.status) }}
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <text class="mono-code">{{ travelTools.bookTicket.params || 'train: "G102", seat: "二等座", amount: 443.5, passenger: "老人本人"' }}</text>
                      </view>
                      <!-- 挂起卡片 -->
                      <view v-if="travelTools.bookTicket.status === 'suspended'" class="suspended-alert-card">
                        <view class="suspend-header">
                          <text class="suspend-icon">⏸️</text>
                          <text class="suspend-title">等待子女确认 (¥{{ travelTools.bookTicket.amount ? Number(travelTools.bookTicket.amount).toFixed(2) : '443.50' }})</text>
                        </view>
                        <text class="suspend-desc">{{ travelTools.bookTicket.desc || '订票涉及代付扣款，已向子女手机发送确认清单' }}</text>
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
                            🚫 模拟子女拒绝
                          </button>
                        </view>
                      </view>
                      <!-- 已执行卡片 -->
                      <view v-else-if="travelTools.bookTicket.status === 'executed'" class="executed-alert-card">
                        <text class="executed-icon">🟢</text>
                        <text class="executed-text">子女已审批同意 · G102二等座已出票，凭身份证直接进站</text>
                      </view>
                      <!-- 已拒绝卡片 (R2) -->
                      <view v-else-if="travelTools.bookTicket.status === 'rejected'" class="rejected-alert-card">
                        <view class="reject-header">
                          <text class="reject-icon">🔴</text>
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
                        <view class="node-status-tag" :class="travelTools.searchHotel.status">
                          {{ formatToolStatus(travelTools.searchHotel.status) }}
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <text class="mono-code">{{ travelTools.searchHotel.params || 'poi: "北京积水潭医院周边1.5km", barrier_free: true' }}</text>
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
                        <view class="node-status-tag" :class="travelTools.bookHotel.status">
                          {{ formatToolStatus(travelTools.bookHotel.status) }}
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <text class="mono-code">{{ travelTools.bookHotel.params || 'hotel: "漫心酒店积水潭店", nights: 2, total_amount: 680.0' }}</text>
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
                            🚫 模拟子女拒绝
                          </button>
                        </view>
                      </view>
                      <!-- 已执行卡片 -->
                      <view v-else-if="travelTools.bookHotel.status === 'executed'" class="executed-alert-card">
                        <text class="executed-icon">🟢</text>
                        <text class="executed-text">子女已审批同意 · 漫心酒店无障碍双床房已预留成功</text>
                      </view>
                      <!-- 已拒绝卡片 (R2) -->
                      <view v-else-if="travelTools.bookHotel.status === 'rejected'" class="rejected-alert-card">
                        <view class="reject-header">
                          <text class="reject-icon">🔴</text>
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
                        <view class="node-status-tag" :class="travelTools.getWeather.status">
                          {{ formatToolStatus(travelTools.getWeather.status) }}
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <text class="mono-code">{{ travelTools.getWeather.params || 'city: "北京", days: 3, elder_comfort_index: true' }}</text>
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

          <!-- 分支 3：邻里助手 (Community Agent · 邻里帮) -->
          <view class="subagent-branch-card community-branch" :class="{ 'collapsed': collapsedAgents.community }">
            <view class="branch-header" @tap="toggleAgentCollapse('community')">
              <view class="branch-header-left">
                <view class="avatar-box community-avatar">
                  <text class="avatar-icon">🏘️</text>
                </view>
                <view class="branch-title-group">
                  <view class="branch-name-row">
                    <text class="branch-name">邻里助手</text>
                    <text class="branch-en-tag">Community Agent · 邻里帮</text>
                  </view>
                  <text class="branch-desc">社区助餐 · 适老陪诊 · 家政保洁</text>
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
                <view class="tools-flow">
                  <view class="tool-node" :class="'node-' + communityTools.orderService.status">
                    <view class="node-connector-dot"></view>
                    <view class="node-card-inner">
                      <view class="node-top-row">
                        <view class="node-name-box">
                          <text class="tool-fn-name">order_service / escort</text>
                          <text class="tool-cn-name">就医全程陪诊服务推荐</text>
                        </view>
                        <view class="node-status-tag" :class="communityTools.orderService.status">
                          {{ formatToolStatus(communityTools.orderService.status) }}
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <text class="mono-code">{{ communityTools.orderService.params || 'service: "异地就医火车站接站+医院全程陪诊", city: "北京"' }}</text>
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

          <!-- 分支 4：规划建造师 (PlanBuilder · 方案聚合) -->
          <view class="subagent-branch-card planbuilder-branch" :class="{ 'collapsed': collapsedAgents.planBuilder }">
            <view class="branch-header" @tap="toggleAgentCollapse('planBuilder')">
              <view class="branch-header-left">
                <view class="avatar-box planbuilder-avatar">
                  <text class="avatar-icon">📐</text>
                </view>
                <view class="branch-title-group">
                  <view class="branch-name-row">
                    <text class="branch-name">规划建造师</text>
                    <text class="branch-en-tag">PlanBuilder · 方案装配</text>
                  </view>
                  <text class="branch-desc">多智能体回报对齐 · 交付物确定性装配</text>
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
                        <view class="node-status-tag" :class="planBuilderTools.composeDeliverable.status">
                          {{ formatToolStatus(planBuilderTools.composeDeliverable.status) }}
                        </view>
                      </view>
                      <view class="mono-params-box">
                        <text class="mono-code">{{ planBuilderTools.composeDeliverable.params || 'kind: "trip_plan", sources: ["health", "travel", "community"]' }}</text>
                      </view>
                      <view v-if="planBuilderTools.composeDeliverable.result" class="result-box">
                        <text class="result-text">✨ 已成功从日志回放提取全部事实，装配成五页大字适老就医计划书</text>
                      </view>
                    </view>
                  </view>

                  <!-- ================= 终极产物叶子节点：可点击计划书 Artifact (R2) ================= -->
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
            <text class="modal-sub">由老友记主调度协同安康助手与银发导航自动生成</text>
          </view>
          <button class="modal-close-btn" @tap="showArtifactModal = false">✕</button>
        </view>
        <scroll-view class="artifact-modal-body" scroll-y>
          <view class="plan-page-card" v-for="(p, pIdx) in artifactPages" :key="pIdx">
            <view class="page-card-head">
              <text class="page-badge">第 {{ pIdx + 1 }} 页</text>
              <text class="page-title">{{ p.title }}</text>
            </view>
            <view class="page-rows">
              <view v-for="(row, rIdx) in p.rows" :key="rIdx" class="page-row">
                <text class="row-label">{{ row.label }}</text>
                <text class="row-val">{{ row.val }}</text>
              </view>
            </view>
            <text v-if="p.note" class="page-note">💡 贴心叮嘱：{{ p.note }}</text>
          </view>
          <view class="disclaimer-note">
            <text>※ 车次、号源、酒店数据来自模拟调度接口，仅供演示体验。出行前请以官方出票信息为准。</text>
          </view>
        </scroll-view>
        <view class="artifact-modal-footer">
          <button class="footer-action-btn secondary" @tap="readAloud">🔊 朗读整本方案</button>
          <button class="footer-action-btn primary" @tap="simulatePrint">🖨️ 打印大字纸质版</button>
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
        planBuilder: false,
      },
      showArtifactModal: false,
      // 演示覆盖状态（可被实际事件覆盖，也可以在点击演示按钮时触发）
      demoModeActive: false,
      demoApprovals: {
        appointment: false, // true = approved, 'rejected' = rejected, false = pending/suspended
        ticket: false,
        hotel: false,
      },
    }
  },
  computed: {
    allExpanded: {
      get() {
        return (
          !this.collapsedAgents.health &&
          !this.collapsedAgents.travel &&
          !this.collapsedAgents.community &&
          !this.collapsedAgents.planBuilder
        )
      },
      set(val) {
        this.collapsedAgents.health = !val
        this.collapsedAgents.travel = !val
        this.collapsedAgents.community = !val
        this.collapsedAgents.planBuilder = !val
      },
    },
    // 是否有任何真实对话/任务开始
    hasTaskStarted() {
      if (this.demoModeActive) return true
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

    // 是否有任何高危操作被拒绝
    hasAnyRejected() {
      if (this.demoModeActive) {
        return (
          this.demoApprovals.appointment === 'rejected' ||
          this.demoApprovals.ticket === 'rejected' ||
          this.demoApprovals.hotel === 'rejected'
        )
      }
      return (this.messages || []).some(
        (m) => m.kind === 'suspend' && m.status === 'rejected',
      )
    },

    // 是否有任何挂起任务待确认
    pendingTasksCount() {
      if (this.demoModeActive) {
        let demoPending = 0
        if (this.demoApprovals.appointment === false) demoPending++
        if (this.demoApprovals.ticket === false) demoPending++
        if (this.demoApprovals.hotel === false) demoPending++
        return demoPending
      }
      return (this.messages || []).filter(
        (m) => m.kind === 'suspend' && m.status === 'pending',
      ).length
    },

    activeAgentsCount() {
      if (!this.hasTaskStarted) return 0
      return 4
    },

    totalToolsCount() {
      if (!this.hasTaskStarted) return 0
      return 8
    },

    // 实时状态文本与药丸样式
    globalStatusText() {
      if (this.thinking || this.rootThinking) return 'LLM 推理规划中'
      if (this.pendingTasksCount > 0) return '高危操作等待审批'
      if (this.hasAnyRejected) return '高危操作已被子女拒绝'
      if (this.isArtifactReady) return '执行闭环 · 交付完毕'
      if (this.hasTaskStarted) return '阶段任务协同进行中'
      return '协同网络就绪 · 待命'
    },

    globalStatusClass() {
      if (this.thinking || this.rootThinking) return 'status-thinking'
      if (this.pendingTasksCount > 0) return 'status-suspended'
      if (this.hasAnyRejected) return 'status-rejected'
      if (this.isArtifactReady) return 'status-completed'
      if (this.hasTaskStarted) return 'status-thinking'
      return 'status-ready'
    },

    isAnyAgentActive() {
      return this.thinking || this.rootThinking || this.pendingTasksCount > 0 || this.hasTaskStarted
    },

    // 根节点状态
    rootStatusClass() {
      if (this.thinking || this.rootThinking) return 'status-thinking'
      if (this.hasAnyRejected) return 'status-rejected'
      if (this.isArtifactReady) return 'status-completed'
      if (this.hasTaskStarted) return 'status-thinking'
      return 'status-ready'
    },

    rootStatusIcon() {
      if (this.thinking || this.rootThinking) return '🔵'
      if (this.hasAnyRejected) return '🔴'
      if (this.isArtifactReady) return '🟢'
      return '🟢'
    },

    rootStatusText() {
      if (this.thinking || this.rootThinking) return '意图拆解与全局调度中'
      if (this.hasAnyRejected) return '局部流程已由家人终止'
      if (this.isArtifactReady) return '全链路执行完毕'
      if (this.hasTaskStarted) return '调度执行中'
      return '主调度就绪 · 等待老人诉求'
    },

    currentScenarioTag() {
      if (!this.hasTaskStarted) return '待命中'
      return '跨城异地就医闭环'
    },

    currentIntentText() {
      // 从最新用户消息中提取意图，若无且未开始则使用就绪指引
      const userMsgs = (this.messages || []).filter((m) => m.isUser && m.text)
      if (userMsgs.length > 0) {
        const last = userMsgs[userMsgs.length - 1].text
        return `解析诉求："${last}" · 拆解专家挂号、双向高铁票、适老酒店及五页就医出行方案`
      }
      if (this.demoModeActive) {
        return '老人诉求："我想去北京看腿疼的老毛病" ➔ 调度安康助手查专家、银发导航订高铁和酒店、生成全套就医出行计划'
      }
      return '等待老人输入诉求… 可按住说话或打字告诉老友记，主调度将实时解析意图并派发至子智能体协同网络。'
    },

    // 任务流水线 4 个阶段
    displaySteps() {
      // 1. 如果有真实的 todo/write 消息，以真实 pipeline 为主，同时同步挂起/审批/拒绝状态
      const todoMsg = (this.messages || []).find((m) => m.kind === 'todo' && Array.isArray(m.todos))
      if (todoMsg && todoMsg.todos.length > 0) {
        return todoMsg.todos.map((t, idx) => {
          let st = t.status || 'in_progress'
          const name = t.text || `阶段 ${idx + 1}`
          if (name.includes('挂号') || name.includes('医院') || name.includes('专家')) {
            if (this.healthTools.registerAppointment.status === 'executed') st = 'completed'
            else if (this.healthTools.registerAppointment.status === 'rejected') st = 'rejected'
            else if (this.healthTools.registerAppointment.status === 'suspended') st = 'suspended'
          } else if (name.includes('车次') || name.includes('车票') || name.includes('高铁') || name.includes('订票')) {
            if (this.travelTools.bookTicket.status === 'executed') st = 'completed'
            else if (this.travelTools.bookTicket.status === 'rejected') st = 'rejected'
            else if (this.travelTools.bookTicket.status === 'suspended') st = 'suspended'
          } else if (name.includes('酒店') || name.includes('住宿')) {
            if (this.travelTools.bookHotel.status === 'executed') st = 'completed'
            else if (this.travelTools.bookHotel.status === 'rejected') st = 'rejected'
            else if (this.travelTools.bookHotel.status === 'suspended') st = 'suspended'
          } else if (name.includes('计划书') || name.includes('装配') || name.includes('聚合') || name.includes('出行方案')) {
            if (this.isArtifactReady) st = 'completed'
            else if (this.hasAnyRejected) st = 'rejected'
          }
          return {
            name,
            status: st,
          }
        })
      }

      // 2. 演示 4 步骤
      if (this.demoModeActive) {
        return [
          {
            name: '积水潭医院骨科田伟主任号挂号',
            status: this.demoApprovals.appointment === true ? 'completed' : (this.demoApprovals.appointment === 'rejected' ? 'rejected' : 'suspended'),
          },
          {
            name: '南京南-北京南 G102 高铁订票',
            status: this.demoApprovals.ticket === true ? 'completed' : (this.demoApprovals.ticket === 'rejected' ? 'rejected' : 'suspended'),
          },
          {
            name: '积水潭医院周边适老酒店2晚预订',
            status: this.demoApprovals.hotel === true ? 'completed' : (this.demoApprovals.hotel === 'rejected' ? 'rejected' : 'suspended'),
          },
          {
            name: '装配五页就医出行大字可打印计划书',
            status: this.isArtifactReady ? 'completed' : (this.hasAnyRejected ? 'rejected' : 'pending'),
          },
        ]
      }

      // 3. 尚未开始任务时的默认状态：均为待进行 ⏳
      if (!this.hasTaskStarted) {
        return [
          { name: '选权威医院挂专家号', status: 'pending' },
          { name: '查明日高铁车次及订票', status: 'pending' },
          { name: '订医院周边适老酒店', status: 'pending' },
          { name: '聚合装配出行就医计划书', status: 'pending' },
        ]
      }

      // 4. 任务进行中或已完成：根据各子智能体真实工具状态动态推导流水线四步
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

      const step4Status = this.isArtifactReady
        ? 'completed'
        : (this.hasAnyRejected
          ? 'rejected'
          : (this.thinking ? 'pending' : 'pending'))

      return [
        { name: '选权威医院挂专家号', status: step1Status },
        { name: '查明日高铁车次及订票', status: step2Status },
        { name: '订医院周边适老酒店', status: step3Status },
        { name: '聚合装配出行就医计划书', status: step4Status },
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
      const msgs = this.messages || []
      const suspends = msgs.filter((m) => m.kind === 'suspend')
      const appointSuspend = suspends.find(
        (m) =>
          m.tool === 'register_appointment' ||
          (m.summary && (m.summary.includes('挂号') || m.summary.includes('医院'))) ||
          m.amount === 100,
      )

      const searchHospTool = msgs.find(
        (m) => m.kind === 'tool' && (m.tool === 'search_hospital' || (m.summary && m.summary.includes('医院'))),
      )
      const appointTool = msgs.find(
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
        if (appointStatus === 'pending') appointStatus = 'suspended'
      } else if (this.demoModeActive) {
        if (this.demoApprovals.appointment === true) appointStatus = 'executed'
        else if (this.demoApprovals.appointment === 'rejected') appointStatus = 'rejected'
        else appointStatus = 'suspended'
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
      if (this.healthTools.registerAppointment.status === 'suspended') return 'status-suspended'
      if (this.healthTools.registerAppointment.status === 'rejected') return 'status-rejected'
      if (this.healthTools.registerAppointment.status === 'executed') return 'status-completed'
      if (this.healthTools.searchHospital.status === 'running' || this.healthTools.registerAppointment.status === 'running') return 'status-thinking'
      if (this.healthTools.searchHospital.status === 'completed') return 'status-completed'
      return 'status-ready'
    },

    healthStatusIcon() {
      if (this.healthTools.registerAppointment.status === 'suspended') return '⏸️'
      if (this.healthTools.registerAppointment.status === 'rejected') return '🔴'
      if (this.healthTools.registerAppointment.status === 'executed' || this.healthTools.searchHospital.status === 'completed') return '🟢'
      if (this.healthTools.searchHospital.status === 'running') return '🔵'
      return '⚪'
    },

    healthStatusText() {
      if (this.healthTools.registerAppointment.status === 'suspended') return '待子女确认挂号'
      if (this.healthTools.registerAppointment.status === 'rejected') return '子女已拒绝挂号'
      if (this.healthTools.registerAppointment.status === 'executed') return '挂号成功 · 已确认'
      if (this.healthTools.searchHospital.status === 'running') return '检索号源中'
      if (this.healthTools.searchHospital.status === 'completed') return '号源检索完成'
      return '健康守护待命'
    },

    // 银发导航工具状态响应
    travelTools() {
      const msgs = this.messages || []
      const suspends = msgs.filter((m) => m.kind === 'suspend')
      const ticketSuspend = suspends.find(
        (m) =>
          m.tool === 'book_ticket' ||
          (m.summary && (m.summary.includes('车票') || m.summary.includes('高铁') || m.summary.includes('票'))) ||
          m.amount === 443.5,
      )
      const hotelSuspend = suspends.find(
        (m) =>
          m.tool === 'book_hotel' ||
          (m.summary && (m.summary.includes('酒店') || m.summary.includes('房'))) ||
          m.amount === 680,
      )

      const searchTrainTool = msgs.find(
        (m) => m.kind === 'tool' && (m.tool === 'search_train' || (m.summary && m.summary.includes('车次'))),
      )
      const bookTicketTool = msgs.find(
        (m) => m.kind === 'tool' && (m.tool === 'book_ticket' || (m.summary && m.summary.includes('订票'))),
      )
      const searchHotelTool = msgs.find(
        (m) => m.kind === 'tool' && (m.tool === 'search_hotel' || (m.summary && m.summary.includes('酒店'))),
      )
      const bookHotelTool = msgs.find(
        (m) => m.kind === 'tool' && (m.tool === 'book_hotel' || (m.summary && m.summary.includes('预订'))),
      )
      const weatherTool = msgs.find(
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
        if (ticketStatus === 'pending') ticketStatus = 'suspended'
      } else if (this.demoModeActive) {
        if (this.demoApprovals.ticket === true) ticketStatus = 'executed'
        else if (this.demoApprovals.ticket === 'rejected') ticketStatus = 'rejected'
        else ticketStatus = 'suspended'
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
        if (hotelStatus === 'pending') hotelStatus = 'suspended'
      } else if (this.demoModeActive) {
        if (this.demoApprovals.hotel === true) hotelStatus = 'executed'
        else if (this.demoApprovals.hotel === 'rejected') hotelStatus = 'rejected'
        else hotelStatus = 'suspended'
        hotelConfId = 'conf_demo_hotel'
      }

      let weatherStatus = 'pending'
      let weatherParams = weatherTool && weatherTool.args ? this.formatParams(weatherTool.args) : ''
      let weatherResult = ''
      if (weatherTool) {
        weatherStatus = weatherTool.status === 'running' ? 'running' : 'completed'
        weatherResult = weatherTool.result || weatherTool.summary || '北京晴朗 18~26℃'
      } else if (this.demoModeActive || (this.hasTaskStarted && !this.thinking)) {
        weatherStatus = 'completed'
        weatherResult = '北京晴朗 18~26℃，空气良，紫外线适中，建议着舒适棉织外衣'
      }

      return {
        searchTrain: { status: trainStatus, params: trainParams, result: trainResult },
        bookTicket: { status: ticketStatus, confirmationId: ticketConfId, params: ticketParams, amount: ticketAmount, desc: ticketDesc },
        searchHotel: { status: hotelSearchStatus, params: hotelSearchParams, result: hotelSearchResult },
        bookHotel: { status: hotelStatus, confirmationId: hotelConfId, params: hotelParams, amount: hotelAmount, desc: hotelDesc },
        getWeather: { status: weatherStatus, params: weatherParams, result: weatherResult },
      }
    },

    travelStatusClass() {
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
      if (this.travelTools.bookTicket.status === 'suspended' || this.travelTools.bookHotel.status === 'suspended') {
        return '⏸️'
      }
      if (this.travelTools.bookTicket.status === 'rejected' || this.travelTools.bookHotel.status === 'rejected') {
        return '🔴'
      }
      if (this.travelTools.bookTicket.status === 'executed' || this.travelTools.searchTrain.status === 'completed') {
        return '🟢'
      }
      if (this.thinking) return '🔵'
      return '⚪'
    },

    travelStatusText() {
      if (this.travelTools.bookTicket.status === 'suspended' || this.travelTools.bookHotel.status === 'suspended') {
        return '待子女确认票务/酒店'
      }
      if (this.travelTools.bookTicket.status === 'rejected' || this.travelTools.bookHotel.status === 'rejected') {
        return '子女已拒绝出单'
      }
      if (this.travelTools.bookTicket.status === 'executed' && this.travelTools.bookHotel.status === 'executed') {
        return '车次与酒店均已出单'
      }
      if (this.thinking) return '规划路线与车次中'
      if (this.travelTools.searchTrain.status === 'completed') return '行程车次已规划'
      return '银发导航待命'
    },

    // 邻里助手
    communityTools() {
      const msgs = this.messages || []
      const orderTool = msgs.find(
        (m) => m.kind === 'tool' && (m.tool === 'order_service' || (m.summary && m.summary.includes('陪诊'))),
      )
      let status = 'pending'
      let params = orderTool && orderTool.args ? this.formatParams(orderTool.args) : ''
      if (orderTool) {
        status = orderTool.status === 'running' ? 'running' : 'completed'
      } else if (this.demoModeActive || (this.hasTaskStarted && !this.thinking)) {
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
      if (this.communityTools.orderService.status === 'completed') return '🟢'
      if (this.communityTools.orderService.status === 'running') return '🔵'
      return '⚪'
    },
    communityStatusText() {
      if (this.communityTools.orderService.status === 'completed') return '陪诊服务已待命'
      return '邻里助手待命'
    },

    // 规划建造师
    planBuilderTools() {
      const msgs = this.messages || []
      const hasCard = msgs.some((m) => m.kind === 'card')
      const composeTool = msgs.find((m) => m.kind === 'tool' && m.tool === 'compose_deliverable')
      let params = composeTool && composeTool.args ? this.formatParams(composeTool.args) : ''

      let status = 'pending'
      if (this.hasAnyRejected) {
        status = 'rejected'
      } else if (hasCard) {
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
      if (this.planBuilderTools.composeDeliverable.status === 'running') return 'status-thinking'
      if (this.planBuilderTools.composeDeliverable.status === 'rejected') return 'status-rejected'
      if (this.planBuilderTools.composeDeliverable.status === 'completed') return 'status-completed'
      if (this.pendingTasksCount > 0) return 'status-suspended'
      return 'status-ready'
    },
    planBuilderStatusIcon() {
      if (this.planBuilderTools.composeDeliverable.status === 'running') return '🔵'
      if (this.planBuilderTools.composeDeliverable.status === 'rejected') return '🔴'
      if (this.planBuilderTools.composeDeliverable.status === 'completed') return '🟢'
      if (this.pendingTasksCount > 0) return '⏳'
      return '⚪'
    },
    planBuilderStatusText() {
      if (this.planBuilderTools.composeDeliverable.status === 'running') return '装配计划书中'
      if (this.planBuilderTools.composeDeliverable.status === 'rejected') return '前序审批已拒绝 · 装配终止'
      if (this.planBuilderTools.composeDeliverable.status === 'completed') return '五页计划书装配完成'
      if (this.pendingTasksCount > 0) return '等待前序审批解锁'
      return '方案装配待命'
    },

    isArtifactReady() {
      // 只要有一张 card 消息，或演示状态全部通过
      const hasCard = (this.messages || []).some((m) => m.kind === 'card')
      if (hasCard) return true
      if (this.demoModeActive) {
        return (
          this.demoApprovals.appointment === true &&
          this.demoApprovals.ticket === true &&
          this.demoApprovals.hotel === true
        )
      }
      // 真实交互：若有挂起任务且全部已获审批执行（无拒绝、不在推理中），动态解锁交付物
      const msgs = this.messages || []
      const suspends = msgs.filter((m) => m.kind === 'suspend')
      if (suspends.length > 0 && suspends.every((m) => m.status === 'executed') && !this.hasAnyRejected && !this.thinking) {
        return true
      }
      return false
    },

    artifactPages() {
      // 若实际消息中收到了服务端的 card 消息，优先解析真实卡片页
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

      // 默认/演示 5 页标准方案
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

    toggleAllExpanded() {
      this.allExpanded = !this.allExpanded
    },

    toggleAgentCollapse(agentKey) {
      this.collapsedAgents[agentKey] = !this.collapsedAgents[agentKey]
    },

    formatStepStatus(status) {
      switch (status) {
        case 'completed': return '已完成 ✓'
        case 'in_progress': return '执行中 🔵'
        case 'suspended': return '待审批 ⏸️'
        case 'rejected': return '已拒绝 🔴'
        case 'pending': return '待进行 ⏳'
        default: return status
      }
    },

    formatToolStatus(status) {
      switch (status) {
        case 'completed':
        case 'executed':
          return '已执行 ✓'
        case 'suspended':
          return '⏸️ 待确认'
        case 'running':
          return '执行中 🔵'
        case 'pending':
          return '待调度 ⏳'
        case 'rejected':
          return '已拒绝 🚫'
        default:
          return status
      }
    },

    triggerApprove(confirmationId, toolName) {
      // 触发真实确认或者本地模拟确认
      if (this.demoModeActive) {
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
      uni.showToast({ title: '已模拟子女端审核同意！', icon: 'success' })
    },

    triggerReject(confirmationId, toolName) {
      // 触发拒绝操作
      if (this.demoModeActive) {
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
      uni.showToast({ title: '已模拟子女端拒绝该操作', icon: 'none' })
    },

    loadDemoScenario() {
      this.demoModeActive = true
      this.rootThinking = true
      uni.showLoading({ title: '正在载入异地就医多智能体全链路…' })
      setTimeout(() => {
        uni.hideLoading()
        this.rootThinking = false
        // 初始设为全部展开
        this.allExpanded = true
        // 先设为待确认状态，供体验审批闭环与拒绝拦截
        this.demoApprovals = {
          appointment: false,
          ticket: false,
          hotel: false,
        }
        uni.showToast({ title: '演示全链路已载入，可体验同意或拒绝！', icon: 'none' })
      }, 500)
    },

    exitDemoMode() {
      this.demoModeActive = false
      this.demoApprovals = {
        appointment: false,
        ticket: false,
        hotel: false,
      }
      uni.showToast({ title: '已恢复实时会话跟踪', icon: 'none' })
    },

    openArtifactModal() {
      if (!this.isArtifactReady) {
        uni.showToast({ title: '多智能体尚未完成方案装配，请稍候…', icon: 'none' })
        return
      }
      this.showArtifactModal = true
    },

    readAloud() {
      uni.showToast({ title: '正在为您朗读《就医出行计划书》…', icon: 'none' })
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
  font-size: 34rpx; /* 17px */
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #ffffff;
}

.tree-sub-title {
  font-size: 22rpx; /* 11px */
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
  padding: 6rpx 18rpx;
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
  padding: 8rpx 18rpx;
  background: rgba(255, 255, 255, 0.12);
  border: 1rpx solid rgba(255, 255, 255, 0.2);
  border-radius: 8rpx;
  color: #f1f5f9;
  font-size: 22rpx;
  line-height: 1.2;
  cursor: pointer;
  transition: all 0.2s;
  margin: 0;
}

.icon-action-btn:hover, .icon-action-btn:active {
  background: rgba(255, 255, 255, 0.22);
}

.demo-btn {
  background: #2563eb;
  border-color: #3b82f6;
  color: #ffffff;
  font-weight: 600;
}

.demo-btn:hover {
  background: #1d4ed8;
}

.reset-demo-btn {
  background: rgba(245, 158, 11, 0.25);
  border-color: #f59e0b;
  color: #fcd34d;
  font-weight: 600;
}

.collapse-pane-btn {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.25);
  color: #e2e8f0;
}

.collapse-pane-btn:hover, .collapse-pane-btn:active {
  background: rgba(255, 255, 255, 0.2);
}

.close-drawer-btn {
  width: 56rpx;
  height: 56rpx;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  margin: 0;
  color: #ffffff;
}

.close-icon {
  font-size: 26rpx;
  line-height: 1;
}

/* 拓扑度量信息栏 */
.metrics-bar {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 16rpx 24rpx;
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
  font-size: 22rpx;
  color: #64748b;
  font-weight: 500;
}

.metric-val {
  font-size: 26rpx;
  font-weight: 700;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
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

/* 滚动区域 */
.tree-scroll {
  flex: 1;
  min-height: 0;
  background: #f8fafc;
}

.tree-canvas {
  padding: 24rpx 24rpx 60rpx;
  box-sizing: border-box;
}

/* 根节点：老友记主调度卡片 */
.root-node-card {
  position: relative;
  background: #ffffff;
  border: 2rpx solid #cbd5e1;
  border-radius: 20rpx;
  padding: 24rpx;
  box-shadow: 0 6rpx 24rpx rgba(15, 23, 42, 0.06);
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
}

.root-node-card.is-thinking {
  border-color: #3b82f6;
  box-shadow: 0 0 28rpx rgba(59, 130, 246, 0.25);
  animation: lyj-pulse-glow 2s infinite ease-in-out;
}

.node-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20rpx;
}

.node-badge-group {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.avatar-box {
  width: 68rpx;
  height: 68rpx;
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f1f5f9;
  font-size: 36rpx;
}

.orchestrator-avatar {
  background: #0f172a;
}

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
  font-size: 30rpx; /* 15px */
  font-weight: 700;
  color: #0f172a;
}

.agent-tag-role {
  font-size: 20rpx;
  padding: 4rpx 12rpx;
  background: #f1f5f9;
  border-radius: 6rpx;
  color: #475569;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.node-role-desc {
  font-size: 22rpx;
  color: #64748b;
}

/* 状态标签样式 */
.state-badge {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  padding: 6rpx 16rpx;
  border-radius: 999rpx;
  font-size: 22rpx;
  font-weight: 600;
  border: 1rpx solid transparent;
}

.state-badge.status-thinking {
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #2563eb;
  animation: lyj-badge-pulse 1.6s infinite ease-in-out;
}

.state-badge.status-suspended {
  background: #fffbeb;
  border-color: #fde68a;
  color: #d97706;
  animation: lyj-badge-pulse 1.4s infinite ease-in-out;
}

.state-badge.status-rejected {
  background: #fef2f2;
  border-color: #fecaca;
  color: #dc2626;
}

.state-badge.status-completed {
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #16a34a;
}

.state-badge.status-ready {
  background: #f8fafc;
  border-color: #e2e8f0;
  color: #475569;
}

/* 意图识别框 */
.intent-box {
  background: #f8fafc;
  border: 1rpx solid #e2e8f0;
  border-radius: 12rpx;
  padding: 16rpx 20rpx;
  margin-bottom: 20rpx;
}

.intent-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8rpx;
}

.intent-label {
  font-size: 22rpx;
  font-weight: 700;
  color: #334155;
}

.intent-tag {
  font-size: 20rpx;
  padding: 2rpx 10rpx;
  background: #e0e7ff;
  color: #4338ca;
  border-radius: 6rpx;
  font-weight: 600;
}

.intent-content {
  font-size: 24rpx;
  color: #1e293b;
  line-height: 1.5;
}

/* 步骤流水线 */
.plan-steps-track {
  border-top: 1rpx dashed #cbd5e1;
  padding-top: 16rpx;
}

.track-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12rpx;
}

.track-title {
  font-size: 22rpx;
  font-weight: 700;
  color: #475569;
}

.track-progress {
  font-size: 22rpx;
  font-weight: 600;
  color: #16a34a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.steps-grid {
  display: flex;
  flex-direction: column;
  gap: 10rpx;
}

.step-chip {
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 10rpx 16rpx;
  background: #f8fafc;
  border: 1rpx solid #e2e8f0;
  border-radius: 10rpx;
  transition: all 0.2s;
}

.step-chip.step-completed {
  background: #f0fdf4;
  border-color: #bbf7d0;
  .step-num {
    background: #16a34a;
    color: #ffffff;
  }
  .step-name {
    color: #166534;
    font-weight: 600;
  }
}

.step-chip.step-in_progress {
  background: #eff6ff;
  border-color: #93c5fd;
  .step-num {
    background: #2563eb;
    color: #ffffff;
  }
  .step-name {
    color: #1d4ed8;
    font-weight: 600;
  }
}

.step-chip.step-suspended {
  background: #fffbeb;
  border-color: #fde68a;
  .step-num {
    background: #d97706;
    color: #ffffff;
  }
  .step-name {
    color: #b45309;
    font-weight: 600;
  }
}

.step-chip.step-rejected {
  background: #fef2f2;
  border-color: #fecaca;
  .step-num {
    background: #ef4444;
    color: #ffffff;
  }
  .step-name {
    color: #b91c1c;
    font-weight: 600;
  }
}

.step-num {
  width: 32rpx;
  height: 32rpx;
  border-radius: 50%;
  background: #cbd5e1;
  color: #475569;
  font-size: 20rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.step-name {
  flex: 1;
  font-size: 24rpx;
  color: #334155;
}

.step-status-tag {
  font-size: 20rpx;
  font-weight: 600;
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

/* 分支干线容器 */
.branch-trunk-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16rpx 0 10rpx;
  position: relative;
}

.trunk-line-vertical {
  width: 4rpx;
  height: 36rpx;
  background: #94a3b8;
  transition: all 0.3s;
}

.trunk-line-vertical.flow-active {
  background: linear-gradient(180deg, #2563eb, #60a5fa, #2563eb);
  background-size: 100% 200%;
  animation: linePulseFlow 1.8s linear infinite;
  box-shadow: 0 0 12rpx rgba(37, 99, 235, 0.6);
}

.trunk-label-chip {
  padding: 4rpx 18rpx;
  background: #e2e8f0;
  border-radius: 999rpx;
  margin: 6rpx 0;
}

.trunk-chip-text {
  font-size: 20rpx;
  font-weight: 600;
  color: #475569;
}

.trunk-horizontal-bar {
  width: 85%;
  height: 4rpx;
  background: #94a3b8;
  margin-top: 6rpx;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.trunk-horizontal-bar.flow-active {
  background: linear-gradient(90deg, #60a5fa, #2563eb, #60a5fa);
  box-shadow: 0 0 10rpx rgba(37, 99, 235, 0.4);
}

/* 子智能体分支卡片 */
.subagent-branches-container {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.subagent-branch-card {
  background: #ffffff;
  border: 2rpx solid #e2e8f0;
  border-radius: 18rpx;
  box-shadow: 0 4rpx 16rpx rgba(15, 23, 42, 0.04);
  overflow: hidden;
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.subagent-branch-card.health-branch {
  border-left: 8rpx solid #0284c7;
}

.subagent-branch-card.travel-branch {
  border-left: 8rpx solid #ea580c;
}

.subagent-branch-card.community-branch {
  border-left: 8rpx solid #8b5cf6;
}

.subagent-branch-card.planbuilder-branch {
  border-left: 8rpx solid #059669;
}

.branch-header {
  padding: 18rpx 20rpx;
  background: #f8fafc;
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  border-bottom: 1rpx solid #e2e8f0;
  gap: 10rpx;
}

.branch-header-left {
  display: flex;
  align-items: center;
  gap: 14rpx;
  min-width: 0;
  flex: 1;
}

.health-avatar { background: #e0f2fe; }
.travel-avatar { background: #ffedd5; }
.community-avatar { background: #ede9fe; }
.planbuilder-avatar { background: #dcfce7; }

.branch-title-group {
  display: flex;
  flex-direction: column;
  gap: 2rpx;
  min-width: 0;
}

.branch-name-row {
  display: flex;
  align-items: center;
  gap: 10rpx;
  flex-wrap: wrap;
}

.branch-name {
  font-size: 28rpx;
  font-weight: 700;
  color: #0f172a;
}

.branch-en-tag {
  font-size: 24rpx;
  color: #64748b;
  font-weight: 500;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.branch-desc {
  font-size: 22rpx;
  color: #64748b;
}

.branch-header-right {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-shrink: 0;
}

.accordion-arrow {
  font-size: 20rpx;
  color: #94a3b8;
  display: inline-block;
  transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.collapsed .accordion-arrow {
  transform: rotate(-90deg);
}

.branch-collapsible {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.28s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.25s ease;
  opacity: 0;
  overflow: hidden;
}

.branch-collapsible.is-open {
  grid-template-rows: 1fr;
  opacity: 1;
}

.branch-collapsible > .branch-body {
  min-height: 0;
}

.branch-body {
  padding: 18rpx 20rpx 24rpx;
}

/* 工具流与节点样式 (R2 / R3) */
.tools-flow {
  display: flex;
  flex-direction: column;
  gap: 14rpx;
  position: relative;
  padding-left: 20rpx;
  border-left: 2rpx dashed #cbd5e1;
}

.tool-node {
  position: relative;
  background: #ffffff;
  border: 1rpx solid #e2e8f0;
  border-radius: 12rpx;
  padding: 14rpx 16rpx;
  transition: all 0.2s;
}

.tool-node.node-completed, .tool-node.node-executed {
  border-color: #cbd5e1;
  background: #ffffff;
}

.tool-node.node-running {
  border-color: #60a5fa;
  box-shadow: 0 0 16rpx rgba(59, 130, 246, 0.2);
}

.tool-node.node-suspended {
  border-color: #f59e0b;
  background: #fffdfa;
  box-shadow: 0 0 18rpx rgba(245, 158, 11, 0.25);
  animation: lyj-suspended-glow 1.8s infinite ease-in-out;
}

.tool-node.node-rejected {
  border-color: #ef4444;
  background: #fff8f8;
  box-shadow: 0 0 16rpx rgba(239, 68, 68, 0.18);
}

.node-connector-dot {
  position: absolute;
  left: -29rpx;
  top: 24rpx;
  width: 14rpx;
  height: 14rpx;
  border-radius: 50%;
  background: #94a3b8;
  border: 4rpx solid #ffffff;
}

.node-completed .node-connector-dot, .node-executed .node-connector-dot {
  background: #16a34a;
}

.node-running .node-connector-dot {
  background: #2563eb;
}

.node-suspended .node-connector-dot {
  background: #f59e0b;
}

.node-rejected .node-connector-dot {
  background: #ef4444;
}

.node-card-inner {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.node-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.node-name-box {
  display: flex;
  align-items: baseline;
  gap: 10rpx;
  flex-wrap: wrap;
}

.tool-fn-name {
  font-size: 24rpx;
  font-weight: 700;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.tool-cn-name {
  font-size: 22rpx;
  color: #64748b;
}

.risk-badge {
  font-size: 20rpx;
  padding: 2rpx 10rpx;
  background: #fef3c7;
  color: #b45309;
  border-radius: 6rpx;
  font-weight: 600;
}

.node-status-tag {
  font-size: 20rpx;
  font-weight: 600;
  padding: 2rpx 10rpx;
  border-radius: 6rpx;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

.node-status-tag.completed, .node-status-tag.executed {
  background: #f0fdf4;
  color: #16a34a;
}

.node-status-tag.suspended {
  background: #fffbeb;
  color: #d97706;
}

.node-status-tag.running {
  background: #eff6ff;
  color: #2563eb;
}

.node-status-tag.rejected {
  background: #fee2e2;
  color: #dc2626;
}

.node-status-tag.pending {
  background: #f8fafc;
  color: #94a3b8;
}

/* 参数 mono 块 (R3) */
.mono-params-box {
  background: #f1f5f9;
  border-radius: 8rpx;
  padding: 8rpx 12rpx;
  overflow-x: auto;
}

.mono-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 22rpx; /* 11px */
  color: #334155;
  line-height: 1.4;
  word-break: break-all;
}

.result-box {
  padding: 6rpx 0;
}

.result-text {
  font-size: 22rpx;
  color: #166534;
  line-height: 1.4;
}

/* 挂起警告卡片 (R2) */
.suspended-alert-card {
  background: #fffbeb;
  border: 2rpx dashed #f59e0b;
  border-radius: 10rpx;
  padding: 14rpx;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
  margin-top: 6rpx;
}

.suspend-header {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.suspend-title {
  font-size: 24rpx;
  font-weight: 700;
  color: #b45309;
}

.suspend-desc {
  font-size: 22rpx;
  color: #92400e;
  line-height: 1.4;
}

.suspend-actions-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-top: 8rpx;
  flex-wrap: wrap;
}

.quick-approve-btn {
  background: #d97706;
  color: #ffffff;
  font-size: 22rpx;
  font-weight: 700;
  padding: 8rpx 20rpx;
  border-radius: 8rpx;
  border: none;
  cursor: pointer;
  box-shadow: 0 4rpx 12rpx rgba(217, 119, 6, 0.3);
  transition: all 0.2s;
  margin: 0;
}

.quick-approve-btn:active {
  background: #b45309;
}

.quick-reject-btn {
  background: #f1f5f9;
  color: #dc2626;
  border: 2rpx solid #fca5a5;
  font-size: 22rpx;
  font-weight: 700;
  padding: 6rpx 18rpx;
  border-radius: 8rpx;
  cursor: pointer;
  transition: all 0.2s;
  margin: 0;
}

.quick-reject-btn:active {
  background: #fee2e2;
}

.executed-alert-card {
  background: #f0fdf4;
  border: 1rpx solid #bbf7d0;
  border-radius: 8rpx;
  padding: 8rpx 12rpx;
  display: flex;
  align-items: center;
  gap: 8rpx;
  margin-top: 4rpx;
}

.executed-text {
  font-size: 22rpx;
  color: #15803d;
  font-weight: 600;
}

/* 拒绝状态卡片 (R2) */
.rejected-alert-card {
  background: #fef2f2;
  border: 2rpx dashed #f87171;
  border-radius: 10rpx;
  padding: 14rpx;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
  margin-top: 6rpx;
  animation: fadeIn 0.25s ease-out;
}

.reject-header {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.reject-title {
  font-size: 24rpx;
  font-weight: 700;
  color: #b91c1c;
}

.reject-desc {
  font-size: 22rpx;
  color: #991b1b;
  line-height: 1.4;
}

/* 产物叶子节点 (R2) */
.artifact-leaf-node {
  background: linear-gradient(135deg, #f0fdf4 0%, #e0f2fe 100%);
  border: 2rpx solid #38bdf8;
  border-radius: 14rpx;
  padding: 16rpx 18rpx;
  cursor: pointer;
  transition: all 0.25s;
  box-shadow: 0 4rpx 16rpx rgba(56, 189, 248, 0.15);
  margin-top: 8rpx;
}

.artifact-leaf-node.is-dimmed {
  opacity: 0.75;
  border-color: #cbd5e1;
  background: #f8fafc;
  box-shadow: none;
}

.artifact-leaf-node:hover, .artifact-leaf-node:active {
  transform: translateY(-2rpx);
  box-shadow: 0 8rpx 24rpx rgba(56, 189, 248, 0.28);
}

.leaf-head {
  display: flex;
  align-items: center;
  gap: 14rpx;
}

.leaf-icon-badge {
  width: 56rpx;
  height: 56rpx;
  border-radius: 12rpx;
  background: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.06);
}

.leaf-icon {
  font-size: 32rpx;
}

.leaf-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.leaf-title-row {
  display: flex;
  align-items: center;
  gap: 10rpx;
}

.leaf-title {
  font-size: 26rpx;
  font-weight: 800;
  color: #0f172a;
}

.leaf-tag {
  font-size: 20rpx;
  padding: 2rpx 8rpx;
  background: #dcfce7;
  color: #166534;
  border-radius: 6rpx;
  font-weight: 600;
}

.leaf-desc {
  font-size: 22rpx;
  color: #475569;
}

.leaf-action-badge {
  padding: 6rpx 14rpx;
  background: #64748b;
  color: #ffffff;
  border-radius: 8rpx;
  font-size: 22rpx;
  font-weight: 600;
  transition: all 0.2s;
}

.leaf-action-badge.badge-ready {
  background: #0284c7;
}

/* 交付物弹窗样式 (Artifact Modal) */
.artifact-modal-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
}

.artifact-modal {
  width: 700rpx;
  max-width: 90vw;
  max-height: 85vh;
  background: #ffffff;
  border-radius: 20rpx;
  box-shadow: 0 20rpx 60rpx rgba(0, 0, 0, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.artifact-modal-header {
  padding: 24rpx 28rpx;
  background: #0f172a;
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.modal-title {
  font-size: 30rpx;
  font-weight: 700;
  color: #ffffff;
}

.modal-sub {
  font-size: 22rpx;
  color: #94a3b8;
}

.modal-close-btn {
  width: 52rpx;
  height: 52rpx;
  background: rgba(255, 255, 255, 0.15);
  color: #ffffff;
  border-radius: 50%;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26rpx;
  padding: 0;
  margin: 0;
}

.artifact-modal-body {
  flex: 1;
  min-height: 0;
  padding: 24rpx;
  background: #f8fafc;
  box-sizing: border-box;
}

.plan-page-card {
  background: #ffffff;
  border: 1rpx solid #e2e8f0;
  border-radius: 14rpx;
  padding: 18rpx 20rpx;
  margin-bottom: 20rpx;
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.03);
}

.page-card-head {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 14rpx;
  border-bottom: 2rpx solid #f1f5f9;
  padding-bottom: 10rpx;
}

.page-badge {
  font-size: 20rpx;
  font-weight: 700;
  padding: 4rpx 12rpx;
  background: #0f172a;
  color: #ffffff;
  border-radius: 6rpx;
}

.page-title {
  font-size: 28rpx;
  font-weight: 700;
  color: #0f172a;
}

.page-rows {
  display: flex;
  flex-direction: column;
  gap: 10rpx;
}

.page-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16rpx;
}

.row-label {
  font-size: 24rpx;
  color: #64748b;
  font-weight: 500;
}

.row-val {
  font-size: 24rpx;
  color: #1e293b;
  font-weight: 600;
  text-align: right;
}

.page-note {
  display: block;
  margin-top: 12rpx;
  font-size: 22rpx;
  color: #d97706;
  background: #fffbeb;
  padding: 8rpx 12rpx;
  border-radius: 8rpx;
  line-height: 1.4;
}

.disclaimer-note {
  padding: 16rpx;
  font-size: 22rpx;
  color: #94a3b8;
  line-height: 1.5;
  text-align: center;
}

.artifact-modal-footer {
  padding: 20rpx 24rpx;
  background: #ffffff;
  border-top: 1rpx solid #e2e8f0;
  display: flex;
  gap: 16rpx;
}

.footer-action-btn {
  flex: 1;
  height: 80rpx;
  border-radius: 12rpx;
  font-size: 26rpx;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  cursor: pointer;
  margin: 0;
}

.footer-action-btn.secondary {
  background: #f1f5f9;
  color: #334155;
}

.footer-action-btn.primary {
  background: #2563eb;
  color: #ffffff;
}

/* 动效 Keyframes */
@keyframes lyj-pulse-glow {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.35);
  }
  50% {
    box-shadow: 0 0 20rpx 6rpx rgba(37, 99, 235, 0.2);
  }
}

@keyframes lyj-suspended-glow {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.3);
  }
  50% {
    box-shadow: 0 0 16rpx 4rpx rgba(245, 158, 11, 0.2);
  }
}

@keyframes lyj-badge-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.75; }
}

@keyframes linePulseFlow {
  0% { background-position: 0% 0%; }
  100% { background-position: 0% 200%; }
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* 移动端狭窄屏幕优化 (< 480px / 375px) */
@media screen and (max-width: 480px) {
  .tree-header {
    padding: 16rpx 20rpx;
    flex-wrap: wrap;
    gap: 12rpx;
  }
  .tree-main-title {
    font-size: 28rpx;
  }
  .tree-sub-title {
    display: none;
  }
  .header-right {
    flex-wrap: wrap;
    gap: 8rpx;
  }
  .global-status-pill {
    padding: 4rpx 14rpx;
    font-size: 20rpx;
  }
  .icon-action-btn {
    padding: 6rpx 14rpx;
    font-size: 20rpx;
  }
  .tree-canvas {
    padding: 16rpx 16rpx 40rpx;
  }
  .metrics-bar {
    padding: 12rpx 16rpx;
  }
}

/* 移动端横屏或超矮屏幕优化 (< 500px 高度) */
@media screen and (max-height: 500px) {
  .tree-header {
    padding: 10rpx 16rpx;
  }
  .tree-title-icon {
    font-size: 32rpx;
  }
  .tree-main-title {
    font-size: 26rpx;
  }
  .metrics-bar {
    padding: 8rpx 16rpx;
  }
  .metric-item {
    gap: 2rpx;
  }
  .metric-label {
    font-size: 18rpx;
  }
  .metric-val {
    font-size: 22rpx;
  }
  .tree-canvas {
    padding: 12rpx 12rpx 30rpx;
  }
  .root-node-card {
    padding: 16rpx;
  }
}
</style>
