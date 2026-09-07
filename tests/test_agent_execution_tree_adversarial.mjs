import assert from 'node:assert/strict'
import fs from 'node:fs'

console.log('=== Running Adversarial Tests for AgentExecutionTree.vue ===\n')

const vuePath = 'frontend/laoyouji-app/src/components/AgentExecutionTree.vue'
const vueContent = fs.readFileSync(vuePath, 'utf-8')

// Test static invariant: no demoApprovals anywhere
assert(!vueContent.includes('demoApprovals'), 'demoApprovals must not exist anywhere in AgentExecutionTree.vue')

// Test static invariant: safeMessages is used across computed properties
const occurrences = [...vueContent.matchAll(/this\.messages/g)]
assert.equal(occurrences.length, 1, 'this.messages should only be referenced once, inside safeMessages computed property')

// Test static invariant: reverse lookup is used
assert.ok(!vueContent.includes('msgs.find('), 'AgentExecutionTree.vue must NOT contain un-reversed msgs.find(')
assert.ok(!vueContent.includes('suspends.find('), 'AgentExecutionTree.vue must NOT contain un-reversed suspends.find(')
assert.ok(vueContent.includes('msgs.slice().reverse().find('), 'AgentExecutionTree.vue must use msgs.slice().reverse().find(')
assert.ok(vueContent.includes('suspends.slice().reverse().find('), 'AgentExecutionTree.vue must use suspends.slice().reverse().find(')

const scriptMatch = vueContent.match(/<script>([\s\S]*?)<\/script>/)
assert(scriptMatch, 'Script tag must exist in vue file')
const scriptText = scriptMatch[1]

const sandboxMatch = scriptText.match(/const REPLAY_SANDBOX = (\{[\s\S]*?\n\};?)/)
assert(sandboxMatch, 'REPLAY_SANDBOX must exist')
const REPLAY_SANDBOX = eval('(' + sandboxMatch[1] + ')')

const compObjText = scriptText.substring(scriptText.indexOf('export default {')).replace('export default ', '')
const compDef = eval('(' + compObjText + ')')

// Mock uni global
globalThis.uni = {
  showToast: () => {},
  showModal: () => {},
}

function createTreeInstance(props = {}) {
  const data = compDef.data()
  const vm = {
    ...data,
    messages: props.messages || [],
    thinking: props.thinking || false,
    currentAgent: props.currentAgent || '',
    sessionId: props.sessionId || '',
    user: props.user || null,
    isDesktop: props.isDesktop !== undefined ? props.isDesktop : true,
    _emitted: [],
    $emit(event, payload) {
      this._emitted.push({ event, payload })
    },
    ...compDef.methods,
  }

  for (const [fnName, fn] of Object.entries(compDef.methods)) {
    vm[fnName] = fn.bind(vm)
  }

  for (const [propName, def] of Object.entries(compDef.computed)) {
    const getter = typeof def === 'function' ? def : def.get
    const setter = typeof def === 'object' && def.set ? def.set : undefined
    Object.defineProperty(vm, propName, {
      get: () => getter.call(vm),
      set: setter ? (val) => setter.call(vm, val) : undefined,
      configurable: true,
      enumerable: true,
    })
  }

  return vm
}

// ---------------------------------------------------------------------------
// Test 1: Empty Messages / Default State
// ---------------------------------------------------------------------------
console.log('Test 1: Empty Messages state (no crashes, 0 metrics, no Beijing leakage)')
{
  const vm = createTreeInstance({ messages: [] })
  assert.equal(vm.activeAgentsCount, 0, 'activeAgentsCount should be 0')
  assert.equal(vm.totalToolsCount, 0, 'totalToolsCount should be 0')
  assert.equal(vm.pendingTasksCount, 0, 'pendingTasksCount should be 0')
  assert.equal(vm.isArtifactReady, false, 'isArtifactReady should be false')
  assert.equal(vm.currentScenarioTag, '待命中')
  assert.equal(vm.isHealthActive, false)
  assert.equal(vm.isTravelActive, false)
  assert.equal(vm.isCommunityActive, false)
  assert.equal(vm.isSafetyActive, false)
  assert.equal(vm.isPlanBuilderActive, false)
  assert.equal(vm.displaySteps.length, 0)

  const thoughts = vm.agentThoughts
  assert(!JSON.stringify(thoughts).includes('北京'), 'Empty state must not include 北京')
  assert(!JSON.stringify(thoughts).includes('积水潭'), 'Empty state must not include 积水潭')
  assert(!JSON.stringify(thoughts).includes('田伟'), 'Empty state must not include 田伟')
  assert(!JSON.stringify(thoughts).includes('G102'), 'Empty state must not include G102')
  console.log('✓ Passed: Empty state clean and resilient\n')
}

