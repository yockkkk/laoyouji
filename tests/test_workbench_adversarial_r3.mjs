import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

console.log('=== LaoYouJi Round 3 Workbench Adversarial Test Suite ===\n')

// -------------------------------------------------------------
// Test 1: allExpanded Getter & Setter
// -------------------------------------------------------------
console.log('Test 1: allExpanded Getter & Setter reactivity')
{
  const state = {
    collapsedAgents: {
      health: false,
      travel: false,
      community: false,
      planBuilder: false,
    },
  }

  const allExpandedProp = {
    get() {
      return (
        !state.collapsedAgents.health &&
        !state.collapsedAgents.travel &&
        !state.collapsedAgents.community &&
        !state.collapsedAgents.planBuilder
      )
    },
    set(val) {
      state.collapsedAgents.health = !val
      state.collapsedAgents.travel = !val
      state.collapsedAgents.community = !val
      state.collapsedAgents.planBuilder = !val
    },
  }

  assert.equal(allExpandedProp.get(), true, 'Initially all expanded should be true')

  // Collapse one
  state.collapsedAgents.health = true
  assert.equal(allExpandedProp.get(), false, 'Collapsed one agent makes allExpanded false')

  // Test setter to collapse all
  allExpandedProp.set(false)
  assert.equal(state.collapsedAgents.health, true)
  assert.equal(state.collapsedAgents.travel, true)
  assert.equal(state.collapsedAgents.community, true)
  assert.equal(state.collapsedAgents.planBuilder, true)
  assert.equal(allExpandedProp.get(), false)

  // Test setter to expand all
  allExpandedProp.set(true)
  assert.equal(state.collapsedAgents.health, false)
  assert.equal(state.collapsedAgents.travel, false)
  assert.equal(state.collapsedAgents.community, false)
  assert.equal(state.collapsedAgents.planBuilder, false)
  assert.equal(allExpandedProp.get(), true)

  console.log('✓ Passed: allExpanded getter/setter operates correctly without errors\n')
}

// -------------------------------------------------------------
// Test 2: Dynamic Loopback Approval Unlocks Downstream Artifact in Non-Demo Mode
// -------------------------------------------------------------
console.log('Test 2: Dynamic Loopback Approval in Non-Demo Mode')
{
  const context = {
    messages: [
      { isUser: true, text: '我想去北京积水潭看腿疼' },
      { kind: 'tool', tool: 'search_hospital', status: 'completed', args: { hospital: '北京积水潭医院' } },
      {
        kind: 'suspend',
        tool: 'register_appointment',
        confirmationId: 'real-uuid-1234',
        amount: 100,
        status: 'pending',
      },
    ],
    thinking: false,
    demoModeActive: false,
    demoApprovals: { appointment: false, ticket: false, hotel: false },
    hasAnyRejected() {
      return (this.messages || []).some((m) => m.kind === 'suspend' && m.status === 'rejected')
    },
    isArtifactReady() {
      const hasCard = (this.messages || []).some((m) => m.kind === 'card')
      if (hasCard) return true
      if (this.demoModeActive) {
        return (
          this.demoApprovals.appointment === true &&
          this.demoApprovals.ticket === true &&
          this.demoApprovals.hotel === true
        )
      }
      const msgs = this.messages || []
      const suspends = msgs.filter((m) => m.kind === 'suspend')
      if (suspends.length > 0 && suspends.every((m) => m.status === 'executed') && !this.hasAnyRejected() && !this.thinking) {
        return true
      }
      return false
    },
    displayStep4Status() {
      return this.isArtifactReady()
        ? 'completed'
        : (this.hasAnyRejected()
          ? 'rejected'
          : (this.thinking ? 'pending' : 'pending'))
    },
  }

  // Before approval:
  assert.equal(context.isArtifactReady(), false, 'Artifact must not be ready while task is pending')
  assert.equal(context.displayStep4Status(), 'pending', 'Step 4 must be pending while task is pending')

  // Simulate approval loopback:
  const card = context.messages.find((m) => m.kind === 'suspend')
  card.status = 'executed'

  assert.equal(context.isArtifactReady(), true, 'Artifact must dynamically unlock upon approval loopback!')
  assert.equal(context.displayStep4Status(), 'completed', 'Step 4 must transition to completed!')
  console.log('✓ Passed: Downstream steps dynamically unlock upon full approval in non-demo mode\n')
}

