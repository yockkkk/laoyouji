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
 * 注入高德自定义 Marker 的全局样式（幂等，仅注一次）。
 *
 * 为什么不放在页面 .vue 的 <style> 里：高德的 Marker DOM 是 AMap 通过
 * document.createElement 动态插进它自己的容器的，uni-app H5 会给页面样式加
 * data-v 作用域标记（即便写了非 scoped，编译期也可能被限定域），于是
 * `.elder-map-marker` 这类选择器根本命中不到高德插进来的节点 —— 结果就是
 * 站点标签退化成没有底色、没有内边距、逐字竖排的黑色文字。
 * 这里用 JS 直接往 document.head 塞一段无作用域的 <style>，是文档级样式，
 * 一定能命中高德的 Marker 节点。长辈端与子女端两套地图的标记样式都在这里。
 */
let markerStylesInjected = false
export function ensureAmapMarkerStyles() {
  if (typeof document === 'undefined' || markerStylesInjected) return
  if (document.getElementById('amap-marker-styles')) {
    markerStylesInjected = true
    return
  }
  const style = document.createElement('style')
  style.id = 'amap-marker-styles'
  style.type = 'text/css'
  style.textContent = `
/* —— 长辈端 route-map 标记 —— */
.elder-map-marker{display:inline-block;padding:6px 14px;border-radius:20px;font-size:13px;font-weight:700;line-height:1.2;white-space:nowrap;box-shadow:0 3px 8px rgba(0,0,0,.2);border:2px solid #fff;color:#fff;pointer-events:auto;}
.elder-map-marker.badge-start{background:#10b981;}
.elder-map-marker.badge-station{background:#2563eb;}
.elder-map-marker.badge-end{background:#ef4444;}
.elder-live-pulse-marker{position:relative;width:60px;height:60px;display:flex;align-items:center;justify-content:center;}
.elder-live-pulse-marker .pulse-ring{position:absolute;width:50px;height:50px;border-radius:50%;background:rgba(232,84,30,.35);animation:elderBreathe 1.8s infinite ease-out;}
@keyframes elderBreathe{0%{transform:scale(.6);opacity:1;}100%{transform:scale(1.6);opacity:0;}}
.elder-live-pulse-marker .pulse-core{position:relative;z-index:2;background:#e8541e;color:#fff;font-size:12px;font-weight:800;line-height:1.2;padding:4px 8px;border-radius:14px;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.25);white-space:nowrap;}
/* —— 子女端 guardian 标记 —— */
.child-map-station-badge{display:inline-block;padding:4px 10px;border-radius:12px;font-size:11px;font-weight:700;line-height:1.2;color:#fff;white-space:nowrap;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.25);pointer-events:auto;}
.child-elder-breathe-marker{position:relative;width:90px;height:40px;display:flex;align-items:center;justify-content:center;}
.child-elder-breathe-marker .breathe-wave{position:absolute;width:36px;height:36px;border-radius:50%;background:rgba(37,99,235,.35);animation:childBreatheWave 1.6s infinite ease-out;}
@keyframes childBreatheWave{0%{transform:scale(.6);opacity:1;}100%{transform:scale(2.0);opacity:0;}}
.child-elder-breathe-marker .breathe-core{position:relative;z-index:2;background:#1d4ed8;color:#fff;font-size:11px;font-weight:800;line-height:1.2;padding:3px 8px;border-radius:12px;border:2px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,.3);white-space:nowrap;}
.child-offroute-marker-bubble{display:inline-block;background:#ef4444;color:#fff;font-size:11px;font-weight:800;line-height:1.2;padding:4px 10px;border-radius:14px;border:2px solid #fff;box-shadow:0 2px 8px rgba(239,68,68,.4);white-space:nowrap;animation:offrouteBounce .8s infinite alternate;}
@keyframes offrouteBounce{from{transform:translateY(0);}to{transform:translateY(-4px);}}
`
  document.head.appendChild(style)
  markerStylesInjected = true
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