// ---------------------------------------------------------------------------
// Test 2: Incomplete / Corrupted SSE Messages Array
// ---------------------------------------------------------------------------
console.log('Test 2: Incomplete/Corrupted SSE messages array (null items, primitives, malformed objects)')
{
  const corruptMessages = [
    null,
    undefined,
    'ping',
    12345,
    { text: null },
    { kind: null },
    { kind: 'todo', todos: [null, { content: '整理药箱' }] },
    null,
    { kind: 'tool', tool: null, args: null },
    { kind: 'card', pages: null, sections: null },
  ]
  const vm = createTreeInstance({ messages: corruptMessages })

  assert.doesNotThrow(() => vm.hasTaskStarted)
  assert.doesNotThrow(() => vm.displaySteps)
  assert.doesNotThrow(() => vm.isArtifactReady)
  assert.doesNotThrow(() => vm.artifactDisplayTitle)
  assert.doesNotThrow(() => vm.artifactPages)
  assert.doesNotThrow(() => vm.agentThoughts)
  assert.doesNotThrow(() => vm.currentScenarioTag)
  assert.doesNotThrow(() => vm.currentIntentText)

  assert.equal(vm.displaySteps.length, 1)
  assert.equal(vm.displaySteps[0].name, '整理药箱')
  console.log('✓ Passed: Corrupted SSE payloads handled without crashes\n')
}

// ---------------------------------------------------------------------------
// Test 3: Non-Beijing Scenario: Daily Greeting
// ---------------------------------------------------------------------------
console.log('Test 3: Daily Greeting Dialogue ("早上好")')
{
  const vm = createTreeInstance({
    messages: [
      { isUser: true, text: '早上好，老友记' },
      { kind: 'text', isUser: false, text: '早上好！今天天气很舒适，您有什么需要我帮忙的吗？' },
    ],
  })

  assert.equal(vm.currentScenarioTag, '日常关怀与问候')
  assert(vm.currentIntentText.includes('早上好，老友记'))
  assert.equal(vm.activeAgentsCount, 0, 'No specialized agent should be active for greeting')
  assert.equal(vm.totalToolsCount, 0)
  assert.equal(vm.pendingTasksCount, 0)
  assert.equal(vm.isArtifactReady, false)

  const thoughts = vm.agentThoughts
  assert(thoughts.orchestrator.includes('早上好，老友记'))
  assert(thoughts.health.includes('待命'))
  assert(thoughts.travel.includes('待命'))
  assert(thoughts.community.includes('待命'))

  const jsonThoughts = JSON.stringify(thoughts)
  assert(!jsonThoughts.includes('北京'))
  assert(!jsonThoughts.includes('积水潭'))
  assert(!jsonThoughts.includes('田伟'))
  assert(!jsonThoughts.includes('G102'))
  console.log('✓ Passed: Daily greeting strictly free of medical mock data\n')
}

