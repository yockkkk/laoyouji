/**
 * TR5.8 · 双端 E2E 门禁（按大改后的契约重写）
 *
 * 前置：
 *   后端  `backend/.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000`
 *         （`LLM_PROVIDER=mock` + `STORAGE_BACKEND=local` 即可整条离线跑）
 *   前端  `cd frontend/laoyouji-app && npm run dev:h5` → 127.0.0.1:5173
 *   跑法  `node frontend/e2e/elder-flow.mjs`
 *
 * 上一版这个脚本已经测不了现在的应用了：它点 `.tab`（`LyjTabBar.vue` 已删，
 * 底栏现在是 `pages.json` 里的原生 tabBar）、断言 2 张挂起卡（真跑出来是 3 张）、
 * 用 `?quick=` 自动发送通道（已改成"只填输入框"）、拿假底栏第 3 项去子女端隐私页
 * （子女端现在是顶部分段控件 + 页面栈，根本没有底栏）。
 *
 * 这一版钉的是"演示当天必须成立"的七件事 —— 每一条都对应 DEMO_SCRIPT.md 里
 * 会当众念出来的一句话：
 *   1 装配自检：23 个工具、4 个 Agent（台上要念的数字，先让脚本对一遍）
 *   2 老人端首屏：麦克风 + 今日用药；原生底栏能切页
 *   3 快捷入口**只把话填进输入框**，不替老人按发送（R5 的界面侧）
 *   4 旗舰指令 → 真步骤条（`todo` 整表快照）+ 两条子智能体回报（扇出唯一的可见证据）
 *   5 三张挂起卡，金额 100 / 553.5 / 658，合计 1311.5 —— 此刻一分钱没花
 *   6 五页计划书：标题带老人姓名、五个页标题齐全、脚注写着模拟数据披露
 *   7 子女端 3 条待确认 → 同意 1 条 → 冻结参数重放 → 剩 2 条；
 *     **老人端那张黄卡就地变绿**（这条以前写在彩排单上靠人眼看，现在归脚本管）
 *
 * 一条自律：断言只写"界面上真能指出来的东西"。数字对不上就红，不许把
 * `>=` 当护身符 —— 那样等于把台上会被戳破的差错留到台上。
 */
import puppeteer from 'puppeteer-core'

const CHROME =
  process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const APP = process.env.APP_URL || 'http://127.0.0.1:5173'
const API = process.env.API_URL || 'http://127.0.0.1:8000'
const SHOTS = 'C:/Users/lenovo/Desktop/develop/laoyouji/docs/shots'

const FLAGSHIP = '我想去北京看腿疼的老毛病'

/** 与 `providers/llm/mock.py` 的旗舰轨迹一一对应：挂号 / 车票 / 酒店 329×2。 */
const EXPECT_AMOUNTS = [100, 553.5, 658]
const EXPECT_TOTAL = 1311.5
/** `agents/plan_builder.py` 写死的页序，五页齐全才算交付物成立。 */
const EXPECT_PAGES = ['挂号信息', '车票', '酒店', '随身清单', '穿衣']
const EXPECT_TOOLS = 23
const EXPECT_AGENTS = 4

/** uni-app H5 的原生 tabBar 条目。类名是框架内部约定，见 tapTab 的报错说明。 */
const TABBAR_ITEM = '.uni-tabbar__item'
/** uni-app H5 把 class 落在 `<uni-input>` 外壳上，真正的原生 input 在里面。 */
const INPUT_SEL = '.text-input input, input.text-input, .input-area input'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

let passed = 0
function assert(cond, msg) {
  if (!cond) throw new Error('❌ ' + msg)
  passed += 1
  console.log('  ✅ ' + msg)
}
function skip(msg) {
  console.log('  ⏭️  跳过：' + msg)
}

/**
 * uni-app H5 的 @tap 由触摸事件驱动：用 touchscreen 模拟，click 不触发。
 *
 * 先 scrollIntoView 再量坐标：420×900 的视口装不下确认详情页整张卡，
 * 【同意】按钮在折线以下时 getBoundingClientRect 给的 y 会超出视口，
 * 触摸落在空处 —— 表现是"点了没反应"，很容易误判成前端 bug。
 */
