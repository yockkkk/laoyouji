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

    <!-- 行程关联的待审批事项。
         这里服务的**只有金融高危动作**（risk_rules.HIGH_RISK_TOOLS = {"pay"}）——
         挂号不在此列：康乐"知会不审批"，挂号当场办好、同一步给子女发一条知会，
         老人不该为看病等谁点头。原来的副标题写"长辈已发起申请，等待您确认核准"，
         配上"（挂号、车票、酒店等高危操作）"的注释，把这套审批机制说成了就医流程的
         一环，与产品立场正相反。
         实况：现役装配里没有任何工具命中 HIGH_RISK_TOOLS（pay 未在册），所以这个区块
         在旗舰链上是 0 条、不渲染。保留它是因为后端 routes_confirm.py 那条通道还在，
         将来真有付费动作时子女端要有地方确认。 -->
    <view v-if="pendingConfirmations && pendingConfirmations.length > 0" class="pending-section">
      <view class="pending-section-head">
        <text class="pending-section-title">✋ 待您确认的付款事项 ({{ pendingConfirmations.length }})</text>
        <text class="pending-section-sub">涉及付款的操作才需要您点头；挂号、出行这类不经过这里</text>
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

    <!-- 隐私保护友好提示卡片 (当长辈未开放位置共享时温馨提示，杜绝白屏) -->
    <view v-else-if="trip && locationOff" class="location-off-card">
      <view class="location-off-icon">🔒</view>
      <text class="location-off-title">长辈暂未开放实时位置共享</text>
      <text class="location-off-desc">
        长辈当前设置的位置隐私权限为不公开位置。您可以致电长辈核实行程安全，或在长辈手机端“隐私设置”中调整共享权限。
      </text>
      <button class="location-off-btn" @tap="callElder">致电长辈核实</button>
    </view>

    <template v-else-if="trip && !locationOff">
      <!-- 真实高德地图行程守护视窗 (Leaflet + 高德栅格瓦片渲染) -->
      <view class="gaode-guard-card">
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

        <!-- 地图 Canvas 挂载点 -->
        <div id="child-gaode-map" class="child-amap-canvas"></div>

        <view v-if="mapLoading" class="map-loading-overlay">
          <text class="map-loading-text">高德地图加载中…</text>
        </view>
        <view v-else-if="mapFailed" class="map-loading-overlay">
          <text class="map-loading-text">地图加载失败，请检查网络后重试</text>
          <button class="map-retry-btn" size="mini" @tap="initChildMap">重新加载地图</button>
        </view>

        <!-- 没路线可画时的如实交代。放在地图上方而不是盖住地图 —— 地图本身还能看
             （长辈位置、"全览"这些控件都还有用），缺的只是那条线，说清楚缺的是什么。 -->
        <view v-if="!mapLoading && !mapFailed && mapEmptyNotice" class="map-empty-notice">
          <text class="map-empty-notice-text">{{ mapEmptyNotice }}</text>
        </view>

        <!-- 地图浮动工具条 -->
        <view class="guard-map-statusbar">
          <view class="status-indicator-pill">
            <view class="status-indicator-dot" :class="{ alert: isOffRoute }"></view>
            <text class="status-indicator-text">
              {{ isOffRoute ? '⚠️ 发现偏离规划路线' : (latestCheckpoint && latestCheckpoint.lng != null ? '🟢 实时守护中 (10秒刷新)' : '⚪ 等待长辈位置上报') }}
            </text>
          </view>
          <view class="map-ctrl-btns">
            <button class="ctrl-btn" size="mini" @tap="resetChildMapView">全览</button>
            <button class="ctrl-btn" size="mini" @tap="focusElderLocation">长辈位置</button>
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
        <view v-for="(cp, i) in checkpointsDesc" :key="cp.id || i" class="cp">
          <view class="cp-left">
            <view class="cp-dot" :class="cp.status"></view>
            <view v-if="i < checkpointsDesc.length - 1" class="cp-line"></view>
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
import { publishPendingCount } from '../../store/pendingBadge'

const PRECISION_NOTE = {
  city: '长辈将位置权限设为城市级，以下仅展示粗化后的地点，已隐藏详细门牌号与精确坐标。',
  off: '长辈未开放位置共享，无法查看实时经纬度与航迹。',
}