// ---------------------------------------------------------------------------
// Test 4: Real Medical Consultation (Guangzhou Hospital)
// ---------------------------------------------------------------------------
console.log('Test 4: Real Health Consultation (Guangzhou search_hospital & register)')
{
  const vm = createTreeInstance({
    messages: [
      { isUser: true, text: '我想去广州省中医院看心内科' },
      {
        kind: 'tool',
        tool: 'search_hospital',
        agent: 'health',
        status: 'completed',
        args: { city: '广州', department: '心内科' },
        result: '锁定广州中医药大学第一附属医院心内科林主任号源',
      },
      {
        kind: 'todo',
        todos: [
          { content: '广州心内科挂号', status: 'in_progress' },
        ],
      },
    ],
  })

  assert.equal(vm.currentScenarioTag, '健康医疗就诊规划')
  assert.equal(vm.isHealthActive, true)
  assert.equal(vm.isTravelActive, false)
  assert.equal(vm.isCommunityActive, false)
  assert.equal(vm.activeAgentsCount, 1)
  assert.equal(vm.totalToolsCount, 1)
  assert.equal(vm.pendingTasksCount, 0)

  const healthTool = vm.healthTools[0]
  assert.equal(healthTool.name, 'search_hospital')
  assert.equal(healthTool.args.city, '广州')
  assert.equal(healthTool.args.department, '心内科')

  const thoughts = vm.agentThoughts
  assert(thoughts.health.includes('广州心内科号源'))
  assert(!JSON.stringify(thoughts).includes('北京'))
  assert(!JSON.stringify(thoughts).includes('积水潭'))
  console.log('✓ Passed: Real health workflow properly derived\n')
}

// ---------------------------------------------------------------------------
// Test 5: High-Risk Operation Suspend & Approval Loopback
// ---------------------------------------------------------------------------
console.log('Test 5: High-Risk Operation Suspend & Approval Loopback')
{
  const messages = [
    { isUser: true, text: '挂号确认测试' },
    {
      kind: 'tool',
      tool: 'register_appointment',
      agent: 'health',
      status: 'suspended',
      args: { hospital: '广东省中医院', doctor: '张专家', fee: 100 },
      confirmationId: 'conf_test_001',
    },
    {
      kind: 'suspend',
      confirmationId: 'conf_test_001',
      tool: 'register_appointment',
      amount: 100,
      status: 'pending',
      summary: '门诊预约挂号',
    },
  ]

  const vm = createTreeInstance({ messages })
  assert.equal(vm.pendingTasksCount, 1)
  assert.equal(vm.isSafetyActive, true)
  assert.equal(vm.isArtifactReady, false)
  assert.equal(vm.safetyStatusClass, 'status-suspended')

  // Simulate approval
  const suspendMsg = messages.find((m) => m.kind === 'suspend')
  suspendMsg.status = 'executed'

  assert.equal(vm.pendingTasksCount, 0)
  assert.equal(vm.isArtifactReady, true)
  assert.equal(vm.safetyStatusClass, 'status-completed')
  console.log('✓ Passed: High risk suspension and approval loopback verified\n')
}

// ---------------------------------------------------------------------------
// Test 6: Child Rejection Flow
// ---------------------------------------------------------------------------
console.log('Test 6: Child Rejection Flow')
{
  const messages = [
    { isUser: true, text: '订酒店' },
    {
      kind: 'tool',
      tool: 'book_hotel',
      agent: 'travel',
      status: 'suspended',
      args: { hotel: '杭州西湖度假酒店', price: 500 },
      confirmationId: 'conf_hotel_001',
    },
    {
      kind: 'suspend',
      confirmationId: 'conf_hotel_001',
      tool: 'book_hotel',
      status: 'pending',
    },
  ]

  const vm = createTreeInstance({ messages })
  assert.equal(vm.pendingTasksCount, 1)
  assert.equal(vm.hasAnyRejected, false)

  // Child rejects
  messages[1].status = 'rejected'
  messages[2].status = 'rejected'

  assert.equal(vm.hasAnyRejected, true)
  assert.equal(vm.pendingTasksCount, 0)
  assert.equal(vm.isArtifactReady, false)
  assert.equal(vm.safetyStatusClass, 'status-rejected')
  console.log('✓ Passed: Rejection flow handled safely\n')
}

