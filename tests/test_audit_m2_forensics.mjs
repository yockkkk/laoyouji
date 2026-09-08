import fs from 'node:fs'
import assert from 'node:assert'
import path from 'node:path'

const vuePath = path.resolve('frontend/laoyouji-app/src/components/AgentExecutionTree.vue')
const vueContent = fs.readFileSync(vuePath, 'utf8')

console.log('=== Milestone 2 Forensic Integrity Check ===\n')

// 1. Check genuine removal of planning-dag-card and .dag-* styles
console.log('[Check 1] Verify planning-dag-card and .dag-* complete absence...')
const dagClassMatches = vueContent.match(/\.dag-[\w-]+|planning-dag-card|dag-node|dag-canvas/gi)
assert.strictEqual(dagClassMatches, null, 'Found DAG classes in AgentExecutionTree.vue: ' + JSON.stringify(dagClassMatches))

// Check case-insensitive \bdag\b
const dagWordMatches = vueContent.match(/\bdag\b/gi)
assert.strictEqual(dagWordMatches, null, 'Found word "dag" in AgentExecutionTree.vue: ' + JSON.stringify(dagWordMatches))
console.log('  ✓ PASS: Zero DAG elements, classes, styles, or comments found.\n')

// 2. Verify no facade / CSS hiding techniques (opacity: 0, visibility: hidden, display: none on dag)
console.log('[Check 2] Verify no facade / hidden CSS rules...')
assert.ok(!vueContent.includes('.planning-dag-card { display: none'), 'Must not hide via display: none')
assert.ok(!vueContent.includes('.planning-dag-card { opacity: 0'), 'Must not hide via opacity: 0')
assert.ok(!vueContent.includes('.planning-dag-card { visibility: hidden'), 'Must not hide via visibility: hidden')
console.log('  ✓ PASS: No facade or hidden CSS tricks.\n')

// 3. Verify .artifact-avatar and artifact-leaf-node are genuine components and not degraded
console.log('[Check 3] Verify .artifact-avatar and artifact-leaf-node genuine preservation...')
assert.ok(vueContent.includes('artifact-leaf-node'), 'artifact-leaf-node class must exist in template')
assert.ok(vueContent.includes('.artifact-leaf-node'), 'artifact-leaf-node style must exist in CSS')
assert.ok(vueContent.includes('.artifact-avatar'), '.artifact-avatar style must exist in CSS')
assert.ok(vueContent.includes('isArtifactReady'), 'isArtifactReady must exist')
assert.ok(vueContent.includes('openArtifactModal'), 'openArtifactModal must exist')
assert.ok(vueContent.includes('artifactPages'), 'artifactPages must exist')
assert.ok(vueContent.includes('artifactDisplayTitle'), 'artifactDisplayTitle must exist')
assert.ok(vueContent.includes('artifactDisplaySubtitle'), 'artifactDisplaySubtitle must exist')

// Verify artifact modal structure exists
assert.ok(vueContent.includes('artifact-modal-mask'), 'artifact-modal-mask must exist')
assert.ok(vueContent.includes('artifact-modal-body'), 'artifact-modal-body must exist')
assert.ok(vueContent.includes('plan-page-card'), 'plan-page-card must exist in modal')
console.log('  ✓ PASS: Artifact components and styles are fully genuine and intact.\n')

// 4. Verify Header buttons converged to exactly 3 buttons
console.log('[Check 4] Verify header buttons convergence...')
const headerMatch = vueContent.match(/<view class="header-right">([\s\S]*?)<\/view>\s*<\/view>/)
assert.ok(headerMatch, 'Header right container must exist')
const headerRightText = headerMatch[1]
const buttonCount = (headerRightText.match(/<button\b/g) || []).length
assert.strictEqual(buttonCount, 3, 'Header must contain exactly 3 buttons (expand/collapse, desktop close, mobile close)')
assert.ok(headerRightText.includes('toggleAllExpanded'), 'Header must contain toggleAllExpanded button')
assert.ok(headerRightText.includes('isDesktop'), 'Header must contain desktop close condition')
assert.ok(headerRightText.includes('!isDesktop'), 'Header must contain mobile close condition')
assert.ok(!headerRightText.includes('replay'), 'Header must NOT contain replay button')
console.log('  ✓ PASS: Exactly 3 header buttons verified (allExpanded, desktop close, mobile close).\n')

// 5. Verify Critical Preserved Computeds: hasTaskStarted, isArtifactReady, pendingTasksCount
console.log('[Check 5] Verify preserved computed properties...')
const scriptMatch = vueContent.match(/<script>([\s\S]*?)<\/script>/)
assert.ok(scriptMatch, 'Script block must exist')
const script = scriptMatch[1]