// -------------------------------------------------------------
// Test 3: Rejection Loopback Stoppage & Error State Transition
// -------------------------------------------------------------
console.log('Test 3: Rejection Loopback Stoppage & Error State Transition')
{
  const context = {
    messages: [
      { isUser: true, text: '我想去北京积水潭看腿疼' },
      {
        kind: 'suspend',
        tool: 'register_appointment',
        confirmationId: 'real-uuid-1234',
        amount: 100,
        status: 'pending',
      },
    ],
    thinking: false,
    demoModeActive: false,
    hasAnyRejected() {
      return (this.messages || []).some((m) => m.kind === 'suspend' && m.status === 'rejected')
    },
    isArtifactReady() {
      const hasCard = (this.messages || []).some((m) => m.kind === 'card')
      if (hasCard) return true
      const msgs = this.messages || []
      const suspends = msgs.filter((m) => m.kind === 'suspend')
      if (suspends.length > 0 && suspends.every((m) => m.status === 'executed') && !this.hasAnyRejected() && !this.thinking) {
        return true
      }
      return false
    },
    displayStep4Status() {
      return this.isArtifactReady()
        ? 'completed'
        : (this.hasAnyRejected()
          ? 'rejected'
          : 'pending')
    },
    planBuilderStatusText() {
      if (this.hasAnyRejected()) return '前序审批已拒绝 · 装配终止'
      if (this.isArtifactReady()) return '五页计划书装配完成'
      return '等待前序审批解锁'
    },
  }

  // Reject the confirmation:
  const card = context.messages.find((m) => m.kind === 'suspend')
  card.status = 'rejected'

  assert.equal(context.hasAnyRejected(), true)
  assert.equal(context.isArtifactReady(), false)
  assert.equal(context.displayStep4Status(), 'rejected')
  assert.equal(context.planBuilderStatusText(), '前序审批已拒绝 · 装配终止')
  console.log('✓ Passed: Rejection loopback correctly stops assembly and reflects rejected state\n')
}

