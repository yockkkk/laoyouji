/**
 * 高德地图 JS API 2.0 异步加载与地图辅助工具库
 * 包含：
 * 1. 凭据与安全密钥预注入
 * 2. 浏览器环境动态脚本加载（全端兼容防御）
 * 3. 距离与经纬度计算工具
 */

export const AMAP_JS_KEY = '706804e5a0a33cdf140126d75bedd3ac'
export const AMAP_SECURITY_CODE = '6c6e8eddf72527878c4eb76d7273e380'

let amapLoadPromise = null

export function loadAMap() {
  if (typeof window === 'undefined') {
    return Promise.reject(new Error('非浏览器环境无法加载高德地图 JS API'))
  }

  if (window.AMap) {
    return Promise.resolve(window.AMap)
  }

  if (amapLoadPromise) {
    return amapLoadPromise
  }

  // 注入安全配置（必须在脚本加载之前）
  window._AMapSecurityConfig = {
    securityJsCode: AMAP_SECURITY_CODE,
  }

  amapLoadPromise = new Promise((resolve, reject) => {
    if (window.AMap) {
      resolve(window.AMap)
      return
    }

    const existingScript = document.querySelector('script[src*="webapi.amap.com/maps"]')
    if (existingScript) {
      let checkCount = 0
      const timer = setInterval(() => {
        if (window.AMap) {
          clearInterval(timer)
          resolve(window.AMap)
        } else if (++checkCount > 50) {
          clearInterval(timer)
          reject(new Error('高德地图脚本加载超时'))
        }
      }, 100)
      return
    }

    const script = document.createElement('script')
    script.type = 'text/javascript'
    script.src = `https://webapi.amap.com/maps?v=2.0&key=${AMAP_JS_KEY}&plugin=AMap.Scale,AMap.ToolBar,AMap.MoveAnimation`
    script.async = true
    script.onload = () => {
      if (window.AMap) {
        resolve(window.AMap)
      } else {
        reject(new Error('高德地图脚本已加载但 AMap 对象不存在'))
      }
    }
    script.onerror = (e) => {
      reject(new Error('高德地图 JS API 脚本网络请求失败'))
    }
    document.head.appendChild(script)
  })

  return amapLoadPromise
}

/**
 * 球面大圆距离（米）
 */
export function calcDistanceMeters(p1, p2) {
  if (!p1 || !p2) return Infinity
  const [lng1, lat1] = Array.isArray(p1) ? p1 : [p1.lng, p1.lat]
  const [lng2, lat2] = Array.isArray(p2) ? p2 : [p2.lng, p2.lat]
  if (lng1 == null || lat1 == null || lng2 == null || lat2 == null) return Infinity

  const R = 6371000
  const dLat = (lat2 - lat1) * (Math.PI / 180)
  const dLng = (lng2 - lng1) * (Math.PI / 180)
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * (Math.PI / 180)) * Math.cos(lat2 * (Math.PI / 180)) * Math.sin(dLng / 2) * Math.sin(dLng / 2)
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
  return R * c
}
