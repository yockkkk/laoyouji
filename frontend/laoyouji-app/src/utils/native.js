/**
 * 原生提醒适配层 —— Android 壳 window.KangleNative 的 H5 侧唯一入口。
 *
 * 为什么单开一层：康乐 H5 同时跑在两种环境里 ——
 *   1) 小米真机上的康乐 App（WebView 壳），window.KangleNative 存在，能排真的系统闹钟；
 *   2) 浏览器 / 微信里直接打开，没有桥，提醒只能是"没有"。
 * 两种环境页面都要照常渲染，所以降级逻辑只在这一个文件里写一次：所有桥调用收口到 call()，
 * 拿不到桥就返回该函数的"空值形态"，绝不抛异常、绝不 console.error 刷屏（契约 §3.8）。
 *
 * 边界（照契约 §11 写，不粉饰）：
 *   - 后端没有调度器、也不推送，闹钟 100% 由手机本地排；必须先打开过一次 App 并登录过；
 *   - 拿不到 SCHEDULE_EXACT_ALARM 时走不精确路径，Doze 下可能晚几分钟 —— syncReminders
 *     的 mode 字段（"exact" / "inexact"）就是用来如实展示这件事的，别把它说成"到点必响"；
 *   - 时间是设备本地时区解释的，后端 times 是裸 "HH:MM"，从不换算成瞬时。
 *
 * 风格与 utils/amap.js 一致：全部具名导出，没有 default。
 */
import { get } from '../api/client'
import { getCurrentUser } from '../store/user'

/* 本地偏好键（契约 §10.2 冻结）。问候是纯本机定时，后端没有接口，只存这两个键。 */
const GREETING_ENABLED_KEY = 'lyj_greeting_enabled'
const GREETING_TIME_KEY = 'lyj_greeting_time'

/* times 校验正则：与 pages/elder/medications.vue:172 逐字相同的那个（契约 §0）。 */
const TIME_RE = /^([01]?\d|2[0-3]):[0-5]\d$/

/* 问候默认 08:00，与后端种子里张桂芳的用药时刻同点。 */
const GREETING_DEFAULT_TIME = '08:00'

/* 通知点击回流的目标路由（契约 §3.7 / §10.5 冻结）。 */
const DEFAULT_ROUTE = '/pages/elder/home'
const TAB_ROUTES = [
  '/pages/elder/home',
  '/pages/elder/chat',
  '/pages/elder/medications',
  '/pages/elder/profile',
]

/**
 * 引导弹层的事件名。契约把 openKeepAliveGuide() 定义为"打开 profile.vue 的引导弹层"，
 * 既没给事件常量、也没允许往导出表里加东西，所以这个字符串在 native.js 与
 * pages/elder/profile.vue 各写一份 —— 改一处必须同时改另一处。
 */
const KEEPALIVE_GUIDE_EVENT = 'kangle:keepalive-guide'

/* syncAll 的 30 秒防抖窗口（契约 §10.3）。 */
const SYNC_DEBOUNCE_MS = 30000

/** 桥不存在时的统一空值形态。每次给新对象，免得调用方改坏了共享常量。 */
function noBridge() {
  return { ok: false, reason: 'no_bridge' }
}

/**
 * 取桥对象。包 try 是因为个别 ROM 上 addJavascriptInterface 注入出来的对象
 * 连属性访问都会抛 TypeError。
 */
function bridge() {
  try {
    if (typeof window === 'undefined') return null
    return window.KangleNative || null
  } catch (e) {
    return null
  }
}

/** 唯一收口点：所有桥方法调用都从这里走，失败一律当成"桥没给结果"。 */
function call(name, ...args) {
  const b = bridge()
  if (!b || typeof b[name] !== 'function') return null
  try {
    return b[name](...args)
  } catch (e) {
    return null
  }
}

/** 桥返回的字符串一律是合法 JSON；解析不出来（含空串/null）就按"没拿到"处理。 */
function parseJson(raw) {
  if (typeof raw !== 'string' || !raw) return null
  try {
    const v = JSON.parse(raw)
    return v && typeof v === 'object' ? v : null
  } catch (e) {
    return null
  }
}

function pad2(n) {
  return String(n).padStart(2, '0')
}

/** 读本机的问候偏好。读不到就用默认值，不抛。 */
function readLocalPrefs() {
  let enabled = true
  let time = GREETING_DEFAULT_TIME
  try {
    const rawEnabled = uni.getStorageSync(GREETING_ENABLED_KEY)
    if (rawEnabled !== '' && rawEnabled !== undefined && rawEnabled !== null) {
      enabled = String(rawEnabled) !== '0'
    }
  } catch (e) {
    /* 读不到就是默认开 */
  }
  try {
    const rawTime = uni.getStorageSync(GREETING_TIME_KEY)
    if (typeof rawTime === 'string' && TIME_RE.test(rawTime)) time = rawTime
  } catch (e) {
    /* 读不到就是默认 08:00 */
  }
  return { enabled, time }
}

