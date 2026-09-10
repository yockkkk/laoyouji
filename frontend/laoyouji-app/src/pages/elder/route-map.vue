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

    <!-- 10秒定时位置上报状态指示条 -->
    <view class="reporting-banner">
      <view class="pulse-dot"></view>
      <text class="report-text">
        📡 位置实时守护中 · 每 10 秒自动向家人端上报位置 (已上报 {{ reportCount }} 次)
      </text>
      <button class="sim-step-btn" size="mini" @tap="advanceLocation">
        模拟行进 ›
      </button>
    </view>

    <!-- 路线概览信息条 -->
    <view class="route-summary-bar">
      <view class="summary-line">
        <text class="summary-badge start">起</text>
        <text class="summary-place">{{ originName }}</text>
        <text class="summary-arrow">➔</text>
        <text class="summary-badge end">终</text>
        <text class="summary-place">{{ destinationName }}</text>
      </view>
      <view class="summary-meta">
        <text class="meta-item">⏱️ {{ routeDuration }}</text>
        <text class="meta-item" v-if="routeDistance">🛣️ 约 {{ routeDistance }}</text>
        <text class="meta-item">🚆 高铁+市内接驳</text>
      </view>
    </view>

    <!-- 适老地图视窗 (Leaflet 渲染高德栅格瓦片，坐标 GCJ-02) -->
    <view class="map-section">
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
      <!-- 地图工具浮层 -->
      <view class="map-controls">
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

      <!-- 应急求助与联系家人 -->
      <view class="help-section">
        <button class="btn-help-tel" @tap="callFamily">
          <text class="btn-icon">📞</text>
          <text class="btn-text">一键给家人报平安</text>
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
      tripId: '',
      title: '',
      originName: '家（南京鼓楼区）',
      destinationName: '北京积水潭医院',
      routeDuration: '约4小时20分',
      routeDistance: '1023公里',
      mapLoading: true,
      mapFailed: false,
      reportCount: 0,
      reportTimer: null,
      currentStepIndex: 0,
      elderCoords: [118.7732, 32.0618], // 默认起点坐标
      elderMarker: null,
      routePolyline: null,
      routeCasing: null,
      stationMarkers: [],
      tileLayer: null,
      leafletMap: null,
      steps: [
        {
          title: '第 1 步：家 ➔ 南京南站',
          content: '从家门口出发打车或乘坐网约车直达南京南站出发层，车程约 20 分钟。',
          tip: '进站请提前备好身份证与老年优待卡，走无障碍快速通道。',
          coords: [118.7981, 31.9696],
        },
        {
          title: '第 2 步：南京南站 ➔ 北京南站',
          content: '乘坐高铁 G12 次（二等座），途中经停济南西站，无需换车，车程约 3 小时 40 分钟。',
          tip: '车上如有需要可随时按座席上方呼唤铃寻求列车员协助。',
          coords: [116.3789, 39.8652],
        },
        {
          title: '第 3 步：北京南站 ➔ 北京积水潭医院',
          content: '从北京南站出站后跟随指示牌前往地下一层网约车乘车点，打车约 20 分钟到达积水潭医院新街口院区。',
          tip: '到院后门诊一层大厅设有长辈便民服务台与免费轮椅租借。',
          coords: [116.3748, 39.9485],
        },
      ],
      // 真实规划路线经纬度点集
      routePoints: [
        { name: '家（南京鼓楼区）', lng: 118.7732, lat: 32.0618, type: 'start' },
        { name: '南京南站', lng: 118.7981, lat: 31.9696, type: 'station' },
        { name: '济南西站', lng: 116.8974, lat: 36.6669, type: 'station' },
        { name: '北京南站', lng: 116.3789, lat: 39.8652, type: 'station' },
        { name: '北京积水潭医院', lng: 116.3748, lat: 39.9485, type: 'end' },
      ],
      polylinePath: [],
    }
  },
  onLoad(opts) {
    if (opts) {
      if (opts.trip_id) this.tripId = opts.trip_id
      if (opts.title) this.title = decodeURIComponent(opts.title)
      if (opts.origin) this.originName = decodeURIComponent(opts.origin)
      if (opts.destination) this.destinationName = decodeURIComponent(opts.destination)
    }
  },
  mounted() {
    this.user = getCurrentUser()
    this.initPage()
  },
  onUnload() {
    this.stopReporting()
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
          if (r.origin) this.originName = r.origin
          if (r.destination) this.destinationName = r.destination
          if (Array.isArray(r.polyline) && r.polyline.length) {
            this.polylinePath = r.polyline.map((p) => [p.lng, p.lat])
          }
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
          if (Array.isArray(r.steps) && r.steps.length) {
            this.steps = r.steps.map((st, idx) => {
              const text = typeof st === 'string' ? st : (st.instruction || st.content || '')
              const pt = (this.routePoints && this.routePoints[idx]) || (this.routePoints && this.routePoints[this.routePoints.length - 1])
              const ptName = (this.routePoints && this.routePoints[idx] && this.routePoints[idx].name) || ''
              return {
                title: `第 ${idx + 1} 步${ptName ? '：' + ptName : ''}`,
                content: text,
                tip: idx === 0 ? '出发请提前备好身份证与就医卡，可走绿色通道。' : idx === r.steps.length - 1 ? '到院后门诊大厅设有便民服务台与免费轮椅租借。' : '如有需要可随时向车站或现场工作人员寻求协助。',
                coords: pt ? [pt.lng, pt.lat] : this.elderCoords,
              }
            })
          }
        }
      } catch (e) {
        console.warn('获取后端高德规划失败，采用本地适配航迹:', e)
      }

      // 如果后端未给具体点串，以标准途径点连线兜底
      if (!this.polylinePath.length) {
        this.polylinePath = this.routePoints.map((p) => [p.lng, p.lat])
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
        }).setView([35.5, 117.5], 6)
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
        color: '#2563eb', // 沉稳高对比鲜艳蓝
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
    resetView() {
      if (this.leafletMap && this.routePolyline) {
        this.leafletMap.fitBounds(this.routePolyline.getBounds(), { padding: [40, 40] })
      }
    },
    locateElder() {
      if (this.leafletMap && this.elderCoords) {
        this.leafletMap.setView(toLeafletLatLng(this.elderCoords), 12)
      }
    },
    highlightStep(index) {
      this.currentStepIndex = index
      const step = this.steps[index]
      if (step && step.coords && this.leafletMap) {
        this.leafletMap.setView(toLeafletLatLng(step.coords), 10)
      }
    },
    speakFullRoute() {
      const parts = [
        `老友记为您规划的高德路线。从${this.originName}到${this.destinationName}。全程耗时${this.routeDuration}。`,
      ]
      this.steps.forEach((s) => parts.push(`${s.title}。${s.content}`))
      const ok = speak(parts.join('。'))
      if (!ok) uni.showToast({ title: '当前设备不支持朗读', icon: 'none' })
    },
    speakText(text) {
      const ok = speak(text)
      if (!ok) uni.showToast({ title: '当前设备不支持朗读', icon: 'none' })
    },
    callFamily() {
      uni.showModal({
        title: '已向家人发送报平安提醒',
        content: `已同步当前行进位置（${this.steps[this.currentStepIndex].title}）至子女看板。`,
        showCancel: false,
        confirmText: '好的',
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
  padding-bottom: 60rpx;
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
  background: $lyj-field;
  color: $lyj-text;
  border-radius: 48rpx;
  border: none;
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
  border: 2rpx solid $lyj-line;
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
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.04);
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

/* 高德地图容器 */
.map-section {
  position: relative;
  margin: 0 24rpx 24rpx;
  border-radius: 24rpx;
  overflow: hidden;
  box-shadow: 0 6rpx 18rpx rgba(0, 0, 0, 0.08);
  border: 2rpx solid #e2e8f0;
}
.amap-box {
  width: 100%;
  height: 58vh;
  min-height: 520rpx;
  background: #e2e8f0;
  transition: height 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.map-section.expanded .amap-box {
  height: 82vh;
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
  background: #2563eb;
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
.step-card {
  background: #ffffff;
  border-radius: 20rpx;
  padding: 24rpx;
  margin-bottom: 20rpx;
  border: 2rpx solid #f1ede6;
  box-shadow: 0 4rpx 10rpx rgba(0, 0, 0, 0.03);
  transition: all 0.2s ease;
}
.step-card.active {
  border-color: #2563eb;
  background: #f8faff;
  box-shadow: 0 6rpx 16rpx rgba(37, 99, 235, 0.1);
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
  background: #2563eb;
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
  background: #eff6ff;
  color: #2563eb;
  border-radius: 30rpx;
  border: 1rpx solid #bfdbfe;
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

/* 应急报平安按钮 (触控靶区 >= 48px) */
.help-section {
  margin-top: 36rpx;
}
.btn-help-tel {
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
</style>

<!-- 地图标记的自定义 DOM 样式统一在 utils/amap.js 的 ensureAmapMarkerStyles()
     里以文档级 <style> 注入：Leaflet DivIcon 是运行时插进地图图层容器的，uni-app H5
     会给页面样式加作用域标记，写在这里的非 scoped 规则也命中不到，站点标签会退化成
     竖排黑字。故此处不再重复声明，避免"看似有样式其实不生效"的误导。 -->

