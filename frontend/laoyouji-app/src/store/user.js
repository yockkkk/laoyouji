/**
 * 登录态（演示级）：本地存储当前角色与家庭成员信息。
 * 竞赛原型不做真实鉴权；正式落地对接微信/手机号登录。
 */
const KEY = 'lyj_user'

export function getCurrentUser() {
  try {
    const raw = uni.getStorageSync(KEY)
    return raw ? JSON.parse(raw) : null
  } catch (e) {
    return null
  }
}

export function setCurrentUser(user) {
  uni.setStorageSync(KEY, JSON.stringify(user))
}

export function clearCurrentUser() {
  uni.removeStorageSync(KEY)
}

/** 拉取演示家庭（后端 /api/demo/family）。 */
export async function loadDemoFamily(get) {
  const d = await get('/api/demo/family')
  return {
    elders: d.elders || [],
    children: d.children || [],
  }
}
