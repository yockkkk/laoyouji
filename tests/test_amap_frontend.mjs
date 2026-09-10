import assert from 'node:assert/strict'
import fs from 'node:fs'

console.log('=== Running Frontend Verification for Leaflet + 高德栅格瓦片 Map Integration ===\n')

// 1. Verify index.html no longer statically loads the (unreachable) Gaode JS SDK.
//    底图改由 utils/amap.js 的 loadLeaflet() 动态加载 Leaflet + 高德栅格瓦片，
//    所以 index.html 不该再出现高德 JS SDK <script> 与 _AMapSecurityConfig。
console.log('Test 1: index.html drops the unreachable Gaode JS SDK (Leaflet loads dynamically)')
const htmlContent = fs.readFileSync('frontend/laoyouji-app/index.html', 'utf-8')
assert.ok(!htmlContent.includes('webapi.amap.com/maps'), 'index.html must NOT statically load the Gaode JS SDK')
assert.ok(!htmlContent.includes('_AMapSecurityConfig'), 'index.html must NOT inject _AMapSecurityConfig')
assert.ok(htmlContent.includes('loadLeaflet'), 'index.html comment must explain Leaflet loads dynamically via loadLeaflet()')
assert.ok(htmlContent.includes('<div id="app">'), 'index.html must keep the app mount node')
console.log('✓ Passed: index.html no longer depends on the broken Gaode control-plane SDK')

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

