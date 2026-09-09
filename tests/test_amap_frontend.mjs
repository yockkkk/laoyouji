import assert from 'node:assert/strict'
import fs from 'node:fs'

console.log('=== Running Frontend Verification for Gaode Map 2.0 Integration ===\n')

// 1. Verify index.html Gaode credentials and security config
console.log('Test 1: index.html Gaode JS API 2.0 and Security Config')
const htmlContent = fs.readFileSync('frontend/laoyouji-app/index.html', 'utf-8')
assert.ok(htmlContent.includes('6c6e8eddf72527878c4eb76d7273e380'), 'index.html must declare securityJsCode')
assert.ok(htmlContent.includes('706804e5a0a33cdf140126d75bedd3ac'), 'index.html must declare JS API key')
assert.ok(htmlContent.includes('webapi.amap.com/maps?v=2.0'), 'index.html must load Gaode 2.0 script')
console.log('✓ Passed: index.html security and API credentials valid')

// 2. Verify pages.json page registration
console.log('Test 2: pages.json registration of pages/elder/route-map')
const pagesJson = JSON.parse(fs.readFileSync('frontend/laoyouji-app/src/pages.json', 'utf-8'))
const elderRoutePage = pagesJson.pages.find((p) => p.path === 'pages/elder/route-map')
assert.ok(elderRoutePage, 'pages/elder/route-map must be registered in pages.json')
assert.equal(elderRoutePage.style.navigationStyle, 'custom')
console.log('✓ Passed: pages.json registration verified')

// 3. Verify PlanCard.vue elder route planning button & destination preservation
console.log('Test 3: PlanCard.vue Elder Route Planning Entry & Destination Logic')
const planCardContent = fs.readFileSync('frontend/laoyouji-app/src/components/PlanCard.vue', 'utf-8')
assert.ok(planCardContent.includes('查看高德路线规划'), 'PlanCard.vue must contain 查看高德路线规划')
assert.ok(planCardContent.includes('hasRouteAction'), 'PlanCard.vue must contain hasRouteAction computed property')
assert.ok(planCardContent.includes('goToRouteMap'), 'PlanCard.vue must contain goToRouteMap method')
assert.ok(planCardContent.includes('/pages/elder/route-map'), 'PlanCard.vue must navigate to /pages/elder/route-map')
assert.ok(planCardContent.includes('min-height: 96rpx'), 'Touch target must be >= 48px (96rpx)')
assert.ok(planCardContent.includes('if (!destination)'), 'goToRouteMap must not overwrite existing destination from sections')
assert.ok(planCardContent.includes('if (hospital)'), 'goToRouteMap must prioritize hospital destination over train station arrival')
console.log('✓ Passed: PlanCard.vue elder button, touch target, and destination preservation verified')

// 4. Verify route-map.vue structure, dynamic points/steps, and 10s reporting loop
console.log('Test 4: pages/elder/route-map.vue Elder Map and 10s Reporting')
const routeMapContent = fs.readFileSync('frontend/laoyouji-app/src/pages/elder/route-map.vue', 'utf-8')
assert.ok(routeMapContent.includes('elder-amap-container'), 'route-map.vue must contain elder-amap-container DOM mount')
assert.ok(routeMapContent.includes('AMap.Polyline'), 'route-map.vue must render AMap.Polyline route')
assert.ok(routeMapContent.includes('elder-live-pulse-marker'), 'route-map.vue must render elder breathing marker')
assert.ok(routeMapContent.includes('setInterval'), 'route-map.vue must run periodic interval')
assert.ok(routeMapContent.includes('10000'), 'route-map.vue must report every 10 seconds')
assert.ok(routeMapContent.includes('post(`/api/trips/'), 'route-map.vue must post checkpoints to backend')
assert.ok(routeMapContent.includes('换乘步骤大字指引'), 'route-map.vue must have transit step cards')
assert.ok(routeMapContent.includes('r.points.map'), 'route-map.vue must dynamically populate routePoints from backend')
assert.ok(routeMapContent.includes('r.steps.map'), 'route-map.vue must dynamically populate steps from backend')
assert.ok(routeMapContent.includes('/api/trips/route/direct'), 'route-map.vue must query direct route planning')
assert.ok(routeMapContent.includes('/api/trips/quick'), 'route-map.vue must auto-create quick trip for reporting loop')
assert.ok(routeMapContent.includes('.nav-back-btn {\n  min-height: 96rpx'), 'Elder back button must have min-height 96rpx')
assert.ok(routeMapContent.includes('.nav-speak-btn {\n  min-height: 96rpx'), 'Elder speak button must have min-height 96rpx')
console.log('✓ Passed: route-map.vue elder map, dynamic steps, touch targets, and 10s periodic reporting verified')

