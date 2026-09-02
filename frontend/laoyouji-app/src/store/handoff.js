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
let pending = null

/**
 * 放一句话进交接位。
 * @param {string} text 要交给聊天页的文字
 * @param {boolean} autoSend true = 直接发给老友记；false = 只填进输入框等老人确认
 */
export function putUtterance(text, autoSend) {
  const t = (text || '').trim()
  if (!t) return
  pending = { text: t, autoSend: !!autoSend }
}

/** 取走并清空。取不到返回 null。**只能被消费一次。** */
export function takeUtterance() {
  const p = pending
  pending = null
  return p
}
