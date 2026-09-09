<template>
  <view class="guardian">
    <LyjBack />
    <LyjSegment current="guardian" />

    <!-- 顶部多行程切换与选择器 -->
    <view v-if="tripOptions.length > 0" class="trip-selector-box">
      <view class="selector-head">
        <view class="selector-label-group">
          <text class="selector-icon">🛡️</text>
          <text class="selector-label">守护行程：</text>
        </view>
        <picker
          mode="selector"
          :range="tripOptions"
          range-key="label"
          :value="selectedTripIndex"
          @change="onPickerChange"
        >
          <view class="picker-current-pill">
            <text class="picker-text">{{ currentTripShortLabel }}</text>
            <text class="picker-dropdown-icon">▾ 切换</text>
          </view>
        </picker>
      </view>

      <!-- 快捷横向切换标签 (多行程与历史行程) -->
      <scroll-view scroll-x class="trip-tags-scroll" :show-scrollbar="false">
        <view class="trip-tags-wrap">
          <view
            v-for="t in allTrips"
            :key="t.id"
            class="trip-tag-item"
            :class="{ active: t.id === tripId }"
            @tap="switchTrip(t.id)"
          >
            <text class="tag-name">{{ formatTripTitle(t) }}</text>
            <text class="tag-badge" :class="t.status">{{ statusText(t.status) }}</text>
          </view>
        </view>
      </scroll-view>
    </view>

    <!-- 当前行程头部概要 -->
    <view v-if="trip" class="trip-head">
      <view class="trip-head-main">
        <text class="trip-title">{{ trip.purpose || '未命名出行计划' }}</text>
        <text class="trip-sub">{{ statusText(trip.status) }} · {{ reportLine }}</text>
      </view>
      <view class="trip-head-status" :class="trip.status">
        <text>{{ statusText(trip.status) }}</text>
      </view>
    </view>

    <!-- 隐私级别说明提示条 -->
    <view v-if="precisionNote" class="precision-note">
      <text class="precision-text">🔒 {{ precisionNote }}</text>
    </view>

    <!-- 行程关联待审批事项（挂号、车票、酒店等高危操作） -->
    <view v-if="pendingConfirmations && pendingConfirmations.length > 0" class="pending-section">
      <view class="pending-section-head">
        <text class="pending-section-title">✋ 行程关联待审批事项 ({{ pendingConfirmations.length }})</text>
        <text class="pending-section-sub">长辈已发起申请，等待您确认核准</text>
      </view>
      <view v-for="t in pendingConfirmations" :key="t.id" class="pending-card" @tap="goDetail(t)">
        <view class="pending-card-top">
          <view class="pending-icon">{{ taskIcon(t) }}</view>
          <view class="pending-main">
            <view class="pending-summary-row">
              <text class="pending-summary">{{ taskSummary(t) }}</text>
              <text v-if="t.amount" class="pending-cost">¥{{ t.amount }}</text>
            </view>
            <text v-if="taskReason(t)" class="pending-reason">原因：{{ taskReason(t) }}</text>
          </view>
        </view>
        <view class="pending-action-bar">
          <text class="pending-go" @tap.stop="goDetail(t)">查看详情 ›</text>
          <view v-if="t.status === 'executed' || t.status === 'approved'" class="inline-status success">
            <text>✅ 已同意并办理</text>
          </view>
          <view v-else-if="t.status === 'rejected'" class="inline-status rejected">
            <text>🚫 已拒绝</text>
          </view>
          <view v-else class="pending-btns">
            <button
              class="btn-approve"
              size="mini"
              :loading="actionLoading[t.id] === 'approve'"
              :disabled="!!actionLoading[t.id]"
              @tap.stop="approveTask(t)"
            >
              同意
            </button>
            <button
              class="btn-reject"
              size="mini"
              :loading="actionLoading[t.id] === 'reject'"
              :disabled="!!actionLoading[t.id]"
              @tap.stop="rejectTask(t)"
            >
              拒绝
            </button>
          </view>
        </view>
      </view>
    </view>

    <!-- 空状态 -->
    <view v-if="!trip && loaded" class="empty-card">
      <text class="empty-text">{{ emptyText }}</text>
    </view>

    <template v-else-if="trip && !locationOff">
      <!-- 真实高德地图行程守护视窗 (高德 JS API 2.0 Canvas 渲染) -->
      <view class="gaode-guard-card" :class="{ expanded: isMapExpanded }">
        <!-- 偏航警报气泡 (长辈偏离路线时醒目显示) -->
        <view v-if="isOffRoute" class="offroute-alert-bubble">
          <view class="alert-icon-pulse">⚠️</view>
          <view class="alert-info">
            <text class="alert-title">偏航警报：长辈已偏离规划路线！</text>
            <text class="alert-detail">{{ offRouteDetail }}</text>
          </view>
          <button class="alert-action-btn" size="mini" @tap="callElder">
            致电核实
          </button>
        </view>

        <!-- 长辈实时位置与状态浮动条 -->
        <view class="elder-live-status-card" v-if="latestCheckpoint">
          <view class="live-status-main">
            <view class="live-avatar-box">👴</view>
            <view class="live-info-box">
              <view class="live-place-row">
                <text class="live-place-name">{{ latestCheckpoint.location || '已连接' }}</text>
                <text class="live-status-tag" :class="latestCheckpoint.status">
                  {{ latestCheckpoint.status === 'off_route' ? '⚠️ 偏航预警' : latestCheckpoint.status === 'arrived' ? '🏁 已到达' : '🟢 正常行进' }}
                </text>
              </view>
              <text class="live-note" v-if="latestCheckpoint.note">{{ latestCheckpoint.note }}</text>
              <text class="live-time" v-if="latestCheckpoint.created_at">最新同步：{{ formatCheckpointTime(latestCheckpoint.created_at) }}</text>
            </view>
          </view>
          <button class="live-focus-btn" size="mini" @tap="focusElderLocation">📍 聚焦长辈</button>
        </view>

        <!-- 地图 Canvas 挂载点 -->
        <div id="child-gaode-map" class="child-amap-canvas" :class="{ expanded: isMapExpanded }"></div>

        <view v-if="mapLoading" class="map-loading-overlay">
          <text class="map-loading-text">高德地图 2.0 视窗渲染中…</text>
        </view>

        <!-- 地图浮动工具条 -->
        <view class="guard-map-statusbar">
          <view class="status-indicator-pill">
            <view class="status-indicator-dot" :class="{ alert: isOffRoute }"></view>
            <text class="status-indicator-text">
              {{ isOffRoute ? '⚠️ 发现偏离规划路线' : '🟢 实时守护中 (8秒自动刷新)' }}
            </text>
          </view>
          <view class="map-ctrl-btns">
            <button class="ctrl-btn expand" size="mini" @tap="toggleMapExpand">
              {{ isMapExpanded ? '🗗 恢复标准' : '🔍 放大地图' }}
            </button>
            <button class="ctrl-btn" size="mini" @tap="resetChildMapView">🗺️ 全览</button>
            <button class="ctrl-btn" size="mini" @tap="focusElderLocation">📍 父母位置</button>
          </view>
        </view>

        <!-- 演示与调试模拟操作栏 -->
        <view class="sim-action-row">
          <text class="sim-row-label">演示操作：</text>
          <button class="sim-pill-btn normal" size="mini" @tap="simElderMove('normal')">
            模拟正常前进
          </button>
          <button class="sim-pill-btn warn" size="mini" @tap="simElderMove('offroute')">
            模拟偏航告警
          </button>
        </view>
      </view>

      <!-- 位置记录时间线 -->
      <view class="section">
        <view class="section-title-row">
          <text class="section-title">📍 位置记录时间线</text>
          <text class="section-sub-tip">接收长辈端 10 秒定时上报</text>
        </view>
        <view v-if="!checkpoints.length" class="empty-row">
          <text>长辈暂未上报新位置（进入高德路线规划后每 10 秒自动更新）</text>
        </view>
        <view v-for="(cp, i) in checkpoints" :key="cp.id || i" class="cp">
          <view class="cp-left">
            <view class="cp-dot" :class="cp.status"></view>
            <view v-if="i < checkpoints.length - 1" class="cp-line"></view>
          </view>
          <view class="cp-body">
            <view class="cp-row">
              <text class="cp-location">{{ cp.location }}</text>
              <text class="cp-time">{{ fmtTime(cp.created_at) }}</text>
            </view>
            <text class="cp-note" :class="cp.status">{{ cp.note || cp.status }}</text>
          </view>
        </view>
      </view>
    </template>
  </view>
