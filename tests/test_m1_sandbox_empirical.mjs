import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'
import assert from 'node:assert/strict'

console.log('======================================================================')
console.log('=== Milestone 1: Empirical Headless Chrome Sandbox Verification ===')
console.log('======================================================================\n')

const distDir = path.resolve('frontend/laoyouji-app/dist/build/h5')
if (!fs.existsSync(distDir)) {
  console.error('Dist directory does not exist! Run npm run build:h5 first.')
  process.exit(1)
}

// 1. Create static server
const mimeTypes = {
  '.html': 'text/html',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
}

const server = http.createServer((req, res) => {
  let reqPath = req.url.split('?')[0].split('#')[0]
  if (reqPath === '/' || reqPath === '') reqPath = '/index.html'
  const filePath = path.join(distDir, reqPath)
  if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
    const ext = path.extname(filePath)
    res.writeHead(200, { 'Content-Type': mimeTypes[ext] || 'application/octet-stream' })
    fs.createReadStream(filePath).pipe(res)
  } else {
    // SPA fallback
    const indexPath = path.join(distDir, 'index.html')
    res.writeHead(200, { 'Content-Type': 'text/html' })
    fs.createReadStream(indexPath).pipe(res)
  }
})

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
const port = server.address().port
console.log(`[Static Server] Serving H5 build on http://127.0.0.1:${port}`)

// 2. Launch headless Chrome with remote debugging
const chromePath = 'C:\\\\Program Files\\\\Google\\\\Chrome\\\\Application\\\\chrome.exe'
const cdpPort = 9222 + Math.floor(Math.random() * 500)
const userDataDir = path.resolve(`temp_chrome_profile_${cdpPort}`)

const chromeProcess = spawn(
  chromePath,
  [
    '--headless=new',
    `--remote-debugging-port=${cdpPort}`,
    `--user-data-dir=${userDataDir}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    '--window-size=1920,1080',
    'about:blank',
  ],
  { stdio: 'ignore' }
)

// Cleanup helper
function cleanup() {
  try { chromeProcess.kill('SIGTERM') } catch (e) {}
  try { server.close() } catch (e) {}
  try { fs.rmSync(userDataDir, { recursive: true, force: true }) } catch (e) {}
}

process.on('exit', cleanup)
process.on('SIGINT', () => { cleanup(); process.exit(1) })

// Wait for CDP to be ready
let wsUrl = null
for (let i = 0; i < 30; i++) {
  try {
    const res = await fetch(`http://127.0.0.1:${cdpPort}/json/version`)
    if (res.ok) {
      const data = await res.json()
      wsUrl = data.webSocketDebuggerUrl
      break
    }
  } catch (e) {
    await new Promise((r) => setTimeout(r, 200))
  }
}

if (!wsUrl) {
  console.error('Failed to connect to headless Chrome via CDP!')
  cleanup()
  process.exit(1)
}

console.log(`[CDP] Connected to Chrome DevTools Protocol at ${wsUrl}`)

// Simple CDP client over native WebSocket
class CdpClient {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl)
    this.id = 1
    this.pending = new Map()
    this.events = []
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws.onopen = resolve
      this.ws.onerror = reject
      this.ws.onmessage = (msg) => {
        const data = JSON.parse(msg.data)
        if (data.id && this.pending.has(data.id)) {
          const { resolve, reject } = this.pending.get(data.id)
          this.pending.delete(data.id)
          if (data.error) reject(data.error)
          else resolve(data.result)
        } else if (data.method) {
          this.events.push(data)
        }
      }
    })
  }

  async send(method, params = {}) {
    const msgId = this.id++
    return new Promise((resolve, reject) => {
      this.pending.set(msgId, { resolve, reject })
      this.ws.send(JSON.stringify({ id: msgId, method, params }))
    })
  }

  async evaluate(expression) {
    const res = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    })
    if (res.exceptionDetails) {
      throw new Error(JSON.stringify(res.exceptionDetails))
    }
    return res.result?.value
  }

  async setViewport(width, height) {
    await this.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      deviceScaleFactor: 1,
      mobile: width <= 480,
    })
  }

  async navigate(url) {
    await this.send('Page.navigate', { url })
    await new Promise((r) => setTimeout(r, 1200)) // Wait for uni-app router and rendering
  }
}

const cdp = new CdpClient(wsUrl)
await cdp.connect()