/**
 * 桥存在性探针。契约给的判据是 `typeof window.KangleNative !== 'undefined' && isSupported()`，
 * 这里额外把两次访问都包进 try —— 探针本身不能成为崩溃点。
 */
export function nativeSupported() {
  const b = bridge()
  if (!b) return false
  try {
    if (typeof b.isSupported === 'function') return !!b.isSupported()
    return true
  } catch (e) {
    return false
  }
}

/** 透传原生平台信息（版本/品牌/H5 地址）；无桥返回 null。 */
export function getPlatformInfo() {
  return parseJson(call('getPlatformInfo'))
}

/**
 * 声明式全量覆盖：把合成好的提醒数组整份推给原生。
 * 重复调是安全的 —— 原生侧先 cancelAll 再按这份快照重排（契约 §4.3）。
 */
export function syncReminders(list) {
  let payload = '[]'
  try {
    payload = JSON.stringify(Array.isArray(list) ? list : [])
  } catch (e) {
    return noBridge()
  }
  return parseJson(call('syncReminders', payload)) || noBridge()
}

/** 回读原生侧已存的规范形态；无桥返回空数组。 */
export function getReminders() {
  const res = parseJson(call('getReminders'))
  return res && Array.isArray(res.items) ? res.items : []
}

/** 清空原生存储 + 取消全部闹钟（退出登录 / 关闭全部提醒时调）。 */
export function cancelAll() {
  return parseJson(call('cancelAll')) || noBridge()
}

/** 只读探测各权限状态，不弹任何框 —— 用来驱动"我的"页的引导状态。 */
export function checkPermissions() {
  return parseJson(call('checkPermissions')) || noBridge()
}

/** 申请权限 / 跳设置页。name 取契约 §3.4 的取值表。异步路径，别在这里等结果。 */
export function requestPermission(name) {
  return parseJson(call('requestPermission', String(name || ''))) || noBridge()
}

/** 跳系统设置页。name 取契约 §3.4 的取值表。 */
export function openSettings(name) {
  return parseJson(call('openSettings', String(name || ''))) || noBridge()
}

/**
 * 打开 page/elder/profile.vue 里的保活引导弹层。
 * 这是纯 UI 触发：native.js 只负责发事件，弹层由页面自己渲染。
 * 没有桥就不做 —— 浏览器里本来也没有"自启动/省电白名单"可设置（契约 §3.8）。
 */
export function openKeepAliveGuide() {
  if (!nativeSupported()) return noBridge()
  try {
    uni.$emit(KEEPALIVE_GUIDE_EVENT)
  } catch (e) {
    return noBridge()
  }
  return { ok: true, opened: true }
}

/** 立刻发一条测试通知（引导页"试一下"按钮）。 */
export function notifyNow(reminder) {
  let payload = '{}'
  try {
    payload = JSON.stringify(reminder || {})
  } catch (e) {
    return noBridge()
  }
  return parseJson(call('notifyNow', payload)) || noBridge()
}

/**
 * 时段问候文案。**逐字**照抄 pages/elder/home.vue:112-119 的桶，
 * 否则首页显示"早上好"、通知弹出来却是"晚上好"，长辈会以为两次不是一回事。
 */