assert.ok(/hasTaskStarted\s*\(\)\s*\{/.test(script), 'hasTaskStarted computed must exist')
assert.ok(/isArtifactReady\s*\(\)\s*\{/.test(script), 'isArtifactReady computed must exist')
assert.ok(/pendingTasksCount\s*\(\)\s*\{/.test(script), 'pendingTasksCount computed must exist')
console.log('  ✓ PASS: hasTaskStarted, isArtifactReady, and pendingTasksCount are fully preserved.\n')

// 6. Verify Zero Mock Data / Beijing Medical hardcoded text
console.log('[Check 6] Verify zero mock data / Beijing medical references...')
const forbiddenKeywords = ['积水潭', '田伟', 'G102', '漫心酒店']
for (const kw of forbiddenKeywords) {
  assert.ok(!vueContent.includes(kw), `Forbidden keyword "${kw}" must not appear in AgentExecutionTree.vue`)
}
console.log('  ✓ PASS: No Beijing medical mock data found in AgentExecutionTree.vue.\n')

// 7. Verify Component Behavior Execution with Vue object
console.log('[Check 7] Verify dynamic behavior on Vue component object...')
const compObjText = script.substring(script.indexOf('export default {')).replace('export default ', '')
const compDef = eval('(' + compObjText + ')')

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

  for (const [compName, compVal] of Object.entries(compDef.computed)) {
    if (typeof compVal === 'function') {
      Object.defineProperty(vm, compName, {
        get: compVal.bind(vm),
        enumerable: true,
        configurable: true,
      })
    } else if (compVal && compVal.get) {
      Object.defineProperty(vm, compName, {
        get: compVal.get.bind(vm),
        set: compVal.set ? compVal.set.bind(vm) : undefined,
        enumerable: true,
        configurable: true,
      })
    }
  }

  return vm
}

const vmEmpty = createTreeInstance({ messages: [], thinking: false })

// Verify empty state behavior
assert.strictEqual(vmEmpty.hasTaskStarted, false)
assert.strictEqual(vmEmpty.isArtifactReady, false)
assert.strictEqual(vmEmpty.pendingTasksCount, 0)
assert.strictEqual(vmEmpty.artifactPages.length, 0)
assert.strictEqual(vmEmpty.artifactDisplayTitle, '《智能协同服务交付物》')

// Verify artifact ready state when card is delivered
const vmCard = createTreeInstance({
  messages: [
    { kind: 'user', content: '帮我买包降压药' },
    { kind: 'card', title: '降压药代购计划书', sections: [{ heading: '药品明细', rows: [{ k: '名称', v: '氨氯地平' }] }] }
  ],
  thinking: false
})
assert.strictEqual(vmCard.hasTaskStarted, true)
assert.strictEqual(vmCard.isArtifactReady, true)
assert.strictEqual(vmCard.artifactDisplayTitle, '《降压药代购计划书》')
assert.strictEqual(vmCard.artifactPages.length, 1)
assert.strictEqual(vmCard.artifactPages[0].title, '药品明细')
console.log('  ✓ PASS: Dynamic computed state behaves genuinely without mock data.\n')

// 8. Adversarial Stress Testing
console.log('[Check 8] Adversarial Stress Testing on Milestone 2 Invariants...')

// Stress 8.1: Malformed and corrupted messages array
const vmCorrupt = createTreeInstance({
  messages: [null, undefined, 123, 'random string', {}, { kind: null }, { kind: 'card' }],
  thinking: false
})
assert.doesNotThrow(() => vmCorrupt.hasTaskStarted)
assert.doesNotThrow(() => vmCorrupt.isArtifactReady)
assert.doesNotThrow(() => vmCorrupt.artifactDisplayTitle)
assert.doesNotThrow(() => vmCorrupt.artifactPages)
assert.strictEqual(vmCorrupt.isArtifactReady, true) // card exists
assert.strictEqual(vmCorrupt.artifactDisplayTitle, '《长辈生活智能助理交付方案》') // dynamic scenario-derived title
assert.strictEqual(vmCorrupt.artifactPages.length, 0)
console.log('  ✓ PASS: Corrupted messages handled safely without unhandled exceptions.')

// Stress 8.2: Mixed Rejection & Approval (Artifact must NOT be ready if rejected)
const vmMixed = createTreeInstance({
  messages: [
    { kind: 'suspend', tool: 'high_risk_op', status: 'completed' },
    { kind: 'suspend', tool: 'another_op', status: 'rejected' }
  ],
  thinking: false
})
assert.strictEqual(vmMixed.hasAnyRejected, true)
assert.strictEqual(vmMixed.isArtifactReady, false, 'Artifact must not be ready when any step is rejected')
assert.strictEqual(vmMixed.planBuilderStatusText, '前序审批已拒绝 · 装配终止')
console.log('  ✓ PASS: Safety rejection correctly aborts artifact readiness and locks assembly.')

// Stress 8.3: Toast feedback on unready artifact modal open
let toastShown = null
globalThis.uni = {
  showToast: (opts) => { toastShown = opts }
}
const vmUnready = createTreeInstance({ messages: [], thinking: false })
vmUnready.openArtifactModal()
assert.ok(toastShown && toastShown.title.includes('尚未完成方案装配'), 'Unready artifact open must show toast warning')
assert.strictEqual(vmUnready.showArtifactModal, false, 'Modal mask must remain closed when unready')
console.log('  ✓ PASS: openArtifactModal rejects unready access safely.')

// Stress 8.4: Ready modal opens cleanly
vmCard.openArtifactModal()
assert.strictEqual(vmCard.showArtifactModal, true, 'Modal opens when artifact is ready')
console.log('  ✓ PASS: openArtifactModal opens cleanly when artifact is ready.')

console.log('\n===================================================')
console.log('FORENSIC VERDICT: ALL AUDIT CHECKS EMPIRICALLY PASSED!')
console.log('===================================================')
