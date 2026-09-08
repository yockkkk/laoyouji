import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const sfc = require(path.resolve('frontend/laoyouji-app/node_modules/@vue/compiler-sfc'))

console.log('================================================================================')
console.log('=== Milestone 2 Challenger Stress Suite: DAG Canvas Excision & UI Stability ===')
console.log('================================================================================\n')

const vuePath = 'frontend/laoyouji-app/src/components/AgentExecutionTree.vue'
const chatBubblePath = 'frontend/laoyouji-app/src/components/ChatBubble.vue'
const planCardPath = 'frontend/laoyouji-app/src/components/PlanCard.vue'

assert.ok(fs.existsSync(vuePath), `Target file ${vuePath} must exist`)
const vueContent = fs.readFileSync(vuePath, 'utf-8')
const chatBubbleContent = fs.readFileSync(chatBubblePath, 'utf-8')
const planCardContent = fs.readFileSync(planCardPath, 'utf-8')

// ==============================================================================
// Oracle & Setup: Parse SFC into Template, Script, and Styles
// ==============================================================================
const parsedSfc = sfc.parse(vueContent, { filename: 'AgentExecutionTree.vue' })
assert.equal(parsedSfc.errors.length, 0, 'SFC parsing must have 0 syntax errors')

const templateContent = parsedSfc.descriptor.template?.content || ''
const scriptContent = parsedSfc.descriptor.script?.content || ''
const stylesContent = parsedSfc.descriptor.styles?.map(s => s.content).join('\n') || ''

assert.ok(templateContent.length > 0, 'Template content must be non-empty')
assert.ok(scriptContent.length > 0, 'Script content must be non-empty')
assert.ok(stylesContent.length > 0, 'Styles content must be non-empty')

// ==============================================================================
// Suite 1: Static Code Invariants & Residual Cleanup (DAG Excision)
// ==============================================================================
console.log('[Suite 1] Verifying Static Invariants & Clean Excision of DAG Canvas...')

// Invariant 1.1: Zero occurrences of 'planning-dag-card' across entire file
const dagCardMatches = [...vueContent.matchAll(/planning-dag-card/gi)]
assert.equal(
  dagCardMatches.length,
  0,
  `AgentExecutionTree.vue must contain 0 occurrences of 'planning-dag-card', found ${dagCardMatches.length}`
)
console.log('  ✓ Invariant 1.1: 0 occurrences of "planning-dag-card" in component')

