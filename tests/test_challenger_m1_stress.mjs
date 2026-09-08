import assert from 'node:assert/strict'
import fs from 'node:fs'

console.log('======================================================================')
console.log('=== Milestone 1 Challenger Stress Suite (Adversarial Empirical) ===')
console.log('======================================================================\n')

const vuePath = 'frontend/laoyouji-app/src/components/AgentExecutionTree.vue'
const chatBubblePath = 'frontend/laoyouji-app/src/components/ChatBubble.vue'
const planCardPath = 'frontend/laoyouji-app/src/components/PlanCard.vue'

const vueContent = fs.readFileSync(vuePath, 'utf-8')
const chatBubbleContent = fs.readFileSync(chatBubblePath, 'utf-8')
const planCardContent = fs.readFileSync(planCardPath, 'utf-8')

// ===========================================================================
// Section 1: Static Replay Excision & Residual Leakage Invariants
// ===========================================================================
console.log('[Challenger Suite 1] Verifying Complete Replay Excision...')

// Invariant 1.1: Case-insensitive 'replay' matches in AgentExecutionTree.vue
const replayMatches = [...vueContent.matchAll(/replay/gi)]
assert.equal(
  replayMatches.length,
  0,
  `AgentExecutionTree.vue MUST contain 0 occurrences of 'replay' (case-insensitive), but found ${replayMatches.length}: ${replayMatches.map(m => m[0]).join(', ')}`
)
console.log('  ✓ Invariant 1.1 Passed: Zero occurrences of "replay" in AgentExecutionTree.vue')

// Invariant 1.2: REPLAY_SANDBOX invariant
assert.ok(!vueContent.includes('REPLAY_SANDBOX'), 'REPLAY_SANDBOX must not exist anywhere in AgentExecutionTree.vue')
console.log('  ✓ Invariant 1.2 Passed: REPLAY_SANDBOX completely absent')

// Invariant 1.3: Replay methods invariant
const replayMethods = [
  'toggleReplayMode',
  'startReplay',
  'pauseReplay',
  'resumeReplay',
  'toggleReplayPlay',
  'nextReplayStep',
  'prevReplayStep',
  'resetReplay',
  'seekReplay',
  'exitReplay',
  'currentReplayStepInfo',
  'replayStepInfo',
]
for (const m of replayMethods) {
  assert.ok(!vueContent.includes(m), `Method/property '${m}' must be completely removed from AgentExecutionTree.vue`)
}
console.log('  ✓ Invariant 1.3 Passed: All 12 replay-related methods and computeds absent')

// Invariant 1.4: Replay CSS classes invariant
const replayCssClasses = [
  '.replay-btn',
  '.replay-trigger-btn',
  '.replay-controller-bar',
  '.replay-narrative',
  '.narrative-tag',
  '.narrative-step-num',
  '.narrative-title',
  '.replay-buttons-row',
  '.replay-progress-track',
  '.replay-progress-dot',
]
for (const cls of replayCssClasses) {
  assert.ok(!vueContent.includes(cls), `CSS class '${cls}' must be completely removed from AgentExecutionTree.vue`)
}
console.log('  ✓ Invariant 1.4 Passed: All replay CSS classes completely eliminated')

// ===========================================================================
// Section 2: Negative Constraints (Voice TTS Replay Preservation)
// ===========================================================================
console.log('\n[Challenger Suite 2] Verifying Negative Constraints (TTS Voice Replay Preserved)...')

const chatBubbleReplayCount = [...chatBubbleContent.matchAll(/replay/gi)].length
assert.ok(chatBubbleReplayCount >= 7, `ChatBubble.vue must preserve voice replay (expected >= 7, got ${chatBubbleReplayCount})`)
console.log(`  ✓ Invariant 2.1 Passed: ChatBubble.vue contains ${chatBubbleReplayCount} replay occurrences for audio TTS`)

const planCardReplayCount = [...planCardContent.matchAll(/replay/gi)].length
assert.ok(planCardReplayCount >= 7, `PlanCard.vue must preserve voice replay (expected >= 7, got ${planCardReplayCount})`)
console.log(`  ✓ Invariant 2.2 Passed: PlanCard.vue contains ${planCardReplayCount} replay occurrences for audio TTS`)

