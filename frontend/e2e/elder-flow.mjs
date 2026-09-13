/**
 * 康乐 · 双端 E2E 门禁（照**现在**这份产品重写）
 *
 * 前置：
 *   后端  `cd backend && ./.venv/Scripts/python.exe -X utf8 -m uvicorn app.main:app --port 8000`
 *         （`LLM_PROVIDER=mock` + `STORAGE_BACKEND=local` 即可整条离线跑）
 *   前端  `cd frontend/laoyouji-app && npm run dev:h5` → 127.0.0.1:5174
 *   跑法  `node frontend/e2e/elder-flow.mjs`
 *
 * ---------------------------------------------------------------------------
 * 上一版这个脚本测的是**已经被砍掉的那半个产品**，照它彩排会当场翻车：
 *   · 它点 `.tab` 找底栏 —— `LyjTabBar.vue` 早删了，老人端底栏现在是 `pages.json`
 *     里的**原生 tabBar**（`.uni-tabbar__item`）。
 *   · 它断言 3 张挂起卡、金额 100 / 553.5 / 658、合计 1311.5 —— 车票和酒店
 *     （跨城就医）已经整个砍掉，**现在挂起卡一张都不该有**。
 *   · 它断言 5 页计划书 —— 现在是**4 页**。
 *   · 它断言子女端 `.seg-item` 三项、`.confirm-item` 三条待确认、`.btn-approve`
 *     批一条 —— 子女端分段控件现在是**五项**（看板/家人/通知/守护/隐私），
 *     而"待确认"这件事在产品上**不存在**：就医是**知会不审批**。
 *   · 它等 `.plan-title` / `.step-title` —— 那两个类名只活在 `StepTimeline.vue`
 *     里，而那个组件**没有任何地方 import**（死文件）。步骤条与子智能体回报
 *     现在都搬进了右侧的 `AgentExecutionTree`（手机端是抽屉）。
 *
 * ---------------------------------------------------------------------------
 * 这一版钉的是"演示当天必须成立"的八件事，每条都对应 DEMO_SCRIPT.md 里
 * 会当众念出来的一句话：
 *   1 装配自检：22 个工具、4 个 Agent（台上要念的数字，先让脚本对一遍）
 *   2 老人端首屏：大麦克风 + 4 条用药提醒；原生底栏按**文字**能切页
 *     （注意：**聊天页故意藏了底栏** —— `chat.vue` 的 `onShow` 会 `uni.hideTabBar()`，
 *      因为聊天页自带贴底输入条。离开聊天页走顶栏那个「‹ 首页」back-btn。）
 *   3 快捷入口**只把话填进输入框**，不替老人按发送
 *   4 旗舰指令 → 挂号卡（绿的、已告诉家人）+ 4 页计划书（标题带姓名、页序齐全、
 *     脚注披露模拟数据）+ 全屏 **0 张挂起卡**
 *   5 链路抽屉里是真步骤条（后端 `todo` 整表快照驱动的 4 个阶段）
 *   6 子女端**看板/通知中心都只出现「就医知会」，没有同意/拒绝按钮**
 *   7 反向链：报 138/86 → 老人听到"不用特意跑医院"，且**一个号都不挂**
 *   8 守护页 / 隐私分级两页仍在（加分项，别在收敛里被悄悄删掉）
 *
 * 一条自律：断言只写"界面上真能指出来的东西"。数字对不上就红，不许把 `>=`
 * 当护身符 —— 那样等于把台上会被戳破的差错留到台上。
 *
 * 截图落 `os.tmpdir()`（可用 `SHOT_DIR` 覆盖），不往仓库里写文件。
 */
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import puppeteer from 'puppeteer-core'

const CHROME =
  process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const APP = process.env.APP_URL || 'http://127.0.0.1:5174'
const API = process.env.API_URL || 'http://127.0.0.1:8000'
const SHOTS = process.env.SHOT_DIR || path.join(os.tmpdir(), 'kangle-e2e')

/**
 * 旗舰指令必须是**本地**就近就医。旧稿那句"我想去北京看腿疼的老毛病"不能再用了：
 * 跨城就医砍掉之后，"北京"只会被离线剧本当成目的地，整条链会演成"去北京挂号"。
 */
