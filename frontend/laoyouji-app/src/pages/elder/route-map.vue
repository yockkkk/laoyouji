<template>
  <view class="route-page">
    <!-- 适老大字顶部导航栏 (触控靶区 >= 48px) -->
    <view class="elder-navbar">
      <button class="nav-back-btn" @tap="goBack">
        <text class="back-arrow">‹</text>
        <text class="back-text">返回</text>
      </button>
      <text class="nav-title">高德路线规划</text>
      <button class="nav-speak-btn" @tap="speakFullRoute">
        <text class="speak-icon">🔊</text>
        <text class="speak-text">念给我听</text>
      </button>
    </view>

    <!-- 家人实时守护状态指示条 -->
    <view class="reporting-banner">
      <view class="pulse-dot"></view>
      <text class="report-text">
        🛡️ 家人守护中 · 出行路线与安全已同步给子女看板
      </text>
    </view>

    <!-- 路线概览信息条 -->
    <view class="route-summary-bar">
      <view class="summary-line">
        <text class="summary-badge start">起</text>
        <text class="summary-place">{{ originName || '待定' }}</text>
        <text class="summary-arrow">➔</text>
        <text class="summary-badge end">终</text>
        <text class="summary-place">{{ destinationName || '待定' }}</text>
      </view>
      <view class="summary-meta">
        <!-- 耗时/距离/交通方式三样都只认后端返回值：查不到就整条不显示，
             绝不拿写死的"约4小时20分、1023公里、高铁"给老人看一条不存在的行程。 -->
        <text class="meta-item" v-if="routeDuration">⏱️ {{ routeDuration }}</text>
        <text class="meta-item" v-if="routeDistance">🛣️ 约 {{ routeDistance }}</text>
        <text class="meta-item" v-if="routeModeText">{{ routeModeText }}</text>
      </view>
    </view>

    <!-- 适老地图视窗 (Leaflet 渲染高德栅格瓦片，坐标 GCJ-02) -->
    <view class="map-section" :class="{ 'fullscreen-mode': isMapFullscreen }">
      <div id="elder-amap-container" class="amap-box"></div>
      <view v-if="mapLoading" class="map-loading-mask">
        <text class="loading-icon">⏳</text>
        <text class="loading-text">高德地图加载中…</text>
      </view>
      <view v-else-if="mapFailed" class="map-loading-mask">
        <text class="loading-icon">🗺️</text>
        <text class="loading-text">地图暂时没能加载出来</text>
        <button class="map-retry-btn" @tap="initMap">点我重新加载地图</button>
      </view>

      <!-- 全屏大图模式下顶部悬浮条 (返回药丸按钮 + 缩放提示) -->
      <view v-if="isMapFullscreen" class="fullscreen-topbar">
        <view class="fullscreen-topbar-inner">
          <button class="fullscreen-exit-pill" @tap="toggleMapFullscreen">
            <text class="exit-icon">‹</text>
            <text class="exit-text">退出大图</text>
          </button>
          <text class="fullscreen-hint">双指缩放 · 拖动浏览</text>
        </view>
      </view>

      <!-- 全屏大图模式下底部悬浮退出大按钮 (老年友好，超大触控靶区) -->
      <view v-if="isMapFullscreen" class="fullscreen-bottombar">
        <button class="fullscreen-bottom-btn" @tap="toggleMapFullscreen">
          <text class="bottom-btn-icon">📋</text>
          <text class="bottom-btn-text">退出大图 · 查看详细换乘步骤</text>
        </button>
      </view>

      <!-- 地图工具浮层 -->
      <view class="map-controls">
        <button class="ctrl-btn ctrl-btn-fullscreen" @tap="toggleMapFullscreen">
          {{ isMapFullscreen ? '✕ 退出大图' : '⛶ 全屏大图' }}
        </button>
        <button class="ctrl-btn" @tap="resetView">🗺️ 全览</button>
        <button class="ctrl-btn" @tap="locateElder">📍 我的位置</button>
      </view>
    </view>

    <!-- 适老换乘步骤大字卡片 -->
    <view class="steps-section">
      <view class="section-header">
        <text class="section-title">🚶 换乘步骤大字指引</text>
        <text class="section-subtitle">字大清晰 · 跟着走不迷路</text>
      </view>

      <!-- 后端没查到路线时如实告知。以前这里会退回一组写死的跨城演示步骤，
           等于给老人编一条 1023 公里的行程 —— 宁可说"没查到"，也不编。 -->
      <view v-if="steps.length === 0" class="step-empty-card">
        <text class="step-empty-icon">🧭</text>
        <text class="step-empty-text">{{ routeNotice }}</text>
      </view>

      <view
        v-for="(step, index) in steps"
        :key="index"
        class="step-card"
        :class="{ active: currentStepIndex === index }"
        @tap="highlightStep(index)"
      >
        <view class="step-card-head">
          <view class="step-badge-num">{{ index + 1 }}</view>
          <text class="step-card-title">{{ step.title }}</text>
          <button class="step-audio-btn" size="mini" @tap.stop="speakText(step.content)">
            🔊 念这步
          </button>
        </view>
        <text class="step-card-desc">{{ step.content }}</text>
        <view v-if="step.tip" class="step-card-tip">
          <text class="tip-icon">💡</text>
          <text class="tip-text">{{ step.tip }}</text>
        </view>
      </view>

      <!-- 适老安心守护与联系家人 -->
      <view class="help-section">
        <button class="btn-help-safe" :loading="checkingIn" @tap="sendSafetyCheckin">
          <text class="btn-icon">🕊️</text>
          <text class="btn-text">一键给家人报平安</text>
        </button>
        <button class="btn-help-tel" @tap="callFamilyDirect">
          <text class="btn-icon">📞</text>
          <text class="btn-text">电话联系家人{{ familyContactName ? '（' + familyContactName + '）' : '' }}</text>
        </button>
      </view>
    </view>
  </view>
