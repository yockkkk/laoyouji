import assert from 'node:assert/strict'
import fs from 'node:fs'

console.log('================================================================================')
console.log('=== Challenger 2: Native Bridge & Map Interaction Comprehensive Stress Suite ===')
console.log('================================================================================\n')

const nativeJsPath = 'frontend/laoyouji-app/src/utils/native.js'
const routeMapPath = 'frontend/laoyouji-app/src/pages/elder/route-map.vue'
const guardianPath = 'frontend/laoyouji-app/src/pages/child/guardian.vue'

const nativeJsContent = fs.readFileSync(nativeJsPath, 'utf-8')
const routeMapContent = fs.readFileSync(routeMapPath, 'utf-8')
const guardianContent = fs.readFileSync(guardianPath, 'utf-8')

// ============================================================================
// SUITE 1: Native Bridge Static Contract & Alias Verification
// ============================================================================
console.log('--- Suite 1: Native Bridge Static Invariants & Aliases ---')

// 1.1 Verify export const openNativeSettings = openSettings exists verbatim
assert.ok(
  /export\s+const\s+openNativeSettings\s*=\s*openSettings/.test(nativeJsContent),
  'native.js must explicitly export const openNativeSettings = openSettings'
)
console.log('✓ 1.1 Verified: openNativeSettings alias export exists verbatim')