// ---------------------------------------------------------------------------
// Test 7: Replay Mode Sandbox & Seamless Restoration
// ---------------------------------------------------------------------------
console.log('Test 7: Replay Mode Sandbox & Seamless Restoration')
{
  const vm = createTreeInstance({
    messages: [
      { isUser: true, text: '我想去社区食堂吃午饭' },
      {
        kind: 'tool',
        tool: 'canteen_order',
        agent: 'community',
        args: { menu_item: '软食套餐A' },
        status: 'completed',
      },
    ],
  })

  assert.equal(vm.replay.active, false)
  assert.equal(vm.currentScenarioTag, '邻里助老便民服务')
  assert.equal(vm.isCommunityActive, true)

  // Start replay
  vm.toggleReplayMode()
  assert.equal(vm.replay.active, true)
  assert.equal(vm.currentScenarioTag, '跨城异地就医全闭环')

  // Step 1: Health active in replay
  vm.seekReplay(1)
  assert.equal(vm.isHealthActive, true)

  // Step 3: Safety Intercept
  vm.seekReplay(3)
  assert.equal(vm.pendingTasksCount, 3)
  assert.equal(vm.isSafetyActive, true)

  // Step 5: Artifact Delivered
  vm.seekReplay(5)
  assert.equal(vm.isArtifactReady, true)
  assert.equal(vm.artifactPages.length, 5)

  // Exit Replay: Must immediately restore the real session cleanly
  vm.exitReplay()
  assert.equal(vm.replay.active, false)
  assert.equal(vm.currentScenarioTag, '邻里助老便民服务')
  assert.equal(vm.isCommunityActive, true)
  assert.equal(vm.isHealthActive, false)
  assert.equal(vm.isTravelActive, false)
  assert.equal(vm.totalToolsCount, 1)
  assert.equal(vm.pendingTasksCount, 0)
  assert.equal(vm.isArtifactReady, false)

  const thoughts = vm.agentThoughts
  assert(!JSON.stringify(thoughts).includes('北京'))
  assert(!JSON.stringify(thoughts).includes('积水潭'))
  console.log('✓ Passed: Replay mode sandbox fully isolated, restore is immediate\n')
}

// ---------------------------------------------------------------------------
// Test 8: JSON string in tool args and tool with name field
// ---------------------------------------------------------------------------
console.log('Test 8: JSON string in tool args & name field fallback')
{
  const vm = createTreeInstance({
    messages: [
      { isUser: true, text: '帮我买杭州的高铁票' },
      {
        kind: 'tool',
        name: 'search_train',
        agent: 'travel',
        args: '{"origin":"上海","destination":"杭州"}',
        status: 'completed',
        data: '查询到G7301次列车',
      },
    ],
  })

  assert.equal(vm.totalToolsCount, 1)
  assert.equal(vm.isTravelActive, true)
  const tool = vm.travelTools[0]
  assert.equal(tool.name, 'search_train')
  assert.equal(tool.args.origin, '上海')
  assert.equal(tool.args.destination, '杭州')
  assert.equal(tool.result, '查询到G7301次列车')
  console.log('✓ Passed: JSON string in args and name field fallback\n')
}

// ---------------------------------------------------------------------------
// Test 9: Complete Tool Coverage (no dropping of pay_deposit, build_plan, trip_plan, etc.)
// ---------------------------------------------------------------------------
console.log('Test 9: Complete Tool Coverage (no dropped tools in any category)')
{
  const allBackendTools = [
    'search_hospital', 'register_appointment', 'interpret_report', 'add_medication', 'check_scam', 'diet_advice',
    'search_train', 'book_ticket', 'search_hotel', 'plan_route', 'hail_ride', 'book_hotel', 'get_weather',
    'canteen_order', 'order_service', 'query_order_status', 'push_activities',
    'compose_deliverable', 'build_plan', 'trip_plan',
    'pay_deposit', 'plain_say', 'get_user_profile'
  ]

  const toolMessages = allBackendTools.map((tool, idx) => ({
    kind: 'tool',
    tool,
    status: 'completed',
    callId: `call_${idx}`,
  }))

  const vm = createTreeInstance({ messages: toolMessages })
  assert.equal(vm.totalToolsCount, allBackendTools.length, `totalToolsCount (${vm.totalToolsCount}) must equal total tools (${allBackendTools.length})`)

  // Check specific assignments
  assert.ok(vm.planBuilderTools.some((t) => t.name === 'build_plan'), 'build_plan must be in planBuilderTools')
  assert.ok(vm.planBuilderTools.some((t) => t.name === 'trip_plan'), 'trip_plan must be in planBuilderTools')
  assert.ok(vm.communityTools.some((t) => t.name === 'pay_deposit'), 'pay_deposit must be in communityTools')
  assert.ok(vm.highRiskTools.some((t) => t.name === 'pay_deposit'), 'pay_deposit must be in highRiskTools')
  assert.ok(vm.communityTools.some((t) => t.name === 'plain_say'), 'plain_say must be in communityTools')
  assert.ok(vm.communityTools.some((t) => t.name === 'get_user_profile'), 'get_user_profile must be in communityTools')

  console.log('✓ Passed: All registered tools categorized without any dropping\n')
}