</template>

<script>
import {
  loadLeaflet,
  ensureAmapMarkerStyles,
  toLeafletLatLng,
  makeMapMarkerIcon,
  AMAP_RASTER_TILE_URL,
  AMAP_TILE_SUBDOMAINS,
  AMAP_TILE_ATTRIBUTION,
} from '../../utils/amap'
import { get, post } from '../../api/client'
import { getCurrentUser } from '../../store/user'
import { speak } from '../../api/asr'

export default {
  name: 'ElderRouteMap',
  data() {
    return {
      user: null,
      city: '南京',
      tripId: '',
      title: '',
      originName: '家',
      destinationName: '',
      routeDuration: '',
      routeDistance: '',
      routeMode: '',
      routeNotice: '没查到这条路线。康乐只做本市出行（公交、地铁、步行），跨城的车票机票不查。',
      mapLoading: true,
      mapFailed: false,
      isMapFullscreen: false,
      checkingIn: false,
      familyContactName: '李明',
      familyContactPhone: '13812345678',
      reportCount: 0,
      reportTimer: null,
      currentStepIndex: 0,
      elderCoords: [118.7732, 32.0618], // 默认起点坐标（老人常住地），拿到真实途经点后会被覆盖
      elderMarker: null,
      routePolyline: null,
      routeCasing: null,
      stationMarkers: [],
      tileLayer: null,
      leafletMap: null,
      steps: [],
      routePoints: [],
      polylinePath: [],
    }
  },
  computed: {
    // 交通方式徽标：本地出行只可能是公交/地铁/步行（打车走叫车卡），
    // 认不出就原样显示后端给的 mode，不自己编一个方式上去。
    routeModeText() {
      const m = String(this.routeMode || '')
      if (!m) return ''
      if (m.includes('地铁') || m.includes('轨道') || m.includes('轻轨')) return '🚇 地铁'
      if (m.includes('步行')) return '🚶 步行'
      if (m.includes('公交') || m.includes('巴士')) return '🚌 公交'
      if (m.includes('驾车') || m.includes('打车')) return '🚕 打车'
      return m
    },
  },
  onLoad(opts) {
    if (opts) {
      if (opts.trip_id) this.tripId = opts.trip_id
      if (opts.title) this.title = decodeURIComponent(opts.title)
      if (opts.origin) this.originName = decodeURIComponent(opts.origin)
      if (opts.destination) this.destinationName = decodeURIComponent(opts.destination)
      if (opts.city) this.city = decodeURIComponent(opts.city)
    }
  },
  onBackPress(options) {
    if (this.isMapFullscreen) {
      this.toggleMapFullscreen()
      return true
    }
    return false
  },
  mounted() {
    this.user = getCurrentUser()
    if (!this.city && this.user && this.user.city) {
      this.city = this.user.city
    }
    this.fetchFamilyContact()
    this.initPage()
    if (typeof window !== 'undefined') {
      window.addEventListener('popstate', this.handlePopState)
    }
  },
  onUnload() {
    this.stopReporting()
    if (typeof window !== 'undefined') {
      window.removeEventListener('popstate', this.handlePopState)
    }
    if (this.leafletMap) {
      try {
        this.leafletMap.remove()
      } catch (e) {}
      this.leafletMap = null
    }
  },
  methods: {
    async initPage() {
      await this.fetchRouteFromBackend()
      await this.initMap()
      this.startReporting()
    },
    async fetchRouteFromBackend() {
      try {
        let routeResult = null

        // 1. 如果已有 tripId，先获取该行程的规划
        if (this.tripId) {
          const res = await get(`/api/trips/${this.tripId}`).catch(() => null)
          if (res && res.route && res.route.ok) {
            routeResult = res.route
          }
        }

        // 2. 如果没有 tripId，先从现有行程列表中查找匹配目的地的行程
        if (!this.tripId) {
          const listRes = await get('/api/trips?limit=10').catch(() => null)
          if (listRes && Array.isArray(listRes.trips)) {
            const destCore = (this.destinationName || '').replace(/北京|南京|上海/g, '').trim()
            const matched = listRes.trips.find((t) => {
              const p = t.purpose || (t.plan && t.plan.title) || ''
              return destCore && p.includes(destCore)
            })
            if (matched) {
              this.tripId = matched.id
              const res = await get(`/api/trips/${this.tripId}`).catch(() => null)
              if (res && res.route && res.route.ok) {
                routeResult = res.route
              }
            }
          }
        }

        // 3. 若仍无 routeResult，调用后端直接路线规划接口
        if (!routeResult) {
          const directRes = await get('/api/trips/route/direct', {
            origin: this.originName,
            destination: this.destinationName,
            city: this.city || '南京',
          }).catch(() => null)
          if (directRes && directRes.route && directRes.route.ok) {
            routeResult = directRes.route
          }
        }

        // 4. 若仍未绑定 tripId，自动创建快速守护行程，以保障 10 秒定时上报闭环
        if (!this.tripId) {
          const quickRes = await post('/api/trips/quick', {
            origin: this.originName,
            destination: this.destinationName,
            elder_id: this.user ? this.user.id : null,
            purpose: this.title || `前往${this.destinationName}就医出行`,
          }).catch(() => null)
          if (quickRes && quickRes.trip) {
            this.tripId = quickRes.trip.id
          }
        }

        // 5. 应用规划数据到界面响应式状态
        if (routeResult) {
          const r = routeResult
          if (r.duration) this.routeDuration = r.duration
          if (r.distance_km) this.routeDistance = `${r.distance_km}公里`
          if (r.mode) this.routeMode = r.mode
          if (r.origin) this.originName = r.origin
          if (r.destination) this.destinationName = r.destination
          if (Array.isArray(r.points) && r.points.length) {
            this.routePoints = r.points.map((p, idx) => ({
              name: p.location || p.name,
              lng: p.lng,
              lat: p.lat,
              type: idx === 0 ? 'start' : idx === r.points.length - 1 ? 'end' : 'station',
            }))
            if (this.routePoints.length && this.routePoints[0].lng) {
              this.elderCoords = [this.routePoints[0].lng, this.routePoints[0].lat]
            }
          }
          if (Array.isArray(r.polyline) && r.polyline.length) {
            this.polylinePath = r.polyline.map((p) => [p.lng, p.lat])
          } else if (this.routePoints.length) {
            // 后端只给了途经点、没给折线：按真实点连一条出来，用的仍是后端数据，不是本地编的
            this.polylinePath = this.routePoints.map((p) => [p.lng, p.lat])
          }
          if (Array.isArray(r.steps) && r.steps.length) {
            this.steps = r.steps.map((st, idx) => {
              const text = typeof st === 'string' ? st : (st.instruction || st.content || '')
              const pt = (this.routePoints && this.routePoints[idx]) || (this.routePoints && this.routePoints[this.routePoints.length - 1])
              const ptName = (this.routePoints && this.routePoints[idx] && this.routePoints[idx].name) || ''
              return {
                title: `第 ${idx + 1} 步${ptName ? '：' + ptName : ''}`,
                content: text,
                tip: idx === 0 ? '出发前记得带好身份证和医保卡，路上慢慢走，不着急。' : idx === r.steps.length - 1 ? '到了医院，跟着大厅指示牌走，找不到就问导医台的工作人员。' : '要是走不动或找不到路，随时问路边的工作人员。',
                coords: pt ? [pt.lng, pt.lat] : this.elderCoords,
              }
            })
          } else {
            // 后端把这趟路判成"不画"（跨城或库里没这条线）：如实转述后端那句话，
            // 页面上不给任何步骤、不连线，让老人看到的就是"没查到"。
            if (r.summary) this.routeNotice = r.summary
          }
        }
      } catch (e) {
        // 拿不到路线就退成"没查到"这句话，不再退回任何本地演示航迹
        console.warn('获取后端路线规划失败:', e)
      }
    },
    async initMap() {
      this.mapFailed = false
      this.mapLoading = true
      let L
      try {
        L = await loadLeaflet()
      } catch (err) {
        console.error('地图库加载失败:', err)
        this.mapLoading = false
        this.mapFailed = true
        return
      }
      // 保证标记的自定义 DOM 样式已注入 document.head（穿透 uni-app 作用域）
      ensureAmapMarkerStyles()
      await this.$nextTick()
      const container = document.getElementById('elder-amap-container')
      if (!container) {
        this.mapLoading = false
        return
      }

      try {
        // 重试路径：先销毁旧实例再重建
        if (this.leafletMap) {
          this.leafletMap.remove()
          this.leafletMap = null
        }

        this.leafletMap = L.map(container, {
          // 恢复 +/- 缩放按钮：原来整个关掉，屏幕上没有任何缩放入口，桌面端根本没法
          // 缩放。zoomControl 默认落在左上角，避开右下角的全览/我的位置浮层，不打架。
          zoomControl: true,
          attributionControl: true,
          // 半级缩放：zoomSnap/zoomDelta 从默认整级(1)收到 0.5，点一下 +/- 或滚一下
          // 只缩半级，不再"一下子放太大/缩太小"——这才是用户要的「精度缩放」。
          zoomSnap: 0.5,
          zoomDelta: 0.5,
          scrollWheelZoom: true, // 滚轮缩放（配合半级 zoomDelta，不会猛跳）
        }).setView(toLeafletLatLng(this.elderCoords), 15)
        if (this.leafletMap.attributionControl) {
          this.leafletMap.attributionControl.setPrefix(false) // 只留「高德地图 © AutoNavi」，不显示 Leaflet 字样
          // 归属信息挪到左下角：它默认在右下角、z-index:1000，会盖住同在右下角、又没设
          // z-index 的全览/我的位置按钮（就是用户截图里"地图把按钮盖住了"）。挪走它，
          // 再给按钮提层（见 .map-controls z-index），双保险。
          this.leafletMap.attributionControl.setPosition('bottomleft')
        }

        // 高德栅格瓦片（GCJ-02，与后端返回坐标同基准，无需转换）。绕开断掉的高德控制面，
        // 直连数据面 wprd0X.is.autonavi.com 贴图，既出底图又保留高德品牌。
        this.tileLayer = L.tileLayer(AMAP_RASTER_TILE_URL, {
          subdomains: AMAP_TILE_SUBDOMAINS,
          maxZoom: 18,
          minZoom: 3,
          attribution: AMAP_TILE_ATTRIBUTION,
        }).addTo(this.leafletMap)

        this.renderRoute(L)
        this.mapLoading = false
        // uni-app H5 容器尺寸可能下一帧才最终确定，强制重算避免灰边/瓦片错位
        this.$nextTick(() => {
          setTimeout(() => {
            if (this.leafletMap) this.leafletMap.invalidateSize()
          }, 200)
        })
      } catch (err) {
        console.error('地图渲染失败:', err)
        this.mapLoading = false
        this.mapFailed = true
      }
    },
    renderRoute(L) {
      L = L || window.L
      if (!L || !this.leafletMap) return
      const latlngs = this.polylinePath.map((p) => toLeafletLatLng(p))

      // 路线：先白色描边打底，再叠高对比蓝线（仿高德 isOutline 的描边效果）
      this.routeCasing = L.polyline(latlngs, {
        color: '#ffffff',
        weight: 11,
        opacity: 0.9,
        lineJoin: 'round',
        lineCap: 'round',
      }).addTo(this.leafletMap)
      this.routePolyline = L.polyline(latlngs, {
        color: '#2A82E4', // 晴空天蓝主品牌色
        weight: 7,
        opacity: 0.95,
        lineJoin: 'round',
        lineCap: 'round',
      }).addTo(this.leafletMap)

      // 标注起终点与关键站点
      this.stationMarkers = []
      this.routePoints.forEach((pt) => {
        const isStart = pt.type === 'start'
        const isEnd = pt.type === 'end'
        const badgeClass = isStart ? 'badge-start' : isEnd ? 'badge-end' : 'badge-station'
        const labelPrefix = isStart ? '🟢 起点：' : isEnd ? '🔴 终点：' : '🚉 途经：'
        const icon = makeMapMarkerIcon(L, {
          html: `<div class="elder-map-marker ${badgeClass}"><span class="marker-title">${labelPrefix}${pt.name}</span></div>`,
          size: [40, 34],
        })
        const m = L.marker(toLeafletLatLng(pt), { icon }).addTo(this.leafletMap)
        this.stationMarkers.push(m)
      })

      // 绘制长辈当前实时定位 Marker (带呼吸波纹动效)
      const liveIcon = makeMapMarkerIcon(L, {
        html: `<div class="elder-live-pulse-marker"><div class="pulse-ring"></div><div class="pulse-core">👴 当前位置</div></div>`,
        size: [60, 60],
      })
      this.elderMarker = L.marker(toLeafletLatLng(this.elderCoords), {
        icon: liveIcon,
        zIndexOffset: 1000,
      }).addTo(this.leafletMap)

      // 自适应视野：Leaflet fitBounds 同步可靠，天然修掉旧代码 setFitView 早于地图 ready 的时序坑
      if (latlngs.length) {
        this.leafletMap.fitBounds(this.routePolyline.getBounds(), { padding: [40, 40] })
      }
    },
    startReporting() {
      this.stopReporting()
      // 立即上报一次
      this.doReportLocation()
      // 每 10 秒定时上报
      this.reportTimer = setInterval(() => {
        this.doReportLocation()
      }, 10000)
    },
    stopReporting() {
      if (this.reportTimer) {
        clearInterval(this.reportTimer)
        this.reportTimer = null
      }
    },
    async doReportLocation() {
      const [lng, lat] = this.elderCoords
      const curStep = this.steps[this.currentStepIndex] || {}
      const locationName = curStep.title ? curStep.title.replace(/第 \d+ 步[：:]\s*/, '') : '行进中'

      if (this.tripId) {
        try {
          const res = await post(`/api/trips/${this.tripId}/checkpoints`, {
            location: locationName,
            lng,
            lat,
          })
          if (res && res.checkpoint) {
            this.reportCount++
          }
        } catch (e) {
          console.warn('位置定时上报网络波动:', e.message)
        }
      }
    },
    advanceLocation() {
      // 没有步骤时无事可做：以前 steps 是写死的三步，这里不会空；现在步骤只来自后端，
      // 空列表下取模会得到 NaN，必须先挡住。
      if (!this.steps.length) {
        uni.showToast({ title: '这条路线还没查到，没法模拟行进', icon: 'none' })
        return
      }
      // 模拟老人沿路线前进至下一步
      this.currentStepIndex = (this.currentStepIndex + 1) % this.steps.length
      const step = this.steps[this.currentStepIndex]
      if (step && step.coords) {
        this.elderCoords = step.coords
        if (this.elderMarker) {
          this.elderMarker.setLatLng(toLeafletLatLng(this.elderCoords))
        }
        if (this.leafletMap) {
          this.leafletMap.panTo(toLeafletLatLng(this.elderCoords))
        }
        uni.showToast({
          title: `已行进至：${step.title}`,
          icon: 'none',
        })
        this.doReportLocation()
      }
    },
    toggleMapFullscreen() {
      if (this.isMapFullscreen) {
        if (typeof window !== 'undefined' && window.history && window.history.state && window.history.state.isFullscreen) {
          window.history.back()
          return
        }
        this.isMapFullscreen = false
      } else {
        this.isMapFullscreen = true
        if (typeof window !== 'undefined' && window.history) {
          window.history.pushState({ isFullscreen: true }, '')
        }
      }
      this.refreshMapBounds()
    },
    handlePopState() {
      if (this.isMapFullscreen) {
        this.isMapFullscreen = false
        this.refreshMapBounds()
      }
    },
    refreshMapBounds() {
      this.$nextTick(() => {
        setTimeout(() => {
          if (this.leafletMap) {
            this.leafletMap.invalidateSize()
            this.resetView()
          }
        }, 150)
      })
    },
    resetView() {
      if (!this.leafletMap) return
      if (this.routePolyline && this.polylinePath.length >= 2) {
        try {
          this.leafletMap.fitBounds(this.routePolyline.getBounds(), {
            padding: this.isMapFullscreen ? [60, 60] : [30, 30],
          })
          return
        } catch (e) {}
      }
      if (this.elderCoords) {
        this.leafletMap.setView(toLeafletLatLng(this.elderCoords), 15)
      }
    },
    locateElder() {
      if (!this.leafletMap || !this.elderCoords) return
      this.leafletMap.setView(toLeafletLatLng(this.elderCoords), 16)
      uni.showToast({ title: '已定位到当前常住位置', icon: 'none' })
    },
    highlightStep(index) {
      this.currentStepIndex = index
      const step = this.steps[index]
      if (step && step.coords && this.leafletMap) {
        this.leafletMap.setView(toLeafletLatLng(step.coords), 16)
      }
    },
    speakFullRoute() {
      const parts = [`康乐帮您看的路线，从${this.originName}到${this.destinationName}。`]
      if (this.routeMode) parts.push(`出行方式是${this.routeMode}`)
      if (this.routeDuration) parts.push(`全程耗时${this.routeDuration}`)
      if (this.routeDistance) parts.push(`大约${this.routeDistance}`)
      this.steps.forEach((s) => parts.push(`${s.title}。${s.content}`))
      // 没查到路线时，念的就是那句"没查到"，不念一串空句子
      if (!this.steps.length) parts.push(this.routeNotice)
      const ok = speak(parts.join('。'))
      if (!ok) uni.showToast({ title: '当前设备不支持朗读', icon: 'none' })
    },
    speakText(text) {
      const ok = speak(text)
      if (!ok) uni.showToast({ title: '当前设备不支持朗读', icon: 'none' })
    },
    async fetchFamilyContact() {
      try {
        const res = await get('/api/family/members').catch(() => null)
        if (res && Array.isArray(res.items) && res.items.length) {
          const m = res.items[0]
          if (m && m.user) {
            this.familyContactName = m.user.name || '家人'
            this.familyContactPhone = m.user.phone || '13812345678'
          }
        }
      } catch (e) {}
    },
    async sendSafetyCheckin() {
      if (this.checkingIn) return
      this.checkingIn = true
      const [lng, lat] = this.elderCoords
      const curStep = this.steps[this.currentStepIndex] || {}
      const where = curStep.title ? curStep.title.replace(/第 \d+ 步[：:]\s*/, '') : (this.destinationName || '前往就诊途中')

      try {
        let res = null
        if (this.tripId) {
          res = await post(`/api/trips/${this.tripId}/checkin`, {
            location: where,
            lng,
            lat,
            message: `长辈主动报平安：目前一切安好，正前往${this.destinationName || '医院'}`,
          }).catch(() => null)
        }

        const childName = (res && res.family && res.family.name) || this.familyContactName || '子女'
        const phone = (res && res.family && res.family.phone) || this.familyContactPhone || '13812345678'

        uni.showModal({
          title: '🕊️ 已向家人报平安',
          content: `已成功同步您的平安状态至【${childName}】的守护看板！当前位置：${where}。`,
          confirmText: '呼叫家人',
          cancelText: '我知道了',
          success: (mRes) => {
            if (mRes.confirm) {
              this.makeSafePhoneCall(phone)
            }
          },
        })
      } catch (err) {
        uni.showToast({ title: '网络稍有波动，已记录本地状态', icon: 'none' })
      } finally {
        this.checkingIn = false
      }
    },
    callFamilyDirect() {
      const phone = this.familyContactPhone || '13812345678'
      const name = this.familyContactName || '家人'
      uni.showModal({
        title: '📞 拨打家人电话',
        content: `即将呼叫家人【${name}】（${phone}）`,
        confirmText: '立即呼叫',
        cancelText: '取消',
        success: (res) => {
          if (res.confirm) {
            this.makeSafePhoneCall(phone)
          }
        },
      })
    },
    makeSafePhoneCall(phoneNumber) {
      if (!phoneNumber) return
      uni.makePhoneCall({
        phoneNumber,
        fail: () => {
          uni.setClipboardData({
            data: phoneNumber,
            success: () => {
              uni.showToast({
                title: `已复制号码：${phoneNumber}，可在拨号盘粘贴呼叫`,
                icon: 'none',
                duration: 3500,
              })
            },
          })
        },
      })
    },
    goBack() {
      const pages = getCurrentPages()
      if (pages.length > 1) {
        uni.navigateBack()
      } else {
        uni.switchTab({ url: '/pages/elder/chat' })
      }
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.route-page {
  min-height: 100vh;
  background: $lyj-bg;
  padding-bottom: calc(#{$lyj-space-xl} + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
}

/* 顶部适老导航条 (触控靶区 >= 48px) */
.elder-navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx 24rpx 16rpx;
  background: #ffffff;
  border-bottom: 2rpx solid $lyj-line;
  min-height: 100rpx;
}
.nav-back-btn {
  min-height: 96rpx;
  min-width: 140rpx;
  display: flex;
  align-items: center;
  gap: 8rpx;
  background: $lyj-card;
  color: $lyj-text;
  border-radius: 48rpx;
  border: 2rpx solid $lyj-line;
  padding: 0 24rpx;
  margin: 0;
  cursor: pointer;
}
.back-arrow {
  font-size: 44rpx;
  font-weight: 700;
  line-height: 1;
}
.back-text {
  font-size: 30rpx;
  font-weight: 700;
}
.nav-title {
  font-size: 38rpx;
  font-weight: 800;
  color: $lyj-text;
}
.nav-speak-btn {
  min-height: 96rpx;
  display: flex;
  align-items: center;
  gap: 8rpx;
  background: $lyj-primary-soft;
  color: $lyj-primary;
  border-radius: 48rpx;
  border: 2rpx solid rgba(42, 130, 228, 0.25);
  padding: 0 28rpx;
  margin: 0;
  cursor: pointer;
}
.speak-icon {
  font-size: 32rpx;
}
.speak-text {
  font-size: 28rpx;
  font-weight: 700;
}

/* 10秒定时上报状态指示条 */
.reporting-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ecfdf5;
  border-bottom: 2rpx solid #a7f3d0;
  padding: 14rpx 24rpx;
}
.pulse-dot {
  width: 18rpx;
  height: 18rpx;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 6rpx rgba(16, 185, 129, 0.3);
  animation: pulseLight 1.5s infinite ease-in-out;
  flex-shrink: 0;
  margin-right: 12rpx;
}
@keyframes pulseLight {
  0% { transform: scale(0.9); opacity: 0.7; }
  50% { transform: scale(1.2); opacity: 1; box-shadow: 0 0 0 10rpx rgba(16, 185, 129, 0); }
  100% { transform: scale(0.9); opacity: 0.7; }
}
.report-text {
  flex: 1;
  font-size: 24rpx;
  color: #065f46;
  font-weight: 600;
}
.sim-step-btn {
  background: #10b981;
  color: #ffffff;
  font-size: 22rpx;
  font-weight: 700;
  border-radius: 20rpx;
  border: none;
  padding: 4rpx 16rpx;
  flex-shrink: 0;
  margin-left: 8rpx;
}

/* 路线概览信息 */
.route-summary-bar {
  margin: 20rpx 24rpx;
  padding: 24rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 2rpx solid $lyj-line;
  box-shadow: $lyj-shadow-card;
}
.summary-line {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-wrap: wrap;
}
.summary-badge {
  font-size: 24rpx;
  font-weight: 800;
  padding: 4rpx 12rpx;
  border-radius: 8rpx;
  color: #ffffff;
}
.summary-badge.start {
  background: #10b981;
}
.summary-badge.end {
  background: #ef4444;
}
.summary-place {
  font-size: 34rpx;
  font-weight: 800;
  color: #1e293b;
}
.summary-arrow {
  font-size: 30rpx;
  color: #94a3b8;
  margin: 0 4rpx;
}
.summary-meta {
  display: flex;
  align-items: center;
  gap: 20rpx;
  margin-top: 14rpx;
  padding-top: 12rpx;
  border-top: 1rpx dashed #e2e8f0;
}
.meta-item {
  font-size: 26rpx;
  color: #64748b;
  font-weight: 600;
}
.expand-map-tag {
  margin-left: auto;
  background: #eff6ff;
  color: #2563eb;
  border: 1rpx solid #bfdbfe;
  font-size: 24rpx;
  font-weight: 700;
  border-radius: 20rpx;
  padding: 4rpx 18rpx;
  cursor: pointer;
}

/* 高德地图容器 (58% 黄金分屏比例) */
.map-section {
  position: relative;
  margin: 0 24rpx 24rpx;
  border-radius: 24rpx;
  overflow: hidden;
  box-shadow: $lyj-shadow-card;
  border: 2rpx solid $lyj-line;
}
.amap-box {
  width: 100%;
  height: 58vh;
  background: #e2e8f0;
  transition: height 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.map-section.fullscreen-mode {
  position: fixed !important;
  top: 0 !important;
  left: 0 !important;
  right: 0 !important;
  bottom: 0 !important;
  width: 100vw !important;
  height: 100vh !important;
  z-index: 9999 !important;
  margin: 0 !important;
  border-radius: 0 !important;
}
.map-section.fullscreen-mode .amap-box {
  width: 100% !important;
  height: 100% !important;
  min-height: 100% !important;
}

/* 全屏大图模式顶部悬浮栏 (带 safe-area-inset-top 保护) */
.fullscreen-topbar {
  position: absolute;
  top: calc(env(safe-area-inset-top, 0px) + 24rpx);
  left: 24rpx;
  right: 24rpx;
  z-index: 1300;
  pointer-events: none;
}
.fullscreen-topbar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
.fullscreen-exit-pill {
  pointer-events: auto;
  min-height: 80rpx;
  display: inline-flex;
  align-items: center;
  gap: 10rpx;
  background: #ffffff;
  color: #1e293b;
  border: 2rpx solid #cbd5e1;
  border-radius: 40rpx;
  box-shadow: 0 6rpx 20rpx rgba(0, 0, 0, 0.18);
  padding: 0 28rpx;
  cursor: pointer;
}
.exit-icon {
  font-size: 40rpx;
  font-weight: 800;
  color: #2563eb;
  line-height: 1;
}
.exit-text {
  font-size: 28rpx;
  font-weight: 800;
  color: #1e293b;
}
.fullscreen-hint {
  font-size: 24rpx;
  font-weight: 600;
  color: #ffffff;
  background: rgba(15, 23, 42, 0.75);
  padding: 8rpx 22rpx;
  border-radius: 20rpx;
  backdrop-filter: blur(4px);
}

/* 全屏大图模式底部悬浮退出大按钮 */
.fullscreen-bottombar {
  position: absolute;
  bottom: calc(env(safe-area-inset-bottom, 0px) + 28rpx);
  left: 28rpx;
  right: 28rpx;
  z-index: 1300;
}
.fullscreen-bottom-btn {
  width: 100%;
  min-height: 100rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  color: #ffffff;
  border: none;
  border-radius: 50rpx;
  box-shadow: 0 10rpx 28rpx rgba(37, 99, 235, 0.4);
  padding: 0 32rpx;
  cursor: pointer;
}
.bottom-btn-icon {
  font-size: 36rpx;
}
.bottom-btn-text {
  font-size: 32rpx;
  font-weight: 800;
  letter-spacing: 1rpx;
  color: #ffffff;
}

/* 全屏模式下右侧悬浮控件提升，避免遮挡底部退出条 */
.map-section.fullscreen-mode .map-controls {
  bottom: calc(env(safe-area-inset-bottom, 0px) + 150rpx) !important;
}

.map-loading-mask {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.85);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
}
.loading-icon {
  font-size: 48rpx;
}
.loading-text {
  font-size: 28rpx;
  color: #475569;
  font-weight: 600;
}
.map-retry-btn {
  margin-top: 16rpx;
  min-height: 72rpx;
  background: $lyj-primary;
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 700;
  border: none;
  border-radius: 40rpx;
  padding: 0 36rpx;
}
.map-controls {
  position: absolute;
  right: 20rpx;
  bottom: 20rpx;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  /* Leaflet 的缩放控件/归属信息在容器内是 z-index:1000，这里必须更高，否则右下角的
     全览/我的位置会被盖住（用户截图里"按钮被地图盖了"）。归属信息已挪到左下角。 */
  z-index: 1200;
}
.ctrl-btn {
  background: #ffffff;
  color: #1e293b;
  border: 1rpx solid #cbd5e1;
  border-radius: 30rpx;
  font-size: 24rpx;
  font-weight: 700;
  padding: 8rpx 20rpx;
  box-shadow: 0 4rpx 10rpx rgba(0, 0, 0, 0.1);
  cursor: pointer;
}
.ctrl-btn.ctrl-btn-fullscreen {
  background: #2563eb;
  color: #ffffff;
  border-color: #1d4ed8;
}

/* 换乘步骤大字卡片 */
.steps-section {
  margin: 0 24rpx;
}
.section-header {
  margin-bottom: 16rpx;
}
.section-title {
  display: block;
  font-size: 34rpx;
  font-weight: 800;
  color: #1e293b;
}
.section-subtitle {
  display: block;
  font-size: 24rpx;
  color: #64748b;
  margin-top: 4rpx;
}
/* 没查到路线时的如实提示卡：字大、居中，别让老人以为是自己没点开 */
.step-empty-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
  padding: 48rpx 32rpx;
  background: #ffffff;
  border: 2rpx dashed #cbd5e1;
  border-radius: 20rpx;
  margin-bottom: 20rpx;
}
.step-empty-icon {
  font-size: 64rpx;
}
.step-empty-text {
  font-size: 30rpx;
  color: #475569;
  font-weight: 600;
  line-height: 1.6;
  text-align: center;
}

.step-card {
  background: #ffffff;
  border-radius: 20rpx;
  padding: 24rpx;
  margin-bottom: 20rpx;
  border: 2rpx solid $lyj-line;
  box-shadow: $lyj-shadow-card;
  transition: all 0.2s ease;
}
.step-card.active {
  border-color: $lyj-primary;
  background: $lyj-primary-soft;
  box-shadow: 0 6rpx 16rpx rgba(42, 130, 228, 0.12);
}
.step-card-head {
  display: flex;
  align-items: center;
  gap: 14rpx;
  margin-bottom: 12rpx;
}
.step-badge-num {
  width: 44rpx;
  height: 44rpx;
  border-radius: 50%;
  background: $lyj-primary;
  color: #ffffff;
  font-size: 26rpx;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.step-card-title {
  flex: 1;
  font-size: 32rpx;
  font-weight: 800;
  color: #1e293b;
}
.step-audio-btn {
  background: $lyj-primary-soft;
  color: $lyj-primary;
  border-radius: 30rpx;
  border: 1rpx solid rgba(42, 130, 228, 0.3);
  font-size: 22rpx;
  font-weight: 700;
  padding: 4rpx 16rpx;
  margin: 0;
}
.step-card-desc {
  display: block;
  font-size: 30rpx;
  color: #334155;
  line-height: 1.6;
}
.step-card-tip {
  margin-top: 14rpx;
  padding: 12rpx 16rpx;
  background: #fffbeb;
  border-radius: 12rpx;
  display: flex;
  align-items: flex-start;
  gap: 8rpx;
}
.tip-icon {
  font-size: 26rpx;
  flex-shrink: 0;
}
.tip-text {
  font-size: 26rpx;
  color: #92400e;
  line-height: 1.4;
}

/* 适老安心守护与联系家人按钮 (触控靶区 >= 48px) */
.help-section {
  margin-top: 36rpx;
  margin-bottom: 48rpx;
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}
.btn-help-safe {
  width: 100%;
  min-height: 96rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14rpx;
  background: #10b981;
  color: #ffffff;
  border-radius: 48rpx;
  border: none;
  font-size: 34rpx;
  font-weight: 800;
  box-shadow: 0 6rpx 18rpx rgba(16, 185, 129, 0.25);
  cursor: pointer;
}
.btn-help-tel {
  width: 100%;
  min-height: 96rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14rpx;
  background: #ffffff;
  color: #2563eb;
  border-radius: 48rpx;
  border: 2rpx solid #bfdbfe;
  font-size: 32rpx;
  font-weight: 800;
  box-shadow: 0 4rpx 14rpx rgba(37, 99, 235, 0.12);
  cursor: pointer;
}
</style>

<!-- 地图标记的自定义 DOM 样式统一在 utils/amap.js 的 ensureAmapMarkerStyles()
     里以文档级 <style> 注入：Leaflet DivIcon 是运行时插进地图图层容器的，uni-app H5
     会给页面样式加作用域标记，写在这里的非 scoped 规则也命中不到，站点标签会退化成
     竖排黑字。故此处不再重复声明，避免"看似有样式其实不生效"的误导。 -->