async function tap(page, selector, index = 0) {
  const rect = await page.evaluate(
    (sel, i) => {
      const el = [...document.querySelectorAll(sel)][i]
      if (!el) return null
      el.scrollIntoView({ block: 'center' })
      const r = el.getBoundingClientRect()
      return { x: r.x + r.width / 2, y: r.y + r.height / 2 }
    },
    selector,
    index
  )
  if (!rect) throw new Error(`tap 目标不存在：${selector}[${index}]`)
  await sleep(200) // 等滚动落位，别在滑动过程中按下
  await page.touchscreen.touchStart(rect.x, rect.y)
  await page.touchscreen.touchEnd()
  await sleep(1200)
}

/**
 * 按**文字**点原生底栏，而不是按下标 —— 底栏顺序以后可能调，
 * "点『聊天』能到聊天页"才是要守住的那条约定。
 */
async function tapTab(page, label) {
  const hit = await page.evaluate(
    (sel, want) => {
      const items = [...document.querySelectorAll(sel)]
      const labels = items.map((el) => (el.textContent || '').trim())
      const i = labels.findIndex((t) => t.includes(want))
      if (i < 0) return { total: items.length, index: -1, labels }
      const r = items[i].getBoundingClientRect()
      return { total: items.length, index: i, x: r.x + r.width / 2, y: r.y + r.height / 2 }
    },
    TABBAR_ITEM,
    label
  )
  if (!hit.total) {
    throw new Error(
      `❌ 老人端底栏不存在（选择器 ${TABBAR_ITEM} 一个都没匹配到）。\n` +
        '   pages.json 里配了 tabBar，H5 端本该渲染出来。如果是 uni-app 换了内部类名，' +
        '改本文件顶部的 TABBAR_ITEM 常量；\n' +
        '   **不要**改成用 URL 直接跳页绕过去 —— 那样测的就不是导航模型，' +
        'TR4.1 交付的东西就没人验了。'
    )
  }
  if (hit.index < 0) {
    throw new Error(`❌ 底栏里没有「${label}」这一项。现有：${hit.labels.join(' / ')}`)
  }
  await page.touchscreen.touchStart(hit.x, hit.y)
  await page.touchscreen.touchEnd()
  await sleep(1200)
}

async function count(page, sel) {
  return page.$$eval(sel, (els) => els.length)
}

async function visibleCount(page, sel) {
  return page.$$eval(sel, (els) =>
    els.filter((el) => {
      const style = getComputedStyle(el)
      const rect = el.getBoundingClientRect()
      return (
        style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        style.opacity !== '0' &&
        rect.width > 0 &&
        rect.height > 0
      )
    }).length
  )
}

async function texts(page, sel) {
  return page.$$eval(sel, (els) => els.map((e) => (e.textContent || '').trim()))
}

/**
 * 等某个选择器的数量**稳定到**期望值，返回最后观测到的数量。
 * 只等不断言：数量对不对交给调用方 assert，这样成功/失败都走同一行输出。
 */
async function settleCount(page, sel, want, timeoutMs) {
  const t0 = Date.now()
  let n = await count(page, sel)
  while (n !== want && Date.now() - t0 < timeoutMs) {
    await sleep(1000)
    n = await count(page, sel)
  }
  return n
}

async function setInput(page, text) {
  const ok = await page.evaluate(
    (sel, val) => {
      const el = document.querySelector(sel)
      if (!el) return false
      // 中文经 CDP keyboard 会被当成 IME 组合输入，所以走原生 setter + input 事件
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        'value'
      ).set
      setter.call(el, val)
      el.dispatchEvent(new Event('input', { bubbles: true }))
      return true
    },
    INPUT_SEL,
    text
  )
  if (!ok) throw new Error('找不到聊天输入框：' + INPUT_SEL)
  await sleep(400)
}

async function getInput(page) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel)
    return el ? el.value : null
  }, INPUT_SEL)
}

async function newPage(browser) {
  const page = await browser.newPage()
  await page.setViewport({ width: 420, height: 900, hasTouch: true })
  page.on('pageerror', (e) => console.log('  [页面错误]', e.message))
  return page
}

async function loginAs(page, role) {
  await page.goto(APP + '/#/', { waitUntil: 'networkidle2' })
  await page.waitForSelector('.role-card', { timeout: 15000 })
  await sleep(800)
  // 登录页两张角色卡：0 = 我是老人，1 = 我是家人
  await tap(page, '.role-card', role === 'child' ? 1 : 0)
}