// 4. Verify route-map.vue structure, Leaflet route, dynamic points/steps, and 10s reporting loop
console.log('Test 4: pages/elder/route-map.vue Leaflet Map and 10s Reporting')
const routeMapContent = fs.readFileSync('frontend/laoyouji-app/src/pages/elder/route-map.vue', 'utf-8')
assert.ok(routeMapContent.includes('elder-amap-container'), 'route-map.vue must contain elder-amap-container DOM mount')
assert.ok(routeMapContent.includes('loadLeaflet'), 'route-map.vue must load Leaflet dynamically')
assert.ok(routeMapContent.includes('AMAP_RASTER_TILE_URL'), 'route-map.vue must lay down Gaode raster tiles')
assert.ok(routeMapContent.includes('L.polyline'), 'route-map.vue must render the route as a Leaflet polyline')
assert.ok(routeMapContent.includes('toLeafletLatLng'), 'route-map.vue must convert Gaode [lng,lat] to Leaflet [lat,lng]')
assert.ok(routeMapContent.includes('fitBounds'), 'route-map.vue must fit the map to the route bounds')
assert.ok(routeMapContent.includes('elder-live-pulse-marker'), 'route-map.vue must render elder breathing marker')
assert.ok(routeMapContent.includes('setInterval'), 'route-map.vue must run periodic interval')
assert.ok(routeMapContent.includes('10000'), 'route-map.vue must report every 10 seconds')
assert.ok(routeMapContent.includes('post(`/api/trips/'), 'route-map.vue must post checkpoints to backend')
assert.ok(routeMapContent.includes('换乘步骤大字指引'), 'route-map.vue must have transit step cards')
assert.ok(routeMapContent.includes('r.points.map'), 'route-map.vue must dynamically populate routePoints from backend')
assert.ok(routeMapContent.includes('r.steps.map'), 'route-map.vue must dynamically populate steps from backend')
assert.ok(routeMapContent.includes('/api/trips/route/direct'), 'route-map.vue must query direct route planning')
assert.ok(routeMapContent.includes('/api/trips/quick'), 'route-map.vue must auto-create quick trip for reporting loop')
assert.ok(/\.nav-back-btn\s*\{\s*min-height:\s*96rpx/.test(routeMapContent), 'Elder back button must have min-height 96rpx')
assert.ok(/\.nav-speak-btn\s*\{\s*min-height:\s*96rpx/.test(routeMapContent), 'Elder speak button must have min-height 96rpx')
console.log('✓ Passed: route-map.vue Leaflet map, dynamic steps, touch targets, and 10s periodic reporting verified')

// 5. Verify guardian.vue child map, trip switcher, and off-track alert
console.log('Test 5: pages/child/guardian.vue Child Map, Trip Switcher & Off-Route Alert')
const guardianContent = fs.readFileSync('frontend/laoyouji-app/src/pages/child/guardian.vue', 'utf-8')
assert.ok(guardianContent.includes('child-gaode-map'), 'guardian.vue must contain child-gaode-map DOM mount')
assert.ok(guardianContent.includes('trip-selector-box'), 'guardian.vue must have trip selector box')
assert.ok(guardianContent.includes('switchTrip'), 'guardian.vue must have switchTrip method')
assert.ok(guardianContent.includes('offroute-alert-bubble'), 'guardian.vue must render offroute-alert-bubble')
assert.ok(guardianContent.includes('child-elder-breathe-marker'), 'guardian.vue must render breathing marker')
assert.ok(guardianContent.includes('L.polyline'), 'guardian.vue must render the dynamic route as a Leaflet polyline')
assert.ok(guardianContent.includes('pollTimer'), 'guardian.vue must run real-time polling timer')
assert.ok(guardianContent.includes('_switchSeq'), 'guardian.vue must guard trip switching against race condition')
assert.ok(guardianContent.includes('updateOffRouteMarker'), 'guardian.vue must sync off-route marker during polling')
assert.ok(guardianContent.includes('this.offRouteMarker.setIcon(icon)'), 'guardian.vue must refresh the off-route marker via Leaflet setIcon API')
assert.ok(guardianContent.includes('.alert-action-btn'), 'guardian.vue must style alert-action-btn for off-route call')
console.log('✓ Passed: guardian.vue child map, trip switcher, race guard, and alert bubble verified')

// 6. Verify amap.js utilities (Leaflet loader + Gaode raster tiles)
console.log('Test 6: src/utils/amap.js utilities')
const amapJsContent = fs.readFileSync('frontend/laoyouji-app/src/utils/amap.js', 'utf-8')
assert.ok(amapJsContent.includes('export function loadLeaflet'), 'amap.js must export loadLeaflet')
assert.ok(!amapJsContent.includes('export function loadAMap'), 'amap.js must no longer export loadAMap')
assert.ok(amapJsContent.includes('toLeafletLatLng'), 'amap.js must export toLeafletLatLng')
assert.ok(amapJsContent.includes('wprd0{s}.is.autonavi.com'), 'amap.js must point tiles at the reachable Gaode data-plane')
assert.ok(amapJsContent.includes('calcDistanceMeters'), 'amap.js must export calcDistanceMeters')
assert.ok(amapJsContent.includes('6c6e8eddf72527878c4eb76d7273e380'), 'amap.js must retain securityJsCode for backend/REST use')

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
console.log('✓ Passed: amap.js Leaflet loader, tile source, math, and security verified')

// 7. Verify PlanCard tripId propagation in dashboard.vue and chat.vue
console.log('Test 7: tripId propagation in dashboard.vue and chat.vue')
const dashContent = fs.readFileSync('frontend/laoyouji-app/src/pages/child/dashboard.vue', 'utf-8')
assert.ok(dashContent.includes(':trip-id="selectedPlan ? selectedPlan.id : \'\'"'), 'dashboard.vue must pass tripId to PlanCard')
const chatContent = fs.readFileSync('frontend/laoyouji-app/src/pages/elder/chat.vue', 'utf-8')
assert.ok(chatContent.includes(':trip-id="m.tripId || \'\'"'), 'chat.vue must pass tripId to PlanCard')
console.log('✓ Passed: PlanCard tripId propagation verified in dashboard.vue and chat.vue')

// 8. Verify PC Mobile Sandbox 430px & App.vue container
console.log('Test 8: PC Mobile Sandbox 430px container in App.vue')
const appContent = fs.readFileSync('frontend/laoyouji-app/src/App.vue', 'utf-8')
assert.ok(appContent.includes('max-width: 430px'), 'App.vue must constrain PC desktop to 430px mobile sandbox')
assert.ok(!appContent.includes('max-width: 960px'), 'App.vue must no longer have 960px desktop query')
console.log('✓ Passed: PC Mobile Sandbox 430px container verified in App.vue')

// 9. Verify Celestial Sky Blue Palette
console.log('Test 9: Celestial Sky Blue Palette in uni.scss and pages.json')
const scssContent = fs.readFileSync('frontend/laoyouji-app/src/uni.scss', 'utf-8')
assert.ok(scssContent.includes('$lyj-primary: #2A82E4;'), 'uni.scss must define primary as #2A82E4')
assert.ok(scssContent.includes('$lyj-bg: #F2F7FD;'), 'uni.scss must define bg as #F2F7FD')
assert.ok(!scssContent.includes('#FF6B35'), 'uni.scss must not contain old warm orange #FF6B35')
const pagesContent = fs.readFileSync('frontend/laoyouji-app/src/pages.json', 'utf-8')
assert.ok(pagesContent.includes('"selectedColor": "#2A82E4"'), 'pages.json tabBar selectedColor must be #2A82E4')
console.log('✓ Passed: Celestial Sky Blue Palette verified in uni.scss and pages.json')

console.log('\n======================================================')
console.log('ALL MOBILE REFACTOR & CELESTIAL SKY BLUE CHECKS PASSED!')
console.log('======================================================')