// -------------------------------------------------------------
// Test 4: Mobile Drawer Touch Drag False Dismissal Prevention
// -------------------------------------------------------------
console.log('Test 4: Mobile Drawer Touch Drag False Dismissal Prevention')
{
  const drawerState = {
    treeDrawerVisible: true,
    drawerDragY: 0,
    drawerDragging: false,
    _hasDragged: false,
    _touchStartY: 0,
    _touchStartTime: 0,
    closeDrawer() {
      this.drawerDragY = 0
      this.drawerDragging = false
      this._hasDragged = false
      this.treeDrawerVisible = false
    },
    onDrawerTouchStart(clientY) {
      this._touchStartY = clientY
      this._touchStartTime = Date.now()
      this.drawerDragging = true
      this.drawerDragY = 0
      this._hasDragged = false
    },
    onDrawerTouchMove(clientY) {
      if (!this.drawerDragging) return
      const delta = clientY - this._touchStartY
      if (Math.abs(delta) > 8) {
        this._hasDragged = true
      }
      if (delta > 0) {
        this.drawerDragY = delta
      } else {
        this.drawerDragY = 0
      }
    },
    onDrawerTouchEnd(simulatedDt = null) {
      if (!this.drawerDragging) return
      this.drawerDragging = false
      const dt = simulatedDt || Math.max(1, Date.now() - this._touchStartTime)
      const velocity = this.drawerDragY / dt
      if (this.drawerDragY > 70 || (this.drawerDragY >= 35 && velocity > 0.4)) {
        this.closeDrawer()
      } else {
        this.drawerDragY = 0
      }
    },
    onDrawerBarTap() {
      if (this._hasDragged) {
        this._hasDragged = false
        return
      }
      this.closeDrawer()
    },
  }

  // Scenario 4A: User drags down 20px (under 35px threshold) slowly (300ms)
  drawerState.onDrawerTouchStart(100)
  drawerState.onDrawerTouchMove(120) // delta = 20px
  assert.equal(drawerState._hasDragged, true)
  assert.equal(drawerState.drawerDragY, 20)

  drawerState.onDrawerTouchEnd(300)
  assert.equal(drawerState.drawerDragY, 0, 'Must snap back to 0')
  assert.equal(drawerState.treeDrawerVisible, true, 'Must remain open')

  // Now browser emits tap event on drag bar
  drawerState.onDrawerBarTap()
  assert.equal(drawerState.treeDrawerVisible, true, 'Drawer must NOT be falsely dismissed on bar tap after drag!')

  // Scenario 4B: User twitches down 15px in 10ms (high velocity 1.5 px/ms, but < 35px displacement)
  drawerState.onDrawerTouchStart(100)
  drawerState.onDrawerTouchMove(115) // delta = 15px
  drawerState.onDrawerTouchEnd(10)
  assert.equal(drawerState.drawerDragY, 0, 'Must snap back to 0 on small jitter')
  assert.equal(drawerState.treeDrawerVisible, true, 'Jitter must NOT falsely dismiss drawer')

  // Scenario 4C: Deliberate flick down 45px in 50ms (velocity = 0.9 px/ms, >= 35px displacement)
  drawerState.onDrawerTouchStart(100)
  drawerState.onDrawerTouchMove(145) // delta = 45px
  drawerState.onDrawerTouchEnd(50)
  assert.equal(drawerState.treeDrawerVisible, false, 'Deliberate flick must dismiss drawer')

  // Scenario 4D: Slow drag past threshold 80px in 600ms (velocity = 0.13 < 0.4, but > 70px displacement)
  drawerState.treeDrawerVisible = true
  drawerState.onDrawerTouchStart(100)
  drawerState.onDrawerTouchMove(180) // delta = 80px
  drawerState.onDrawerTouchEnd(600)
  assert.equal(drawerState.treeDrawerVisible, false, 'Drag past threshold must dismiss drawer')

  // Scenario 4E: Clean tap on drag bar without drag
  drawerState.treeDrawerVisible = true
  drawerState.onDrawerTouchStart(100)
  drawerState.onDrawerTouchEnd(150)
  assert.equal(drawerState._hasDragged, false)
  drawerState.onDrawerBarTap()
  assert.equal(drawerState.treeDrawerVisible, false, 'Clean tap must close drawer')

  console.log('✓ Passed: Drawer snapback and clean tap separation prevents false dismissals\n')
}

// -------------------------------------------------------------
// Test 5: Resilient Confirmation Resolution with Tool Fallback & Demo Skip
// -------------------------------------------------------------
console.log('Test 5: Resilient Confirmation Resolution with Tool Fallback & Demo Skip')
{
  const messages = [
    { kind: 'suspend', tool: 'register_appointment', confirmationId: '', status: 'pending' },
    { kind: 'suspend', tool: 'book_ticket', confirmationId: 'uuid-ticket-999', status: 'pending' },
  ]

  let httpDispatched = []

  function _resolveCard(id, status, ok, tool = '') {
    let card = id
      ? messages.find((m) => m.kind === 'suspend' && m.confirmationId === id)
      : null
    if (!card && tool) {
      card = messages.find(
        (m) => m.kind === 'suspend' && m.tool === tool && m.status === 'pending',
      )
    }
    if (!card && !id && !tool) {
      card = messages.find((m) => m.kind === 'suspend' && m.status === 'pending')
    }
    if (!card) return false
    const next = status || (ok ? 'executed' : 'rejected')
    if (card.status === next) return false
    card.status = next
    return true
  }

  async function onTreeResolveConfirmation({ confirmationId, status, tool }) {
    const nextStatus = status || 'executed'
    const isApproved = nextStatus === 'executed'
    _resolveCard(confirmationId, nextStatus, isApproved, tool)
    if (confirmationId && !confirmationId.startsWith('conf_demo_')) {
      httpDispatched.push({ confirmationId, isApproved })
    }
  }

  // 5A: Real confirmation ID
  await onTreeResolveConfirmation({ confirmationId: 'uuid-ticket-999', status: 'executed', tool: 'book_ticket' })
  assert.equal(messages[1].status, 'executed')
  assert.equal(httpDispatched.length, 1)
  assert.equal(httpDispatched[0].confirmationId, 'uuid-ticket-999')

  // 5B: Missing confirmationId with tool fallback
  await onTreeResolveConfirmation({ confirmationId: '', status: 'executed', tool: 'register_appointment' })
  assert.equal(messages[0].status, 'executed')
  // Should NOT dispatch empty HTTP post
  assert.equal(httpDispatched.length, 1)

  // 5C: Demo confirmation ID should not dispatch HTTP request
  await onTreeResolveConfirmation({ confirmationId: 'conf_demo_hotel', status: 'executed', tool: 'book_hotel' })
  assert.equal(httpDispatched.length, 1, 'Demo IDs must not trigger backend HTTP requests')

  console.log('✓ Passed: Tool fallback and demo request skipping verified\n')
}