// ===========================================================================
// Component Instantiation & Setup
// ===========================================================================
const scriptMatch = vueContent.match(/<script>([\s\S]*?)<\/script>/)
assert(scriptMatch, 'Script tag must exist in AgentExecutionTree.vue')
const scriptText = scriptMatch[1]

const compObjText = scriptText.substring(scriptText.indexOf('export default {')).replace('export default ', '')
const compDef = eval('(' + compObjText + ')')

// Mock uni global
globalThis.uni = {
  showToast: (opts) => { globalThis._lastToast = opts },
  showModal: (opts) => { globalThis._lastModal = opts },
}

function createTreeInstance(props = {}) {
  const data = compDef.data()
  const vm = {
    ...data,
    messages: props.messages,
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

// Invariant 1.5: data() has no replay key
{
  const initialData = compDef.data()
  assert.equal(initialData.replay, undefined, 'data() must not contain a replay property')
  console.log('  ✓ Invariant 1.5 Passed: Component data() has no replay property')
}

// ===========================================================================
// Section 3: Extreme Adversarial Fuzzing on Props & Messages
// ===========================================================================
console.log('\n[Challenger Suite 3] Stress-Testing Adversarial / Fuzzed Inputs...')

// Case 3.1: Null, undefined, and empty array messages prop
{
  for (const invalidMessages of [null, undefined, []]) {
    const vm = createTreeInstance({ messages: invalidMessages })
    assert.doesNotThrow(() => vm.safeMessages, `safeMessages must not throw on messages=${JSON.stringify(invalidMessages)}`)
    assert.deepEqual(vm.safeMessages, [], `safeMessages must return [] when messages is ${typeof invalidMessages}`)
    assert.equal(vm.activeAgentsCount, 0)
    assert.equal(vm.totalToolsCount, 0)
    assert.equal(vm.isArtifactReady, false)
    assert.equal(vm.currentScenarioTag, '待命中')
  }
  console.log('  ✓ Case 3.1 Passed: Null, undefined, and empty array messages gracefully fallback to []')
}

// Case 3.2: Malformed tool calls inside messages (both kind === 'tool' and unexpected schemas)
{
  const malformedToolMessages = [
    { kind: 'tool', tool: null, args: null },
    { kind: 'tool', tool: undefined, args: undefined },
    { kind: 'tool', tool: '', args: '' },
    { kind: 'tool', tool: 123, args: { invalid: true } },
    { kind: 'tool', tool: 'broken_json', args: '{ broken json: true' },
    { kind: 'tool', tool: 'array_args', args: [1, 2, 3] },
    { kind: 'tool', tool: 'search_hospital', args: { city: '杭州', hospital_name: '浙医二院' } },
    { kind: 'tool', name: 'book_train_ticket', args: '{"from":"成都","to":"九寨沟"}' },
    { kind: 'unexpected_kind', some_prop: true },
    null,
    undefined,
    12345,
    'corrupted_string',
  ]

  const vm = createTreeInstance({ messages: malformedToolMessages })
  assert.doesNotThrow(() => vm.allTools, 'allTools should not throw on malformed tool calls')
  assert.doesNotThrow(() => vm.highRiskTools, 'highRiskTools should not throw on malformed tool calls')
  assert.doesNotThrow(() => vm.travelTools, 'travelTools should not throw')
  assert.doesNotThrow(() => vm.healthTools, 'healthTools should not throw')

  // Two valid tools parsed: search_hospital (health) and book_train_ticket (travel)
  assert.equal(vm.travelTools.length, 1)
  assert.equal(vm.travelTools[0].name, 'book_train_ticket')
  assert.equal(vm.healthTools.length, 1)
  assert.equal(vm.healthTools[0].name, 'search_hospital')
  console.log('  ✓ Case 3.2 Passed: Malformed messages & tool items handled robustly with zero exceptions')
}

// Case 3.3: Malformed Todos and Todos with Missing Fields
{
  const malformedTodoMessages = [
    { kind: 'todo', todos: null },
    { kind: 'todo', todos: 'not an array' },
    { kind: 'todo', todos: [null, undefined, 123, 'hello'] },
    {
      kind: 'todo',
      todos: [
        null,
        undefined,
        123,
        'hello',
        { id: 1 }, // missing text/content/title, should fallback to '待办事项 5'
        { content: '整理常备药品' },
        { text: '预约陪诊服务', status: 'in_progress' },
        { title: '安全审核确认', status: 'completed' },
      ],
    },
  ]

  const vm = createTreeInstance({ messages: malformedTodoMessages })
  assert.doesNotThrow(() => vm.displaySteps, 'displaySteps must not throw on corrupted todos')
  assert.equal(vm.displaySteps.length, 4, 'displaySteps should extract 4 valid todo objects from latest snapshot')
  assert.equal(vm.displaySteps[0].name, '待办事项 1')
  assert.equal(vm.displaySteps[1].name, '整理常备药品')
  assert.equal(vm.displaySteps[2].name, '预约陪诊服务')
  assert.equal(vm.displaySteps[3].name, '安全审核确认')
  console.log('  ✓ Case 3.3 Passed: Corrupted todos extracted cleanly across text/content/title fallbacks')
}

// Case 3.4: Adversarial Agent Status and Emojis
{
  const statusMessages = [
    { kind: 'agent_status', agent: null, status: null },
    { kind: 'agent_status', agent: undefined, status: 'thinking' },
    { kind: 'agent_status', agent: '🤖 unknown_agent', status: 'thinking' },
    { kind: 'agent_status', agent: '🚄 travel#2', status: 'done' },
    { kind: 'status', agent: '🩺 health', thought: '正在为老人分析挂号科室与骨科专家号源...' },
    { kind: 'status', agent: '❤️ community', reasoning: '正在协同社区邻里互助志愿者...' },
  ]

  const vm = createTreeInstance({ messages: statusMessages })
  assert.doesNotThrow(() => vm.agentThoughts)
  const thoughts = vm.agentThoughts
  assert.equal(thoughts.health, '正在为老人分析挂号科室与骨科专家号源...')
  assert.equal(thoughts.community, '正在协同社区邻里互助志愿者...')
  console.log('  ✓ Case 3.4 Passed: Agent status with emojis/scopes safely mapped to thoughts')
}

// ===========================================================================
// Section 4: Performance & Massive Concurrency Stress Test (10,000 Messages)
// ===========================================================================
console.log('\n[Challenger Suite 4] Massive Concurrency & Stress Test (10,000 Messages)...')

{
  const massiveMessages = []
  const agents = ['health', 'travel', 'community', 'safety', 'planBuilder', 'main']
  const tools = ['search_hospital', 'book_car', 'find_volunteer', 'verify_order', 'compose_deliverable']

  for (let i = 0; i < 10000; i++) {
    const agent = agents[i % agents.length]
    const tool = tools[i % tools.length]
    if (i % 5 === 0) {
      massiveMessages.push({
        kind: 'tool',
        agent,
        callId: `call_${i}`,
        tool,
        name: tool,
        args: { index: i, city: '杭州', item: `测试项_${i}`, fee: 10 },
        status: i % 2 === 0 ? 'completed' : 'running',
      })
    } else if (i % 5 === 1) {
      massiveMessages.push({
        kind: 'tool_result',
        agent,
        callId: `call_${i - 1}`,
        tool,
        content: `执行成功 ${i}`,
      })
    } else if (i % 5 === 2) {
      massiveMessages.push({
        kind: 'agent_status',
        agent,
        status: i % 2 === 0 ? 'thinking' : 'done',
      })
    } else if (i % 5 === 3) {
      massiveMessages.push({
        kind: 'todo',
        todos: [
          { id: `todo_${i}`, content: `步骤 ${i % 10}`, status: 'in_progress' },
        ],
      })
    } else {
      massiveMessages.push({
        isUser: false,
        kind: 'text',
        text: `系统正常流转中第 ${i} 步`,
      })
    }
  }

  const vm = createTreeInstance({ messages: massiveMessages })

  const startMs = Date.now()
  const displaySteps = vm.displaySteps
  const allTools = vm.allTools
  const highRiskTools = vm.highRiskTools
  const thoughts = vm.agentThoughts
  const scenarioTag = vm.currentScenarioTag
  const durationMs = Date.now() - startMs

  console.log(`  ✓ Evaluated all computeds across 10,000 messages in ${durationMs}ms`)
  assert.ok(durationMs < 1500, `Evaluation must complete in under 1500ms, took ${durationMs}ms`)
  assert.ok(allTools.length > 1000, 'Should aggregate thousands of tool calls')
  assert.ok(displaySteps.length > 0, 'Should aggregate display steps')
  assert.ok(thoughts !== null, 'Thoughts should not be null')
  console.log('  ✓ Case 4.1 Passed: Component performs within high-speed bounds without OOM or call stack error')
}

// ===========================================================================
// Section 5: Interaction Methods Freedom from Residual Replay
// ===========================================================================
console.log('\n[Challenger Suite 5] Testing Interaction Methods for Residual Replay Invocations...')

{
  const vm = createTreeInstance({
    messages: [
      {
        kind: 'suspend',
        confirmationId: 'conf_101',
        tool: 'book_car',
        params: { destination: '市民中心' },
      },
      {
        kind: 'suspend',
        confirmationId: 'conf_102',
        tool: 'book_train_ticket',
        params: { to: '苏州' },
      },
    ],
  })

  // Test triggerApprove
  assert.doesNotThrow(() => vm.triggerApprove('conf_101', 'book_car'))
  assert.equal(vm._emitted.length, 1)
  assert.equal(vm._emitted[0].event, 'resolve-confirmation')
  assert.equal(vm._emitted[0].payload.confirmationId, 'conf_101')
  assert.equal(vm._emitted[0].payload.status, 'executed')

  // Test triggerReject
  assert.doesNotThrow(() => vm.triggerReject('conf_102', 'book_train_ticket'))
  assert.equal(vm._emitted.length, 2)
  assert.equal(vm._emitted[1].event, 'resolve-confirmation')
  assert.equal(vm._emitted[1].payload.confirmationId, 'conf_102')
  assert.equal(vm._emitted[1].payload.status, 'rejected')

  // Test approveAllPending
  assert.doesNotThrow(() => vm.approveAllPending())
  assert.equal(vm._emitted.length, 4, 'approveAllPending should emit approvals for both pending tasks')

  // Test UI state toggle methods
  assert.doesNotThrow(() => vm.toggleAllExpanded())
  assert.doesNotThrow(() => vm.toggleAgentCollapse('health'))
  assert.doesNotThrow(() => vm.scrollToSection('travel'))
  assert.equal(vm.collapsedAgents.travel, false)

  console.log('  ✓ Case 5.1 Passed: All interaction methods execute purely on real state without any replay references')
}

// ===========================================================================
// Section 6: Absence of Hardcoded Medical Entities Across Diverse Scenarios
// ===========================================================================
console.log('\n[Challenger Suite 6] Absolute Absence of Hardcoded Beijing Medical Mock Entities...')

const diverseScenarios = [
  {
    name: 'Chengdu Sightseeing',
    userText: '我想去成都锦里和宽窄巷子逛逛，帮我安排一下车和门票',
    expectedTag: '长途跨城出行方案',
  },
  {
    name: 'Wuhan Community Help',
    userText: '社区明天有测量血压的义诊吗？帮我问问邻居小李',
    expectedTag: '邻里助老便民服务',
  },
  {
    name: 'Hangzhou Health Checkup',
    userText: '我想去浙大一院挂个眼科检查一下视力',
    expectedTag: '日常健康咨询与慢病管理',
  },
]

for (const scenario of diverseScenarios) {
  const vm = createTreeInstance({
    messages: [
      { isUser: true, text: scenario.userText },
      { kind: 'text', isUser: false, text: `好的，正在为您处理：${scenario.userText}` },
    ],
  })

  const serializedAll = JSON.stringify({
    scenarioTag: vm.currentScenarioTag,
    intentText: vm.currentIntentText,
    thoughts: vm.agentThoughts,
    steps: vm.displaySteps,
    artifact: vm.artifactPages,
  })

  assert.ok(!serializedAll.includes('北京'), `Scenario "${scenario.name}" leaked '北京'`)
  assert.ok(!serializedAll.includes('积水潭'), `Scenario "${scenario.name}" leaked '积水潭'`)
  assert.ok(!serializedAll.includes('田伟'), `Scenario "${scenario.name}" leaked '田伟'`)
  assert.ok(!serializedAll.includes('G102'), `Scenario "${scenario.name}" leaked 'G102'`)
  assert.ok(!serializedAll.includes('漫心酒店'), `Scenario "${scenario.name}" leaked '漫心酒店'`)
}
console.log('  ✓ Case 6.1 Passed: Zero mock medical entities leaked across diverse regional scenarios')

// ===========================================================================
// Section 7: Elimination of Replay Fallbacks in Computed Properties
// ===========================================================================
console.log('\n[Challenger Suite 7] Verifying Elimination of Replay Fallbacks in Computed Properties...')

{
  // When no card and incomplete tools exist, artifactPages MUST be empty array []
  const vm = createTreeInstance({
    messages: [
      { isUser: true, text: '你好' },
      { kind: 'agent_status', agent: 'health', status: 'thinking' },
    ],
  })
  assert.equal(vm.isArtifactReady, false, 'Artifact must NOT be ready in incomplete state')
  assert.deepEqual(vm.artifactPages, [], 'artifactPages must return [] and NOT fall back to REPLAY_SANDBOX.artifactPages')
  console.log('  ✓ Case 7.1 Passed: artifactPages correctly returns [] instead of mock sandbox pages')
}

// ===========================================================================
// Section 8: Rapid Sequential SSE Stream Simulation
// ===========================================================================
console.log('\n[Challenger Suite 8] Rapid Sequential SSE Stream Simulation (200 events)...')

{
  const vm = createTreeInstance({ messages: [] })
  const streamEvents = []

  // Create stream of 200 events
  for (let i = 0; i < 200; i++) {
    if (i === 0) {
      streamEvents.push({ isUser: true, text: '帮我预约明天的体检和去医院的车' })
    } else if (i < 50) {
      streamEvents.push({
        kind: 'agent_status',
        agent: i % 2 === 0 ? 'health' : 'travel',
        status: 'thinking',
      })
    } else if (i < 150) {
      streamEvents.push({
        kind: 'tool',
        agent: i % 2 === 0 ? 'health' : 'travel',
        callId: `stream_call_${i}`,
        tool: i % 2 === 0 ? 'search_hospital' : 'book_car',
        status: i < 100 ? 'running' : 'completed',
        summary: `正在处理任务 #${i}`,
      })
    } else {
      streamEvents.push({
        kind: 'todo',
        todos: [
          { id: `todo_1`, text: '确定体检科室', status: 'completed' },
          { id: `todo_2`, text: '安排出行车辆', status: 'completed' },
        ],
      })
    }
  }

  const startStream = Date.now()
  for (const event of streamEvents) {
    vm.messages.push(event)
    // Access reactive computeds to trigger getter evaluations
    const _active = vm.activeAgentsCount
    const _tools = vm.allTools.length
    const _steps = vm.displaySteps.length
  }
  const streamDurationMs = Date.now() - startStream
  console.log(`  ✓ Processed 200 SSE events sequentially in ${streamDurationMs}ms (${(streamDurationMs / 200).toFixed(3)}ms/event)`)
  assert.ok(streamDurationMs < 1000, `Stream processing must take < 1000ms, took ${streamDurationMs}ms`)
  console.log('  ✓ Case 8.1 Passed: SSE stream simulation completes with ultra-low latency and consistent state')
}

console.log('\n======================================================================')
console.log('=== ALL CHALLENGER ADVERSARIAL TESTS PASSED WITH ZERO DEFECTS! ===')
console.log('======================================================================\n')