// ---------------------------------------------------------------------------
// Test 10: Confirmation Loopback Updates Tool Status & Clears Pending Count
// ---------------------------------------------------------------------------
console.log('Test 10: Confirmation Loopback Updates Tool Status & Clears Pending Count')
{
  const messages = [
    { kind: 'tool', tool: 'register_appointment', status: 'suspended', confirmationId: 'conf_99' },
    { kind: 'suspend', tool: 'register_appointment', status: 'executed', confirmationId: 'conf_99' },
  ]

  const vm = createTreeInstance({ messages })
  assert.equal(vm.healthTools[0].status, 'completed', 'Approved suspend must update tool status to completed')
  assert.equal(vm.pendingTasksCount, 0, 'Approved suspend must clear pendingTasksCount to 0')
  assert.equal(vm.isArtifactReady, true, 'Fully approved tools must unlock artifact readiness')

  // Now test rejection
  const rejMessages = [
    { kind: 'tool', tool: 'register_appointment', status: 'suspended', confirmationId: 'conf_100' },
    { kind: 'suspend', tool: 'register_appointment', status: 'rejected', confirmationId: 'conf_100' },
  ]
  const rejVm = createTreeInstance({ messages: rejMessages })
  assert.equal(rejVm.healthTools[0].status, 'rejected', 'Rejected suspend must update tool status to rejected')
  assert.equal(rejVm.pendingTasksCount, 0, 'Rejected suspend must not remain pending')
  assert.equal(rejVm.hasAnyRejected, true, 'hasAnyRejected must become true')

  console.log('✓ Passed: Confirmation loopback properly updates tool status and clears pending tasks\n')
}

// ---------------------------------------------------------------------------
// Test 11: CurrentAgent with Emoji Prefix Activates Subagent Branches
// ---------------------------------------------------------------------------
console.log('Test 11: CurrentAgent with Emoji Prefix Activates Subagent Branches')
{
  const vmHealth = createTreeInstance({
    messages: [{ isUser: true, text: '查号' }],
    thinking: true,
    currentAgent: '🏥 安康助手',
  })
  assert.equal(vmHealth.isHealthActive, true, '🏥 安康助手 must activate isHealthActive during thinking')
  assert.equal(vmHealth.healthStatusClass, 'status-thinking', 'healthStatusClass must be status-thinking')

  const vmTravel = createTreeInstance({
    messages: [{ isUser: true, text: '查票' }],
    thinking: true,
    currentAgent: '🧭 银发导航',
  })
  assert.equal(vmTravel.isTravelActive, true, '🧭 银发导航 must activate isTravelActive during thinking')
  assert.equal(vmTravel.travelStatusClass, 'status-thinking', 'travelStatusClass must be status-thinking')

  const vmComm = createTreeInstance({
    messages: [{ isUser: true, text: '陪诊' }],
    thinking: true,
    currentAgent: '🏘️ 邻里帮',
  })
  assert.equal(vmComm.isCommunityActive, true, '🏘️ 邻里帮 must activate isCommunityActive during thinking')
  assert.equal(vmComm.communityStatusClass, 'status-thinking', 'communityStatusClass must be status-thinking')

  console.log('✓ Passed: Emoji-prefixed currentAgent accurately triggers branch activation\n')
}

