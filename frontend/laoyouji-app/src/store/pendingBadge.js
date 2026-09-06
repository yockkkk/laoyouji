/**
 * 子女端"有新的高危操作待审批"提醒（角标 + 震动）。
 *
 * 这是搬家丢掉的能力的接替：原来 dashboard 轮询里 pending.length 变多就
 * uni.vibrateShort()，待确认列表搬去通知页后没人再接 —— 子女不主动点开
 * 通知页就不知道家里老人在等他点头。
 *
 * 设计：dashboard 的 5s 轮询和通知页的 loadAll 都调 publishPendingCount，
 * 数量变多 → 震动（不分页面，在哪一侧都该知道）；数量变化 → 写 storage
 * 并广播事件，LyjSegment 在"通知"项上画未读角标。
 */

const STORAGE_KEY = 'laoyouji_pending_count'
export const PENDING_EVENT = 'lyj-pending-count'

/** 发布最新待确认数。变多震动，变了就广播；没变什么都不做。 */
export function publishPendingCount(n) {
  const count = Number(n) || 0
  let prev = 0
  try {
    prev = Number(uni.getStorageSync(STORAGE_KEY)) || 0
  } catch (e) {
    /* storage 不可用时 prev 按 0 走 */
  }
  if (count === prev) return
  try {
    uni.setStorageSync(STORAGE_KEY, count)
  } catch (e) {}
  uni.$emit(PENDING_EVENT, count)
  if (count > prev) {
    try {
      uni.vibrateShort && uni.vibrateShort()
    } catch (e) {
      /* H5 不支持震动，静默 */
    }
  }
}

/** 组件挂载时读一次快照（事件只推变化，挂载晚的组件需要初始值）。 */
export function readPendingCount() {
  try {
    return Number(uni.getStorageSync(STORAGE_KEY)) || 0
  } catch (e) {
    return 0
  }
}
