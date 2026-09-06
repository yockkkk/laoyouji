import assert from 'node:assert/strict'

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

console.log('=== ALL ADVERSARIAL TESTS PASSED (6/6) ===')