</template>

<script>
import LyjSegment from '../../components/LyjSegment.vue'
import { loadAMap } from '../../utils/amap'
import { get, post } from '../../api/client'
import { getCurrentUser } from '../../store/user'
import { publishPendingCount } from '../../store/pendingBadge'

const PRECISION_NOTE = {
  city: '长辈将位置权限设为城市级，以下仅展示粗化后的地点，已隐藏详细门牌号与精确坐标。',
  off: '长辈未开放位置共享，无法查看实时经纬度与航迹。',
}

const DEFAULT_POINTS = [
  { name: '家（南京鼓楼区）', lng: 118.7732, lat: 32.0618, type: 'start' },
  { name: '南京南站', lng: 118.7981, lat: 31.9696, type: 'station' },
  { name: '济南西站', lng: 116.8974, lat: 36.6669, type: 'station' },
  { name: '北京南站', lng: 116.3789, lat: 39.8652, type: 'station' },
  { name: '北京积水潭医院', lng: 116.3748, lat: 39.9485, type: 'end' },
]

export default {
  name: 'ChildGuardian',
  components: { LyjSegment },
  data() {
    return {
      user: null,
      tripId: '',
      trip: null,
      allTrips: [],
      checkpoints: [],
      precision: '',
      loaded: false,
      mapLoading: true,
      pendingConfirmations: [],
      actionLoading: {},
      pollTimer: null,
      amapInstance: null,
      routePolyline: null,
      elderMarker: null,
      offRouteMarker: null,
      waypointMarkers: [],
      elderCoords: [118.7732, 32.0618],
      routeCoords: [],
      routePointsData: DEFAULT_POINTS,
      isMapExpanded: false,
      simStep: 0,
      _switchSeq: 0,
    }
  },
  computed: {
    statusTextMap() {
      return { planned: '已规划', ongoing: '进行中', completed: '已完成' }
    },
    locationOff() {
      return this.precision === 'off'
    },
    precisionNote() {
      return PRECISION_NOTE[this.precision] || ''
    },
    reportLine() {
      if (this.locationOff) return '位置未开放'
      return `共 ${this.checkpoints.length} 次位置记录`
    },
    emptyText() {
      if (!this.loaded) return '加载中…'
      return '还没有出行行程。长辈规划行程后将在此实时守护。'
    },
    tripOptions() {
      return this.allTrips.map((t) => ({
        label: `${t.purpose || t.title || '出行计划'}（${this.statusText(t.status)}）`,
        value: t.id,
      }))
    },
    selectedTripIndex() {
      const idx = this.allTrips.findIndex((t) => t.id === this.tripId)
      return idx >= 0 ? idx : 0
    },
    currentTripShortLabel() {
      if (!this.trip) return '选择行程'
      const p = this.trip.purpose || this.trip.title || '出行计划'
      return p.length > 14 ? p.slice(0, 14) + '…' : p
    },
    latestCheckpoint() {
      if (!this.checkpoints || !this.checkpoints.length) return null
      return this.checkpoints[this.checkpoints.length - 1]
    },
    isOffRoute() {
      if (!this.latestCheckpoint) return false
      return this.latestCheckpoint.status === 'off_route'
    },
    offRouteDetail() {
      if (!this.latestCheckpoint) return ''
      return this.latestCheckpoint.note || `长辈当前处于规划路线外（${this.latestCheckpoint.location}）`
    },
  },
  onLoad(opts) {
    this.tripId = (opts && opts.trip_id) || ''
  },
  onShow() {
    this.user = getCurrentUser()
    if (!this.user || this.user.role !== 'child') {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.initData()
  },
  onHide() {
    this.stopPolling()
  },
  onUnload() {
    this.stopPolling()
    if (this.amapInstance) {
      try {
        this.amapInstance.destroy()
      } catch (e) {}
    }
  },
  methods: {
    statusText(s) {
      return { planned: '已规划', ongoing: '进行中', completed: '已完成' }[s] || s || '进行中'
    },
    formatTripTitle(t) {
      const title = t.purpose || t.title || '出行计划'
      return title.length > 10 ? title.slice(0, 10) + '…' : title
    },
    async initData() {
      await this.loadTripsAndDetail()
      await this.initChildAmap()
      this.startPolling()
    },
    async loadTripsAndDetail() {
      try {
        // 1. 获取子女关联老人的所有行程列表
        const [dashRes, tripsRes] = await Promise.all([
          get(`/api/child/${this.user.id}/dashboard`).catch(() => null),
          get('/api/trips').catch(() => null),
        ])

        if (tripsRes && Array.isArray(tripsRes.trips)) {
          this.allTrips = tripsRes.trips
        } else if (dashRes && Array.isArray(dashRes.trips)) {
          this.allTrips = dashRes.trips
        }

        // 确定当前展示的 tripId (优先匹配进行中且有定位记录的行程)
        if (!this.tripId && this.allTrips.length > 0) {
          const activeTrip = this.allTrips.find((t) => t.status === 'ongoing' && t.has_checkpoints)
            || this.allTrips.find((t) => t.status === 'ongoing')
            || this.allTrips.find((t) => t.has_checkpoints)
            || this.allTrips[0]
          this.tripId = activeTrip.id
        }

        // 2. 加载选中的行程详情
        if (this.tripId) {
          const tripDetailRes = await get(`/api/trips/${this.tripId}`, { child_id: this.user.id })
          if (tripDetailRes) {
            this.trip = tripDetailRes.trip
            this.checkpoints = tripDetailRes.checkpoints || []
            this.precision = tripDetailRes.precision || ''

            // 提取后端返回的高德规划路线
            if (tripDetailRes.route && tripDetailRes.route.ok) {
              const r = tripDetailRes.route
              if (Array.isArray(r.polyline) && r.polyline.length) {
                this.routeCoords = r.polyline.map((p) => [p.lng, p.lat])
              }
              if (Array.isArray(r.points) && r.points.length) {
                this.routePointsData = r.points.map((p) => ({
                  name: p.location || p.name,
                  lng: p.lng,
                  lat: p.lat,
                  type: p.desc && p.desc.includes('起点') ? 'start' : p.desc && p.desc.includes('目的地') ? 'end' : 'station',
                }))
              }
            }
          }
        }

        // 提取待审批事项
        if (dashRes && Array.isArray(dashRes.pending_confirmations)) {
          this.pendingConfirmations = dashRes.pending_confirmations
          publishPendingCount(
            this.pendingConfirmations.filter((x) => !x.status || x.status === 'pending').length,
          )
        }

        // 同步最新的长辈经纬度
        if (this.latestCheckpoint && this.latestCheckpoint.lng && this.latestCheckpoint.lat) {
          this.elderCoords = [this.latestCheckpoint.lng, this.latestCheckpoint.lat]
        } else if (dashRes && dashRes.latest_location && dashRes.latest_location.lng && dashRes.latest_location.lat) {
          this.elderCoords = [dashRes.latest_location.lng, dashRes.latest_location.lat]
          if (!this.checkpoints.length) {
            this.checkpoints.push(dashRes.latest_location)
          }
        } else if (this.routePointsData.length) {
          this.elderCoords = [this.routePointsData[0].lng, this.routePointsData[0].lat]
        }
      } catch (e) {
        uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
      this.loaded = true
    },
    async switchTrip(newTripId) {
      if (this.tripId === newTripId) return
      this.tripId = newTripId
      this.routeCoords = []
      const seq = ++this._switchSeq
      await this.loadTripsAndDetail()
      if (seq !== this._switchSeq) return
      this.renderTripOnMap()
    },
    onPickerChange(e) {
      const idx = e.detail.value
      if (this.tripOptions[idx]) {
        this.switchTrip(this.tripOptions[idx].value)
      }
    },
    async initChildAmap() {
      try {
        const AMap = await loadAMap()
        const container = document.getElementById('child-gaode-map')
        if (!container) return

        if (!this.amapInstance) {
          this.amapInstance = new AMap.Map(container, {
            zoom: 6,
            center: [117.5, 35.5],
            viewMode: '2D',
            mapStyle: 'amap://styles/normal',
          })
        }
        this.renderTripOnMap()
        this.mapLoading = false
      } catch (err) {
        console.error('子女端高德地图初始化失败:', err)
        this.mapLoading = false
      }
    },
    renderTripOnMap() {
      if (!this.amapInstance || typeof window === 'undefined' || !window.AMap) return
      const AMap = window.AMap

      // 清除旧图层与站点标记
      if (this.routePolyline) {
        this.amapInstance.remove(this.routePolyline)
        this.routePolyline = null
      }
      if (this.waypointMarkers.length) {
        this.amapInstance.remove(this.waypointMarkers)
        this.waypointMarkers = []
      }
      if (this.offRouteMarker) {
        this.amapInstance.remove(this.offRouteMarker)
        this.offRouteMarker = null
      }

      // 如果未获取到详细 polyline，使用途经点连线兜底
      const polyPath = this.routeCoords.length
        ? this.routeCoords
        : this.routePointsData.map((p) => [p.lng, p.lat])

      // 绘制行程真实路线轨迹 Polyline
      this.routePolyline = new AMap.Polyline({
        path: polyPath,
        isOutline: true,
        outlineColor: '#ffffff',
        borderWeight: 2,
        strokeColor: '#2563eb', // 专业沉稳高德蓝
        strokeOpacity: 0.92,
        strokeWeight: 7,
        strokeStyle: 'solid',
        lineJoin: 'round',
        lineCap: 'round',
        showDir: true,
      })
      this.amapInstance.add(this.routePolyline)

      // 绘制途经打点 Markers
      this.routePointsData.forEach((pt) => {
        const isStart = pt.type === 'start'
        const isEnd = pt.type === 'end'
        const badgeColor = isStart ? '#10b981' : isEnd ? '#ef4444' : '#3b82f6'
        const prefix = isStart ? '起·' : isEnd ? '终·' : '站·'

        const markerEl = document.createElement('div')
        markerEl.className = 'child-map-station-badge'
        markerEl.style.backgroundColor = badgeColor
        markerEl.innerText = `${prefix}${pt.name}`

        const marker = new AMap.Marker({
          position: [pt.lng, pt.lat],
          content: markerEl,
          offset: new AMap.Pixel(-40, -28),
        })
        this.waypointMarkers.push(marker)
        this.amapInstance.add(marker)
      })

      // 绘制/更新长辈当前位置呼吸 Marker
      if (!this.elderMarker) {
        const liveEl = document.createElement('div')
        liveEl.className = 'child-elder-breathe-marker'
        liveEl.innerHTML = `
          <div class="breathe-wave"></div>
          <div class="breathe-core">👴 父母实时位置</div>
        `
        this.elderMarker = new AMap.Marker({
          position: this.elderCoords,
          content: liveEl,
          offset: new AMap.Pixel(-45, -20),
          zIndex: 130,
        })
        this.amapInstance.add(this.elderMarker)
      } else {
        this.elderMarker.setPosition(this.elderCoords)
      }

      // 同步偏航警告点标记
      this.updateOffRouteMarker()

      // 自适应视野缩放
      this.amapInstance.setFitView([this.routePolyline])
    },
    updateOffRouteMarker() {
      if (!this.amapInstance || typeof window === 'undefined' || !window.AMap) return
      const AMap = window.AMap

      if (this.isOffRoute && this.latestCheckpoint && this.latestCheckpoint.lng != null && this.latestCheckpoint.lat != null) {
        const offPos = [this.latestCheckpoint.lng, this.latestCheckpoint.lat]
        const offEl = document.createElement('div')
        offEl.className = 'child-offroute-marker-bubble'
        offEl.innerHTML = `⚠️ 偏离路线点：${this.latestCheckpoint.location}`

        if (!this.offRouteMarker) {
          this.offRouteMarker = new AMap.Marker({
            position: offPos,
            content: offEl,
            offset: new AMap.Pixel(-60, -32),
            zIndex: 140,
          })
          this.amapInstance.add(this.offRouteMarker)
        } else {
          this.offRouteMarker.setPosition(offPos)
          this.offRouteMarker.setContent(offEl)
        }
      } else if (this.offRouteMarker) {
        this.amapInstance.remove(this.offRouteMarker)
        this.offRouteMarker = null
      }
    },
    startPolling() {
      this.stopPolling()
      this.pollTimer = setInterval(async () => {
        if (!this.tripId) return
        try {
          const res = await get(`/api/trips/${this.tripId}/realtime`, { child_id: this.user.id })
          if (res && res.latest_checkpoint) {
            const cp = res.latest_checkpoint
            // 若有新位置坐标且与当前不同，更新并在地图上平滑移动
            if (cp.lng && cp.lat) {
              const newPos = [cp.lng, cp.lat]
              this.elderCoords = newPos
              if (this.elderMarker) {
                this.elderMarker.setPosition(newPos)
              }
            }
            // 增量检查是否有新上报记录
            if (
              !this.checkpoints.length ||
              this.checkpoints[this.checkpoints.length - 1].id !== cp.id
            ) {
              this.checkpoints.push(cp)
            }
            // 动态同步地图偏航告警气泡打点
            this.updateOffRouteMarker()
          }
        } catch (e) {
          // 轮询偶发静默
        }
      }, 8000)
    },
    toggleMapExpand() {
      this.isMapExpanded = !this.isMapExpanded
      this.$nextTick(() => {
        if (this.amapInstance) {
          setTimeout(() => {
            if (this.routePolyline) {
              this.amapInstance.setFitView([this.routePolyline])
            } else {
              this.amapInstance.setFitView()
            }
          }, 200)
        }
      })
    },
    formatCheckpointTime(ts) {
      if (!ts) return '刚刚'
      try {
        const d = new Date(ts)
        const hh = String(d.getHours()).padStart(2, '0')
        const mm = String(d.getMinutes()).padStart(2, '0')
        const ss = String(d.getSeconds()).padStart(2, '0')
        return `${hh}:${mm}:${ss}`
      } catch (e) {
        return ts
      }
    },
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },
    resetChildMapView() {
      if (this.amapInstance && this.routePolyline) {
        this.amapInstance.setFitView([this.routePolyline])
      }
    },
    focusElderLocation() {
      if (this.amapInstance && this.elderCoords) {
        this.amapInstance.setZoomAndCenter(13, this.elderCoords)
        uni.showToast({ title: '已定位父母当前坐标', icon: 'none' })
      }
    },
    callElder() {
      uni.showModal({
        title: '致电长辈确认',
        content: `长辈当前位置：${this.latestCheckpoint ? this.latestCheckpoint.location : '偏离路线'}。是否立即呼叫长辈电话？`,
        confirmText: '立即呼叫',
        cancelText: '取消',
        success: (res) => {
          if (res.confirm) {
            uni.makePhoneCall({
              phoneNumber: '13800000000',
              fail: () => {
                uni.showToast({ title: '已模拟拨打长辈电话', icon: 'none' })
              },
            })
          }
        },
      })
    },
    async simElderMove(type) {
      if (!this.tripId) return
      if (type === 'offroute') {
        // 模拟偏航到朝阳区三里屯
        try {
          const res = await post(`/api/trips/${this.tripId}/checkpoints`, {
            location: '北京市朝阳区三里屯太古里',
            lng: 116.455,
            lat: 39.937,
          })
          if (res && res.checkpoint) {
            this.checkpoints.push(res.checkpoint)
            this.elderCoords = [116.455, 39.937]
            this.renderTripOnMap()
            uni.showToast({ title: '已触发偏航模拟上报！', icon: 'none' })
          }
        } catch (e) {
          uni.showToast({ title: e.message || '模拟失败', icon: 'none' })
        }
      } else {
        // 模拟正常前进到下一站点
        this.simStep = (this.simStep + 1) % this.routePointsData.length
        const targetPoint = this.routePointsData[this.simStep]
        try {
          const res = await post(`/api/trips/${this.tripId}/checkpoints`, {
            location: targetPoint.name,
            lng: targetPoint.lng,
            lat: targetPoint.lat,
          })
          if (res && res.checkpoint) {
            this.checkpoints.push(res.checkpoint)
            this.elderCoords = [targetPoint.lng, targetPoint.lat]
            this.renderTripOnMap()
            uni.showToast({ title: `已行进到：${targetPoint.name}`, icon: 'none' })
          }
        } catch (e) {
          uni.showToast({ title: e.message || '模拟失败', icon: 'none' })
        }
      }
    },
    taskIcon(t) {
      const map = {
        book_ticket: '🚄',
        search_train: '🚄',
        register_appointment: '🏥',
        search_hospital: '🏥',
        book_hotel: '🏨',
        order_service: '🧹',
        pay: '💸',
      }
      return map[t.tool_name] || '✋'
    },
    taskSummary(t) {
      const card = t.summary_for_child || {}
      return card.summary || t.tool_name || '需要您确认的事项'
    },
    taskReason(t) {
      const card = t.summary_for_child || {}
      return card.reason || ''
    },
    goDetail(t) {
      uni.navigateTo({
        url: `/pages/child/confirm-detail?id=${t.id}&child_id=${this.user.id}`,
      })
    },
    async approveTask(t) {
      if (this.actionLoading[t.id]) return
      if (t.status && t.status !== 'pending') return
      this.actionLoading[t.id] = 'approve'
      try {
        const res = await post(`/api/confirmations/${t.id}/approve?child_id=${this.user.id}`)
        const nextStatus = res.status || (res.ok ? 'executed' : 'failed')
        t.status = nextStatus
        publishPendingCount(
          this.pendingConfirmations.filter((x) => !x.status || x.status === 'pending').length,
        )
        uni.showToast({ title: '已同意并办理', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '操作失败', icon: 'none' })
      } finally {
        delete this.actionLoading[t.id]
      }
    },
    async rejectTask(t) {
      if (this.actionLoading[t.id]) return
      if (t.status && t.status !== 'pending') return
      const confirmed = await new Promise((resolve) => {
        uni.showModal({
          title: '确认拒绝',
          content: '确定要拒绝长辈的这项请求吗？',
          confirmText: '拒绝',
          confirmColor: '#ef4444',
          cancelText: '再想想',
          success: (r) => resolve(!!r.confirm),
          fail: () => resolve(false),
        })
      })
      if (!confirmed) return
      this.actionLoading[t.id] = 'reject'
      try {
        const res = await post(`/api/confirmations/${t.id}/reject?child_id=${this.user.id}`)
        const nextStatus = res.status || 'rejected'
        t.status = nextStatus
        publishPendingCount(
          this.pendingConfirmations.filter((x) => !x.status || x.status === 'pending').length,
        )
        uni.showToast({ title: '已拒绝', icon: 'none' })
      } catch (err) {
        uni.showToast({ title: err.message || '操作失败', icon: 'none' })
      } finally {
        delete this.actionLoading[t.id]
      }
    },
    fmtTime(iso) {
      if (!iso) return ''
      const d = new Date(iso)
      if (!Number.isFinite(d.getTime())) return ''
      const pad = (n) => String(n).padStart(2, '0')
      return `${pad(d.getHours())}:${pad(d.getMinutes())}`
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.guardian {
  min-height: 100vh;
  background: #f8fafc;
  padding: $lyj-space-md 0 $lyj-space-xl;
  box-sizing: border-box;
}

/* 行程选择器与多行程切换栏 */
.trip-selector-box {
  margin: $lyj-space-sm $lyj-space-md;
  background: #ffffff;
  border-radius: 16rpx;
  border: 1rpx solid #e2e8f0;
  padding: 18rpx 20rpx;
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.04);
}
.selector-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.selector-label-group {
  display: flex;
  align-items: center;
  gap: 8rpx;
}
.selector-icon {
  font-size: 32rpx;
}
.selector-label {
  font-size: 28rpx;
  font-weight: 700;
  color: #1e293b;
}
.picker-current-pill {
  display: flex;
  align-items: center;
  gap: 8rpx;
  background: #eff6ff;
  border: 1rpx solid #bfdbfe;
  border-radius: 30rpx;
  padding: 6rpx 20rpx;
  cursor: pointer;
}
.picker-text {
  font-size: 26rpx;
  color: #1d4ed8;
  font-weight: 700;
}
.picker-dropdown-icon {
  font-size: 22rpx;
  color: #3b82f6;
}
.trip-tags-scroll {
  width: 100%;
  white-space: nowrap;
  margin-top: 14rpx;
  padding-top: 10rpx;
  border-top: 1rpx dashed #f1f5f9;
}
.trip-tags-wrap {
  display: flex;
  gap: 12rpx;
}
.trip-tag-item {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  background: #f1f5f9;
  border-radius: 10rpx;
  padding: 8rpx 16rpx;
  border: 1rpx solid #e2e8f0;
  cursor: pointer;
  flex-shrink: 0;
}
.trip-tag-item.active {
  background: #1e293b;
  border-color: #1e293b;
}
.tag-name {
  font-size: 24rpx;
  color: #475569;
  font-weight: 600;
}
.trip-tag-item.active .tag-name {
  color: #ffffff;
}
.tag-badge {
  font-size: 20rpx;
  padding: 2rpx 8rpx;
  border-radius: 6rpx;
  background: #cbd5e1;
  color: #334155;
  font-weight: 700;
}
.tag-badge.ongoing {
  background: #dbeafe;
  color: #1d4ed8;
}
.tag-badge.completed {
  background: #dcfce7;
  color: #15803d;
}

/* 行程头部 */
.trip-head {
  padding: $lyj-space-sm $lyj-space-lg;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.trip-head-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}
.trip-title {
  font-size: 34rpx;
  font-weight: 800;
  color: #0f172a;
}
.trip-sub {
  font-size: 26rpx;
  color: #64748b;
}
.trip-head-status {
  padding: 6rpx 18rpx;
  border-radius: 20rpx;
  font-size: 24rpx;
  font-weight: 700;
  background: #dbeafe;
  color: #1d4ed8;
}
.trip-head-status.completed {
  background: #dcfce7;
  color: #15803d;
}

/* 隐私提示 */
.precision-note {
  margin: $lyj-space-xs $lyj-space-md;
  padding: $lyj-space-md;
  background: #eff6ff;
  border: 2rpx solid #bfdbfe;
  border-radius: $lyj-radius;
}
.precision-text {
  font-size: 26rpx;
  color: #1d4ed8;
  line-height: 1.5;
}

/* 高德地图行程守护视窗 */
.gaode-guard-card {
  position: relative;
  margin: $lyj-space-sm $lyj-space-md;
  background: #ffffff;
  border-radius: 20rpx;
  overflow: hidden;
  border: 2rpx solid #e2e8f0;
  box-shadow: 0 4rpx 14rpx rgba(0, 0, 0, 0.06);
  transition: all 0.3s ease;
}
.gaode-guard-card.expanded {
  margin: 0 8rpx $lyj-space-md;
  border-radius: 24rpx;
  box-shadow: 0 10rpx 30rpx rgba(0, 0, 0, 0.15);
}
.elder-live-status-card {
  padding: 16rpx 20rpx;
  background: #f8fafc;
  border-bottom: 2rpx solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}
.live-status-main {
  display: flex;
  align-items: center;
  gap: 16rpx;
  flex: 1;
  min-width: 0;
}
.live-avatar-box {
  width: 64rpx;
  height: 64rpx;
  border-radius: 50%;
  background: #e0f2fe;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 36rpx;
  flex-shrink: 0;
}
.live-info-box {
  flex: 1;
  min-width: 0;
}
.live-place-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-wrap: wrap;
}
.live-place-name {
  font-size: 28rpx;
  font-weight: 800;
  color: #0f172a;
}
.live-status-tag {
  font-size: 22rpx;
  font-weight: 700;
  padding: 2rpx 12rpx;
  border-radius: 12rpx;
  background: #dcfce7;
  color: #15803d;
}
.live-status-tag.off_route {
  background: #fee2e2;
  color: #b91c1c;
}
.live-status-tag.arrived {
  background: #e0e7ff;
  color: #4338ca;
}
.live-note {
  display: block;
  font-size: 22rpx;
  color: #64748b;
  margin-top: 4rpx;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.live-time {
  display: block;
  font-size: 20rpx;
  color: #94a3b8;
  margin-top: 2rpx;
}
.live-focus-btn {
  background: #2563eb;
  color: #ffffff;
  font-size: 22rpx;
  font-weight: 700;
  border-radius: 24rpx;
  border: none;
  padding: 6rpx 20rpx;
  flex-shrink: 0;
}
.child-amap-canvas {
  width: 100%;
  height: 760rpx;
  background: #f1f5f9;
  transition: height 0.3s ease;
}
.child-amap-canvas.expanded {
  height: 82vh;
  min-height: 600px;
}
@media (min-width: 768px) {
  .child-amap-canvas {
    height: 540px;
  }
  .child-amap-canvas.expanded {
    height: 80vh;
    min-height: 680px;
  }
}
.map-loading-overlay {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
}
.map-loading-text {
  font-size: 26rpx;
  color: #475569;
  font-weight: 600;
}

/* 偏航预警悬浮气泡 */
.offroute-alert-bubble {
  position: absolute;
  top: 16rpx;
  left: 16rpx;
  right: 16rpx;
  z-index: 100;
  background: #fef2f2;
  border: 2rpx solid #ef4444;
  border-radius: 16rpx;
  padding: 16rpx 20rpx;
  display: flex;
  align-items: center;
  gap: 12rpx;
  box-shadow: 0 6rpx 18rpx rgba(239, 68, 68, 0.2);
  animation: shakeAlert 0.4s ease;
}
@keyframes shakeAlert {
  0%, 100% { transform: translateY(0); }
  25% { transform: translateY(-4rpx); }
  75% { transform: translateY(4rpx); }
}
.alert-icon-pulse {
  font-size: 40rpx;
  flex-shrink: 0;
}
.alert-info {
  flex: 1;
  min-width: 0;
}
.alert-title {
  display: block;
  font-size: 28rpx;
  font-weight: 800;
  color: #991b1b;
}
.alert-detail {
  display: block;
  font-size: 24rpx;
  color: #b91c1c;
  margin-top: 4rpx;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.alert-action-btn,
.alert-call-btn {
  background: #ef4444;
  color: #ffffff;
  font-size: 24rpx;
  font-weight: 700;
  border-radius: 24rpx;
  border: none;
  padding: 4rpx 18rpx;
  flex-shrink: 0;
}

/* 地图状态与工具栏 */
.guard-map-statusbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14rpx 20rpx;
  background: #ffffff;
  border-top: 1rpx solid #e2e8f0;
}
.status-indicator-pill {
  display: flex;
  align-items: center;
  gap: 10rpx;
}
.status-indicator-dot {
  width: 16rpx;
  height: 16rpx;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 4rpx rgba(16, 185, 129, 0.25);
}
.status-indicator-dot.alert {
  background: #ef4444;
  box-shadow: 0 0 0 4rpx rgba(239, 68, 68, 0.25);
  animation: dotFlash 1s infinite alternate;
}
@keyframes dotFlash {
  from { opacity: 0.5; }
  to { opacity: 1; }
}
.status-indicator-text {
  font-size: 24rpx;
  font-weight: 700;
  color: #334155;
}
.map-ctrl-btns {
  display: flex;
  gap: 10rpx;
}
.ctrl-btn {
  background: #f1f5f9;
  color: #334155;
  border: 1rpx solid #cbd5e1;
  border-radius: 20rpx;
  font-size: 22rpx;
  font-weight: 700;
  padding: 4rpx 16rpx;
  margin: 0;
  cursor: pointer;
}
.ctrl-btn.expand {
  background: #2563eb;
  color: #ffffff;
  border-color: #1d4ed8;
}

/* 模拟操作栏 */
.sim-action-row {
  display: flex;
  align-items: center;
  gap: 10rpx;
  padding: 12rpx 20rpx;
  background: #f8fafc;
  border-top: 1rpx dashed #e2e8f0;
}
.sim-row-label {
  font-size: 22rpx;
  color: #64748b;
  font-weight: 600;
}
.sim-pill-btn {
  font-size: 22rpx;
  font-weight: 700;
  border-radius: 20rpx;
  padding: 2rpx 16rpx;
  margin: 0;
}
.sim-pill-btn.normal {
  background: #e0f2fe;
  color: #0369a1;
  border: 1rpx solid #bae6fd;
}
.sim-pill-btn.warn {
  background: #fee2e2;
  color: #b91c1c;
  border: 1rpx solid #fca5a5;
}

/* 时间线 */
.section {
  background: #ffffff;
  border-radius: 20rpx;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md;
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.04);
  border: 1rpx solid #e2e8f0;
}
.section-title-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 12rpx;
}
.section-title {
  font-size: 30rpx;
  font-weight: 800;
  color: #0f172a;
}
.section-sub-tip {
  font-size: 22rpx;
  color: #94a3b8;
}
.empty-row {
  padding: $lyj-space-md 0;
  font-size: 26rpx;
  color: #94a3b8;
}
.cp {
  display: flex;
  gap: $lyj-space-md;
  padding: $lyj-space-sm 0;
}
.cp-left {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.cp-dot {
  width: 20rpx;
  height: 20rpx;
  border-radius: 50%;
  background: #10b981;
  flex-shrink: 0;
  margin-top: $lyj-space-xs;
}
.cp-dot.off_route {
  background: #ef4444;
}
.cp-line {
  flex: 1;
  width: 4rpx;
  background: #e2e8f0;
  margin: $lyj-space-xs 0;
}
.cp-body {
  flex: 1;
  padding-bottom: $lyj-space-sm;
}
.cp-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: $lyj-space-sm;
}
.cp-location {
  font-size: 28rpx;
  font-weight: 700;
  color: #1e293b;
}
.cp-time {
  font-size: 24rpx;
  color: #94a3b8;
}
.cp-note {
  display: block;
  font-size: 26rpx;
  color: #475569;
  line-height: 1.4;
  margin-top: $lyj-space-xs;
}
.cp-note.off_route {
  color: #dc2626;
  font-weight: 700;
}

/* 待审批 */
.pending-section {
  margin: $lyj-space-sm $lyj-space-md;
  background: #fffbeb;
  border: 2rpx solid #fde68a;
  border-radius: $lyj-radius;
  padding: $lyj-space-md;
}
.pending-section-head {
  margin-bottom: $lyj-space-sm;
}
.pending-section-title {
  display: block;
  font-size: $lyj-font-md;
  font-weight: 700;
  color: #b45309;
}
.pending-section-sub {
  display: block;
  font-size: $lyj-font-xs;
  color: #92400e;
  margin-top: 4rpx;
}
.pending-card {
  background: #ffffff;
  border: 1rpx solid #fde68a;
  border-radius: 12rpx;
  padding: $lyj-space-md;
  margin-bottom: $lyj-space-sm;
  box-shadow: 0 2rpx 6rpx rgba(180, 83, 9, 0.06);
}
.pending-card:last-child {
  margin-bottom: 0;
}
.pending-card-top {
  display: flex;
  gap: $lyj-space-sm;
}
.pending-icon {
  font-size: 40rpx;
  flex-shrink: 0;
}
.pending-main {
  flex: 1;
  min-width: 0;
}
.pending-summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.pending-summary {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: #1e293b;
}
.pending-cost {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: #dc2626;
  font-variant-numeric: tabular-nums;
}
.pending-reason {
  display: block;
  font-size: $lyj-font-xs;
  color: #64748b;
  margin-top: 4rpx;
}
.pending-action-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: $lyj-space-sm;
  padding-top: $lyj-space-xs;
  border-top: 1rpx dashed #f1f5f9;
}
.pending-go {
  font-size: $lyj-font-xs;
  color: #3b82f6;
  cursor: pointer;
}
.inline-status {
  font-size: $lyj-font-xs;
  font-weight: 600;
  padding: 4rpx 16rpx;
  border-radius: 999rpx;
}
.inline-status.success {
  background: #dcfce7;
  color: #15803d;
}
.inline-status.rejected {
  background: #f1f5f9;
  color: #64748b;
}
.pending-btns {
  display: flex;
  gap: $lyj-space-xs;
}
.btn-approve {
  background: #10b981;
  color: #ffffff;
  font-size: $lyj-font-xs;
  font-weight: 700;
  border: none;
  border-radius: 8rpx;
  padding: 0 20rpx;
  min-height: 32px;
}
.btn-reject {
  background: #f1f5f9;
  color: #64748b;
  font-size: $lyj-font-xs;
  font-weight: 700;
  border: 1rpx solid #cbd5e1;
  border-radius: 8rpx;
  padding: 0 20rpx;
  min-height: 32px;
}
.empty-card {
  margin: $lyj-space-md;
  padding: $lyj-space-xl $lyj-space-md;
  background: #ffffff;
  border-radius: $lyj-radius;
  text-align: center;
}
.empty-text {
  font-size: $lyj-font-md;
  color: #64748b;
  line-height: $lyj-line-height;
}
</style>