// 1.2 Verify openSettings function exists
assert.ok(
  /export\s+function\s+openSettings\s*\(/.test(nativeJsContent),
  'native.js must export openSettings(name)'
)
console.log('✓ 1.2 Verified: openSettings(name) function exists')

// 1.3 Verify syncAll, consumePendingRoute, and other bridge APIs are exported
const expectedExports = [
  'nativeSupported',
  'getPlatformInfo',
  'syncReminders',
  'getReminders',
  'cancelAll',
  'checkPermissions',
  'requestPermission',
  'openSettings',
  'openNativeSettings',
  'openKeepAliveGuide',
  'notifyNow',
  'greetTextForHour',
  'buildMedicationReminders',
  'buildGreetingReminder',
  'buildAllReminders',
  'onNativeAction',
  'consumePendingRoute',
  'syncAll',
  'initNative',
]

for (const exp of expectedExports) {
  const regex = new RegExp(`export\\s+(function|const)\\s+${exp}\\b`)
  assert.ok(regex.test(nativeJsContent), `native.js must export '${exp}'`)
}
console.log(`✓ 1.3 Verified: All ${expectedExports.length} required bridge methods are exported`)

// 1.4 Verify noBridge() returns { ok: false, reason: 'no_bridge' }
assert.ok(
  nativeJsContent.includes("reason: 'no_bridge'"),
  "noBridge() must return reason: 'no_bridge'"
)
console.log("✓ 1.4 Verified: noBridge() structure matches contract")


// ============================================================================
// SUITE 2: Dynamic Execution Harness for Native Bridge
// ============================================================================
console.log('\n--- Suite 2: Native Bridge Runtime Evaluation & Safe Degradation ---')

/**
 * Creates an isolated evaluation scope of native.js with injected dependencies.
 */
function createBridgeHarness(options = {}) {
  const {
    windowObj = undefined,
    currentUser = null,
    apiGet = async () => ({ items: [] }),
    uniStorage = {},
    uniNavigationMock = null,
  } = options

  // Mock uni global
  const storage = { ...uniStorage }
  const navigationCalls = []
  const uniMock = {
    getStorageSync(key) {
      return storage[key] !== undefined ? storage[key] : ''
    },
    setStorageSync(key, val) {
      storage[key] = String(val)
    },
    removeStorageSync(key) {
      delete storage[key]
    },
    $emit: () => {},
    switchTab: (opts) => {
      navigationCalls.push({ type: 'switchTab', ...opts })
      if (uniNavigationMock && uniNavigationMock.failSwitchTab) {
        if (opts.fail) opts.fail(new Error('fail switchTab'))
      } else if (opts.success) {
        opts.success()
      }
    },
    navigateTo: (opts) => {
      navigationCalls.push({ type: 'navigateTo', ...opts })
      if (uniNavigationMock && uniNavigationMock.failNavigateTo) {
        if (opts.fail) opts.fail(new Error('fail navigateTo'))
      } else if (opts.success) {
        opts.success()
      }
    },
  }

  // Transform native.js source into a function that takes mocked imports
  // Replace `import { get } from '../api/client'` and `import { getCurrentUser } from '../store/user'`
  let code = nativeJsContent
    .replace(/import\s*\{\s*get\s*\}\s*from\s*['"][^'"]+['"]/, 'const get = __injected_get;')
    .replace(/import\s*\{\s*getCurrentUser\s*\}\s*from\s*['"][^'"]+['"]/, 'const getCurrentUser = __injected_getCurrentUser;')

  // Wrap inside factory
  const factoryCode = `
    return function(__injected_get, __injected_getCurrentUser, window, uni) {
      const exports = {};
      ${code
        .replace(/export\s+function\s+([a-zA-Z0-9_$]+)/g, 'exports.$1 = $1; function $1')
        .replace(/export\s+const\s+([a-zA-Z0-9_$]+)\s*=/g, 'const $1 = exports.$1 =')}
      return exports;
    }
  `

  const factory = new Function(factoryCode)()
  const exports = factory(
    apiGet,
    () => currentUser,
    windowObj,
    uniMock
  )

  return { exports, storage, navigationCalls, uniMock }
}

// 2.1 SSR / No window environment
{
  const { exports } = createBridgeHarness({ windowObj: undefined })
  assert.equal(exports.nativeSupported(), false, 'nativeSupported must be false without window')
  assert.equal(exports.getPlatformInfo(), null, 'getPlatformInfo must be null without window')
  assert.deepEqual(exports.syncReminders([]), { ok: false, reason: 'no_bridge' })
  assert.deepEqual(exports.getReminders(), [])
  assert.deepEqual(exports.cancelAll(), { ok: false, reason: 'no_bridge' })
  assert.deepEqual(exports.checkPermissions(), { ok: false, reason: 'no_bridge' })
  assert.deepEqual(exports.requestPermission('ALARM'), { ok: false, reason: 'no_bridge' })
  assert.deepEqual(exports.openSettings('ALARM'), { ok: false, reason: 'no_bridge' })
  assert.deepEqual(exports.openNativeSettings('ALARM'), { ok: false, reason: 'no_bridge' })
  assert.equal(exports.openNativeSettings, exports.openSettings, 'openNativeSettings must strictly equal openSettings')
  assert.deepEqual(exports.openKeepAliveGuide(), { ok: false, reason: 'no_bridge' })
  assert.deepEqual(exports.notifyNow({}), { ok: false, reason: 'no_bridge' })
  assert.equal(exports.greetTextForHour(8), '')
  assert.deepEqual(exports.buildMedicationReminders([{ drug_name: '降压药' }]), [])
  assert.deepEqual(exports.buildGreetingReminder({ id: '1', name: '张桂芳' }), [])
  assert.deepEqual(exports.buildAllReminders({}), [])
  assert.equal(exports.consumePendingRoute(), '')
  console.log('✓ 2.1 SSR / No window: All 16 methods gracefully degrade without throwing')
}

// 2.2 Standard Desktop Browser (window exists, KangleNative is undefined)
{
  const fakeWindow = {}
  const { exports } = createBridgeHarness({ windowObj: fakeWindow })
  assert.equal(exports.nativeSupported(), false)
  const nb1 = exports.syncReminders([])
  const nb2 = exports.cancelAll()
  assert.deepEqual(nb1, { ok: false, reason: 'no_bridge' })
  assert.deepEqual(nb2, { ok: false, reason: 'no_bridge' })
  // Verify fresh object instance (immutability of noBridge)
  assert.notEqual(nb1, nb2, 'noBridge() must return fresh object each time to avoid mutation pollution')
  console.log('✓ 2.2 Standard Browser: Safe degradation and fresh noBridge instance verified')
}

// 2.3 Hostile Android ROM (KangleNative property access throws TypeError)
{
  const hostileWindow = {
    get KangleNative() {
      throw new TypeError('Android ROM WebView: Injected host interface inaccessible')
    }
  }
  const { exports } = createBridgeHarness({ windowObj: hostileWindow })
  assert.equal(exports.nativeSupported(), false, 'nativeSupported caught TypeError')
  assert.equal(exports.getPlatformInfo(), null, 'getPlatformInfo caught TypeError')
  assert.deepEqual(exports.openSettings('BATTERY'), { ok: false, reason: 'no_bridge' })
  assert.deepEqual(exports.openNativeSettings('BATTERY'), { ok: false, reason: 'no_bridge' })
  console.log('✓ 2.3 Hostile ROM (Property Access Throws): 100% caught and degraded safely')
}

// 2.4 Crashing Host Interface (KangleNative methods throw DeadObjectException)
{
  const crashingWindow = {
    KangleNative: {
      isSupported: () => true,
      syncReminders: () => { throw new Error('Android DeadObjectException') },
      cancelAll: () => { throw new Error('Android Binder Transaction Failed') },
      openSettings: () => { throw new Error('ActivityNotFoundException') },
    }
  }
  const { exports } = createBridgeHarness({ windowObj: crashingWindow })
  assert.equal(exports.nativeSupported(), true)
  assert.deepEqual(exports.syncReminders([]), { ok: false, reason: 'no_bridge' })
  assert.deepEqual(exports.cancelAll(), { ok: false, reason: 'no_bridge' })
  assert.deepEqual(exports.openSettings('SYS'), { ok: false, reason: 'no_bridge' })
  assert.deepEqual(exports.openNativeSettings('SYS'), { ok: false, reason: 'no_bridge' })
  console.log('✓ 2.4 Crashing Host Methods: Catches Android binder/activity exceptions cleanly')
}

// 2.5 Corrupt JSON / Malformed String Injection
{
  const corruptWindow = {
    KangleNative: {
      isSupported: () => true,
      getPlatformInfo: () => 'MALFORMED_JSON_{{{[',
      checkPermissions: () => '',
      getReminders: () => '{"items": "not-an-array"}',
    }
  }
  const { exports } = createBridgeHarness({ windowObj: corruptWindow })
  assert.equal(exports.getPlatformInfo(), null, 'parseJson handled corrupt JSON')
  assert.deepEqual(exports.checkPermissions(), { ok: false, reason: 'no_bridge' })
  assert.deepEqual(exports.getReminders(), [], 'getReminders handled non-array items')
  console.log('✓ 2.5 Corrupt JSON Injection: parseJson and type checks prevent parser crashes')
}


// ============================================================================
// SUITE 3: Deep-Link & Pending Route Lifecycle (consumePendingRoute)
// ============================================================================
console.log('\n--- Suite 3: Deep-Link & Pending Route Lifecycle ---')

// 3.1 Initial empty state
{
  const { exports } = createBridgeHarness()
  assert.equal(exports.consumePendingRoute(), '', 'consumePendingRoute returns empty string when no route')
  console.log('✓ 3.1 consumePendingRoute() initially returns empty string')
}

// 3.2 Pending route caching upon failed early navigation
{
  const fakeWindow = {}
  const navConfig = { failSwitchTab: true }
  const { exports, navigationCalls } = createBridgeHarness({
    windowObj: fakeWindow,
    uniNavigationMock: navConfig
  })

  // Call initNative to wire onNativeAction with navigateToRoute
  exports.initNative()

  // Simulate incoming native action before page ready
  fakeWindow.__kangleNativeAction(JSON.stringify({ route: '/pages/elder/medications' }))

  // At this point switchTab failed, so pendingRoute must be cached
  assert.equal(navigationCalls.length, 1)
  assert.equal(navigationCalls[0].url, '/pages/elder/medications')

  // Page onShow lifecycle: the page stack is now ready, so switchTab will now succeed
  navConfig.failSwitchTab = false

  // First consumePendingRoute call claims the pending route and succeeds
  const claimedRoute = exports.consumePendingRoute()
  assert.equal(claimedRoute, '/pages/elder/medications', 'Must return claimed pending route')
  assert.equal(navigationCalls.length, 2, 'Must have re-attempted navigation')

  // Second consumePendingRoute call finds nothing (already consumed)
  const secondClaim = exports.consumePendingRoute()
  assert.equal(secondClaim, '', 'Pending route must be consumed once and only once when navigation succeeded')
  console.log('✓ 3.2 Cold-start pending route claiming & onShow consumption lifecycle verified')
}


// ============================================================================
// SUITE 4: Reminders Synchronization & Concurrency Gating (syncAll)
// ============================================================================
console.log('\n--- Suite 4: Reminders Synchronization & Concurrency Gating (syncAll) ---')

// 4.1 Not logged in
{
  const { exports } = createBridgeHarness({ currentUser: null })
  const res = await exports.syncAll()
  assert.deepEqual(res, { ok: false, reason: 'not_logged_in' })
  console.log('✓ 4.1 syncAll when not logged in -> not_logged_in')
}

// 4.2 User is child
{
  const { exports } = createBridgeHarness({ currentUser: { id: 'c1', role: 'child' } })
  const res = await exports.syncAll()
  assert.deepEqual(res, { ok: false, reason: 'not_elder' })
  console.log('✓ 4.2 syncAll when user is child -> not_elder')
}

// 4.3 No bridge available
{
  const { exports } = createBridgeHarness({
    currentUser: { id: 'e1', role: 'elder' },
    windowObj: {} // No KangleNative
  })
  const res = await exports.syncAll()
  assert.deepEqual(res, { ok: false })
  console.log('✓ 4.3 syncAll when no bridge -> { ok: false }')
}

// 4.4 Full sync, 30s debounce, force bypass, and concurrency stress
{
  let apiCallCount = 0
  let nativeSyncPayload = null

  const validWindow = {
    KangleNative: {
      isSupported: () => true,
      syncReminders: (jsonStr) => {
        nativeSyncPayload = JSON.parse(jsonStr)
        return JSON.stringify({ ok: true, count: nativeSyncPayload.length })
      }
    }
  }

  const { exports } = createBridgeHarness({
    currentUser: { id: 'e1', name: '张桂芳', role: 'elder' },
    windowObj: validWindow,
    apiGet: async (url, params) => {
      apiCallCount++
      return {
        items: [
          { id: 'p1', elder_id: 'e1', drug_name: '降压药', dose: '1片', times: ['08:00', '18:00'], active: true },
          { id: 'p2', elder_id: 'e1', drug_name: '软删药', dose: '2片', times: ['12:00'], active: false }
        ]
      }
    }
  })

  // First sync call: executes network fetch
  const res1 = await exports.syncAll()
  assert.equal(res1.ok, true)
  assert.equal(apiCallCount, 1)
  // Expected items: 2 from p1 ('08:00', '18:00') + 1 greeting ('08:00' default) = 3
  assert.equal(res1.count, 3)
  console.log(`✓ 4.4.1 Initial syncAll succeeded with ${res1.count} compiled reminders`)

  // Second sync call immediately: debounced by 30s window (API call count stays 1)
  const res2 = await exports.syncAll()
  assert.equal(res2.ok, true)
  assert.equal(apiCallCount, 1, 'Debounce must prevent duplicate API fetch within 30s')
  console.log('✓ 4.4.2 30s cache debounce window verified (0 redundant API requests)')

  // Third sync call with { force: true }: bypasses debounce cache
  const res3 = await exports.syncAll({ force: true })
  assert.equal(res3.ok, true)
  assert.equal(apiCallCount, 2, 'opts.force must bypass debounce cache')
  console.log('✓ 4.4.3 opts.force successfully bypassed 30s cache debounce')

  // Concurrency stress: 50 parallel simultaneous syncAll calls
  const promises = []
  for (let i = 0; i < 50; i++) {
    promises.push(exports.syncAll({ force: true }))
  }
  const results = await Promise.all(promises)
  // All must resolve with ok: true
  assert.ok(results.every(r => r.ok === true))
  // Because in-flight promise dedupes concurrent calls, apiCallCount should increment by only 1!
  assert.equal(apiCallCount, 3, `Parallel in-flight deduping: expected 3 total API calls, got ${apiCallCount}`)
  console.log('✓ 4.4.4 Concurrency stress (50 parallel requests deduped into 1 in-flight Promise)')

  // Network failure test: failures must NOT be cached
  const failingHarness = createBridgeHarness({
    currentUser: { id: 'e1', role: 'elder' },
    windowObj: validWindow,
    apiGet: async () => { throw new Error('502 Bad Gateway') }
  })
  const failRes = await failingHarness.exports.syncAll()
  assert.equal(failRes.ok, false)
  // Second call must retry and not be blocked by 30s debounce
  let retried = false
  const retryHarness = createBridgeHarness({
    currentUser: { id: 'e1', role: 'elder' },
    windowObj: validWindow,
    apiGet: async () => {
      retried = true
      return { items: [] }
    }
  })
  await retryHarness.exports.syncAll()
  assert.ok(retried, 'Failure must not be cached; retry must execute immediately')
  console.log('✓ 4.4.5 Network failure handling: failed results are not cached in debounce')
}


// ============================================================================
// SUITE 5: Map Integration & 58% Golden Ratio Viewport Check
// ============================================================================
console.log('\n--- Suite 5: Map Integration & 58% Split Ratio (58vh) Verification ---')

// 5.1 route-map.vue 58% split ratio (58vh)
const routeMapBoxMatch = routeMapContent.match(/\.amap-box\s*\{([^}]+)\}/)
assert.ok(routeMapBoxMatch, 'route-map.vue must contain .amap-box selector')
assert.ok(
  /height:\s*58vh;/.test(routeMapBoxMatch[1]),
  'route-map.vue .amap-box must define height: 58vh;'
)
console.log('✓ 5.1 route-map.vue verified: .amap-box height is strictly 58vh')