// Get page target
const targetsRes = await fetch(`http://127.0.0.1:${cdpPort}/json`)
const targets = await targetsRes.json()
const pageTarget = targets.find((t) => t.type === 'page')
assert.ok(pageTarget, 'Must find page target')

const pageCdp = new CdpClient(pageTarget.webSocketDebuggerUrl)
await pageCdp.connect()

// Enable Page and Runtime domains
await pageCdp.send('Page.enable')
await pageCdp.send('Runtime.enable')

const findings = []

async function gotoPage(hash, role = 'elder') {
  await pageCdp.evaluate(`(() => {
    const user = ${role === 'elder' ? JSON.stringify({ id: 1, name: '张大爷', role: 'elder' }) : JSON.stringify({ id: 2, name: '张小强', role: 'child' })};
    window.localStorage.setItem('lyj_user', JSON.stringify(user));
    window.localStorage.setItem('lyj_token', 'mock_jwt_token_for_challenger');
    if (window.uni && window.uni.reLaunch) {
      window.uni.reLaunch({ url: '${hash.replace('#', '')}' });
    } else {
      window.location.hash = '${hash}';
    }
  })()`)
  await new Promise((r) => setTimeout(r, 2000))
}


// TEST SUITE 1: Desktop Viewport (1920x1080) Layout & Bounding Rect Analysis
// =========================================================================
console.log('\n--- Test 1: Desktop 1920x1080 Sandbox & Fixed Element Placement ---')
await pageCdp.setViewport(1920, 1080)
await pageCdp.navigate(`http://127.0.0.1:${port}/`)
await gotoPage('#/pages/elder/home')

const desktopMetrics = await pageCdp.evaluate(`(() => {
  const uniApp = document.querySelector('uni-app');
  const uniTabbar = document.querySelector('uni-tabbar');
  const innerTabbar = document.querySelector('.uni-tabbar');
  const pageHead = document.querySelector('uni-page-head');
  const body = document.body;

  const appRect = uniApp ? uniApp.getBoundingClientRect() : null;
  const tabbarRect = uniTabbar ? uniTabbar.getBoundingClientRect() : null;
  const innerTabbarRect = innerTabbar ? innerTabbar.getBoundingClientRect() : null;
  const headRect = pageHead ? pageHead.getBoundingClientRect() : null;

  return {
    window: { width: window.innerWidth, height: window.innerHeight },
    bodyStyle: {
      display: window.getComputedStyle(body).display,
      justifyContent: window.getComputedStyle(body).justifyContent,
      alignItems: window.getComputedStyle(body).alignItems,
      backgroundColor: window.getComputedStyle(body).backgroundColor,
    },
    app: appRect ? {
      left: Math.round(appRect.left),
      top: Math.round(appRect.top),
      right: Math.round(appRect.right),
      bottom: Math.round(appRect.bottom),
      width: Math.round(appRect.width),
      height: Math.round(appRect.height),
    } : null,
    tabbar: tabbarRect ? {
      left: Math.round(tabbarRect.left),
      top: Math.round(tabbarRect.top),
      right: Math.round(tabbarRect.right),
      bottom: Math.round(tabbarRect.bottom),
      width: Math.round(tabbarRect.width),
      height: Math.round(tabbarRect.height),
    } : null,
    innerTabbar: innerTabbarRect ? {
      left: Math.round(innerTabbarRect.left),
      top: Math.round(innerTabbarRect.top),
      right: Math.round(innerTabbarRect.right),
      bottom: Math.round(innerTabbarRect.bottom),
      width: Math.round(innerTabbarRect.width),
      height: Math.round(innerTabbarRect.height),
      position: window.getComputedStyle(innerTabbar).position,
    } : null,
    head: headRect ? {
      left: Math.round(headRect.left),
      top: Math.round(headRect.top),
      right: Math.round(headRect.right),
      bottom: Math.round(headRect.bottom),
      width: Math.round(headRect.width),
      height: Math.round(headRect.height),
      position: window.getComputedStyle(pageHead).position,
    } : null,
  };
})()`)

console.log('Desktop 1920x1080 Metrics:', JSON.stringify(desktopMetrics, null, 2))