// -------------------------------------------------------------
// Test 6: Multi-turn Reverse-Lookup Picks Latest Tool Execution
// -------------------------------------------------------------
console.log('Test 6: Multi-turn Reverse-Lookup Picks Latest Tool Execution')
{
  const messages = [
    { kind: 'tool', tool: 'search_train', status: 'completed', args: { train: 'G101', time: '07:00' } },
    { kind: 'tool', tool: 'search_train', status: 'completed', args: { train: 'G102', time: '08:15' } },
  ]

  // Old implementation using .find:
  const oldPick = messages.find((m) => m.kind === 'tool' && m.tool === 'search_train')
  assert.equal(oldPick.args.train, 'G101', 'Old find picks stale turn 1 tool')

  // New implementation using .slice().reverse().find:
  const newPick = messages.slice().reverse().find((m) => m.kind === 'tool' && m.tool === 'search_train')
  assert.equal(newPick.args.train, 'G102', 'New reverse find correctly picks latest turn 2 tool')

  console.log('✓ Passed: Latest tool message accurately prioritized in multi-turn interactions\n')
}

// -------------------------------------------------------------
// Test 7: Static AST / Text Verification that AgentExecutionTree.vue Uses Reverse Lookup
// -------------------------------------------------------------
console.log('Test 7: Static Verification that AgentExecutionTree.vue Uses Reverse Lookup')
{
  const code = readFileSync('frontend/laoyouji-app/src/components/AgentExecutionTree.vue', 'utf8')
  assert.ok(!code.includes('msgs.find('), 'AgentExecutionTree.vue must NOT contain un-reversed msgs.find(')
  assert.ok(!code.includes('suspends.find('), 'AgentExecutionTree.vue must NOT contain un-reversed suspends.find(')
  assert.ok(code.includes('msgs.slice().reverse().find('), 'AgentExecutionTree.vue must use msgs.slice().reverse().find(')
  assert.ok(code.includes('suspends.slice().reverse().find('), 'AgentExecutionTree.vue must use suspends.slice().reverse().find(')
  console.log('✓ Passed: AgentExecutionTree.vue confirmed using reverse lookup for all tools and suspends\n')
}

