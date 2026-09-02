/**
 * 后端 HTTP 客户端（uni.request Promise 封装）。
 * 后端地址可配置：开发默认本机 FastAPI。
 */
const BASE_URL = 'http://127.0.0.1:8000'

export { BASE_URL }

export function request(method, url, data = null, opts = {}) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: BASE_URL + url,
      method,
      data,
      timeout: opts.timeout || 30000,
      header: { 'Content-Type': 'application/json' },
      success: (res) => {
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

/** 上传录音文件到 ASR 服务 */
export function uploadAudio(filePath, dialect = 'mandarin') {
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: BASE_URL + '/api/asr/upload',
      filePath,
      name: 'file',
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