const debugInfo = await pageCdp.evaluate(`(() => {
  const uniApp = document.querySelector('uni-app');
  const cs = window.getComputedStyle(uniApp);
  return {
    href: window.location.href,
    boxSizing: cs.boxSizing,
    width: cs.width,
    maxWidth: cs.maxWidth,
    marginLeft: cs.marginLeft,
    marginRight: cs.marginRight,
    paddingLeft: cs.paddingLeft,
    paddingRight: cs.paddingRight,
    borderLeftWidth: cs.borderLeftWidth,
    borderRightWidth: cs.borderRightWidth,
    offsetWidth: uniApp.offsetWidth,
    clientWidth: uniApp.clientWidth,
    scrollWidth: uniApp.scrollWidth,
    parentTag: uniApp.parentElement.tagName,
    parentWidth: uniApp.parentElement.clientWidth,
  };
})()`)
const appWrapperInfo = await pageCdp.evaluate(`(() => {
  const appEl = document.querySelector('#app');
  const cs = window.getComputedStyle(appEl);
  const rect = appEl.getBoundingClientRect();
  return {
    rect: { left: rect.left, top: rect.top, width: rect.width, height: rect.height },
    display: cs.display,
    width: cs.width,
    height: cs.height,
    flex: cs.flex,
  };
})()`)
console.log('App Wrapper (#app) info:', JSON.stringify(appWrapperInfo, null, 2))



// Check uni-app width
const app = desktopMetrics.app
if (app) {
  console.log(`  uni-app Container: width=${app.width}px, height=${app.height}px, top=${app.top}px, bottom=${app.bottom}px, left=${app.left}px`)
  if (app.width !== 430) {
    const msg = `uni-app width is ${app.width}px instead of exactly 430px (due to #app wrapper or flex sizing)`
    console.error(`  ❌ DEFECT: ${msg}`)
    findings.push({ severity: 'HIGH', category: 'Sandbox Width', description: msg })
  } else {
    console.log(`  ✓ uni-app width is strictly 430px`)
  }

  // Check Tabbar bounds against uni-app
  const it = desktopMetrics.innerTabbar
  if (it && it.height > 0) {
    console.log(`  .uni-tabbar: top=${it.top}px, bottom=${it.bottom}px, left=${it.left}px, width=${it.width}px, position=${it.position}`)
    if (it.bottom !== app.bottom) {
      const msg = `Tabbar bottom (${it.bottom}px) does not align with uni-app container bottom (${app.bottom}px). Offset: ${it.bottom - app.bottom}px. Tabbar escapes chassis due to position: fixed.`
      console.error(`  ❌ DEFECT: ${msg}`)
      findings.push({ severity: 'HIGH', category: 'Fixed Escape', description: msg })
    } else {
      console.log(`  ✓ Tabbar bottom aligns with uni-app bottom!`)
    }
  }
}

// =========================================================================
// TEST SUITE 2: Chat Page (.chat-page) Bounding Box & Escape Verification
// =========================================================================
console.log('\n--- Test 2: Chat Page (.chat-page) Desktop 1920x1080 Metrics ---')
await gotoPage('#/pages/elder/chat')

const chatMetrics = await pageCdp.evaluate(`(() => {
  const uniApp = document.querySelector('uni-app');
  const chatPage = document.querySelector('.chat-page');
  const appRect = uniApp ? uniApp.getBoundingClientRect() : null;
  const chatRect = chatPage ? chatPage.getBoundingClientRect() : null;

  return {
    app: appRect ? {
      left: Math.round(appRect.left),
      top: Math.round(appRect.top),
      bottom: Math.round(appRect.bottom),
      width: Math.round(appRect.width),
      height: Math.round(appRect.height),
    } : null,
    chat: chatRect ? {
      left: Math.round(chatRect.left),
      top: Math.round(chatRect.top),
      bottom: Math.round(chatRect.bottom),
      width: Math.round(chatRect.width),
      height: Math.round(chatRect.height),
      position: window.getComputedStyle(chatPage).position,
    } : null,
  };
})()`)

console.log('Chat Page Metrics:', JSON.stringify(chatMetrics, null, 2))