// 这里原来有一份 DEFAULT_POINTS：家（南京鼓楼区）→ 南京南站 → 济南西站 → 北京南站
// → 北京积水潭医院。它是**编出来的**：后端没回路线时（没有行程、或行程还没算路），
// renderTripOnMap 会拿它兜底连出一条南京到北京的高铁折线，还给每个站打上"站·济南西站"
// 的标记 —— 老人端根本没规划过这条线，子女端却看着自己的父母正在跨城。
// 康乐只做本市出行（公交/地铁/步行），本市产品更不该在守护页上画跨城航迹。
// 现在默认全空：拿不到真数据就显示如实的空态，宁可不画。
//
// 姊妹页 pages/elder/route-map.vue 上一轮已经这样改过，这里保持同一口径。

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
      mapFailed: false,
      pendingConfirmations: [],
      actionLoading: {},
      pollTimer: null,
      leafletMap: null,
      tileLayer: null,
      routePolyline: null,
      routeCasing: null,
      elderMarker: null,
      offRouteMarker: null,
      waypointMarkers: [],
      // 全空起步：长辈的坐标只能来自真实上报，路线只能来自后端算出的结果。
      // 在这里预置一个坐标（原来写的是南京鼓楼区）等于给子女看一个没发生过的位置。
      elderCoords: null,
      routeCoords: [],
      routePointsData: [],
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
    // 地图上到底有没有真东西可画。两个来源：后端算出的路线（routeCoords 是 polyline，
    // routePointsData 是途经点）。都没有就不该画线，也不该假装"实时守护中"。
    hasRouteData() {
      return this.routeCoords.length >= 2 || this.routePointsData.length > 0
    },
    mapEmptyNotice() {
      if (this.locationOff) return ''
      if (!this.trip) return ''
      // 说得具体一点：子女要能分清"路还没算"和"老人没动过"——这是两件事，
      // 分开说才不会让一句含糊的"暂无数据"把两种情况糊在一起。
      const noRoute = !this.hasRouteData
      const noPosition = !(this.latestCheckpoint && this.latestCheckpoint.lng != null)
      if (noRoute && noPosition) {
        return '这条行程还没有路线，也没收到长辈的位置上报。等他出门上报一次，这里就会显示。'
      }
      if (noRoute) {
        return '还没算出这条行程的路线。康乐只做本市出行（公交、地铁、步行）——所以这里不会出现跨城的航迹。'
      }
      return ''
    },
    offRouteDetail() {
      if (!this.latestCheckpoint) return ''
      return this.latestCheckpoint.note || `长辈当前处于规划路线外（${this.latestCheckpoint.location}）`
    },
    checkpointsDesc() {
      // 时间线展示专用：先折叠"连续同地点同状态"的重复上报（10 秒定时会刷出一串
      // 相同的"途经XX，一切正常"，即用户反馈的"过于频繁"），再倒序把最新情况放最上面。
      // 绝不改动 this.checkpoints 本身——地图轨迹与 latestCheckpoint 仍依赖它升序排列。
      const src = this.checkpoints || []
      const folded = []
      for (const cp of src) {
        const prev = folded[folded.length - 1]
        if (prev && prev.location === cp.location && prev.status === cp.status) {
          folded[folded.length - 1] = cp // 同地点同状态连续上报，只保留最新一条的时间
          continue
        }
        folded.push(cp)
      }
      return folded.reverse()
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
    if (this.leafletMap) {
      try {
        this.leafletMap.remove()
      } catch (e) {}
      this.leafletMap = null
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
    dedupTripList(list) {
      // 前端展示兜底去重（与后端 trip_dedup_key 同源思路）：进行中/待出发行程
      // 按 (长辈+目的地+标题) 折叠，只留最新一条；终态行程各自保留绝不合并。
      // 列表已按 -created_at 降序，保留首个即保留最新。兜住 dashboard 回退路径。
      if (!Array.isArray(list)) return []
      const seen = new Set()
      const out = []
      for (const t of list) {
        const status = t.status || 'planned'
        let key
        if (status === 'planned' || status === 'ongoing') {
          const dest = (t.destination || '').trim()
          const purpose = (t.purpose || t.title || '').trim()
          key = `active:${t.elder_id || ''}:${dest}:${purpose}`
        } else {
          key = `terminal:${t.id}`
        }
        if (seen.has(key)) continue
        seen.add(key)
        out.push(t)
      }
      return out
    },
    async initData() {
      await this.loadTripsAndDetail()
      await this.initChildMap()
      this.startPolling()
    },
    async loadTripsAndDetail() {
      try {
        // 1. 获取子女关联老人的所有行程列表
        const [dashRes, tripsRes] = await Promise.all([
          get(`/api/child/${this.user.id}/dashboard`).catch(() => null),
          get('/api/trips', { child_id: this.user.id }).catch(() => null),
        ])

        if (dashRes && Array.isArray(dashRes.trips) && dashRes.trips.length > 0) {
          this.allTrips = this.dedupTripList(dashRes.trips)
        } else if (tripsRes && Array.isArray(tripsRes.trips) && tripsRes.trips.length > 0) {
          this.allTrips = this.dedupTripList(tripsRes.trips)
        }

        // 确定当前展示的 tripId
        if (!this.tripId) {
          if (this.allTrips.length > 0) {
            this.tripId = this.allTrips[0].id
          }
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
    async initChildMap() {
      let L
      try {
        L = await loadLeaflet()
      } catch (err) {
        console.error('子女端地图库加载失败:', err)
        this.mapLoading = false
        this.mapFailed = true
        return
      }
      // 标记的自定义 DOM 样式必须走文档级注入才能命中（穿透 uni-app 作用域），
      // 否则站点/偏航气泡会退化成竖排黑字。与长辈端 route-map 共用同一份样式。
      ensureAmapMarkerStyles()
      await this.$nextTick()
      const container = document.getElementById('child-gaode-map')
      if (!container) {
        this.mapLoading = false
        return
      }

      try {
        this.mapFailed = false
        if (!this.leafletMap) {
          this.leafletMap = L.map(container, {
            zoomControl: true,
            attributionControl: true,
            zoomSnap: 0.5,
            zoomDelta: 0.5,
            scrollWheelZoom: true,
          }).setView([35.5, 117.5], 6)
          if (this.leafletMap.attributionControl) {
            this.leafletMap.attributionControl.setPrefix(false)
            this.leafletMap.attributionControl.setPosition('bottomleft')
          }
          // 高德栅格瓦片（GCJ-02，与后端坐标同基准）。绕开断掉的高德控制面，直连数据面贴图。
          this.tileLayer = L.tileLayer(AMAP_RASTER_TILE_URL, {
            subdomains: AMAP_TILE_SUBDOMAINS,
            maxZoom: 18,
            minZoom: 3,
            attribution: AMAP_TILE_ATTRIBUTION,
          }).addTo(this.leafletMap)
        }
        this.renderTripOnMap()
        this.mapLoading = false
        this.$nextTick(() => {
          setTimeout(() => {
            if (this.leafletMap) this.leafletMap.invalidateSize()
          }, 200)
        })
      } catch (err) {
        console.error('子女端地图初始化失败:', err)
        this.mapLoading = false
        this.mapFailed = true
      }
    },
    renderTripOnMap() {
      const L = window.L
      if (!this.leafletMap || !L) return

      // 清除旧图层与站点标记
      if (this.routeCasing) {
        this.leafletMap.removeLayer(this.routeCasing)
        this.routeCasing = null
      }
      if (this.routePolyline) {
        this.leafletMap.removeLayer(this.routePolyline)
        this.routePolyline = null
      }
      if (this.waypointMarkers.length) {
        this.waypointMarkers.forEach((m) => this.leafletMap.removeLayer(m))
        this.waypointMarkers = []
      }
      if (this.offRouteMarker) {
        this.leafletMap.removeLayer(this.offRouteMarker)
        this.offRouteMarker = null
      }

      // 没有真路线就不画线。途经点连线只是"后端给了点、没给 polyline"时的兜底，
      // 不是"后端什么都没给"时用来凑一条出来的 —— 后者画出来的每一段都在替老人
      // 编一段没走过的路。空态由模板上的提示卡承担（见 hasRouteData）。
      const polyLngLat = this.routeCoords.length
        ? this.routeCoords
        : this.routePointsData.map((p) => [p.lng, p.lat])
      const latlngs = polyLngLat.map((p) => toLeafletLatLng(p))

      // 行程真实路线轨迹：白色描边打底 + 高德蓝主线
      if (latlngs.length >= 2) {
        this.routeCasing = L.polyline(latlngs, {
          color: '#ffffff',
          weight: 10,
          opacity: 0.9,
          lineJoin: 'round',
          lineCap: 'round',
        }).addTo(this.leafletMap)
        this.routePolyline = L.polyline(latlngs, {
          color: '#2A82E4', // 晴空浅天蓝主线
          weight: 7,
          opacity: 0.92,
          lineJoin: 'round',
          lineCap: 'round',
        }).addTo(this.leafletMap)
      }

      // 绘制途经打点 Markers
      this.routePointsData.forEach((pt) => {
        const isStart = pt.type === 'start'
        const isEnd = pt.type === 'end'
        const badgeColor = isStart ? '#10b981' : isEnd ? '#ef4444' : '#3b82f6'
        const prefix = isStart ? '起·' : isEnd ? '终·' : '站·'
        const icon = makeMapMarkerIcon(L, {
          html: `<div class="child-map-station-badge" style="background-color:${badgeColor}">${prefix}${pt.name}</div>`,
          size: [40, 26],
        })
        const marker = L.marker(toLeafletLatLng(pt), { icon }).addTo(this.leafletMap)
        this.waypointMarkers.push(marker)
      })

      // 绘制/更新长辈当前位置呼吸 Marker。
      // elderCoords 为 null 表示"还没有任何真实上报"——这时候**不能画**：那个
      // "👴 父母实时位置"的气泡一旦落在地图上，就是在替长辈声明一个没上报过的位置。
      // 已经画出来的 marker 遇到坐标被清空也要收掉（切行程时会发生）。
      if (!this.elderCoords || this.elderCoords.length < 2) {
        if (this.elderMarker) {
          this.leafletMap.removeLayer(this.elderMarker)
          this.elderMarker = null
        }
      } else if (!this.elderMarker) {
        const liveIcon = makeMapMarkerIcon(L, {
          html: `<div class="child-elder-breathe-marker"><div class="breathe-wave"></div><div class="breathe-core">👴 父母实时位置</div></div>`,
          size: [90, 40],
        })
        this.elderMarker = L.marker(toLeafletLatLng(this.elderCoords), {
          icon: liveIcon,
          zIndexOffset: 1000,
        }).addTo(this.leafletMap)
      } else {
        this.elderMarker.setLatLng(toLeafletLatLng(this.elderCoords))
      }

      // 同步偏航警告点标记
      this.updateOffRouteMarker()

      // 自适应视野缩放
      if (latlngs.length) {
        this.leafletMap.fitBounds(this.routePolyline.getBounds(), { padding: [40, 40] })
      }
    },
    updateOffRouteMarker() {
      const L = window.L
      if (!this.leafletMap || !L) return

      if (this.isOffRoute && this.latestCheckpoint && this.latestCheckpoint.lng != null && this.latestCheckpoint.lat != null) {
        const offLatLng = toLeafletLatLng([this.latestCheckpoint.lng, this.latestCheckpoint.lat])
        const icon = makeMapMarkerIcon(L, {
          html: `<div class="child-offroute-marker-bubble">⚠️ 偏离路线点：${this.latestCheckpoint.location}</div>`,
          size: [40, 28],
        })
        if (!this.offRouteMarker) {
          this.offRouteMarker = L.marker(offLatLng, { icon, zIndexOffset: 2000 }).addTo(this.leafletMap)
        } else {
          this.offRouteMarker.setLatLng(offLatLng)
          this.offRouteMarker.setIcon(icon)
        }
      } else if (this.offRouteMarker) {
        this.leafletMap.removeLayer(this.offRouteMarker)
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
                this.elderMarker.setLatLng(toLeafletLatLng(newPos))
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
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },
    resetChildMapView() {
      if (this.leafletMap && this.routePolyline) {
        this.leafletMap.fitBounds(this.routePolyline.getBounds(), { padding: [40, 40] })
      }
    },
    focusElderLocation() {
      if (this.leafletMap && this.elderCoords) {
        this.leafletMap.setView(toLeafletLatLng(this.elderCoords), 12)
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
        // 偏航点**从长辈当前真实坐标往外挪一点**算出来，不写死城市。
        // 原来这里钉的是「北京市朝阳区三里屯太古里」(116.455/39.937)：
        // 一位南京的老人，在子女端地图上"偏航"到了北京 —— 一则本市产品里没有这种
        // 行程，二则就算只是演示按钮，地图上会出现一条从南京连到北京的线。
        // 偏航告警要证明的是"离开既定路线会被发现"，这件事与具体是哪座城无关。
        const base = this.elderCoords
          || (this.routePointsData.length ? [this.routePointsData[0].lng, this.routePointsData[0].lat] : null)
        if (!base) {
          uni.showToast({ title: '还没有长辈位置，先等一次上报', icon: 'none' })
          return
        }
        // 偏移量必须**明确越过**后端的走廊容差，否则这次"偏航"会被后端判成 normal，
        // 按钮弹一句"已触发偏航告警"、地图上却什么警报都没有 —— 按钮在说谎。
        // 后端 routes_guardian.py 的 tolerance = 3500 米（本市出行就一条 3.5km 走廊，
        // 判定用的是点到折线**线段**的最短距离，见 amap_service.min_distance_to_corridor_m）。
        // 取 +0.06° 经度 / +0.04° 纬度：南京纬度上约 5.7km / 4.4km，直线约 7.2km；
        // 而这条行程的走廊全长也就几公里，离走廊上任何一点都在 4km 开外，稳稳越过阈值。
        // 这仍是"老人在本市走岔了"的量级，不是另一座城。
        const offLng = Number(base[0]) + 0.06
        const offLat = Number(base[1]) + 0.04
        try {
          const res = await post(`/api/trips/${this.tripId}/checkpoints`, {
            location: '偏离既定路线（演示上报）',
            lng: offLng,
            lat: offLat,
          })
          if (res && res.checkpoint) {
            this.checkpoints.push(res.checkpoint)
            this.elderCoords = [offLng, offLat]
            this.renderTripOnMap()
            // 报后端**实际判出来的**档位，而不是替它宣布成功 ——
            // 判成 normal 就直说没触发，别让按钮文案与地图上的实况对不上。
            uni.showToast({
              title:
                res.checkpoint.status === 'off_route'
                  ? '已触发偏航告警，地图上可看到警报'
                  : '上报成功，但后端判定未偏离路线',
              icon: 'none',
            })
          }
        } catch (e) {
          uni.showToast({ title: e.message || '模拟失败', icon: 'none' })
        }
      } else {
        // 模拟正常前进到下一站点。
        // 途经点为空时不能再往下走：routePointsData.length 是 0，取模会得到 NaN，
        // 于是 targetPoint 是 undefined，下一行读 .name 直接抛。
        if (!this.routePointsData.length) {
          uni.showToast({ title: '这条行程还没有路线点，先规划路线', icon: 'none' })
          return
        }
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
      // 只留**在册**的工具。book_ticket / search_train / book_hotel / order_service
      // 都已随产品收敛删掉（现役 22 个工具，见后端装配），留着它们等于给不存在的
      // 工具备一个图标 —— 后来人一看就以为这产品还在订票订酒店。
      // register_appointment 留着不是因为它会挂起（它在 risk_rules.NON_PAYMENT_TOOLS
      // 里，挂号当场办好、只发知会），而是因为旧会话的历史数据里可能有它的挂起记录。
      const map = {
        register_appointment: '🏥',
        search_hospital: '🏥',
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
  background: $lyj-card;
  border-radius: $lyj-radius;
  border: 2rpx solid $lyj-line;
  padding: 18rpx 20rpx;
  box-shadow: $lyj-shadow-card;
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
  color: $lyj-child-text;
}
.picker-current-pill {
  display: flex;
  align-items: center;
  gap: 8rpx;
  background: $lyj-primary-soft;
  border: 1rpx solid rgba(42, 130, 228, 0.3);
  border-radius: 30rpx;
  padding: 6rpx 20rpx;
  cursor: pointer;
}
.picker-text {
  font-size: 26rpx;
  color: $lyj-primary-dark;
  font-weight: 700;
  white-space: nowrap;
}
.picker-dropdown-icon {
  font-size: 22rpx;
  color: $lyj-primary;
}
.trip-tags-scroll {
  width: 100%;
  white-space: nowrap;
  margin-top: 14rpx;
  padding-top: 10rpx;
  border-top: 1rpx dashed $lyj-line;
}
.trip-tags-wrap {
  display: flex;
  gap: 12rpx;
}
.trip-tag-item {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  background: $lyj-field;
  border-radius: 12rpx;
  padding: 8rpx 16rpx;
  border: 1rpx solid $lyj-line;
  cursor: pointer;
  flex-shrink: 0;
  white-space: nowrap;
  word-break: keep-all;
}
.trip-tag-item.active {
  background: $lyj-primary;
  border-color: $lyj-primary;
}
.tag-name {
  font-size: 24rpx;
  color: $lyj-child-body;
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
  background: $lyj-card;
  border-radius: $lyj-radius;
  overflow: hidden;
  border: 2rpx solid $lyj-line;
  box-shadow: $lyj-shadow-card;
}
.child-amap-canvas {
  width: 100%;
  height: 58vh;
  background: #f1f5f9;
  transition: height 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.gaode-guard-card.expanded .child-amap-canvas {
  height: 82vh;
}
.map-loading-overlay {
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
  gap: 16rpx;
}
.map-loading-text {
  font-size: 26rpx;
  color: #475569;
  font-weight: 600;
}
/* 没路线可画时的如实交代条。刻意做得显眼但不报警（中性灰蓝，不用红/黄）——
   它说的是"还没数据"，不是"出事了"。 */
.map-empty-notice {
  background: #f1f5f9;
  border-left: 6rpx solid #94a3b8;
  border-radius: 8rpx;
  padding: 16rpx 20rpx;
  margin: 12rpx 16rpx;
}
.map-empty-notice-text {
  font-size: 24rpx;
  color: #475569;
  line-height: 1.6;
}
.map-retry-btn {
  background: $lyj-primary;
  color: #ffffff;
  font-size: 24rpx;
  font-weight: 700;
  border: none;
  border-radius: 24rpx;
  padding: 4rpx 24rpx;
  margin: 0;
}

/* 偏航预警悬浮气泡 */
.offroute-alert-bubble {
  position: absolute;
  top: 16rpx;
  left: 16rpx;
  right: 16rpx;
  z-index: 1300;
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
  background: $lyj-primary-soft;
  color: $lyj-primary-dark;
  border: 1rpx solid rgba(42, 130, 228, 0.3);
  border-radius: 20rpx;
  font-size: 24rpx;
  font-weight: 700;
  padding: 6rpx 20rpx;
  margin: 0;
  white-space: nowrap;
  word-break: keep-all;
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
  white-space: nowrap;
  word-break: keep-all;
}
.sim-pill-btn.normal {
  background: $lyj-primary-soft;
  color: $lyj-primary-dark;
  border: 1rpx solid rgba(42, 130, 228, 0.3);
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
  font-size: $lyj-font-sm;
  font-weight: 600;
  padding: 8rpx 20rpx;
  border-radius: $lyj-radius-pill;
  min-height: 88rpx;
  white-space: nowrap;
  word-break: keep-all;
  flex-shrink: 0;
  display: flex;
  align-items: center;
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
  align-items: center;
  gap: $lyj-space-sm;
}
.btn-approve {
  background: #10b981;
  color: #ffffff;
  font-size: $lyj-font-sm;
  font-weight: 700;
  border: none;
  border-radius: $lyj-radius;
  padding: 0 32rpx;
  min-height: 88rpx;
  line-height: 88rpx;
  white-space: nowrap;
  word-break: keep-all;
  flex-shrink: 0;
}
.btn-reject {
  background: #f1f5f9;
  color: #64748b;
  font-size: $lyj-font-sm;
  font-weight: 700;
  border: 1rpx solid #cbd5e1;
  border-radius: $lyj-radius;
  padding: 0 32rpx;
  min-height: 88rpx;
  line-height: 88rpx;
  white-space: nowrap;
  word-break: keep-all;
  flex-shrink: 0;
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

/* 隐私保护卡片 */
.location-off-card {
  margin: $lyj-space-md;
  padding: $lyj-space-xl $lyj-space-lg;
  background: #ffffff;
  border-radius: 20rpx;
  border: 1rpx solid #e2e8f0;
  box-shadow: 0 4rpx 14rpx rgba(0, 0, 0, 0.05);
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 16rpx;
}
.location-off-icon {
  font-size: 72rpx;
  line-height: 1;
  margin-bottom: 8rpx;
}
.location-off-title {
  font-size: 32rpx;
  font-weight: 800;
  color: #1e293b;
}
.location-off-desc {
  font-size: 26rpx;
  color: #64748b;
  line-height: 1.6;
  max-width: 580rpx;
}
.location-off-btn {
  margin-top: 16rpx;
  background: #2563eb;
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 700;
  border-radius: 40rpx;
  border: none;
  padding: 8rpx 40rpx;
  cursor: pointer;
}
</style>

<!-- 高德 Marker 的自定义 DOM 样式统一在 utils/amap.js 的 ensureAmapMarkerStyles()
     里以文档级 <style> 注入（子女端 .child-map-station-badge / .child-elder-breathe-marker
     / .child-offroute-marker-bubble 及其动效都在那里）。高德 Marker 是运行时插进它
     自己容器的，uni-app H5 的作用域标记会让写在这里的规则命中不到，故此处不再重复声明。 -->