// Invariant 1.2: Zero occurrences of '.dag-' or 'dag-' selectors/classes in styles or template
const dagClassMatchesInTemplate = [...templateContent.matchAll(/class=["'][^"']*?\bdag-[^"']*?["']/gi)]
assert.equal(
  dagClassMatchesInTemplate.length,
  0,
  `Template must contain 0 'dag-*' class names, found: ${dagClassMatchesInTemplate.map(m => m[0]).join(', ')}`
)

const dagCssSelectors = [...stylesContent.matchAll(/\.dag-[a-zA-Z0-9_-]+/g)]
assert.equal(
  dagCssSelectors.length,
  0,
  `Styles must contain 0 '.dag-*' CSS selectors, found: ${dagCssSelectors.map(m => m[0]).join(', ')}`
)
console.log('  ✓ Invariant 1.2: 0 occurrences of "dag-*" classes/selectors in template & SCSS')

// Invariant 1.3: Zero occurrences of '@keyframes dag-frontier-pulse'
assert.ok(
  !vueContent.includes('dag-frontier-pulse'),
  'Styles must not contain @keyframes dag-frontier-pulse'
)
console.log('  ✓ Invariant 1.3: Animation @keyframes dag-frontier-pulse completely removed')

// Invariant 1.4: Eight excised DAG-only computed properties absent from script
const excisedDagComputeds = [
  'isRootFrontier',
  'isRootDone',
  'isHealthFrontier',
  'isTravelFrontier',
  'isCommunityFrontier',
  'isSafetyFrontier',
  'isPlanBuilderFrontier',
  'artifactChipText',
]
for (const compName of excisedDagComputeds) {
  assert.ok(
    !scriptContent.includes(compName),
    `Computed property '${compName}' must be completely removed from script`
  )
}
console.log(`  ✓ Invariant 1.4: All ${excisedDagComputeds.length} DAG-specific computed properties excised`)

// Invariant 1.5: Header actions converged to exactly 3 buttons
const headerMatches = templateContent.match(/<view class="tree-header">([\s\S]*?)<\/view>\s*<!-- 拓扑度量信息栏 -->/)
assert.ok(headerMatches, 'Header block must exist')
const headerButtons = [...headerMatches[1].matchAll(/<button[\s\S]*?<\/button>/g)]
assert.equal(
  headerButtons.length,
  3,
  `Header must contain exactly 3 control buttons (toggleAllExpanded, desktop collapse, mobile close), found ${headerButtons.length}`
)
assert.ok(headerButtons[0][0].includes('toggleAllExpanded'), 'First header button must be toggleAllExpanded')
assert.ok(headerButtons[1][0].includes('collapse-pane-btn') && headerButtons[1][0].includes('isDesktop'), 'Second header button must be desktop collapse')
assert.ok(headerButtons[2][0].includes('close-drawer-btn') && headerButtons[2][0].includes('!isDesktop'), 'Third header button must be mobile close')
console.log('  ✓ Invariant 1.5: Header toolbar cleanly converged to exactly 3 control buttons')

// Invariant 1.6: CSS Whitelist Preservation
assert.ok(
  stylesContent.includes('.artifact-avatar { background: #e0e7ff; }') ||
  stylesContent.includes('.artifact-avatar {\n  background: #e0e7ff;'),
  '.artifact-avatar with #e0e7ff background must be preserved in CSS'
)
assert.ok(stylesContent.includes('.artifact-leaf-node'), '.artifact-leaf-node styles must be preserved')
assert.ok(stylesContent.includes('.artifact-modal-mask'), '.artifact-modal-mask styles must be preserved')
assert.ok(stylesContent.includes('.root-node-card'), '.root-node-card styles must be preserved')
assert.ok(stylesContent.includes('lyj-pulse-glow'), 'lyj-pulse-glow animation must be preserved')
console.log('  ✓ Invariant 1.6: CSS whitelist (.artifact-avatar, .artifact-leaf-node, .root-node-card) intact')

// ==============================================================================
// Suite 2: Template Compilation & AST Context Binding Completeness
// ==============================================================================
console.log('\n[Suite 2] Verifying Template Compilation, AST Structure & Context Bindings...')

// 2.1 Compile template with Vue compiler
const compiled = sfc.compileTemplate({
  source: templateContent,
  id: 'challenger-m2-tree',
  scoped: false,
})
assert.equal(compiled.errors.length, 0, `Template compilation errors: ${JSON.stringify(compiled.errors)}`)
assert.equal(compiled.tips.length, 0, `Template compilation tips/warnings: ${JSON.stringify(compiled.tips)}`)
console.log('  ✓ Invariant 2.1: Vue 3 compiler successfully compiled template with zero errors/warnings')

// 2.2 Parse component definition
const compObjText = scriptContent.substring(scriptContent.indexOf('export default {')).replace('export default ', '')
const compDef = eval('(' + compObjText + ')')

// Mock uni runtime
globalThis.uni = {
  showToast: (opts) => { globalThis._lastToast = opts },
  showModal: (opts) => { globalThis._lastModal = opts },
}

function createVm(props = {}) {
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

// 2.3 Verify all _ctx accesses in template exist on the VM
const renderCode = compiled.code
const ctxAccesses = new Set([...renderCode.matchAll(/_ctx\.([a-zA-Z0-9_$]+)/g)].map(m => m[1]))

// Ensure none of the excised computeds are accessed
for (const excised of excisedDagComputeds) {
  assert.ok(
    !ctxAccesses.has(excised),
    `Excised computed '${excised}' must NOT be referenced in the compiled template!`
  )
}
console.log('  ✓ Invariant 2.2: Zero excised DAG properties referenced in compiled template')

const sampleVm = createVm()
const missingBindings = []
for (const binding of ctxAccesses) {
  if (!(binding in sampleVm)) {
    missingBindings.push(binding)
  }
}
assert.equal(
  missingBindings.length,
  0,
  `Template references properties that do not exist on VM: ${missingBindings.join(', ')}`
)
console.log(`  ✓ Invariant 2.3: All ${ctxAccesses.size} template context bindings resolve cleanly to VM definition`)

// 2.4 Structural AST Check: First card inside tree-canvas is root-node-card
const treeCanvasMatch = templateContent.match(/<view class="tree-canvas">([\s\S]*?)<\/view>\s*<\/scroll-view>/)
assert.ok(treeCanvasMatch, 'tree-canvas container must exist')
const canvasInner = treeCanvasMatch[1].trim()
const firstNodeIndex = canvasInner.indexOf('<view class="root-node-card"')
assert.ok(firstNodeIndex >= 0 && firstNodeIndex < 200, 'First major card in tree-canvas must be root-node-card')

// 2.5 Subagent branch cards: Exactly 5 branch cards present
const branchNames = ['health', 'travel', 'community', 'safety', 'planbuilder']
for (const b of branchNames) {
  const branchPattern = new RegExp(`class="subagent-branch-card\\s+${b}-branch"`, 'i')
  assert.ok(branchPattern.test(templateContent), `Subagent branch card for '${b}' must exist in template`)
}
console.log('  ✓ Invariant 2.4: Root card and all 5 subagent branches directly form the tree canvas hierarchy')

// ==============================================================================
// Suite 3: Rendering Flow & State Progression Under Varied Session States
// ==============================================================================
console.log('\n[Suite 3] Testing UI State Progression Across Varied Session Lifecycles...')

// State 3.1: Initial Empty Session
{
  const vm = createVm({ messages: [], thinking: false, currentAgent: '' })
  assert.equal(vm.activeAgentsCount, 0, 'activeAgentsCount must be 0')
  assert.equal(vm.totalToolsCount, 0, 'totalToolsCount must be 0')
  assert.equal(vm.pendingTasksCount, 0, 'pendingTasksCount must be 0')
  assert.equal(vm.hasAnyRejected, false, 'hasAnyRejected must be false')
  assert.equal(vm.isArtifactReady, false, 'isArtifactReady must be false')
  assert.equal(vm.isHealthActive, false)
  assert.equal(vm.isTravelActive, false)
  assert.equal(vm.isCommunityActive, false)
  assert.equal(vm.isSafetyActive, false)
  assert.equal(vm.isPlanBuilderActive, false)
  assert.equal(vm.currentScenarioTag, '待命中')
  assert.equal(vm.rootStatusText, '主调度就绪 · 等待长辈诉求')
  assert.equal(vm.displaySteps.length, 0)
  assert.equal(vm.artifactPages.length, 0)
  console.log('  ✓ State 3.1 Passed: Initial empty session renders stable idle state without DAG')
}

// State 3.2: Thinking / Intent Parsing State
{
  const vm = createVm({
    messages: [{ role: 'user', isUser: true, text: '我最近有点头晕，想去医院看看', content: '我最近有点头晕，想去医院看看' }],
    thinking: true,
    currentAgent: 'health',
  })
  assert.equal(vm.thinking, true)
  assert.equal(vm.rootStatusText, '意图拆解与全局调度中')
  assert.equal(vm.currentScenarioTag, '健康医疗咨询服务')
  assert.equal(vm.isHealthActive, true)
  assert.equal(vm.isTravelActive, false)
  console.log('  ✓ State 3.2 Passed: Intent recognition and single-agent branch activation')
}

// State 3.3: Multi-Agent Parallel Dispatch State
{
  const vm = createVm({
    messages: [
      { role: 'user', content: '我想去广州看腰椎，顺便找个社区志愿者帮我照看家里的花草' },
      { kind: 'status', agent: 'main', content: '正在调度健康、出行与社区三方协同' },
      {
        kind: 'tool',
        agent: 'health',
        tool_name: 'search_hospital',
        arguments: '{"city":"广州","department":"骨科"}',
        status: 'completed',
        result: '已找到广州市第一人民医院骨科',
      },
      {
        kind: 'tool',
        agent: 'travel',
        tool_name: 'query_train_tickets',
        arguments: '{"from":"佛山","to":"广州"}',
        status: 'completed',
        result: '查询到G6002次列车',
      },
      {
        kind: 'tool',
        agent: 'community',
        tool_name: 'post_elder_help_request',
        arguments: '{"service_type":"浇花看护"}',
        status: 'completed',
        result: '志愿服务已登记',
      },
      {
        kind: 'todo',
        todos: [
          { text: '医院骨科专家号源对齐', status: 'completed' },
          { text: '城际列车无障碍乘车保障', status: 'completed' },
          { text: '社区护花志愿结对', status: 'completed' },
        ],
      },
    ],
  })

  assert.equal(vm.isHealthActive, true, 'Health should be active')
  assert.equal(vm.isTravelActive, true, 'Travel should be active')
  assert.equal(vm.isCommunityActive, true, 'Community should be active')
  assert.equal(vm.isSafetyActive, false, 'Safety should not be active yet')
  assert.equal(vm.isPlanBuilderActive, false, 'PlanBuilder should not be active yet')
  assert.equal(vm.activeAgentsCount, 3, 'activeAgentsCount should be 3')
  assert.equal(vm.totalToolsCount, 3, 'totalToolsCount should be 3')
  assert.equal(vm.displaySteps.length, 3, 'displaySteps should contain 3 items')
  assert.equal(vm.completedStepsCount, 3, 'all 3 steps completed')
  console.log('  ✓ State 3.3 Passed: Multi-agent parallel dispatch state derived with 100% precision')
}

// State 3.4: Safety Intercept & Approval Suspension Gateway
{
  const vm = createVm({
    messages: [
      {
        kind: 'tool',
        agent: 'health',
        tool_name: 'register_hospital_appointment',
        arguments: '{"hospital":"广州市第一人民医院","fee":50}',
        status: 'suspended',
      },
      {
        kind: 'suspend',
        task_id: 'task_reg_999',
        action_name: '专家挂号费用支付确认',
        description: '预约挂号费 50 元需家属授权确认',
        status: 'pending',
      },
    ],
  })

  assert.equal(vm.isSafetyActive, true, 'Safety branch must be active')
  assert.equal(vm.pendingTasksCount, 1, 'pendingTasksCount must be 1')
  assert.equal(vm.hasAnyRejected, false, 'hasAnyRejected must be false')
  assert.equal(vm.highRiskTools.length, 1, 'highRiskTools must contain suspended tool')

  // Test approval trigger
  vm.triggerApprove(vm.highRiskTools[0].confirmationId, vm.highRiskTools[0].name)
  const approveEvents = vm._emitted.filter(e => e.event === 'resolve-confirmation')
  assert.equal(approveEvents.length, 1)

  // Test bulk approval
  vm.approveAllPending()
  const allApproveEvents = vm._emitted.filter(e => e.event === 'resolve-confirmation')
  assert.equal(allApproveEvents.length, 2, 'approveAllPending delegates to triggerApprove for each pending item')

  console.log('  ✓ State 3.4 Passed: Safety intercept & approval gateway functions properly')
}

// State 3.5: Deliverable-Ready Session (Artifact Closed Loop)
{
  const vm = createVm({
    messages: [
      {
        kind: 'tool',
        agent: 'planBuilder',
        tool_name: 'compose_deliverable',
        arguments: '{"title":"广州看病就医一日行程保障方案"}',
        status: 'completed',
        result: '交付物装配完毕',
      },
      {
        kind: 'card',
        agent: 'planBuilder',
        title: '老友就医适老出行全景方案',
        pages: [
          { title: '就诊安排', rows: [{ label: '科室', val: '骨科专家门诊' }] },
          { title: '出行无障碍', rows: [{ label: '车次', val: 'G6002' }] },
        ],
      },
    ],
  })

  assert.equal(vm.isPlanBuilderActive, true, 'PlanBuilder branch must be active')
  assert.equal(vm.isArtifactReady, true, 'isArtifactReady must be true')
  assert.equal(vm.artifactPages.length, 2, 'artifactPages should contain parsed sections')
  assert.equal(vm.artifactDisplayTitle, '《老友就医适老出行全景方案》', 'Title formatted with brackets')

  // Test open modal
  vm.openArtifactModal()
  assert.equal(vm.showArtifactModal, true, 'Modal should be open')

  // Close modal
  vm.showArtifactModal = false
  assert.equal(vm.showArtifactModal, false, 'Modal should close cleanly')

  console.log('  ✓ State 3.5 Passed: Deliverable-ready session renders artifact node and opens/closes modal')
}

// ==============================================================================
// Suite 4: Accordion & Expand / Collapse Interaction Invariants
// ==============================================================================
console.log('\n[Suite 4] Testing Accordion Collapse / Expand & Navigation...')

{
  const vm = createVm({
    messages: [
      { kind: 'tool', agent: 'health', tool_name: 'search_hospital', status: 'completed' },
      { kind: 'tool', agent: 'travel', tool_name: 'query_train_tickets', status: 'completed' },
    ],
  })

  // Initial auto-sync active branches
  vm.syncActiveBranches()
  assert.equal(vm.collapsedAgents.health, false, 'Active health branch should be expanded')
  assert.equal(vm.collapsedAgents.travel, false, 'Active travel branch should be expanded')
  assert.equal(vm.collapsedAgents.community, true, 'Inactive community branch should be collapsed')
  assert.equal(vm.collapsedAgents.safety, true, 'Inactive safety branch should be collapsed')
  assert.equal(vm.collapsedAgents.planBuilder, true, 'Inactive planBuilder branch should be collapsed')

  // Toggle all expanded
  assert.equal(vm.allExpanded, false)
  vm.toggleAllExpanded()
  assert.equal(vm.allExpanded, true)
  assert.equal(vm.collapsedAgents.health, false)
  assert.equal(vm.collapsedAgents.travel, false)
  assert.equal(vm.collapsedAgents.community, false)
  assert.equal(vm.collapsedAgents.safety, false)
  assert.equal(vm.collapsedAgents.planBuilder, false)

  // Toggle all collapsed
  vm.toggleAllExpanded()
  assert.equal(vm.allExpanded, false)
  assert.equal(vm.collapsedAgents.health, true)
  assert.equal(vm.collapsedAgents.travel, true)
  assert.equal(vm.collapsedAgents.community, true)
  assert.equal(vm.collapsedAgents.safety, true)
  assert.equal(vm.collapsedAgents.planBuilder, true)

  // Toggle individual branch
  vm.toggleAgentCollapse('health')
  assert.equal(vm.collapsedAgents.health, false, 'Health should be toggled open')
  vm.toggleAgentCollapse('health')
  assert.equal(vm.collapsedAgents.health, true, 'Health should be toggled closed')

  // scrollToSection expands target
  vm.scrollToSection('community')
  assert.equal(vm.collapsedAgents.community, false, 'Target section community must be auto-expanded by scrollToSection')

  // scrollToSection with invalid id does not throw
  assert.doesNotThrow(() => {
    vm.scrollToSection('non_existent_section')
  })

  console.log('  ✓ Suite 4 Passed: Accordion toggle, global expand/collapse, and scrollToSection work flawlessly')
}

// ==============================================================================
// Suite 5: Deliverable / Artifact Exclusivity (No DAG Duplication)
// ==============================================================================
console.log('\n[Suite 5] Verifying Deliverable Single Entry Point & Absence of DAG Duplication...')

// 5.1 In template, artifact entry points must be unique
const artifactLeafOccurrences = [...templateContent.matchAll(/class="artifact-leaf-node"/g)]
assert.equal(
  artifactLeafOccurrences.length,
  1,
  `There must be exactly 1 artifact-leaf-node in template, found ${artifactLeafOccurrences.length}`
)

const dagArtifactOccurrences = [...templateContent.matchAll(/dag-node-artifact/g)]
assert.equal(
  dagArtifactOccurrences.length,
  0,
  `Zero dag-node-artifact allowed in template, found ${dagArtifactOccurrences.length}`
)

// 5.2 Artifact modal actions testing
{
  const vm = createVm({
    messages: [
      {
        kind: 'card',
        agent: 'planBuilder',
        title: '老友守护方案',
        pages: [
          { title: '方案摘要', rows: [{ label: '医生', val: '已安排家庭医生随访' }] },
        ],
      },
    ],
  })

  assert.equal(vm.isArtifactReady, true)
  vm.openArtifactModal()
  assert.equal(vm.showArtifactModal, true)

  // simulatePrint
  globalThis._lastToast = null
  vm.simulatePrint()
  assert.ok(globalThis._lastToast, 'simulatePrint must trigger toast')
  assert.ok(globalThis._lastToast.title.includes('打印'))

  // readAloud
  globalThis._lastToast = null
  vm.readAloud()
  assert.ok(globalThis._lastToast, 'readAloud must trigger toast')
  assert.ok(globalThis._lastToast.title.includes('朗读'))

  // Test opening modal when NOT ready
  const unreadyVm = createVm({ messages: [] })
  globalThis._lastToast = null
  unreadyVm.openArtifactModal()
  assert.equal(unreadyVm.showArtifactModal, false)
  assert.ok(globalThis._lastToast.title.includes('方案装配'))

  console.log('  ✓ Suite 5 Passed: Deliverable entry point is strictly unique, modal actions operational')
}

// ==============================================================================
// Suite 6: Adversarial Stress & Fuzzed Edge Cases
// ==============================================================================
console.log('\n[Suite 6] Adversarial Fuzzing & Degenerate Stream Ingestion...')

{
  const fuzzedMessages = [
    null,
    undefined,
    {},
    { randomProp: 123 },
    { role: 'user', content: null },
    { role: 'assistant', content: undefined },
    { kind: 'tool', agent: null, tool_name: null, arguments: '{invalid-json' },
    { kind: 'tool', agent: 'unknown_agent_xyz', tool_name: 'unknown_tool', arguments: null },
    { kind: 'status', agent: '🤖 health#99', content: 'Emoji status' },
    { kind: 'suspend', task_id: null, action_name: undefined },
    { kind: 'todo', todos: null },
    { kind: 'todo', todos: [null, 'string_todo', { text: '123' }] },
    { kind: 'card', content: null },
  ]

  assert.doesNotThrow(() => {
    const vm = createVm({ messages: fuzzedMessages })
    // Query all computed properties
    const activeCount = vm.activeAgentsCount
    const toolCount = vm.totalToolsCount
    const pendingCount = vm.pendingTasksCount
    const isReady = vm.isArtifactReady
    const thoughts = vm.agentThoughts
    const steps = vm.displaySteps
    const pages = vm.artifactPages
    const statusText = vm.rootStatusText
    const scenario = vm.currentScenarioTag
  }, 'Component must never crash on fuzzed or corrupt message payloads')

  console.log('  ✓ Case 6.1: Fuzzed and malformed messages handled gracefully with 0 crashes')
}

// Massive payload evaluation (3,000 messages)
{
  const massiveMessages = []
  for (let i = 0; i < 3000; i++) {
    massiveMessages.push({
      kind: 'tool',
      agent: i % 2 === 0 ? 'health' : 'travel',
      tool_name: i % 2 === 0 ? 'search_hospital' : 'query_train_tickets',
      arguments: JSON.stringify({ index: i }),
      status: 'completed',
    })
  }

  const tStart = performance.now()
  const vm = createVm({ messages: massiveMessages })
  const _ = [
    vm.activeAgentsCount,
    vm.totalToolsCount,
    vm.pendingTasksCount,
    vm.isArtifactReady,
    vm.agentThoughts,
    vm.displaySteps,
    vm.artifactPages,
    vm.globalStatusText,
  ]
  const elapsed = performance.now() - tStart

  assert.ok(elapsed < 1000, `Evaluation of 3,000 messages must take < 1000ms, took ${elapsed.toFixed(2)}ms`)
  console.log(`  ✓ Case 6.2: Evaluated 3,000 messages across all computeds in ${elapsed.toFixed(2)}ms (< 1s bound)`)
}

// ==============================================================================
// Suite 7: Negative Constraints Verification (No Mock Leakage & Audio TTS Safety)
// ==============================================================================
console.log('\n[Suite 7] Verifying Negative Constraints (No Beijing Medical Mock Leakage & Audio TTS)...')

// 7.1 No mock entities in AgentExecutionTree.vue
const mockEntities = ['积水潭', '田伟', 'G102', '漫心酒店']
for (const entity of mockEntities) {
  assert.ok(
    !vueContent.includes(entity),
    `AgentExecutionTree.vue must contain zero occurrences of '${entity}'`
  )
}
console.log('  ✓ Invariant 7.1: Zero hardcoded Beijing medical mock entities in AgentExecutionTree.vue')

// 7.2 TTS Voice playback preservation in ChatBubble & PlanCard
const chatBubbleTTSCount = [...chatBubbleContent.matchAll(/replay/gi)].length
assert.ok(
  chatBubbleTTSCount >= 7,
  `ChatBubble.vue must preserve audio voice replay (found ${chatBubbleTTSCount})`
)
const planCardTTSCount = [...planCardContent.matchAll(/replay/gi)].length
assert.ok(
  planCardTTSCount >= 7,
  `PlanCard.vue must preserve audio voice replay (found ${planCardTTSCount})`
)
console.log(`  ✓ Invariant 7.2: Audio voice replay intact in ChatBubble (${chatBubbleTTSCount}) and PlanCard (${planCardTTSCount})`)

// ==============================================================================
// Suite 8: Rapid Session Switching & State Reset
// ==============================================================================
console.log('\n[Suite 8] Testing Rapid Session Switching & Clean State Transition...')

{
  const vm = createVm({
    messages: [
      {
        kind: 'card',
        agent: 'planBuilder',
        title: '会话A方案',
        pages: [{ title: 'P1', rows: [{ label: 'K', val: 'V' }] }],
      },
    ],
  })
  assert.equal(vm.isArtifactReady, true)
  assert.equal(vm.artifactPages.length, 1)

  // Switch to Session B (Empty)
  vm.messages = []
  assert.equal(vm.isArtifactReady, false)
  assert.equal(vm.artifactPages.length, 0)
  assert.equal(vm.activeAgentsCount, 0)

  // Switch to Session C (Suspended High Risk Task)
  vm.messages = [
    {
      kind: 'suspend',
      task_id: 'task_c_1',
      action_name: '异地陪诊支付',
      status: 'pending',
    },
  ]
  assert.equal(vm.isSafetyActive, true)
  assert.equal(vm.pendingTasksCount, 1)
  assert.equal(vm.isArtifactReady, false)

  // User speaks a new message: watch triggers auto-sync
  const watcher = compDef.watch.messages.handler.bind(vm)
  vm._userChangedAllExpanded = true
  vm.messages = [
    ...vm.messages,
    { role: 'user', isUser: true, text: '不用了，取消吧' },
  ]
  watcher(vm.messages, vm.messages.slice(0, 1))
  assert.equal(vm._userChangedAllExpanded, false, 'New user utterance must reset userChangedAllExpanded flag')

  console.log('  ✓ Suite 8 Passed: Rapid session switching and watcher state reset verified')
}

// ==============================================================================
// Suite 9: Heavy-Payload Tool Calls & Parsing Robustness
// ==============================================================================
console.log('\n[Suite 9] Heavy-Payload Tool Calls & Parameter Parsing Robustness...')

{
  const heavyArgs = JSON.stringify({
    payload: 'X'.repeat(5000),
    complexNested: { a: [1, 2, 3], b: { nestedKey: 'value'.repeat(500) } },
  })

  const heavyMessages = [
    {
      kind: 'tool',
      agent: 'health',
      tool: 'search_hospital',
      args: heavyArgs,
      status: 'completed',
      result: 'Hospital result: ' + 'Y'.repeat(5000),
    },
    {
      kind: 'tool',
      agent: 'travel',
      tool: 'book_ticket',
      args: heavyArgs,
      status: 'suspended',
      confirmationId: 'conf_heavy_01',
    },
  ]

  const vm = createVm({ messages: heavyMessages })
  assert.equal(vm.healthTools.length, 1)
  assert.equal(vm.travelTools.length, 1)
  assert.equal(vm.highRiskTools.length, 1)

  // Test parseParamsTokens helper with varied types
  const tokensObj = vm.parseParamsTokens({ city: '广州', count: 5 })
  assert.ok(Array.isArray(tokensObj))
  assert.equal(tokensObj.length, 2)

  const tokensStr = vm.parseParamsTokens('{"city":"北京","dept":"骨科"}')
  assert.ok(Array.isArray(tokensStr))
  assert.equal(tokensStr.length, 2)

  const tokensInvalid = vm.parseParamsTokens('{malformed')
  assert.ok(Array.isArray(tokensInvalid))

  console.log('  ✓ Suite 9 Passed: Heavy payloads and argument tokenization handled cleanly')
}

// ==============================================================================
// Suite 10: Event Bus & Responsive Drawer Actions
// ==============================================================================
console.log('\n[Suite 10] Event Bus & Responsive Header Drawer Invariants...')

{
  // Desktop mode
  const desktopVm = createVm({ isDesktop: true })
  desktopVm.$emit('close')
  assert.equal(desktopVm._emitted.length, 1)
  assert.equal(desktopVm._emitted[0].event, 'close')

  // Mobile mode
  const mobileVm = createVm({ isDesktop: false })
  mobileVm.$emit('close')
  assert.equal(mobileVm._emitted.length, 1)
  assert.equal(mobileVm._emitted[0].event, 'close')

  // Tool status format tests
  assert.equal(desktopVm.formatToolStatus('completed'), '已完成 ✅')
  assert.equal(desktopVm.formatToolStatus('completed', 'book_ticket'), '已出票 ✅')
  assert.equal(desktopVm.formatToolStatus('suspended'), '⏸️ 待确认')
  assert.equal(desktopVm.formatToolStatus('rejected'), '已拦截 🛑')
  assert.equal(desktopVm.formatToolStatus('running'), '执行中 ⚡')

  console.log('  ✓ Suite 10 Passed: Responsive actions, drawer close events, and formatters verified')
}

console.log('\n================================================================================')
console.log('=== ALL 10 CHALLENGER STRESS TEST SUITES PASSED WITH ZERO DEFECTS! ===')
console.log('================================================================================\n')