// ---------------------------------------------------------------------------
// Test 12: Idle State Transition after Turn Completion
// ---------------------------------------------------------------------------
console.log('Test 12: Idle State Transition after Turn Completion')
{
  const vmLive = createTreeInstance({
    messages: [
      { isUser: true, text: '早上好' },
      { isUser: false, text: '早上好！张阿姨。', agent: 'main' },
    ],
    thinking: false,
  })

  assert.equal(vmLive.globalStatusClass, 'status-completed', 'Finished conversation must transition out of status-thinking')
  assert.equal(vmLive.rootStatusClass, 'status-completed', 'Finished conversation must transition rootStatusClass out of status-thinking')
  assert.equal(vmLive.rootStatusIcon, '✅', 'Finished rootStatusIcon must be checkmark')
  assert(vmLive.globalStatusText.includes('随时待命') || vmLive.globalStatusText.includes('已达成'), 'Idle globalStatusText should indicate ready/completed')

  console.log('✓ Passed: Idle conversation state transitions cleanly without stuck status-thinking\n')
}

// ---------------------------------------------------------------------------
// Test 13: ArtifactPages Synthesis from Completed Tools and Body Cards
// ---------------------------------------------------------------------------
console.log('Test 13: ArtifactPages Synthesis from Completed Tools and Body Cards')
{
  // 13A: Card with body object (from appointment tool)
  const vmBodyCard = createTreeInstance({
    messages: [
      {
        kind: 'card',
        title: '专家号已预约',
        body: { '医院': '广州中医院', '科室': '心内科', '挂号费': '50元' },
      },
    ],
  })
  assert.equal(vmBodyCard.isArtifactReady, true)
  assert.equal(vmBodyCard.artifactPages.length, 1)
  assert.equal(vmBodyCard.artifactPages[0].title, '专家号已预约')
  assert.equal(vmBodyCard.artifactPages[0].rows.length, 3)

  // 13B: Approved tools without card event synthesize pages
  const vmSynthesized = createTreeInstance({
    messages: [
      {
        kind: 'tool',
        tool: 'register_appointment',
        agent: 'health',
        status: 'completed',
        args: { hospital: '广东省中医院', doctor: '李主任', fee: 100 },
      },
      {
        kind: 'tool',
        tool: 'search_train',
        agent: 'travel',
        status: 'completed',
        args: { train_no: 'G123', from_station: '广州南', to_station: '深圳北' },
      },
      {
        kind: 'suspend',
        tool: 'register_appointment',
        status: 'executed',
        confirmationId: 'c1',
      },
    ],
    thinking: false,
  })

  assert.equal(vmSynthesized.isArtifactReady, true)
  assert.ok(vmSynthesized.artifactPages.length >= 2, 'Must synthesize pages from completed health and travel tools')
  assert.equal(vmSynthesized.artifactPages[0].title, '健康医疗预约凭证')
  assert.equal(vmSynthesized.artifactPages[1].title, '交通住宿出行凭证')

  console.log('✓ Passed: Artifact pages properly constructed from both body cards and completed tools\n')
}

// ---------------------------------------------------------------------------
// Test 14: Orchestrator Tools Isolation (delegate/todo_write do not leak into community)
// ---------------------------------------------------------------------------
console.log('Test 14: Orchestrator Tools Isolation (delegate/todo_write/ask_user not in communityTools)')
{
  const vm = createTreeInstance({
    messages: [
      { isUser: true, text: '帮我问问专家' },
      { kind: 'tool', tool: 'delegate', agent: 'main', args: { tasks: [{ agent: 'health' }] } },
      { kind: 'tool', tool: 'todo_write', agent: 'main', args: {} },
      { kind: 'tool', tool: 'ask_user', agent: 'main', args: {} },
    ],
  })

  assert.equal(vm.communityTools.length, 0, 'communityTools must not contain delegate, todo_write, or ask_user')
  assert.equal(vm.isCommunityActive, false, 'isCommunityActive must remain false when only orchestrator tools are invoked')
  assert.equal(vm.activeAgentsCount, 0, 'activeAgentsCount must not count community as active')
  console.log('✓ Passed: Orchestrator tools isolated from community branch\n')
}