const FLAGSHIP = '我想在南京就近看腿疼的老毛病'

/**
 * 反向链的报数**必须写成 "138/86" 这个形式**。
 * 离线剧本的血压正则只认两个数字中间夹一个斜杠的写法（`\d{2,3}` 斜杠 `\d{2,3}`）；
 * 而首页那个「量个血压」快捷入口的预设话术是"高压 138 低压 86"（不带斜杠），
 * 剧本认不出来 → 跳过 `log_vital`/`assess_health` 直接去挂号。
 * **所以本脚本只用 `.quick-item` 验证"只填话不发送"，绝不把它发出去。**
 * （那条话术与离线剧本对不上，是产品侧的待修项，不在这份门禁里掩盖。）
 */
const CALM = '帮我记一下血压，138/86'

/** `agents/plan_builder.py` 写死的四页页序，少一页多一页都算交付物不成立。 */
const EXPECT_PAGES = [
  '第一页 · 挂号信息',
  '第二页 · 怎么去医院',
  '第三页 · 随身清单',
  '第四页 · 南京天气与穿衣',
]
const EXPECT_TOOLS = 22
const EXPECT_AGENTS = 4
/** 种子（seed_demo + 康乐人物档案）合计 4 条 active 用药计划。 */
const EXPECT_MEDS = 4
/** 子女端顶部分段控件五项，顺序即产品导航模型。 */
const EXPECT_SEGMENTS = ['看板', '家人', '通知', '守护', '隐私']
/** 老人端原生底栏四项（`pages.json` tabBar）。 */
const EXPECT_TABS = ['首页', '聊天', '吃药', '我的']

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
 * 先 scrollIntoView 再量坐标：420×900 的视口装不下整张计划书，
 * 目标在折线以下时 getBoundingClientRect 给的 y 会超出视口，触摸落在空处 ——
 * 表现是"点了没反应"，很容易误判成前端 bug。
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
        '   **不要**改成用 URL 直接跳页绕过去 —— 那样测的就不是导航模型了。'
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

async function pageText(page) {
  return page.evaluate(() => document.body.innerText)
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
  // 页面错误只打印、不判红：它可能是产品侧噪声，也可能是真崩溃。这里把它压成
  // **一行可读文本** —— 直接印 `e.message` 会得到一句 "Object"，彩排的人看不出
  // 是框架噪声还是自己的改动炸了。
  //
  // 目前已知的一条噪声（产品侧、不是本门禁的事）：离开聊天页时 `chat.vue` 的
  // `goBack()` 调 `uni.showTabBar()`，uni-app H5 会以**非 Error 对象 reject**，
  // 而模板里那个 `try { … } catch {}` 接不住 Promise 拒绝 —— 表现为控制台一条
  // 未捕获拒绝。底栏本身照常显示，不影响导航。
  page.on('pageerror', (e) => {
    const head = (e && (e.stack || e.message)) || e
    console.log('  [页面错误]', String(head).split('\n').slice(0, 2).join(' | '))
  })
  return page
}

async function loginAs(page, role) {
  await page.goto(APP + '/#/', { waitUntil: 'networkidle2' })
  // 登录页默认停在「演示一键直达」，两张角色卡：0 = 长辈，1 = 家属。
  // 走的是页面自己的快捷登录，本文件**不持有也不打印任何口令**。
  await page.waitForSelector('.role-card', { timeout: 15000 })
  await sleep(800)
  await tap(page, '.role-card', role === 'child' ? 1 : 0)
}

async function shot(page, name) {
  // 目录不一定在（换台机器、清过临时目录都会没有），先建再截 ——
  // 截图失败会直接抛出去，把一次已经跑通的链路误判成红的。
  fs.mkdirSync(SHOTS, { recursive: true })
  const p = `${SHOTS}/${name}.png`
  await page.screenshot({ path: p })
  console.log('  📸 截图：' + p)
}

