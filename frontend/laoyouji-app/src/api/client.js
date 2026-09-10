/**
 * 后端 HTTP 客户端（uni.request Promise 封装，自动携带 Bearer Token 与 401 刷新）。
 */
import { getAccessToken, getRefreshToken, setAuthSession, clearCurrentUser } from '../store/user'

const BASE_URL = (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_BASE_URL) || 'http://159.75.94.149:8000'
export { BASE_URL }

let refreshPromise = null

async function tryRefresh() {
  if (refreshPromise) return refreshPromise
  const refreshToken = getRefreshToken()
  if (!refreshToken) throw new Error('缺少 refresh_token')
  refreshPromise = new Promise((resolve, reject) => {
    uni.request({
      url: BASE_URL + '/api/auth/refresh',
      method: 'POST',
      data: { refresh_token: refreshToken },
      header: { 'Content-Type': 'application/json' },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300 && res.data) {
          setAuthSession(res.data)
          resolve(res.data.access_token)
        } else {
          clearCurrentUser()
          reject(new Error('刷新登录失效'))
        }
      },
      fail: (err) => {
        clearCurrentUser()
        reject(err)
      },
      complete: () => {
        refreshPromise = null
      },
    })
  })
  return refreshPromise
}

export function request(method, url, data = null, opts = {}) {
  return new Promise((resolve, reject) => {
    const token = getAccessToken()
    const header = { 'Content-Type': 'application/json' }
    if (token) {
      header['Authorization'] = `Bearer ${token}`
    }

    uni.request({
      url: BASE_URL + url,
      method,
      data,
      timeout: opts.timeout || 30000,
      header,
      success: async (res) => {
        if (res.statusCode === 401 && !opts._retry && !url.startsWith('/api/auth/')) {
          try {
            await tryRefresh()
            const retried = await request(method, url, data, { ...opts, _retry: true })
            return resolve(retried)
          } catch (e) {
            clearCurrentUser()
            uni.reLaunch({ url: '/pages/login/login' })
            return reject(new Error('登录已过期，请重新登录'))
          }
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          const detail =
            res.data && res.data.detail
              ? typeof res.data.detail === 'string'
                ? res.data.detail
                : JSON.stringify(res.data.detail)
              : `请求失败（${res.statusCode}）`
          reject(new Error(detail))
        }
      },
      fail: (err) => reject(new Error(err.errMsg || '网络不可用')),
    })
  })
}

export const get = (url, params) => {
  if (!params) return request('GET', url)
  const qs = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
    .join('&')
  return request('GET', url + (qs ? '?' + qs : ''))
}
export const post = (url, data) => request('POST', url, data)
export const put = (url, data) => request('PUT', url, data)
export const del = (url) => request('DELETE', url)

export function uploadAudio(filePath, dialect = 'mandarin') {
  return new Promise((resolve, reject) => {
    const token = getAccessToken()
    const header = {}
    if (token) header['Authorization'] = `Bearer ${token}`
    uni.uploadFile({
      url: BASE_URL + '/api/asr/upload',
      filePath,
      name: 'file',
      header,
      formData: { dialect },
      success: (res) => {
        if (res.statusCode === 200) {
          try {
            resolve(JSON.parse(res.data))
          } catch (e) {
            reject(new Error('识别结果解析失败'))
          }
        } else {
          reject(new Error('语音识别失败（' + res.statusCode + '）'))
        }
      },
      fail: (err) => reject(new Error(err.errMsg || '上传失败')),
    })
  })
}