async function shot(page, name) {
  const path = `${SHOTS}/${name}.png`
  await page.screenshot({ path })
  console.log('  📸 截图：' + path)
}

async function main() {
  // ======================================================== 第 0 幕 · 装配自检
  console.log('== 第 0 幕 · 后端自检与演示数据复位 ==')
  const health = await fetch(API + '/api/health').then((r) => r.json())
  const len = (x) => (Array.isArray(x) ? x.length : Number(x) || 0)
  assert(health.ok === true, `/api/health ok:true（storage=${health.providers?.storage}）`)
  assert(
    len(health.tools) === EXPECT_TOOLS,
    `工具 ${len(health.tools)} 个（应 ${EXPECT_TOOLS}，台上要念这个数）`
  )
  assert(
    len(health.agents) === EXPECT_AGENTS,
    `Agent ${len(health.agents)} 个（应 ${EXPECT_AGENTS}：main/travel/health/community）`
  )
  await fetch(API + '/api/seed', { method: 'POST' }).then((r) => r.json())
  console.log('  演示数据已复位（张桂芳 / 李明 + 2 个用药计划 + 隐私配置）')

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-gpu',
      '--window-size=420,900',
      // 老人端那一页在后台等家人点同意，别让 Chrome 把它的 5 秒轮询降频掉
      '--disable-backgrounding-occluded-windows',
      '--disable-renderer-backgrounding',
    ],
  })

  try {
    // ==================================================== 第 1 幕 · 老人端首屏
    console.log('\n== 第 1 幕 · 老人端首屏与导航 ==')
    const elder = await newPage(browser)
    await loginAs(elder, 'elder')
    assert(elder.url().includes('/pages/elder/home'), '登录后进入老人端首页')

    assert((await count(elder, '.mic-zone')) === 1, '120px 大麦克风在首屏（不用先进聊天页）')

    await elder.waitForSelector('.reminder-card', { timeout: 15000 })
    const medRows = await texts(elder, '.med-row')
    const medDrugs = await texts(elder, '.med-drug')
    assert(medRows.length === 2, `今日提醒 ${medRows.length} 条用药计划（种子数据 2 条）`)
    assert(
      medDrugs.join(' ').includes('氨基葡萄糖') && medDrugs.join(' ').includes('钙片'),
      '两条药名都渲染出来了：' + medDrugs.join(' / ')
    )

    // 原生底栏：切到聊天页再切回来，返回键与栈都不该被破坏
    await tapTab(elder, '聊天')
    assert(elder.url().includes('/pages/elder/chat'), '点底栏「聊天」进入聊天页（原生 tabBar）')
    await tapTab(elder, '首页')
    assert(elder.url().includes('/pages/elder/home'), '点底栏「首页」回到首页')

    // ============================== 第 2 幕 · 快捷入口只填话，不替老人发送
    console.log('\n== 第 2 幕 · 快捷入口的交接（不许自动发送）==')
    const quicks = await texts(elder, '.quick-item')
    assert(quicks.length > 0, `首页快捷入口 ${quicks.length} 个：${quicks.join(' / ')}`)
    await tap(elder, '.quick-item', 0)
    assert(elder.url().includes('/pages/elder/chat'), '点快捷入口跳到聊天页')
    const draft = await getInput(elder)
    assert(!!draft && draft.length > 2, `预设话术已填进输入框：「${draft}」`)
    assert(
      (await count(elder, '.tool-bubble')) === 0,
      '此刻没有任何工具在跑 —— 快捷入口只填话，发送键还在老人手上'
    )

    // ==================================================== 第 3 幕 · 旗舰场景
    console.log('\n== 第 3 幕 · 旗舰场景：去北京看病 ==')
    await setInput(elder, FLAGSHIP)
    assert((await getInput(elder)) === FLAGSHIP, `输入框已换成旗舰指令：「${FLAGSHIP}」`)
    await tap(elder, '.send-btn')
    console.log('  已发送，等智能体规划与扇出…')

    // 真步骤条：后端 todo 整表快照，四项文案写死在 mock 轨迹里
    await elder.waitForSelector('.plan-title', { timeout: 40000 })
    const planTitle = await elder.$eval('.plan-title', (el) => el.textContent)
    assert(planTitle.includes('办事计划'), `步骤条出现：${planTitle.trim()}`)
    const steps = await settleCount(elder, '.step-title', 4, 30000)
    assert(steps === 4, `步骤条 ${steps} 项（应 4：选医院挂号 / 查车票 / 订酒店 / 出计划书）`)

    // 子智能体回报 —— 界面上唯一看得见的扇出证据
    const reports = (await texts(elder, '.status-bubble')).filter((t) => t.includes('已经查好了'))
    assert(
      reports.some((t) => t.includes('安康助手')) && reports.some((t) => t.includes('银发导航')),
      `两支子智能体各自回报：${reports.join(' | ')}`
    )

    // 三张挂起卡 + 金额逐笔对账
    await elder.waitForSelector('.suspend-card', { timeout: 40000 })
    await settleCount(elder, '.suspend-card', 3, 40000)
    await sleep(3000) // 稳一下再数：多出第 4 张也要红，不能只防少不防多
    const cards = await count(elder, '.suspend-card')
    assert(cards === 3, `挂起卡 ${cards} 张（应 3：挂号 / 车票 / 酒店）`)
    assert(
      (await count(elder, '.suspend-card.s-pending')) === 3,
      '三张卡此刻都是 pending —— 一分钱没花，一个号没挂'
    )
    const amounts = (await texts(elder, '.suspend-card .amount'))
      .map((t) => Number((t.match(/[\d.]+/) || [0])[0]))
      .sort((a, b) => a - b)
    assert(
      JSON.stringify(amounts) === JSON.stringify([...EXPECT_AMOUNTS].sort((a, b) => a - b)),
      `卡面金额 ${amounts.join(' / ')} 元（应 ${EXPECT_AMOUNTS.join(' / ')}）`
    )
    const total = amounts.reduce((s, n) => s + n, 0)
    assert(
      Math.abs(total - EXPECT_TOTAL) < 0.01,
      `合计 ${total} 元（DEMO_SCRIPT 第 1 幕念的是 ${EXPECT_TOTAL} 元）`
    )

    // 五页计划书
    await elder.waitForSelector('.card-title', { timeout: 40000 })
    const cardTitle = (await elder.$eval('.card-title', (el) => el.textContent)).trim()
    assert(
      cardTitle.includes('张桂芳') && cardTitle.includes('就医出行计划书'),
      `计划书标题取自老人记录：${cardTitle}`
    )
    const headings = await texts(elder, '.section-heading')
    assert(headings.length === 5, `计划书 ${headings.length} 页（页序写死，应 5 页）`)
    const missingPage = EXPECT_PAGES.find((kw) => !headings.some((h) => h.includes(kw)))
    assert(
      !missingPage,
      missingPage
        ? `计划书缺了「${missingPage}」那一页，实际页名：${headings.join(' / ')}`
        : `五个页标题齐全：${headings.join(' / ')}`
    )
    const footnotes = await texts(elder, '.footnote')
    assert(
      footnotes.some((t) => t.includes('模拟接口')),
      '脚注渲染了模拟数据披露（合规要求，不是装饰）'
    )
    assert(
      footnotes.some((t) => t.includes('不构成诊断')),
      '免责声明在卡面上（R4 由代码注入，不靠模型自觉）'
    )
    await shot(elder, 'elder-chat')

    // ==================================================== 第 4 幕 · 子女确认
    console.log('\n== 第 4 幕 · 子女端确认与重放执行 ==')
    const child = await newPage(browser)
    await loginAs(child, 'child')
    assert(child.url().includes('/pages/child/dashboard'), '登录后进入子女端看板')
    assert((await count(child, '.seg-item')) === 3, '顶部分段控件三项（看板 / 守护 / 隐私），无底栏')
    assert((await visibleCount(child, TABBAR_ITEM)) === 0, '子女端页面上没有老人端那条底栏')

    const pending = await settleCount(child, '.confirm-item', 3, 25000)
    assert(pending === 3, `看板轮询出现 ${pending} 条待确认（应 3）`)
    const summaries = await texts(child, '.confirm-summary')
    console.log('  待确认：', summaries.join(' | '))
    assert(
      summaries.some((t) => /\d{4}-\d{2}-\d{2}/.test(t) || t.includes('月')),
      '摘要里是渲染过的真实日期，不是模型嘴里的 tomorrow'
    )

    await tap(child, '.confirm-item', 0)
    assert(child.url().includes('/pages/child/confirm-detail'), '下钻进入确认详情页（navigateTo）')
    const detail = (await child.$eval('.summary', (el) => el.textContent)).trim()
    console.log('  详情：', detail)
    const frozen = await child.$eval('.meta-val.mono', (el) => el.textContent)
    assert(frozen.trim().length > 2, `详情页回显冻结参数：${frozen.trim().slice(0, 48)}…`)

    await child.waitForSelector('.btn-approve', { timeout: 10000 })
    await tap(child, '.btn-approve')
    await child.waitForSelector('.announce-text', { timeout: 30000 })
    const announce = (await child.$eval('.announce-text', (el) => el.textContent)).trim()
    assert(announce.length > 5, `冻结参数重放执行成功：${announce.slice(0, 40)}…`)
    assert(
      (await count(child, '.result-text.executed')) === 1,
      '状态条是 executed（不是 failed，也不是 rejected —— 这三种结局不许合成一句）'
    )
    await shot(child, 'child-confirm')

    await child.goBack()
    const remain = await settleCount(child, '.confirm-item', 2, 20000)
    assert(remain === 2, `返回看板后剩 ${remain} 条待确认（应 2）`)

    // =================================== 第 5 幕 · 老人端那张卡就地变绿
    console.log('\n== 第 5 幕 · 老人端黄卡就地变绿 ==')
    await elder.bringToFront()
    await elder.waitForSelector('.suspend-card.s-executed', { timeout: 25000 })
    const green = await count(elder, '.suspend-card.s-executed')
    const stillPending = await count(elder, '.suspend-card.s-pending')
    assert(green === 1, `${green} 张卡变绿（家人只点了 1 条）`)
    assert(stillPending === 2, `另 ${stillPending} 张还在等 —— 不是把整屏都改了`)
    assert(
      (await count(elder, '.suspend-card')) === 3,
      '总数还是 3 张：卡是**就地改状态**，不是又推一张新卡'
    )
    const greenTitle = await elder.$eval('.suspend-card.s-executed .title', (el) => el.textContent)
    assert(
      greenTitle.includes('家人同意了'),
      `绿卡标题改成了结果口吻：${greenTitle.trim()}`
    )
    await shot(elder, 'elder-card-green')

    // ============================ 第 6 幕 · 守护 / 隐私（加分项两页）
    console.log('\n== 第 6 幕 · 行程守护与隐私分级 ==')
    await child.bringToFront() // 第 5 幕把老人端提到前台了，触摸事件要发回这一页
    if (await child.$('.trip-item')) {
      await tap(child, '.trip-item', 0)
      assert(child.url().includes('/pages/child/guardian'), '从看板下钻进入行程守护页')
      const gtext = await child.evaluate(() => document.body.innerText)
      assert(
        gtext.includes('位置记录') || gtext.includes('轨迹') || gtext.includes('行程'),
        '守护页渲染（路线 + 位置时间线）'
      )
      await child.goBack()
      await sleep(1500)
    } else {
      skip('看板没有行程条目 —— 本轮旗舰流程没落 trips，守护页改用 routes_guardian 的接口测')
    }

    await tap(child, '.seg-item', 2)
    assert(child.url().includes('/pages/child/privacy'), '分段控件切到隐私权限页（reLaunch）')
    const ptext = await child.evaluate(() => document.body.innerText)
    assert(
      ptext.includes('位置权限') && ptext.includes('健康权限'),
      '隐私分级两组开关都在（位置 / 健康）'
    )
    assert(
      (await count(child, '.level')) === 6,
      '每组三档共 6 个档位（位置 realtime/city/off、健康 full/summary/off）'
    )
    assert(
      (await count(child, '.level.active')) === 2,
      '两组各有且只有一个档位是选中态 —— 界面不能同时宣称两个权限档'
    )

    // ============================================================ 收尾
    console.log('\n== 结果 ==')
    console.log(`🎉 ${passed} 条断言全绿：模糊指令 → 规划 → 并发扇出 → 三笔拦截 →`)
    console.log('   子女确认 → 冻结重放 → 老人端就地变绿 → 守护与隐私分级')
  } finally {
    await browser.close()
  }
}

main().catch((e) => {
  console.error('\n' + (e.message || e))
  console.error(`（本次跑到第 ${passed} 条断言为止）`)
  process.exit(1)
})