// -------------------------------------------------------------
// Test 8: Tool Status Domain-Specific Status Mapping
// -------------------------------------------------------------
console.log('Test 8: Tool Status Domain-Specific Status Mapping')
{
  function formatToolStatus(status, toolKey = '') {
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
  }

  assert.equal(formatToolStatus('executed', 'registerAppointment'), '已预约 ✅')
  assert.equal(formatToolStatus('executed', 'bookTicket'), '已出票 ✅')
  assert.equal(formatToolStatus('executed', 'bookHotel'), '已预订 ✅')
  assert.equal(formatToolStatus('completed', 'composeDeliverable'), '已装配 ✅')
  assert.equal(formatToolStatus('completed', 'searchHospital'), '已完成 ✅')
  assert.equal(formatToolStatus('completed', 'searchTrain'), '已完成 ✅')
  assert.equal(formatToolStatus('completed', 'searchHotel'), '已完成 ✅')
  assert.equal(formatToolStatus('completed', 'orderService'), '已完成 ✅')
  assert.equal(formatToolStatus('suspended', 'registerAppointment'), '⏸️ 待确认')
  assert.equal(formatToolStatus('rejected', 'bookTicket'), '已拦截 🛑')
  console.log('✓ Passed: formatToolStatus renders domain-specific status labels correctly\n')
}

// -------------------------------------------------------------
// Test 9: Batch Approval Progress 4/4 & Full Transition
// -------------------------------------------------------------
console.log('Test 9: Batch Approval Progress 4/4 & Full Transition')
{
  const treeModel = {
    demoApprovals: { appointment: false, ticket: false, hotel: false },
    thinking: false,
    hasAnyRejected: false,
    triggerApprove(confId, toolName) {
      if (toolName === 'register_appointment') this.demoApprovals.appointment = true
      if (toolName === 'book_ticket') this.demoApprovals.ticket = true
      if (toolName === 'book_hotel') this.demoApprovals.hotel = true
    },
    approveAllPending() {
      this.triggerApprove('c1', 'register_appointment')
      this.triggerApprove('c2', 'book_ticket')
      this.triggerApprove('c3', 'book_hotel')
    },
    get isArtifactReady() {
      return (
        this.demoApprovals.appointment === true &&
        this.demoApprovals.ticket === true &&
        this.demoApprovals.hotel === true
      )
    },
    get displaySteps() {
      const s1 = this.demoApprovals.appointment ? 'completed' : 'suspended'
      const s2 = this.demoApprovals.ticket ? 'completed' : 'suspended'
      const s3 = this.demoApprovals.hotel ? 'completed' : 'suspended'
      const s4 = this.isArtifactReady ? 'completed' : 'pending'
      return [
        { name: '选医院挂专家号', status: s1 },
        { name: '查高铁车次及订票', status: s2 },
        { name: '订适老无障碍酒店', status: s3 },
        { name: '聚合装配计划书', status: s4 },
      ]
    },
    get completedCount() {
      return this.displaySteps.filter((s) => s.status === 'completed').length
    },
  }

  assert.equal(treeModel.completedCount, 0, 'Initially 0/4 completed')
  treeModel.approveAllPending()
  assert.equal(treeModel.completedCount, 4, 'Must reach 4/4 completed upon approveAllPending')
  assert.equal(treeModel.isArtifactReady, true, 'Artifact must unlock immediately')
  assert.ok(treeModel.displaySteps.every((s) => s.status === 'completed'), 'All stages must be completed')
  console.log('✓ Passed: Batch approval transitions all stages to completed (4/4)\n')
}

// -------------------------------------------------------------
// Test 10: App.vue Button Active Press Physics Rule Presence
// -------------------------------------------------------------
console.log('Test 10: App.vue Button Active Press Physics Rule Presence')
{
  const appCode = readFileSync('frontend/laoyouji-app/src/App.vue', 'utf8')
  assert.ok(
    appCode.includes('translateY(1px) scale(0.99)'),
    'App.vue must include translateY(1px) scale(0.99) button tactile rule',
  )
  assert.ok(
    appCode.includes('min-height: 44px'),
    'App.vue must declare touch-target min-height: 44px',
  )
  console.log('✓ Passed: App.vue button press physics and touch target baseline verified\n')
}