export function greetTextForHour(h) {
  if (!nativeSupported()) return ''
  if (h < 6) return '夜深了'
  if (h < 11) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

/**
 * 后端用药计划 → Reminder 数组（契约 §10.1，逐字实现）。
 * 入参是 GET /api/medications?with_logs=false 的 items，每项形如
 * {id, elder_id, drug_name, dose, times, notes, active}。
 * id 生成规则两端必须算出同一个：`med:<planId>:<HH>:<MM>`。
 */
export function buildMedicationReminders(items) {
  if (!nativeSupported()) return []
  const out = []
  const plans = Array.isArray(items) ? items : []
  for (const p of plans) {
    if (!p || p.active === false) continue // 软删的跳过
    const times = Array.isArray(p.times) ? p.times : []
    for (const t of times) {
      if (typeof t !== 'string' || !TIME_RE.test(t)) continue
      const parts = t.split(':')
      const hour = Number(parts[0])
      const minute = Number(parts[1])
      out.push({
        id: `med:${p.id}:${pad2(hour)}:${pad2(minute)}`,
        kind: 'medication',
        title: `该吃${p.drug_name}了`,
        // 剂量 + 医嘱拼一行；两样都没有时给一句兜底，别推一条空白通知给长辈。
        body: [p.dose, p.notes].filter(Boolean).join(' · ') || '记得按时吃药',
        hour,
        minute,
        enabled: true,
        planId: p.id,
        elderId: p.elder_id,
        repeat: 'daily',
      })
    }
  }
  return out
}

/**
 * 晨间问候 → 长度为 1 的 Reminder 数组（契约 §10.2）。
 * 注意 title 的时段桶按**配置的 hour** 算，不是按当前时间算：
 * 否则 08:00 排的闹钟在 20:00 同步时会变成"晚上好"，第二天早上弹出来就是错的。
 */
export function buildGreetingReminder(user) {
  if (!nativeSupported()) return []
  const prefs = readLocalPrefs()
  const parts = prefs.time.split(':')
  const hour = Number(parts[0])
  const minute = Number(parts[1])
  return [
    {
      id: 'greeting:morning',
      kind: 'greeting',
      title: `${greetTextForHour(hour)}，${(user && user.name) || ''}`.trim(),
      body: '今天也要好好照顾自己',
      hour,
      minute,
      enabled: prefs.enabled !== false,
      planId: null,
      elderId: (user && user.id) || null,
      repeat: 'daily',
    },
  ]
}

/**
 * 合并用药 + 问候，按 id 去重（后者覆盖前者，保留首次出现的位置），
 * 再按时刻升序返回 —— 排序只是让日志好读，原生侧不依赖顺序（契约 §10.4）。
 */
export function buildAllReminders(opts) {
  const o = opts || {}
  // o.prefs 是契约 §10.3 约定要传的，但问候读的是同一对本机键、buildGreetingReminder
  // 自己会读，所以这里不再使用它 —— 保留参数只为签名一致，传不传结果都一样。
  const merged = buildMedicationReminders(o.meds).concat(buildGreetingReminder(o.user))
  const byId = new Map()
  for (const r of merged) byId.set(r.id, r)
  const list = []
  byId.forEach((r) => list.push(r))
  return list.sort((a, b) => a.hour * 60 + a.minute - (b.hour * 60 + b.minute))
}

/* ------------------------------------------------------------------ 回流与编排 */

let actionHandler = null

/** 推（原生 __kangleNativeAction）与拉（getPendingAction）两条路共用的分发口。 */
function runAction(payload) {
  let p = payload
  if (typeof p === 'string') {
    try {
      p = JSON.parse(p)
    } catch (e) {
      return
    }
  }
  if (typeof actionHandler !== 'function') return
  try {
    actionHandler(p || {})
  } catch (e) {
    /* 页面自己的处理出错，不该把桥的回流链路带崩 */
  }
}

/**
 * 注册通知点击的回流处理。原生推送用 JSONObject.quote 转义过的 JSON 字符串调
 * window.__kangleNativeAction（契约 §3.7），这里解析成对象再交给 handler。
 */
export function onNativeAction(handler) {
  actionHandler = typeof handler === 'function' ? handler : null
  try {
    if (typeof window === 'undefined') return
    window.__kangleNativeAction = runAction
    // 拉取路径复用同一个 handler：契约 §10.5 里写作 onNativeAction._dispatch(JSON.parse(pending))
    window.__kangleNativeAction._dispatch = runAction
  } catch (e) {
    /* 没有 window 就不注册，调用点照样不报错 */
  }
}

/* 冷启动待跳路由：首个页面 onShow 时由 consumePendingRoute() 领走（契约 §3.7 回流）。 */
let pendingRoute = ''

/**
 * 按 route 跳转；**跳不动就把目标存进 pendingRoute**，留给页面 onShow 再领一次。
 *
 * 为什么必须存：冷启动时 `initNative()` 在 App.vue 的 onLaunch 里跑，早于首个页面的 onLoad，
 * uni 的页面栈还没建立，`switchTab` 这时跳不动 —— 它要么同步抛（被 try/catch 接住），
 * 要么走 fail 回调（catch 根本接不到）。而原生侧 `getPendingAction()` 取走即清，
 * 这份 payload 在本次已经被消费掉，onPageFinished 之后再来就是空串了。
 * 不存下来就没有第二次机会：点用药提醒只会把 App 开到当前 tab，打卡入口还得长辈自己找。
 *
 * 反过来也不能改成 setTimeout 稍后重跳 —— 页面栈"刚建立"时同样不可靠，让页面主动领才是稳的。
 */
function navigateToRoute(url) {
  const target = url || DEFAULT_ROUTE
  try {
    if (TAB_ROUTES.indexOf(target) >= 0) {
      uni.switchTab({
        url: target,
        fail: () => {
          pendingRoute = target
        },
      })
    } else {
      uni.navigateTo({
        url: target,
        fail: () => {
          pendingRoute = target
        },
      })
    }
  } catch (e) {
    pendingRoute = target
  }
}

/**
 * 领走冷启动待跳路由并重跳一次。在**首个页面的 onShow** 里调（此时页面栈已就绪）。
 * 没有待跳路由时什么都不做、返回空串 —— 每次回到首页都调也安全。
 */
export function consumePendingRoute() {
  const url = pendingRoute
  pendingRoute = ''
  if (url) navigateToRoute(url)
  return url
}

/* syncAll 的防抖态：防抖窗口内复用上次结果，窗口内并发则复用同一个 Promise。 */
let lastSyncAt = 0
let lastResult = null
let inflightPromise = null

/** 同步收尾：记防抖时间戳与结果，放掉并发占位（契约 §10.3 第 6 步）。 */
function finishSync(list) {
  const out = list ? syncReminders(list) : { ok: false, reason: 'network_error' }
  lastSyncAt = Date.now()
  // 失败结果不进防抖缓存。缓存的语义是"刚刚同步过、结果还有效"，一次瞬时网络抖动
  // （后端短暂 502 / 切网）显然不满足；缓存住的话这 30 秒里页面 onShow 再调 syncAll
  // 只会原样返回失败结果，长辈这半分钟里改的用药时间排不进闹钟，界面还挂着"同步失败"。
  // 置空即可让下一次调用真的重试。
  lastResult = out.ok ? out : null
  inflightPromise = null
  return out
}

/**
 * 「拉计划 + 合成 + syncReminders」的编排（契约 §10.3）。
 * 只在长辈端同步；子女端不排任何闹钟。
 *
 * `opts.force`：绕开 30 秒防抖。用户**显式改动**提醒（新增/删除用药、改问候时间）时必须传 true ——
 * 防抖窗口按"同步完成时刻"计，长辈「首页 → 吃药页 → 加一味药」的间隔通常远小于 30 秒，
 * 不绕开的话这次调用只会复用首页那次的结果，新加的这条药进不了原生副本，
 * 现场表现就是"刚加的提醒死活不响"。不带参数时行为与契约冻结的 `syncAll()` 完全一致。
 */
export function syncAll(opts) {
  const force = !!(opts && opts.force)
  const user = getCurrentUser()
  if (!user) return Promise.resolve({ ok: false, reason: 'not_logged_in' })
  // role 缺失时不拦（老数据可能没这个字段），只在明确不是长辈时退出。
  if (user.role && user.role !== 'elder') return Promise.resolve({ ok: false, reason: 'not_elder' })
  // 没有桥就什么都不做：浏览器里排不了闹钟，白跑一趟接口没意义。
  if (!nativeSupported()) return Promise.resolve({ ok: false })

  // 并发守卫放在防抖之前：同一瞬间的多次调用复用同一个请求，
  // 防抖窗口（30s）按"同步完成时刻"计，与契约 §10.3 第 6 步一致。
  // force 也不越过这里：放两个请求并发跑，先发的旧结果可能后到、把新副本覆盖回去。
  if (inflightPromise) return inflightPromise
  if (!force && lastResult && lastResult.ok && Date.now() - lastSyncAt < SYNC_DEBOUNCE_MS) {
    return Promise.resolve(lastResult)
  }

  inflightPromise = get('/api/medications', { elder_id: user.id, with_logs: false })
    .then((res) =>
      finishSync(
        buildAllReminders({
          user,
          meds: (res && res.items) || [],
          prefs: readLocalPrefs(),
        })
      )
    )
    .catch(() => finishSync(null))

  return inflightPromise
}

/**
 * App.vue onLaunch 的唯一入口。做三件事（契约 §10.5）：
 *   1) 把通知点击的回流 handler 注册上；
 *   2) 冷启动补课 —— 原生 onPageFinished 的推送可能早于 onLaunch，这里主动拉一次；
 *      原生侧取走即清，两条路不会双触发；
 *   3) 已登录就同步一次提醒（未登录直接跳过，登录后由首页/我的页再触发）。
 * 冷启动这次跳转大概率跳不动（页面栈未就绪），目标会存进 pendingRoute，
 * 由首个页面的 onShow 调 consumePendingRoute() 领走重跳。
 */
export function initNative() {
  onNativeAction((payload) => {
    navigateToRoute((payload && payload.route) || DEFAULT_ROUTE)
  })

  const pending = call('getPendingAction')
  if (typeof pending === 'string' && pending) runAction(pending)

  if (nativeSupported() && getCurrentUser()) syncAll()
}
