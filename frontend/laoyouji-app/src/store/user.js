/**
 * 登录态管理：User 信息与 Bearer Token 持久化。
 */
const USER_KEY = 'lyj_user'
const TOKEN_KEY = 'lyj_token'
const REFRESH_KEY = 'lyj_refresh_token'

export function getCurrentUser() {
  try {
    const raw = uni.getStorageSync(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch (e) {
    return null
  }
}

export function setCurrentUser(user) {
  uni.setStorageSync(USER_KEY, JSON.stringify(user))
}

export function getAccessToken() {
  return uni.getStorageSync(TOKEN_KEY) || ''
}

export function getRefreshToken() {
  return uni.getStorageSync(REFRESH_KEY) || ''
}

export function setAuthSession({ user, access_token, refresh_token }) {
  if (user) setCurrentUser(user)
  if (access_token) uni.setStorageSync(TOKEN_KEY, access_token)
  if (refresh_token) uni.setStorageSync(REFRESH_KEY, refresh_token)
}

export function clearCurrentUser() {
  uni.removeStorageSync(USER_KEY)
  uni.removeStorageSync(TOKEN_KEY)
  uni.removeStorageSync(REFRESH_KEY)
  uni.removeStorageSync('lyj_family')
}

export function isLoggedIn() {
  return !!(getCurrentUser() && getAccessToken())
}