/** 后端复位：`scenario` 认 ASCII key（中文档位在 Windows 控制台容易乱码）。 */
async function seed(scenario) {
  const url = scenario ? `${API}/api/seed?scenario=${scenario}` : `${API}/api/seed`
  const res = await fetch(url, { method: 'POST' }).then((r) => r.json())
  return res
}

async function main() {
  // ======================================================== 第 0 幕 · 装配自检
  console.log('== 第 0 幕 · 后端自检与演示数据复位 ==')
  const health = await fetch(API + '/api/health').then((r) => r.json())
  const len = (x) => (Array.isArray(x) ? x.length : Number(x) || 0)
  assert(health.ok === true, `/api/health ok:true（storage=${health.providers?.storage}）`)
  assert(
    len(health.tools) === EXPECT_TOOLS,
    `工具 ${len(health.tools)} 个（应 ${EXPECT_TOOLS}，台上要念这个数；旧稿写的 23 已经不对）`
  )
  assert(
    len(health.agents) === EXPECT_AGENTS,
    `Agent ${len(health.agents)} 个（应 ${EXPECT_AGENTS}：main/travel/health/community）`
  )
  await seed() // 不传 scenario：走默认档 hypertension_spike（178/105）
  console.log('  演示数据已复位（张桂芳 / 李明 + 4 条用药计划 + 隐私配置，默认档建议就医）')

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-gpu',
      '--window-size=420,900',
      // 老人端那一页在后台等结果，别让 Chrome 把它的轮询降频掉
      '--disable-backgrounding-occluded-windows',
      '--disable-renderer-backgrounding',
    ],
  })

  try {
    // ==================================================== 第 1 幕 · 老人端首屏
    console.log('\n== 第 1 幕 · 老人端首屏与原生底栏 ==')
    const elder = await newPage(browser)
    await loginAs(elder, 'elder')
    assert(elder.url().includes('/pages/elder/home'), '登录后进入老人端首页')

    assert((await count(elder, '.mic-zone')) === 1, '120px 大麦克风在首屏（不用先进聊天页）')
    assert((await count(elder, '.health-entry')) === 1, '「我的健康」入口在首屏（健康页不进 tabBar，从这儿进）')

    await elder.waitForSelector('.reminder-card', { timeout: 15000 })
    const medRows = await texts(elder, '.med-row')
    const medDrugs = await texts(elder, '.med-drug')
    assert(
      medRows.length === EXPECT_MEDS,
      `今日提醒 ${medRows.length} 条用药计划（基础 2 条 + 康乐档案 2 条 = ${EXPECT_MEDS}）`
    )
    assert(
      medDrugs.join(' ').includes('钙片') && medDrugs.join(' ').includes('二甲双胍缓释片'),
      '基础药与档案药都渲染出来了：' + medDrugs.join(' / ')
    )

    // 原生底栏：按文字切页，切过去还能切回来。
    // **故意不拿「聊天」做这一测**：`chat.vue` 的 `onShow` 会 `uni.hideTabBar()`
    // （聊天页自带贴底输入条，底栏留着会压住它），底栏在聊天页是**设计上隐藏**的，
    // 触控点根本不在页面上。真实离开聊天页的路是顶栏那个「‹ 首页」back-btn，
    // 放在第 2 幕单独走一遍。
    const tabLabels = await texts(elder, TABBAR_ITEM)
    assert(
      EXPECT_TABS.every((t) => tabLabels.some((l) => l.includes(t))),
      `原生底栏四项齐全：${tabLabels.join(' / ')}`
    )
    await tapTab(elder, '吃药')
    assert(elder.url().includes('/pages/elder/medications'), '点底栏「吃药」进入吃药页（原生 tabBar）')
    await tapTab(elder, '首页')
    assert(elder.url().includes('/pages/elder/home'), '点底栏「首页」回到首页')

    // ============================== 第 2 幕 · 快捷入口只填话，不替老人发送
    console.log('\n== 第 2 幕 · 快捷入口的交接（不许自动发送）==')
    const quicks = await texts(elder, '.quick-item')
    assert(quicks.length === 4, `首页快捷入口 ${quicks.length} 个（应 4）：${quicks.join(' / ')}`)
    await tap(elder, '.quick-item', 0)
    assert(elder.url().includes('/pages/elder/chat'), '点快捷入口跳到聊天页')
    const draft = await getInput(elder)
    assert(!!draft && draft.length > 2, `预设话术已填进输入框：「${draft}」`)
    assert(
      (await count(elder, '.card-wrap')) === 0 && (await count(elder, '.suspend-card')) === 0,
      '此刻没有任何卡片冒出来 —— 快捷入口只填话，发送键还在老人手上'
    )

    // 离开聊天页的真实路径：顶栏「‹ 首页」back-btn（`goBack()` 会先 showTabBar 再回退）。
    // 走一遍，再点快捷入口回来 —— 底栏在聊天页是隐藏的，这条才是老人真按得到的那条路。
    await tap(elder, '.back-btn')
    assert(
      elder.url().includes('/pages/elder/home'),
      '聊天页顶栏「‹ 首页」能回到首页（底栏在聊天页被 onShow 主动藏起，点不到）'
    )
    await tap(elder, '.quick-item', 0)
    assert(elder.url().includes('/pages/elder/chat'), '再点快捷入口回到聊天页')

    // ==================================================== 第 3 幕 · 旗舰链
    console.log('\n== 第 3 幕 · 旗舰链：本地就近就医（挂号 → 知会 → 四页计划书）==')
    await setInput(elder, FLAGSHIP)
    assert((await getInput(elder)) === FLAGSHIP, `输入框已换成旗舰指令：「${FLAGSHIP}」`)
    await tap(elder, '.send-btn')
    console.log('  已发送，等智能体规划与扇出…')

    // 挂号卡 —— 它是绿的（就医不需要谁点头），不是黄色待确认
    await elder.waitForSelector('.card-wrap', { timeout: 60000 })
    await sleep(4000) // 等交付物齐：先来的可能是天气/路线那张，计划书在后
    const cardTitles = await texts(elder, '.card-title')
    console.log('  已出现的卡片：', cardTitles.join(' | '))
    assert(
      !cardTitles.some((t) => t.includes('待确认')),
      '卡片标题里没有"待确认"这种口吻'
    )

    // 计划书：标题带姓名、页徽章写 4 页
    // 注意：拨号卡/菜谱卡也有 `.card-title` 却没有 `.card-wrap`，
    // 所以定位计划书**按 `.card-wrap` 的整卡文字**找，不按 `.card-title` 的下标找。
    const cardTexts = await texts(elder, '.card-wrap')
    const planIdx = cardTexts.findIndex((t) => t.includes('就医出行计划书'))
    assert(planIdx >= 0, `出现了就医出行计划书（现有卡片：${cardTexts.map((t) => t.slice(0, 18)).join(' / ')}）`)
    const planTitle = (await texts(elder, '.card-title')).find((t) => t.includes('就医出行计划书'))
    assert(
      planTitle.includes('张桂芳') && planTitle.includes('南京'),
      `计划书标题取自老人记录与本市目的地：${planTitle}`
    )
    const badges = await texts(elder, '.page-badge')
    assert(
      badges.some((b) => b.replace(/\s/g, '').includes('共4页')),
      `页徽章写着「共 4 页」（跨城那套砍掉后是 4 页，旧稿的 5 页已作废）：${badges.join(' / ')}`
    )

    // 展开计划书正文：四个页标题、每格都有值（或明写"待补"）、脚注披露模拟数据
    await tap(elder, '.card-head', planIdx)
    const headings = await texts(elder, '.section-heading')
    assert(headings.length === 4, `计划书 ${headings.length} 页（应 4）`)
    const missingPage = EXPECT_PAGES.find((kw) => !headings.some((h) => h.includes(kw)))
    assert(
      !missingPage,
      missingPage
        ? `计划书缺了「${missingPage}」那一页，实际页名：${headings.join(' / ')}`
        : `四个页标题齐全且页序一致：${headings.join(' / ')}`
    )
    const rows = await texts(elder, '.row .val')
    assert(rows.length > 0, `计划书铺开了 ${rows.length} 个字段格`)
    const blanks = rows.filter((v) => !v || v === '待补').length
    console.log(`  其中"待补" ${blanks} 格（取不到就明写待补，绝不编 —— 这是设计，不是缺陷）`)

    const footnotes = await texts(elder, '.footnote')
    assert(
      footnotes.some((t) => t.includes('模拟接口')),
      '脚注渲染了模拟数据披露（合规要求，不是装饰）'
    )
    assert(
      footnotes.some((t) => t.includes('不构成诊断')),
      '计划书卡脚含 plan_builder.DISCLAIMER（「不构成诊断意见」），随卡数据下发'
        + '（chat.vue 的 _toCard 把 d.disclaimer 推进 notes，PlanCard 以 .footnote 渲染）'
        + '—— 不是 R4（HealthDisclaimerGuard）注入的'
    )
    await shot(elder, 'elder-flagship')

    // 全屏 0 张挂起卡 —— "就医不需要子女审批"在界面上的样子
    assert(
      (await count(elder, '.suspend-card')) === 0,
      '老人端 0 张挂起卡（看病不用等谁点头；旧稿那 3 张黄卡已随审批链一起砍掉）'
    )

    // ======================== 第 4 幕 · 链路抽屉：真步骤条（后端整表快照）
    console.log('\n== 第 4 幕 · 智能体执行链路抽屉 ==')
    assert(
      (await count(elder, '.mobile-drawer-panel')) === 0,
      '抽屉默认是收起的（步骤条与子智能体回报不进老人主对话流）'
    )
    await tap(elder, '.tree-toggle-btn')
    await elder.waitForSelector('.mobile-drawer-panel', { timeout: 10000 })
    // 链路树在 DOM 里有**两份**：桌面分屏那一份用 `v-show` 挂着（手机端 `display:none`
    // 但仍在 DOM 里），抽屉这一份用 `v-if`。裸选 `.step-chip` 会把两份一起数进来
    // （4 + 4 = 8）。所以这一整幕的断言一律**钉在抽屉里**，不用全局选择器，
    // 也不用 `visibleCount` 那种"靠样式猜"的写法。
    const inDrawer = (sel) => `.mobile-drawer-panel ${sel}`
    const steps = await settleCount(elder, inDrawer('.step-chip'), 4, 20000)
    assert(steps === 4, `步骤条 ${steps} 项 —— 后端 todo_write 的整表快照，四项都在`)
    const stepNames = await texts(elder, inDrawer('.step-name'))
    assert(
      stepNames.some((n) => n.includes('挂号')) && stepNames.some((n) => n.includes('计划书')),
      `步骤文案与 mock 轨迹一致：${stepNames.join(' ➔ ')}`
    )
    const doneSteps = await count(elder, inDrawer('.step-completed'))
    assert(doneSteps === 4, `4/4 步全部 completed（交付物就绪后第 4 步由卡片就绪态补上）`)
    assert(
      (await count(elder, inDrawer('.subagent-branch-card'))) === 5,
      '链路图上共 5 张分支卡：三个真子 Agent（安康助手 / 银发导航 / 邻里帮）+ 两条非 Agent 环节（安全网关 = 后置过滤、交付聚合 = plan_builder 纯函数模块）'
    )
    assert(
      (await count(elder, inDrawer('.health-branch.is-active-branch'))) === 1 &&
        (await count(elder, inDrawer('.travel-branch.is-active-branch'))) === 1,
      '安康助手与银发导航两条分支同时激活 —— 并行派发不是串行代办'
    )
    await shot(elder, 'elder-tree')
    await tap(elder, inDrawer('.close-drawer-btn'))

    // ==================================================== 第 5 幕 · 子女端
    console.log('\n== 第 5 幕 · 子女端：只出现「就医知会」，没有同意/拒绝 ==')
    const child = await newPage(browser)
    await loginAs(child, 'child')
    assert(child.url().includes('/pages/child/dashboard'), '登录后进入子女端看板')
    const segs = await texts(child, '.seg-item')
    assert(
      segs.length === EXPECT_SEGMENTS.length &&
        EXPECT_SEGMENTS.every((s) => segs.some((t) => t.includes(s))),
      `顶部分段控件五项（看板/家人/通知/守护/隐私），无底栏：${segs.join(' / ')}`
    )
    assert((await visibleCount(child, TABBAR_ITEM)) === 0, '子女端页面上没有老人端那条底栏')

    const noticeTitles = await settleCount(child, '.notice-title', 1, 25000)
    // 等值，不是 >=1。这是子女端**唯一**一条知会计数断言，而"同一笔挂号重复下一遍
    // 不叠第二张卡"正是靠它挡的：写成 >=1 的话，幂等回归（叠出第二条知会）在 E2E
    // 这一侧完全测不出来 —— 冒烟脚本那边是等值，两边口径必须一致。
    assert(noticeTitles === 1, `看板「就医知会」恰好 ${noticeTitles} 条（幂等：重复挂号不叠卡）`)
    const nTitle = (await texts(child, '.notice-title'))[0]
    const nSummary = (await texts(child, '.notice-summary'))[0] || ''
    console.log('  知会：', nTitle)
    console.log('  正文：', nSummary)
    assert(nTitle.startsWith('【就医知会】'), `知会标题一眼分得清「知道」和「待办」：${nTitle}`)
    assert(
      nSummary.includes('挂号费') && nSummary.includes('分诊'),
      '知会正文完整（哪天 / 哪家医院 / 哪位医生 / 多少钱 / 为什么去 / 分诊档位）'
    )
    assert(
      (await count(child, '.notice-foot-text')) === 1,
      '看板自己写明"这不是待办、不用您点"（把误读拦在界面上）'
    )
    assert(
      (await count(child, '.approve-btn')) === 0 && (await count(child, '.reject-btn')) === 0,
      '看板上没有任何同意 / 拒绝按钮 —— 就医不需要子女审批'
    )
    await shot(child, 'child-dashboard')

    // 通知中心：知会进「长辈动态通知」，不进「待我确认」
    await tap(child, '.seg-item', 2)
    assert(child.url().includes('/pages/child/notification'), '分段控件切到通知中心')
    await settleCount(child, '.notif-item', 1, 20000)
    const notifTitles = await texts(child, '.notif-title')
    assert(
      notifTitles.some((t) => t.includes('就医知会')),
      `通知中心出现同一条知会：${notifTitles.join(' | ')}`
    )
    const notifBody = (await texts(child, '.notif-body')).join(' ')
    assert(notifBody.includes('挂号费'), `通知正文带着完整就诊情况：${notifBody.slice(0, 60)}…`)
    await sleep(1500)
    assert(
      (await count(child, '.confirm-card')) === 0,
      '「待我确认」是空的：全程 0 张挂起卡（`confirmation_tasks` 表就是空的）'
    )
    assert(
      (await count(child, '.approve-btn')) === 0 && (await count(child, '.reject-btn')) === 0,
      '通知中心也没有任何同意 / 拒绝入口'
    )

    // ====================== 第 6 幕 · 反向链：保健档不去医院
    console.log('\n== 第 6 幕 · 反向链：报 138/86 → 不吃撵人那一套 ==')
    // 先切回 stable 档：档案本身是 138/86，同一套分诊代码该给出「保健」。
    // 换档 = 复位全库，老人手上这一页的会话 id 随之作废 —— 所以**重开一页**，
    // 让 chat 页自己发现"这个会话在服务端没了"并开一段新会话（那条兜底路径
    // 本来就在代码里，顺手一起验）。
    await seed('stable')
    const elder2 = await newPage(browser)
    await loginAs(elder2, 'elder')
    await tapTab(elder2, '聊天')
    assert(elder2.url().includes('/pages/elder/chat'), '换档后重进聊天页（旧会话 id 自动作废）')
    // 默认是「按住说话」；打字入口要么由快捷入口带出来，要么手点这个切换条 ——
    // 麦克风被拒时的兜底就是它，所以这里点它、而不是绕过它。
    await tap(elder2, '.mode-btn')
    await setInput(elder2, CALM)
    assert((await getInput(elder2)) === CALM, `打字入口可用，已填入「${CALM}」`)
    await tap(elder2, '.send-btn')
    console.log('  已发送，等分诊…')

    const calmText = await waitForText(elder2, '不用特意跑医院', 60000)
    assert(calmText, '老人听到「不用特意跑医院」（138/86 落在保健档）')
    const bubbles = await texts(elder2, '.bubble .text')
    assert(
      bubbles.some((b) => b.includes('记好了') || b.includes('挺稳')),
      `稳定档的定稿口吻：${bubbles.slice(-2).join(' | ').slice(0, 80)}`
    )
    assert(
      (await count(elder2, '.card-wrap')) === 0 && (await count(elder2, '.suspend-card')) === 0,
      '保健档**一张卡都不出**：不挂号、不给子女写知会'
    )
    await shot(elder2, 'elder-calm')

    // 子女端也该是干净的：`/api/seed` 是**整库复位**，上一轮那条知会已经随复位清掉；
    // 而这一轮的登录态也是复位前签发的，所以**重新登录一次**再问 ——
    // 拿到的必须是新库里的事实，不能靠一个作废会话的缓存下结论。
    const child2 = await newPage(browser)
    await loginAs(child2, 'child')
    await sleep(4000)
    const stillNotifs = await count(child2, '.notice-title')
    console.log(`  复位并重新登录后，子女端就医知会 ${stillNotifs} 条`)
    assert(
      stillNotifs === 0,
      '保健档**没有**给子女写知会（复位后仍是 0 条）—— 见数不撵人，也不惊动家人'
    )
    assert(
      (await count(child2, '.approve-btn')) === 0 && (await count(child2, '.reject-btn')) === 0,
      '子女端依然没有任何同意 / 拒绝入口'
    )

    // ====================== 第 7 幕 · 守护 / 隐私（加分项，别被收敛删掉）
    console.log('\n== 第 7 幕 · 守护与隐私分级 ==')
    await tap(child2, '.seg-item', 2)
    assert(child2.url().includes('/pages/child/notification'), '分段控件切到通知中心')
    await sleep(2000)
    assert(
      (await count(child2, '.confirm-card')) === 0,
      '通知中心「待我确认」是空的 —— 全程 0 张挂起卡'
    )

    await tap(child2, '.seg-item', 3)
    assert(child2.url().includes('/pages/child/guardian'), '分段控件切到守护页')
    const gtext = await pageText(child2)
    assert(
      gtext.includes('守护行程') || gtext.includes('行程') || gtext.includes('位置'),
      '守护页渲染（行程选择器 / 轨迹 / 位置时间线）'
    )

    await tap(child2, '.seg-item', 4)
    assert(child2.url().includes('/pages/child/privacy'), '分段控件切到隐私权限页')
    const ptext = await pageText(child2)
    assert(
      ptext.includes('位置权限') && ptext.includes('健康权限'),
      '隐私分级两组开关都在（位置 / 健康）'
    )
    assert(
      (await count(child2, '.level')) === 6,
      '每组三档共 6 个档位（位置 realtime/city/off、健康 full/summary/off）'
    )
    assert(
      (await count(child2, '.level.active')) === 2,
      '两组各有且只有一个档位是选中态 —— 界面不能同时宣称两个权限档'
    )

    // ============================================================ 收尾
    console.log('\n== 结果 ==')
    console.log(`🎉 ${passed} 条断言全绿：装配自检 → 首屏与原生底栏 → 快捷入口交接 →`)
    console.log('   旗舰链（挂号卡 + 4 页计划书 + 0 挂起卡）→ 链路抽屉真步骤条 →')
    console.log('   子女端只读知会 → 反向链不就医 → 守护与隐私分级')
  } finally {
    await browser.close()
  }
}

/**
 * 轮询整页文字里有没有某句话 —— SSE 是流式的，卡片/定稿什么时候到不由我们定。
 * 找到就返回那句话所在的整段，找不到返回空串（由调用方 assert 判红）。
 */
async function waitForText(page, needle, timeoutMs) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeoutMs) {
    const t = await pageText(page).catch(() => '')
    if (t.includes(needle)) return t
    await sleep(1000)
  }
  return ''
}

main().catch((e) => {
  console.error('\n' + (e.message || e))
  console.error(`（本次跑到第 ${passed} 条断言为止）`)
  process.exit(1)
})