if (chatMetrics.chat && chatMetrics.app) {
  const c = chatMetrics.chat
  const a = chatMetrics.app
  console.log(`  .chat-page: width=${c.width}px, height=${c.height}px, top=${c.top}px, bottom=${c.bottom}px`)
  if (c.width > 430) {
    const msg = `.chat-page width (${c.width}px) exceeds 430px boundary`
    console.error(`  ❌ DEFECT: ${msg}`)
    findings.push({ severity: 'CRITICAL', category: 'Chat Page Escape', description: msg })
  } else {
    console.log(`  ✓ .chat-page width (${c.width}px) within 430px`)
  }

  if (c.top !== a.top || c.bottom !== a.bottom) {
    const msg = `.chat-page vertical bounds [top: ${c.top}px, bottom: ${c.bottom}px, height: ${c.height}px] escape uni-app container [top: ${a.top}px, bottom: ${a.bottom}px, height: ${a.height}px]. Because .chat-page is fixed: top: 0, bottom: 0, it fills full browser window height!`
    console.warn(`  ⚠️ DEFECT: ${msg}`)
    findings.push({ severity: 'MEDIUM', category: 'Chat Page Escape', description: msg })
  } else {
    console.log('  ✓ .chat-page perfectly bounded vertically inside uni-app container!')
  }
}

// =========================================================================
// TEST SUITE 3: Mobile Viewport (375x667, 430x932) Responsiveness
// =========================================================================
console.log('\n--- Test 3: Mobile 375x667 (iPhone SE) Responsiveness ---')
await pageCdp.setViewport(375, 667)
await gotoPage('#/pages/elder/home')

const mobileMetrics = await pageCdp.evaluate(`(() => {
  const uniApp = document.querySelector('uni-app');
  const appRect = uniApp ? uniApp.getBoundingClientRect() : null;
  return {
    window: { width: window.innerWidth, height: window.innerHeight },
    app: appRect ? {
      left: Math.round(appRect.left),
      width: Math.round(appRect.width),
      height: Math.round(appRect.height),
      borderRadius: window.getComputedStyle(uniApp).borderRadius,
      boxShadow: window.getComputedStyle(uniApp).boxShadow,
    } : null,
  };
})()`)

console.log('Mobile 375x667 Metrics:', JSON.stringify(mobileMetrics, null, 2))
if (mobileMetrics.app) {
  if (mobileMetrics.app.width !== 375) {
    const msg = `Mobile uni-app width is ${mobileMetrics.app.width}px instead of 100% (375px)`
    console.error(`  ❌ DEFECT: ${msg}`)
    findings.push({ severity: 'HIGH', category: 'Mobile Responsiveness', description: msg })
  } else {
    console.log('  ✓ Mobile 375x667: 100% full-width fit confirmed!')
  }
  if (mobileMetrics.app.left !== 0) {
    const msg = `Mobile uni-app left is ${mobileMetrics.app.left}px instead of 0`
    console.error(`  ❌ DEFECT: ${msg}`)
    findings.push({ severity: 'MEDIUM', category: 'Mobile Responsiveness', description: msg })
  }
}

// =========================================================================
// TEST SUITE 4: Child Pages (dashboard, notification) Desktop Layout
// =========================================================================
console.log('\n--- Test 4: Child Dashboard & Notification Layout ---')
await pageCdp.setViewport(1920, 1080)
await gotoPage('#/pages/child/dashboard', 'child')

const childDashMetrics = await pageCdp.evaluate(`(() => {
  const uniApp = document.querySelector('uni-app');
  const dash = document.querySelector('.dash');
  return {
    appWidth: uniApp ? Math.round(uniApp.getBoundingClientRect().width) : null,
    dashWidth: dash ? Math.round(dash.getBoundingClientRect().width) : null,
  };
})()`)

console.log('Child Dashboard Metrics:', JSON.stringify(childDashMetrics, null, 2))
if (childDashMetrics.dashWidth > 430) {
  const msg = `Dashboard content width (${childDashMetrics.dashWidth}px) exceeds 430px`
  console.error(`  ❌ DEFECT: ${msg}`)
  findings.push({ severity: 'HIGH', category: 'Dashboard Width', description: msg })
} else {
  console.log(`  ✓ Child Dashboard: bounded within container (${childDashMetrics.dashWidth}px <= 430px)`)
}

await gotoPage('#/pages/child/notification', 'child')
const notifMetrics = await pageCdp.evaluate(`(() => {
  const notif = document.querySelector('.notification-page');
  const grid = document.querySelector('.sections-grid');
  return {
    notifWidth: notif ? Math.round(notif.getBoundingClientRect().width) : null,
    gridDisplay: grid ? window.getComputedStyle(grid).display : null,
    gridCols: grid ? window.getComputedStyle(grid).gridTemplateColumns : null,
  };
})()`)