<!-- 高德地图 Marker DOM 样式 -->
<style lang="scss">
.child-map-station-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  color: #ffffff;
  white-space: nowrap;
  border: 2px solid #ffffff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
  pointer-events: auto;
}

/* 子女端长辈位置呼吸波纹动效 Marker */
.child-elder-breathe-marker {
  position: relative;
  width: 90px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.child-elder-breathe-marker .breathe-wave {
  position: absolute;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: rgba(37, 99, 235, 0.35);
  animation: childBreatheWave 1.6s infinite ease-out;
}
@keyframes childBreatheWave {
  0% { transform: scale(0.6); opacity: 1; }
  100% { transform: scale(2.0); opacity: 0; }
}
.child-elder-breathe-marker .breathe-core {
  position: relative;
  z-index: 2;
  background: #1d4ed8;
  color: #ffffff;
  font-size: 11px;
  font-weight: 800;
  padding: 3px 8px;
  border-radius: 12px;
  border: 2px solid #ffffff;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
  white-space: nowrap;
}

.child-offroute-marker-bubble {
  background: #ef4444;
  color: #ffffff;
  font-size: 11px;
  font-weight: 800;
  padding: 4px 10px;
  border-radius: 14px;
  border: 2px solid #ffffff;
  box-shadow: 0 2px 8px rgba(239, 68, 68, 0.4);
  white-space: nowrap;
  animation: offrouteBounce 0.8s infinite alternate;
}
@keyframes offrouteBounce {
  from { transform: translateY(0); }
  to { transform: translateY(-4px); }
}
</style>
