/**
 * 地图加载与辅助工具库（Leaflet + 高德栅格瓦片方案）
 *
 * 为什么不再用高德 JS SDK：本机浏览器连不上高德「控制面」域名
 * （jsapi.amap.com/web/init、vdata.amap.com/style、restapi.amap.com），
 * SDK 在贴底图前的鉴权/取样式请求被直接 reset，于是「有路线折线、没有底图」
 * —— 正是之前整片灰白的现象。而高德「数据面」的栅格瓦片域名
 * wprd0{1..4}.is.autonavi.com 可以直连，所以改用 Leaflet 直接贴高德栅格瓦片，
 * 既绕开了断掉的控制面，又保留「高德地图 © AutoNavi」的底图与品牌。
 *
 * 坐标基准：高德栅格瓦片是 GCJ-02；后端高德 webservice 返回的经纬度也是 GCJ-02，
 * 两者同基准，Leaflet（Web 墨卡托）直接用即可，无需 WGS84↔GCJ-02 转换。
 * 注意：Leaflet 用 [lat, lng] 顺序，与高德 [lng, lat] 相反，统一走 toLeafletLatLng 翻转。
 */

// 高德凭据（保留：后端与潜在 REST 调用仍用同一套 Key/安全码；前端底图已改走瓦片直连）
export const AMAP_JS_KEY = '706804e5a0a33cdf140126d75bedd3ac'
export const AMAP_SECURITY_CODE = '6c6e8eddf72527878c4eb76d7273e380'

// 高德栅格瓦片（数据面，可直连）。style=7 标准路网图，size=1/scl=1 为 256px 瓦片，lang=zh_cn 中文注记。
export const AMAP_RASTER_TILE_URL =
  'https://wprd0{s}.is.autonavi.com/appmaptile?x={x}&y={y}&z={z}&lang=zh_cn&size=1&scl=1&style=7'
export const AMAP_TILE_SUBDOMAINS = ['1', '2', '3', '4']
export const AMAP_TILE_ATTRIBUTION = '高德地图 © AutoNavi'

// Leaflet 运行时（公共 CDN cdnjs，本机可直连；诊断已验证能出图）
export const LEAFLET_CSS_URL = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css'
export const LEAFLET_JS_URL = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js'

let leafletLoadPromise = null

/**
 * 动态加载 Leaflet（CSS + JS，幂等）。
 * 修复旧 loadAMap 的坑：加载失败后不再缓存「被拒 Promise」，允许「重试」按钮
 * 直接重装，不必刷新整页。
 */
export function loadLeaflet() {
  if (typeof window === 'undefined') {
    return Promise.reject(new Error('非浏览器环境无法加载 Leaflet 地图库'))
  }
  if (window.L) {
    return Promise.resolve(window.L)
  }
  if (leafletLoadPromise) {
    return leafletLoadPromise
  }

  const promise = new Promise((resolve, reject) => {
    // 样式表（幂等）
    if (!document.getElementById('leaflet-css')) {
      const link = document.createElement('link')
      link.id = 'leaflet-css'
      link.rel = 'stylesheet'
      link.href = LEAFLET_CSS_URL
      document.head.appendChild(link)
    }

    // 已有脚本在加载中：轮询等待 window.L
    const existing = document.querySelector('script[data-leaflet]')
    if (existing) {
      let checkCount = 0
      const timer = setInterval(() => {
        if (window.L) {
          clearInterval(timer)
          resolve(window.L)
        } else if (++checkCount > 80) {
          clearInterval(timer)
          reject(new Error('Leaflet 脚本加载超时'))
        }
      }, 100)
      return
    }

    const script = document.createElement('script')
    script.src = LEAFLET_JS_URL
    script.async = true
    script.setAttribute('data-leaflet', '1')
    script.onload = () => {
      if (window.L) resolve(window.L)
      else reject(new Error('Leaflet 脚本已加载但 L 对象不存在'))
    }
    script.onerror = () => reject(new Error('Leaflet 脚本网络请求失败'))
    document.head.appendChild(script)
  })

  leafletLoadPromise = promise
  // 失败即清缓存并摘掉坏脚本，让重试能重新走一遍完整加载
  promise.catch(() => {
    leafletLoadPromise = null
    const s = document.querySelector('script[data-leaflet]')
    if (s && !window.L) s.remove()
  })
  return leafletLoadPromise
}

/**
 * 高德 [lng, lat] / {lng, lat} → Leaflet [lat, lng]。
 * 全项目坐标都以高德顺序存储，贴到 Leaflet 前统一在这里翻转，避免各处手滑写反。
 */
export function toLeafletLatLng(p) {
  if (!p) return null
  if (Array.isArray(p)) return [p[1], p[0]]
  return [p.lat, p.lng]
}

/**
 * 生成承载自定义 HTML 的 Leaflet DivIcon。
 * className 统一叠加 lyj-divicon（透明底、flex 居中、overflow 可见），
 * 这样即便药丸文字比 iconSize 宽，也会以中心对齐锚点、完整显示不被裁切。
 */
export function makeMapMarkerIcon(L, { html, className = '', size = [40, 40], anchor } = {}) {
  const w = size[0]
  const h = size[1]
  return L.divIcon({
    html,
    className: ('lyj-divicon ' + className).trim(),
    iconSize: [w, h],
    iconAnchor: anchor || [Math.round(w / 2), Math.round(h / 2)],
  })
}

/**
 * 注入地图自定义 Marker 的全局样式（幂等，仅注一次）。
 *
 * 为什么不放在页面 .vue 的 <style> 里：地图库的标记 DOM（Leaflet DivIcon）是
 * 运行时插进地图自己的图层容器里的，uni-app H5 会给页面样式加 data-v 作用域标记
 * （即便写了非 scoped，编译期也可能被限定域），于是 `.elder-map-marker` 这类
 * 选择器根本命中不到地图插进来的节点 —— 结果就是站点标签退化成没有底色、没有
 * 内边距、逐字竖排的黑色文字。这里用 JS 直接往 document.head 塞一段无作用域的
 * <style>，是文档级样式，一定能命中标记节点。长辈端与子女端两套地图共用这份样式。
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
/* —— Leaflet DivIcon 容器复位（去掉默认白底/边框，改为透明并居中承载自定义内容）—— */
.leaflet-div-icon{background:transparent;border:0;}
.lyj-divicon{background:transparent;border:0;display:flex;align-items:center;justify-content:center;overflow:visible;}
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