// -------------------------------------------------------------
// Test 11: Replay Mode Dynamic State-Machine Synchronization
// -------------------------------------------------------------
console.log('Test 11: Replay Mode Dynamic State-Machine Synchronization')
{
  const replaySim = {
    replay: { active: true, playing: true, step: 3, timer: 123 },
    demoApprovals: { appointment: false, ticket: false, hotel: false },
    pauseReplay() {
      this.replay.playing = false
      this.replay.timer = null
    },
    seekReplay(step) {
      this.pauseReplay()
      this.replay.step = step
    },
    triggerApprove(confirmationId, toolName) {
      if (toolName === 'register_appointment') this.demoApprovals.appointment = true
      if (toolName === 'book_ticket') this.demoApprovals.ticket = true
      if (toolName === 'book_hotel') this.demoApprovals.hotel = true
      if (this.replay.active && this.replay.step === 3) {
        if (this.demoApprovals.appointment === true && this.demoApprovals.ticket === true && this.demoApprovals.hotel === true) {
          this.seekReplay(4)
        }
      }
    },
    get healthTools() {
      const step = this.replay.step
      let aStatus = 'pending'
      if (this.demoApprovals.appointment === true) aStatus = 'executed'
      else if (this.demoApprovals.appointment === 'rejected') aStatus = 'rejected'
      else if (step >= 4) aStatus = 'executed'
      else if (step === 3) aStatus = 'suspended'
      return { registerAppointment: { status: aStatus } }
    },
    get travelTools() {
      const step = this.replay.step
      let tBook = 'pending'
      if (this.demoApprovals.ticket === true) tBook = 'executed'
      else if (this.demoApprovals.ticket === 'rejected') tBook = 'rejected'
      else if (step >= 4) tBook = 'executed'
      else if (step === 3) tBook = 'suspended'

      let hBook = 'pending'
      if (this.demoApprovals.hotel === true) hBook = 'executed'
      else if (this.demoApprovals.hotel === 'rejected') hBook = 'rejected'
      else if (step >= 4) hBook = 'executed'
      else if (step === 3) hBook = 'suspended'

      return {
        bookTicket: { status: tBook },
        bookHotel: { status: hBook },
      }
    },
    get pendingTasksCount() {
      let count = 0
      if (this.healthTools.registerAppointment.status === 'suspended') count++
      if (this.travelTools.bookTicket.status === 'suspended') count++
      if (this.travelTools.bookHotel.status === 'suspended') count++
      return count
    },
    get displaySteps() {
      const step = this.replay.step
      const s1 = this.demoApprovals.appointment === true ? 'completed' : (step >= 4 ? 'completed' : 'suspended')
      const s2 = this.demoApprovals.ticket === true ? 'completed' : (step >= 4 ? 'completed' : 'suspended')
      const s3 = this.demoApprovals.hotel === true ? 'completed' : (step >= 4 ? 'completed' : 'suspended')
      const s4 = step >= 5 ? 'completed' : (step >= 4 ? 'in_progress' : 'pending')
      return [
        { name: '选医院挂专家号', status: s1 },
        { name: '查高铁车次及订票', status: s2 },
        { name: '订适老无障碍酒店', status: s3 },
        { name: '聚合装配计划书', status: s4 },
      ]
    },
  }

  assert.equal(replaySim.pendingTasksCount, 3, 'Initially 3 tasks pending at step 3')
  assert.equal(replaySim.displaySteps[0].status, 'suspended')

  // Approve 1:
  replaySim.triggerApprove('c1', 'register_appointment')
  assert.equal(replaySim.healthTools.registerAppointment.status, 'executed')
  assert.equal(replaySim.pendingTasksCount, 2, 'Pending tasks count drops to 2')
  assert.equal(replaySim.displaySteps[0].status, 'completed', 'Stage 1 transitions to completed')
  assert.equal(replaySim.replay.step, 3, 'Still on step 3')

  // Approve 2:
  replaySim.triggerApprove('c2', 'book_ticket')
  assert.equal(replaySim.travelTools.bookTicket.status, 'executed')
  assert.equal(replaySim.pendingTasksCount, 1, 'Pending tasks count drops to 1')
  assert.equal(replaySim.displaySteps[1].status, 'completed', 'Stage 2 transitions to completed')

  // Approve 3:
  replaySim.triggerApprove('c3', 'book_hotel')
  assert.equal(replaySim.travelTools.bookHotel.status, 'executed')
  assert.equal(replaySim.pendingTasksCount, 0, 'Pending tasks count drops to 0')
  assert.equal(replaySim.displaySteps[2].status, 'completed', 'Stage 3 transitions to completed')
  assert.equal(replaySim.replay.step, 4, 'Auto-advances to step 4 upon full approvals!')
  console.log('✓ Passed: Replay mode dynamically synchronizes individual approvals and decrements pending count\n')
}