console.log('Notification Center Metrics:', JSON.stringify(notifMetrics, null, 2))
if (notifMetrics.gridCols && notifMetrics.gridCols !== 'none') {
  const msg = `Notification gridTemplateColumns is "${notifMetrics.gridCols}", expected single column / none`
  console.error(`  ❌ DEFECT: ${msg}`)
  findings.push({ severity: 'HIGH', category: 'Notification Layout', description: msg })
} else {
  console.log('  ✓ Notification Center: 2-column grid successfully eliminated!')
}

// =========================================================================
// TEST SUITE 5: Empirical Verification of Containing Block Mitigation
// =========================================================================
console.log('\n--- Test 5: Containing Block Mitigation via transform: translate(0, 0) ---')
await pageCdp.setViewport(1920, 1080)
await gotoPage('#/pages/elder/home')

const mitigationTest = await pageCdp.evaluate(`(() => {
  const uniApp = document.querySelector('uni-app');
  if (!uniApp) return null;

  // Apply mitigation
  uniApp.style.transform = 'translate(0, 0)';

  const appRect = uniApp.getBoundingClientRect();
  const innerTabbar = document.querySelector('.uni-tabbar');
  const tabbarRect = innerTabbar ? innerTabbar.getBoundingClientRect() : null;

  return {
    app: {
      left: Math.round(appRect.left),
      top: Math.round(appRect.top),
      bottom: Math.round(appRect.bottom),
      height: Math.round(appRect.height),
    },
    tabbar: tabbarRect ? {
      left: Math.round(tabbarRect.left),
      top: Math.round(tabbarRect.top),
      bottom: Math.round(tabbarRect.bottom),
      height: Math.round(tabbarRect.height),
    } : null,
  };
})()`)

console.log('Mitigation Test (Home Tabbar):', JSON.stringify(mitigationTest, null, 2))
if (mitigationTest && mitigationTest.tabbar) {
  const mApp = mitigationTest.app
  const mTab = mitigationTest.tabbar
  console.log(`  With transform: translate(0, 0): tabbar.bottom = ${mTab.bottom}px, app.bottom = ${mApp.bottom}px`)
  if (mTab.bottom === mApp.bottom) {
    console.log(`  🎉 MITIGATION CONFIRMED! Tabbar is now perfectly docked to the bottom of uni-app chassis!`)
  } else {
    console.log(`  Tabbar bottom delta: ${mTab.bottom - mApp.bottom}px`)
  }
}

await gotoPage('#/pages/elder/chat')
const chatMitigationTest = await pageCdp.evaluate(`(() => {
  const uniApp = document.querySelector('uni-app');
  if (!uniApp) return null;

  uniApp.style.transform = 'translate(0, 0)';

  const appRect = uniApp.getBoundingClientRect();
  const chatPage = document.querySelector('.chat-page');
  const chatRect = chatPage ? chatPage.getBoundingClientRect() : null;

  return {
    app: {
      left: Math.round(appRect.left),
      top: Math.round(appRect.top),
      bottom: Math.round(appRect.bottom),
      height: Math.round(appRect.height),
    },
    chat: chatRect ? {
      left: Math.round(chatRect.left),
      top: Math.round(chatRect.top),
      bottom: Math.round(chatRect.bottom),
      height: Math.round(chatRect.height),
    } : null,
  };
})()`)

console.log('Mitigation Test (Chat Page):', JSON.stringify(chatMitigationTest, null, 2))
if (chatMitigationTest && chatMitigationTest.chat) {
  const mApp = chatMitigationTest.app
  const mChat = chatMitigationTest.chat
  console.log(`  With transform: translate(0, 0): chat.height = ${mChat.height}px, app.height = ${mApp.height}px`)
  if (mChat.height === mApp.height && mChat.top === mApp.top && mChat.bottom === mApp.bottom) {
    console.log(`  🎉 MITIGATION CONFIRMED! .chat-page is now perfectly bounded inside uni-app chassis [height: ${mChat.height}px]!`)
  } else {
    console.log(`  Chat height delta: ${mChat.height - mApp.height}px`)
  }
}

cleanup()
console.log('\n======================================================================')
console.log(`=== EMPIRICAL SUITE COMPLETED: ${findings.length} DEFECTS DETECTED ===`)
console.log('======================================================================')
for (const f of findings) {
  console.log(`[${f.severity}] (${f.category}) ${f.description}`)
}