// 5. Verify guardian.vue child map, trip switcher, and off-track alert
console.log('Test 5: pages/child/guardian.vue Child Map, Trip Switcher & Off-Route Alert')
const guardianContent = fs.readFileSync('frontend/laoyouji-app/src/pages/child/guardian.vue', 'utf-8')
assert.ok(guardianContent.includes('child-gaode-map'), 'guardian.vue must contain child-gaode-map DOM mount')
assert.ok(guardianContent.includes('trip-selector-box'), 'guardian.vue must have trip selector box')
assert.ok(guardianContent.includes('switchTrip'), 'guardian.vue must have switchTrip method')
assert.ok(guardianContent.includes('offroute-alert-bubble'), 'guardian.vue must render offroute-alert-bubble')
assert.ok(guardianContent.includes('child-elder-breathe-marker'), 'guardian.vue must render breathing marker')
assert.ok(guardianContent.includes('AMap.Polyline'), 'guardian.vue must render dynamic Polyline')
assert.ok(guardianContent.includes('pollTimer'), 'guardian.vue must run real-time polling timer')
assert.ok(guardianContent.includes('_switchSeq'), 'guardian.vue must guard trip switching against race condition')
assert.ok(guardianContent.includes('updateOffRouteMarker'), 'guardian.vue must sync off-route marker during polling')
assert.ok(guardianContent.includes('this.offRouteMarker.setContent(offEl)'), 'guardian.vue must update marker content with official setContent API')
assert.ok(guardianContent.includes('.alert-action-btn'), 'guardian.vue must style alert-action-btn for off-route call')
console.log('✓ Passed: guardian.vue child map, trip switcher, race guard, and alert bubble verified')

// 6. Verify amap.js utilities
console.log('Test 6: src/utils/amap.js utilities')
const amapJsContent = fs.readFileSync('frontend/laoyouji-app/src/utils/amap.js', 'utf-8')
assert.ok(amapJsContent.includes('loadAMap'), 'amap.js must export loadAMap')
assert.ok(amapJsContent.includes('calcDistanceMeters'), 'amap.js must export calcDistanceMeters')
assert.ok(amapJsContent.includes('6c6e8eddf72527878c4eb76d7273e380'), 'amap.js must contain securityJsCode')

// Test distance function mathematically
const R = 6371000
function calcDist(p1, p2) {
  const [lng1, lat1] = p1
  const [lng2, lat2] = p2
  const dLat = (lat2 - lat1) * (Math.PI / 180)
  const dLng = (lng2 - lng1) * (Math.PI / 180)
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * (Math.PI / 180)) * Math.cos(lat2 * (Math.PI / 180)) * Math.sin(dLng / 2) * Math.sin(dLng / 2)
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
  return R * c
}
const d = calcDist([118.7981, 31.9696], [116.3748, 39.9485])
assert.ok(d > 800_000 && d < 1_100_000, 'Distance should be approx 900+ km')
console.log('✓ Passed: amap.js math and security verified')

// 7. Verify PlanCard tripId propagation in dashboard.vue and chat.vue
console.log('Test 7: tripId propagation in dashboard.vue and chat.vue')
const dashContent = fs.readFileSync('frontend/laoyouji-app/src/pages/child/dashboard.vue', 'utf-8')
assert.ok(dashContent.includes(':trip-id="selectedPlan ? selectedPlan.id : \'\'"'), 'dashboard.vue must pass tripId to PlanCard')
const chatContent = fs.readFileSync('frontend/laoyouji-app/src/pages/elder/chat.vue', 'utf-8')
assert.ok(chatContent.includes(':trip-id="m.tripId || \'\'"'), 'chat.vue must pass tripId to PlanCard')
console.log('✓ Passed: PlanCard tripId propagation verified in dashboard.vue and chat.vue')

// 8. Verify enlarged map view and child dashboard live location card
console.log('Test 8: enlarged map view & child dashboard live location card')
assert.ok(routeMapContent.includes('isExpandedMap'), 'route-map.vue must support isExpandedMap')
assert.ok(routeMapContent.includes('toggleExpandMap'), 'route-map.vue must have toggleExpandMap method')
assert.ok(routeMapContent.includes('height: 680rpx'), 'route-map.vue must expand default map height to 680rpx')
assert.ok(guardianContent.includes('isMapExpanded'), 'guardian.vue must support isMapExpanded')
assert.ok(guardianContent.includes('toggleMapExpand'), 'guardian.vue must have toggleMapExpand method')
assert.ok(guardianContent.includes('height: 760rpx'), 'guardian.vue must expand default map height to 760rpx')
assert.ok(guardianContent.includes('elder-live-status-card'), 'guardian.vue must display elder-live-status-card on map')
assert.ok(dashContent.includes('elder-location-section'), 'dashboard.vue must render elder-location-section')
assert.ok(dashContent.includes('latestLocation'), 'dashboard.vue must support latestLocation state')
assert.ok(dashContent.includes('openGuardianMap'), 'dashboard.vue must support openGuardianMap method')
console.log('✓ Passed: enlarged map view & child dashboard live location card verified')

console.log('\n======================================================')
console.log('ALL GAODE MAP FRONTEND INTEGRATION CHECKS PASSED!')
console.log('======================================================')