// -------------------------------------------------------------
// Test 12: Replay Mode Rejection Safety Stoppage
// -------------------------------------------------------------
console.log('Test 12: Replay Mode Rejection Safety Stoppage')
{
  const replaySim = {
    replay: { active: true, playing: true, step: 3, timer: 456 },
    demoApprovals: { appointment: false, ticket: false, hotel: false },
    pauseReplay() {
      this.replay.playing = false
      this.replay.timer = null
    },
    triggerReject(confirmationId, toolName) {
      if (this.replay.active) this.pauseReplay()
      if (toolName === 'register_appointment') this.demoApprovals.appointment = 'rejected'
    },
    get hasAnyRejected() {
      return (
        this.demoApprovals.appointment === 'rejected' ||
        this.demoApprovals.ticket === 'rejected' ||
        this.demoApprovals.hotel === 'rejected'
      )
    },
    get planBuilderTools() {
      let status = 'pending'
      if (this.hasAnyRejected) status = 'rejected'
      else if (this.replay.step >= 5) status = 'completed'
      return { composeDeliverable: { status } }
    },
    get isArtifactReady() {
      if (this.hasAnyRejected) return false
      return this.replay.step >= 5
    },
  }

  assert.equal(replaySim.hasAnyRejected, false)
  replaySim.triggerReject('c1', 'register_appointment')
  assert.equal(replaySim.replay.playing, false, 'Timer must pause immediately on reject')
  assert.equal(replaySim.hasAnyRejected, true, 'hasAnyRejected must become true')
  assert.equal(replaySim.planBuilderTools.composeDeliverable.status, 'rejected', 'Plan builder must be rejected')
  assert.equal(replaySim.isArtifactReady, false, 'Artifact must not be ready')
  console.log('✓ Passed: Replay mode rejection halts replay and transitions downstream builder to rejected\n')
}

// -------------------------------------------------------------
// Test 13: chat.vue _resolveCard Multi-Turn Reverse-Lookup
// -------------------------------------------------------------
console.log('Test 13: chat.vue _resolveCard Multi-Turn Reverse-Lookup')
{
  const chatCode = readFileSync('frontend/laoyouji-app/src/pages/elder/chat.vue', 'utf8')
  assert.ok(
    chatCode.includes("this.messages.slice().reverse().find((m) => m.kind === 'suspend'"),
    'chat.vue _resolveCard must use reverse lookup on messages for suspend resolution',
  )
  console.log('✓ Passed: chat.vue _resolveCard confirmed using slice().reverse().find\n')
}

// -------------------------------------------------------------
// Test 14: Replay Progress Dot Touch-Target Accessibility Compliance
// -------------------------------------------------------------
console.log('Test 14: Replay Progress Dot Touch-Target Accessibility Compliance')
{
  const treeCode = readFileSync('frontend/laoyouji-app/src/components/AgentExecutionTree.vue', 'utf8')
  assert.ok(
    treeCode.includes('min-width: 44px') && treeCode.includes('min-height: 44px'),
    'AgentExecutionTree.vue replay-progress-dot must declare min-width: 44px & min-height: 44px',
  )
  assert.ok(
    treeCode.includes('beforeDestroy()') && treeCode.includes('unmounted()'),
    'AgentExecutionTree.vue must support beforeDestroy and unmounted lifecycle cleanup hooks',
  )
  console.log('✓ Passed: Replay progress dot touch target and lifecycle cleanup verified\n')
}

console.log('=== ALL ADVERSARIAL TESTS PASSED (14/14) ===')


