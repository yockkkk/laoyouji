/**
 * 页间一次性交接（老人端首页 → 聊天页）。
 *
 * 为什么不用 query 参数：`uni.switchTab` 的 url **不允许带参数**（平台限制）。
 * 首页和聊天页都进了原生 tabBar，跳转只能走 switchTab，所以原来的
 * `?quick=xxx` 通道在这次改造里必然失效，需要一个模块级的交接位。
 *
 * 故意只用模块变量、不落 storage：刷新页面就该丢掉。一句上次没送出去的话
 * 在几小时后被自动发出去，比丢掉它糟糕得多。
 */
let pendingUtterance = null
let pendingScene = null

/**
 * 放一句话进交接位（老人首页语音对讲输入）。
 * @param {string} text 要交给聊天页的文字
 * @param {boolean} autoSend true = 直接发给康乐；false = 备用
 */
export function putUtterance(text, autoSend) {
  const t = (text || '').trim()
  if (!t) return
  pendingUtterance = { text: t, autoSend: !!autoSend }
}

/** 取走语音交接并清空。**只能被消费一次。** */
export function takeUtterance() {
  const p = pendingUtterance
  pendingUtterance = null
  return p
}

/**
 * 放一个场景化快捷任务进交接位（如：看病挂号、心里闷、今天吃啥）。
 * 场景对象包含：
 * - id: 场景标识 (hospital, companion, recipe)
 * - title: 场景名称
 * - greeting: 助手温暖主动的开场白
 * - agent: 负责助理 (health, community, main)
 * - chips: 适老快捷选项胶囊列表 [{ label, text }]
 *
 * 核心设计原则：绝对不强行向老人输入框塞死板文字，而是由智能助手主动关怀，
 * 附带大字快捷胶囊供老人点按或按住语音对讲。
 */
export function putScene(scene) {
  if (!scene) return
  pendingScene = scene
}

/** 取走场景交接并清空。**只能被消费一次。** */
export function takeScene() {
  const s = pendingScene
  pendingScene = null
  return s
}