// ---------------------------------------------------------------------------
// Test 15: Emoji-prefixed agent in SSE status messages activates subagent branches
// ---------------------------------------------------------------------------
console.log('Test 15: Emoji-prefixed agent in SSE messages activates subagents and updates monologue')
{
  const vm = createTreeInstance({
    messages: [
      { isUser: true, text: '去南京' },
      { kind: 'status', agent: '🧭 银发导航', text: '正在检索南京南站车次...' },
    ],
  })

  assert.equal(vm.isTravelActive, true, 'isTravelActive must be true when message has 🧭 银发导航')
  assert.equal(vm.agentThoughts.travel, '正在检索南京南站车次...', 'travel thought must reflect latest status message')
  console.log('✓ Passed: Emoji-prefixed agent successfully activates branch and sets monologue\n')
}

// ---------------------------------------------------------------------------
// Test 16: PlanBuilder & Safety guard explicit reasoning display
// ---------------------------------------------------------------------------
console.log('Test 16: Explicit reasoning prioritization for PlanBuilder & Safety')
{
  const vm = createTreeInstance({
    messages: [
      { isUser: true, text: '装配方案' },
      { agent: 'plan_builder', reasoning: '已完成多智能体交叉校验与去幻觉对齐，装配就医单。' },
      { agent: 'safety', reasoning: '资金池风控审核通过，全流程免责声明已注入。' },
    ],
  })

  assert.equal(vm.agentThoughts.planBuilder, '已完成多智能体交叉校验与去幻觉对齐，装配就医单。')
  assert.equal(vm.agentThoughts.safety, '资金池风控审核通过，全流程免责声明已注入。')
  console.log('✓ Passed: Explicit reasoning prioritized for PlanBuilder and Safety\n')
}

// ---------------------------------------------------------------------------
// Test 17: Standalone suspend events recognized in highRiskTools
// ---------------------------------------------------------------------------
console.log('Test 17: Standalone suspend events recognized in highRiskTools')
{
  const vm = createTreeInstance({
    messages: [
      {
        kind: 'suspend',
        tool: 'pay_deposit',
        amount: 50,
        status: 'pending',
        confirmationId: 'conf_test_dep',
        message: '需确认社区床位押金',
      },
    ],
  })

  assert.equal(vm.highRiskTools.length, 1, 'highRiskTools must contain standalone suspend')
  assert.equal(vm.highRiskTools[0].confirmationId, 'conf_test_dep')
  assert.equal(vm.highRiskTools[0].amount, '50.00')
  assert.equal(vm.pendingTasksCount, 1, 'pendingTasksCount must equal 1')
  console.log('✓ Passed: Standalone suspend properly represented in highRiskTools\n')
}

// ---------------------------------------------------------------------------
// Test 18: Local hospital visit does not falsely trigger intercity scenario tag
// ---------------------------------------------------------------------------
console.log('Test 18: Local hospital visit distinguishes from intercity travel')
{
  const vmLocal = createTreeInstance({
    messages: [{ isUser: true, text: '我想去医院看病挂个号' }],
  })
  assert.equal(vmLocal.currentScenarioTag, '健康医疗咨询服务', 'Local hospital visit must be 健康医疗咨询服务')

  const vmIntercity = createTreeInstance({
    messages: [{ isUser: true, text: '我想坐高铁去北京看病' }],
  })
  assert.equal(vmIntercity.currentScenarioTag, '跨城就医出行规划', 'Intercity hospital visit must be 跨城就医出行规划')
  console.log('✓ Passed: Local vs intercity scenario tags accurately differentiated\n')
}

console.log('====================================================')
console.log('ALL 18 ADVERSARIAL TEST SUITES PASSED SUCCESSFULLY!')
console.log('====================================================')