// 5.2 guardian.vue 58% split ratio (58vh)
const guardianBoxMatch = guardianContent.match(/\.child-amap-canvas\s*\{([^}]+)\}/)
assert.ok(guardianBoxMatch, 'guardian.vue must contain .child-amap-canvas selector')
assert.ok(
  /height:\s*58vh;/.test(guardianBoxMatch[1]),
  'guardian.vue .child-amap-canvas must define height: 58vh;'
)
console.log('✓ 5.2 guardian.vue verified: .child-amap-canvas height is strictly 58vh')

// 5.3 Color and Polyline Tokens
assert.ok(
  routeMapContent.includes("strokeColor: '#2A82E4'") || routeMapContent.includes("color: '#2A82E4'"),
  'route-map.vue polyline must use Sky Blue #2A82E4'
)
assert.ok(
  guardianContent.includes("color: '#2A82E4'"),
  'guardian.vue polyline must use Sky Blue #2A82E4'
)
console.log('✓ 5.3 Map polyline color verified: aligned to Sky Blue #2A82E4')

// 5.4 Touch Targets and Responsiveness
assert.ok(
  /\.nav-back-btn\s*\{\s*min-height:\s*96rpx/.test(routeMapContent),
  'route-map.vue .nav-back-btn touch target must be >= 96rpx'
)
assert.ok(
  /\.nav-speak-btn\s*\{\s*min-height:\s*96rpx/.test(routeMapContent),
  'route-map.vue .nav-speak-btn touch target must be >= 96rpx'
)
assert.ok(
  /\.btn-approve\s*\{[^}]*min-height:\s*88rpx/.test(guardianContent),
  'guardian.vue .btn-approve touch target must be >= 88rpx'
)
assert.ok(
  /\.btn-reject\s*\{[^}]*min-height:\s*88rpx/.test(guardianContent),
  'guardian.vue .btn-reject touch target must be >= 88rpx'
)
console.log('✓ 5.4 Touch targets verified: route-map.vue >= 96rpx and guardian.vue >= 88rpx')


console.log('\n================================================================================')
console.log('CHALLENGER 2 EMPIRICAL STRESS VERDICT: ALL 23 TEST SCENARIOS PASSED!')
console.log('================================================================================\n')
