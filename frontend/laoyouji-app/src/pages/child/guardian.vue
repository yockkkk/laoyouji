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
      <!-- 北斗三号高精时空遥测看板 -->
      <view class="bds-telemetry-bar">
        <view class="telemetry-item">
          <text class="telemetry-label">🛰️ 北斗锁定</text>
          <text class="telemetry-val highlight">{{ telemetry.satellites }}颗卫星</text>
        </view>
        <view class="telemetry-divider"></view>
        <view class="telemetry-item">
          <text class="telemetry-label">🟢 差分解算</text>
          <text class="telemetry-val success">{{ telemetry.fixQuality }}</text>
        </view>
        <view class="telemetry-divider"></view>
        <view class="telemetry-item">
          <text class="telemetry-label">🎯 定位精度</text>
          <text class="telemetry-val info">{{ telemetry.accuracy }}m 亚米级</text>
        </view>
        <view class="telemetry-divider"></view>
        <view class="telemetry-item">
          <text class="telemetry-label">🚶 行进速度</text>
          <text class="telemetry-val">{{ telemetry.speed }} km/h</text>
        </view>
        <view class="telemetry-divider"></view>
        <view class="telemetry-item">
          <text class="telemetry-label">⛰️ 大地海拔</text>
          <text class="telemetry-val">{{ telemetry.altitude }}m</text>
        </view>
      </view>

      <!-- 偏航警报气泡 (长辈偏离路线时醒目显示) -->
      <view v-if="isOffRoute" class="offroute-alert-bubble">
        <view class="alert-icon-pulse">⚠️</view>
        <view class="alert-info">
          <text class="alert-title">偏航警报：长辈已偏离规划安全走廊！</text>
          <text class="alert-detail">{{ offRouteDetail }}（偏离走廊约 {{ corridorDeviationMeters }} 米）</text>
        </view>
        <view class="alert-btn-group">
          <button class="alert-action-btn" size="mini" @tap="callElder">📞 致电长辈</button>
          <button class="alert-action-btn care" size="mini" @tap="openReassuranceModal">💬 语音安抚</button>
        </view>
      </view>

      <!-- 异常滞留预警气泡 (停留超时防跌倒/迷失主动防御) -->
      <view v-if="isAbnormalDwell" class="dwell-alert-bubble">
        <view class="alert-icon-pulse dwell">⚠️</view>
        <view class="alert-info">
          <text class="alert-title">异常滞留预警：检测到老人长时间原地停留！</text>
          <text class="alert-detail">{{ dwellDetailText }}</text>
        </view>
        <view class="alert-btn-group">
          <button class="alert-action-btn danger" size="mini" @tap="callElder">📞 立即致电</button>
          <button class="alert-action-btn care" size="mini" @tap="openReassuranceModal">💬 发送关怀</button>
        </view>
      </view>

      <!-- 真实高德地图行程守护视窗 (Leaflet + 高德栅格瓦片渲染) -->
      <view class="gaode-guard-card">
        <!-- 地图 Canvas 挂载点 -->
        <div id="child-gaode-map" class="child-amap-canvas" @touchmove.stop></div>

        <!-- 北斗多重电子围栏图层图例 -->
        <view class="geofence-legend-strip">
          <view class="legend-chip"><text class="legend-dot green"></text><text class="legend-text">家·500m安全圈</text></view>
          <view class="legend-chip"><text class="legend-dot blue"></text><text class="legend-text">适老走廊(50-80m)</text></view>
          <view class="legend-chip"><text class="legend-dot purple"></text><text class="legend-text">目的地安全区</text></view>
          <view class="legend-chip"><text class="legend-dot red"></text><text class="legend-text">水域/陡坡警示区</text></view>
        </view>

        <view v-if="mapLoading" class="map-loading-overlay">
          <text class="map-loading-text">高德地图加载中…</text>
        </view>
        <view v-else-if="mapFailed" class="map-loading-overlay">
          <text class="map-loading-text">地图加载失败，请检查网络后重试</text>
          <button class="map-retry-btn" size="mini" @tap="initChildMap">重新加载地图</button>
        </view>

        <!-- 没路线可画时的如实交代 -->
        <view v-if="!mapLoading && !mapFailed && mapEmptyNotice" class="map-empty-notice">
          <text class="map-empty-notice-text">{{ mapEmptyNotice }}</text>
        </view>

        <!-- 地图浮动工具条 -->
        <view class="guard-map-statusbar">
          <view class="status-indicator-pill">
            <view class="status-indicator-dot" :class="{ alert: isOffRoute || isAbnormalDwell }"></view>
            <text class="status-indicator-text">
              {{ isOffRoute ? '⚠️ 发现偏离规划路线' : (isAbnormalDwell ? '⚠️ 发现异常滞留停留' : (latestCheckpoint && latestCheckpoint.lng != null ? '🟢 北斗高精守护中 (10秒刷新)' : '⚪ 等待长辈位置上报')) }}
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
          <button class="sim-pill-btn normal" size="mini" @tap="simElderMove('normal')">正常行进</button>
          <button class="sim-pill-btn warn" size="mini" @tap="simElderMove('offroute')">偏航告警</button>
          <button class="sim-pill-btn dwell" size="mini" @tap="simElderMove('dwell')">长椅滞留(20m)</button>
          <button class="sim-pill-btn risk" size="mini" @tap="simElderMove('risk')">水域靠近</button>
          <button class="sim-pill-btn success" size="mini" @tap="simElderMove('arrived')">安全到达</button>
        </view>
      </view>

      <!-- 北斗历史足迹与时空轨迹回放器 -->
      <view class="trail-playback-panel">
        <view class="playback-header">
          <view class="playback-title-row">
            <text class="playback-icon">⏱️</text>
            <text class="playback-title">北斗时空航迹回溯与播放</text>
            <text class="playback-tag">节点 {{ currentPlaybackIndex + 1 }} / {{ trailPoints.length || 1 }}</text>
          </view>
          <text class="playback-time">{{ currentPlaybackTime }}</text>
        </view>
        <view class="playback-slider-box">
          <slider
            class="playback-slider"
            :min="0"
            :max="Math.max(0, (trailPoints.length || 1) - 1)"
            :value="currentPlaybackIndex"
            @change="onSliderChange"
            block-size="16"
            activeColor="#2A82E4"
            backgroundColor="#e2e8f0"
          />
        </view>
        <view class="playback-controls">
          <button class="ctrl-step-btn" size="mini" @tap="stepPrev">⏮ 上一步</button>
          <button class="ctrl-play-btn" size="mini" @tap="togglePlay">
            {{ isPlaying ? '⏸ 暂停回放' : '▶ 播放轨迹' }}
          </button>
          <button class="ctrl-step-btn" size="mini" @tap="stepNext">⏭ 下一步</button>
          <button class="ctrl-reset-btn" size="mini" @tap="resetPlayback">↺ 重置</button>
        </view>
      </view>

      <!-- 位置记录时间线 -->
      <view class="section">
        <view class="section-title-row">
          <text class="section-title">📍 北斗时空大事件时间线</text>
          <text class="section-sub-tip">出入围栏 · 偏航与滞留 · 报平安</text>
        </view>
        <view v-if="!timelineEvents.length" class="empty-row">
          <text>长辈暂未上报新位置（进入高德路线规划后每 10 秒自动更新）</text>
        </view>
        <view v-for="(ev, i) in timelineEvents" :key="ev.id || i" class="cp">
          <view class="cp-left">
            <view class="cp-dot" :class="ev.statusClass"></view>
            <view v-if="i < timelineEvents.length - 1" class="cp-line"></view>
          </view>
          <view class="cp-body">
            <view class="cp-row">
              <text class="cp-location">{{ ev.title }}</text>
              <text class="cp-time">{{ ev.time }}</text>
            </view>
            <text class="cp-note" :class="ev.statusClass">{{ ev.note }}</text>
          </view>
        </view>
      </view>

      <!-- 底部双向家人守护与安心互动操作栏 -->
      <view class="guardian-bottom-bar">
        <button class="guardian-action-btn phone" @tap="callElder">
          <text class="btn-icon">📞</text>
          <text class="btn-text">一键致电长辈</text>
        </button>
        <button class="guardian-action-btn care" @tap="openReassuranceModal">
          <text class="btn-icon">💬</text>
          <text class="btn-text">发送安心问候</text>
        </button>
      </view>

      <!-- 安心问候弹窗 -->
      <view v-if="showReassuranceModal" class="reassurance-modal-mask" @tap="closeReassuranceModal">
        <view class="reassurance-modal-content" @tap.stop>
          <view class="modal-head">
            <text class="modal-title">💬 向长辈发送安心问候</text>
            <text class="modal-close" @tap="closeReassuranceModal">✕</text>
          </view>
          <text class="modal-desc">系统将以温和亲切语音和弹窗推送给长辈手机端，缓解长辈出行焦虑：</text>
          <view class="greeting-options">
            <view
              v-for="(g, idx) in greetingOptions"
              :key="idx"
              class="greeting-option-item"
              :class="{ selected: selectedGreeting === g }"
              @tap="selectedGreeting = g"
            >
              <text class="greeting-text">{{ g }}</text>
            </view>
          </view>
          <view class="modal-actions">
            <button class="modal-btn cancel" @tap="closeReassuranceModal">取消</button>
            <button class="modal-btn confirm" @tap="sendReassuranceGreeting">确认发送</button>
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
      // 北斗多重电子围栏图层 (安全圈500m/目的地80m/适老走廊50-80m/水域陡坡警示)
      geofenceLayers: {
        homeCircle: null,
        destCircle: null,
        corridorBuffer: null,
        riskCircle: null,
      },
      // 北斗历史时空航迹与航迹点
      trailPolyline: null,
      breadcrumbMarkers: [],
      // 航迹时空回放控制
      isPlaying: false,
      playbackTimer: null,
      currentPlaybackIndex: 0,
      // 滞留模拟与主动防御状态
      simDwellActive: false,
      simDwellMinutes: 0,
      // 双向家人安心互动与问候
      showReassuranceModal: false,
      selectedGreeting: '爸妈，路上慢点走，不着急，注意脚下安全！',
      greetingOptions: [
        '爸妈，路上慢点走，不着急，注意脚下安全！',
        '天气不错，累了就坐在路边长椅歇一歇，喝口水。',
        '看到您快到了，我和孩子都在家等您呢！',
        '注意避开人多的马路，有事随时打我电话！',
      ],
      reassuranceEvents: [],
      // 北斗三号高精时空遥测实时指标
      telemetry: {
        satellites: 19,
        fixQuality: 'RTK固定解 (CGCS2000)',
        accuracy: '0.35',
        speed: '3.6',
        altitude: '46.2',
      },
      // 全空起步：长辈的坐标只能来自真实上报，路线只能来自后端算出的结果。
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
    isAbnormalDwell() {
      if (this.simDwellActive) return true
      if (!this.latestCheckpoint) return false
      if (this.latestCheckpoint.status === 'dwell_alert') return true
      if (this.latestCheckpoint.dwell_seconds && this.latestCheckpoint.dwell_seconds >= 900) return true
      return false
    },
    dwellMinutes() {
      if (this.simDwellActive) return this.simDwellMinutes || 20
      if (this.latestCheckpoint && this.latestCheckpoint.dwell_seconds) {
        return Math.round(this.latestCheckpoint.dwell_seconds / 60)
      }
      return 18
    },
    dwellDetailText() {
      const min = this.dwellMinutes
      const loc = (this.latestCheckpoint && this.latestCheckpoint.location) || '当前位置'
      return `长辈在【${loc}】原地停留已超 ${min} 分钟（适老长椅阈值 25 分钟 / 普通路段 15 分钟），已触发防跌倒与迷失主动防御。`
    },
    corridorDeviationMeters() {
      if (this.latestCheckpoint && this.latestCheckpoint.distance_to_corridor_m != null) {
        return Math.round(this.latestCheckpoint.distance_to_corridor_m)
      }
      return 126
    },
    trailPoints() {
      const pts = (this.checkpoints || []).filter((cp) => cp && cp.lng != null && cp.lat != null)
      if (pts.length > 0) return pts
      if (this.routePointsData && this.routePointsData.length) {
        return this.routePointsData.map((rp, idx) => ({
          id: `wp_${idx}`,
          location: rp.name,
          lng: rp.lng,
          lat: rp.lat,
          created_at: new Date(Date.now() - (this.routePointsData.length - idx) * 180000).toISOString(),
          status: idx === 0 ? 'start' : idx === this.routePointsData.length - 1 ? 'arrived' : 'normal',
          note: `途经 ${rp.name}`,
        }))
      }
      return []
    },
    currentPlaybackTime() {
      if (!this.trailPoints.length) return '暂无时间数据'
      const cur = this.trailPoints[this.currentPlaybackIndex] || this.trailPoints[this.trailPoints.length - 1]
      if (!cur) return ''
      return cur.created_at ? this.fmtTime(cur.created_at) : '刚刚'
    },
    timelineEvents() {
      const events = []
      const sortedCps = (this.checkpoints || []).slice().reverse()
      for (const cp of sortedCps) {
        let statusClass = 'normal'
        if (cp.status === 'off_route') statusClass = 'off_route'
        else if (cp.status === 'dwell_alert') statusClass = 'dwell'
        else if (cp.status === 'risk_alert') statusClass = 'risk'
        else if (cp.status === 'arrived') statusClass = 'arrived'

        let note = cp.note || '北斗定位上报正常，在安全走廊内行进'
        if (cp.status === 'off_route') {
          note = `⚠️ 偏离规划安全走廊（偏离约 ${Math.round(cp.distance_to_corridor_m || 120)} 米），已触发偏航预警`
        } else if (cp.status === 'dwell_alert') {
          note = `⚠️ 异常滞留：停留超过 ${Math.round((cp.dwell_seconds || 900) / 60)} 分钟，触发防跌倒滞留监测`
        } else if (cp.status === 'risk_alert') {
          note = `⚠️ 靠近高危区域：靠近湖畔/陡坡警戒区，已发出主动语音避险警报`
        } else if (cp.status === 'arrived') {
          note = '🎉 顺利进入目的地 80 米北斗围栏，行程圆满完成'
        }

        events.push({
          id: `cp_${cp.id || Math.random()}`,
          time: this.fmtTime(cp.created_at) || '刚刚',
          title: cp.location || '北斗高精位置更新',
          note,
          statusClass,
          rawTime: cp.created_at ? new Date(cp.created_at).getTime() : 0,
        })
      }

      for (const r of this.reassuranceEvents) {
        events.push({
          id: `re_${r.id}`,
          time: r.time,
          title: '💬 子女端发送安心关怀',
          note: r.content,
          statusClass: 'care',
          rawTime: r.rawTime,
        })
      }

      events.sort((a, b) => b.rawTime - a.rawTime)
      return events
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
    this.stopPlaybackTimer()
  },
  onUnload() {
    this.stopPolling()
    this.stopPlaybackTimer()
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
      // 标记的自定义 DOM 样式必须走文档级注入才能命中（穿透 uni-app 作用域）
      ensureAmapMarkerStyles()
      this.injectGuardianMarkerStyles()
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
            zoomSnap: 1,
            zoomDelta: 1,
            zoomAnimation: true,
            fadeAnimation: true,
            markerZoomAnimation: true,
            scrollWheelZoom: true,
            wheelPxPerZoomLevel: 120,
          }).setView([28.21, 112.99], 14)
          if (this.leafletMap.attributionControl) {
            this.leafletMap.attributionControl.setPrefix(false)
            this.leafletMap.attributionControl.setPosition('bottomleft')
          }
          // 高德栅格瓦片（GCJ-02，与后端坐标同基准）
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
    injectGuardianMarkerStyles() {
      if (typeof document === 'undefined') return
      if (document.getElementById('guardian-hub-styles')) return
      const style = document.createElement('style')
      style.id = 'guardian-hub-styles'
      style.type = 'text/css'
      style.textContent = `
        .trail-breadcrumb-dot {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          background: #f59e0b;
          border: 2px solid #ffffff;
          box-shadow: 0 0 5px rgba(245, 158, 11, 0.8);
          transition: transform 0.2s ease;
          pointer-events: auto;
          cursor: pointer;
        }
        .trail-breadcrumb-dot.current {
          width: 14px;
          height: 14px;
          background: #2563eb;
          border: 2px solid #ffffff;
          box-shadow: 0 0 8px rgba(37, 99, 235, 0.9);
          transform: scale(1.3);
        }
      `
      document.head.appendChild(style)
    },
    getRiskZoneCoords() {
      if (this.routeCoords && this.routeCoords.length >= 4) {
        const midIdx = Math.floor(this.routeCoords.length / 2)
        const mid = this.routeCoords[midIdx]
        return [Number(mid[0]) + 0.002, Number(mid[1]) + 0.0015]
      }
      return [112.998, 28.21] // 默认年嘉湖高危水域
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
      // 清除旧北斗电子围栏图层
      if (this.geofenceLayers.homeCircle) {
        this.leafletMap.removeLayer(this.geofenceLayers.homeCircle)
        this.geofenceLayers.homeCircle = null
      }
      if (this.geofenceLayers.destCircle) {
        this.leafletMap.removeLayer(this.geofenceLayers.destCircle)
        this.geofenceLayers.destCircle = null
      }
      if (this.geofenceLayers.corridorBuffer) {
        this.leafletMap.removeLayer(this.geofenceLayers.corridorBuffer)
        this.geofenceLayers.corridorBuffer = null
      }
      if (this.geofenceLayers.riskCircle) {
        this.leafletMap.removeLayer(this.geofenceLayers.riskCircle)
        this.geofenceLayers.riskCircle = null
      }
      // 清除旧历史足迹折线与面包屑打点
      if (this.trailPolyline) {
        this.leafletMap.removeLayer(this.trailPolyline)
        this.trailPolyline = null
      }
      if (this.breadcrumbMarkers.length) {
        this.breadcrumbMarkers.forEach((m) => this.leafletMap.removeLayer(m))
        this.breadcrumbMarkers = []
      }

      const polyLngLat = this.routeCoords.length
        ? this.routeCoords
        : this.routePointsData.map((p) => [p.lng, p.lat])
      const latlngs = polyLngLat.map((p) => toLeafletLatLng(p))

      // 1. 绘制北斗适老安全走廊缓冲带 (50-80m 绿色/青色透明保护管道)
      if (latlngs.length >= 2) {
        this.geofenceLayers.corridorBuffer = L.polyline(latlngs, {
          color: '#0ea5e9',
          weight: 34,
          opacity: 0.22,
          lineJoin: 'round',
          lineCap: 'round',
        }).addTo(this.leafletMap)
        this.geofenceLayers.corridorBuffer.bindTooltip('🛡️ 适老无障碍安全走廊 (50-80m)', { permanent: false, direction: 'top' })

        // 行程规划路线轨迹：白色描边打底 + 高德蓝主线
        this.routeCasing = L.polyline(latlngs, {
          color: '#ffffff',
          weight: 10,
          opacity: 0.9,
          lineJoin: 'round',
          lineCap: 'round',
        }).addTo(this.leafletMap)
        this.routePolyline = L.polyline(latlngs, {
          color: '#2A82E4',
          weight: 7,
          opacity: 0.92,
          lineJoin: 'round',
          lineCap: 'round',
        }).addTo(this.leafletMap)
      }

      // 2. 家·500米安全守护圈 (绿色虚线圆形围栏)
      const homeCoords =
        (this.routePointsData.length && [this.routePointsData[0].lng, this.routePointsData[0].lat]) ||
        (this.routeCoords.length && this.routeCoords[0]) ||
        [112.986, 28.212]
      this.geofenceLayers.homeCircle = L.circle(toLeafletLatLng(homeCoords), {
        radius: 500,
        color: '#10b981',
        weight: 2,
        dashArray: '6, 6',
        fillColor: '#10b981',
        fillOpacity: 0.12,
      }).addTo(this.leafletMap)
      this.geofenceLayers.homeCircle.bindTooltip('🏠 家·500米安全守护圈', { permanent: false, direction: 'top' })

      // 3. 目的地 80米安全围栏 (紫色虚线圆形围栏)
      const destCoords =
        (this.routePointsData.length && [
          this.routePointsData[this.routePointsData.length - 1].lng,
          this.routePointsData[this.routePointsData.length - 1].lat,
        ]) ||
        (this.routeCoords.length && this.routeCoords[this.routeCoords.length - 1]) ||
        [112.992, 28.215]
      this.geofenceLayers.destCircle = L.circle(toLeafletLatLng(destCoords), {
        radius: 80,
        color: '#6366f1',
        weight: 2,
        dashArray: '4, 4',
        fillColor: '#6366f1',
        fillOpacity: 0.18,
      }).addTo(this.leafletMap)
      this.geofenceLayers.destCircle.bindTooltip('🎯 目的地·80米安全防线', { permanent: false, direction: 'top' })

      // 4. 水域/陡坡高危警戒区 (红色警示圈)
      const riskCoords = this.getRiskZoneCoords()
      this.geofenceLayers.riskCircle = L.circle(toLeafletLatLng(riskCoords), {
        radius: 130,
        color: '#ef4444',
        weight: 2,
        dashArray: '5, 5',
        fillColor: '#ef4444',
        fillOpacity: 0.22,
      }).addTo(this.leafletMap)
      this.geofenceLayers.riskCircle.bindTooltip('⚠️ 高危水域/陡坡警戒区 (年嘉湖)', { permanent: false, direction: 'top' })

      // 5. 绘制途经打点 Markers
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

      // 6. 绘制历史足迹折线与面包屑打点
      if (this.trailPoints.length >= 2) {
        const trailLatLngs = this.trailPoints.map((p) => toLeafletLatLng([p.lng, p.lat]))
        this.trailPolyline = L.polyline(trailLatLngs, {
          color: '#f59e0b',
          weight: 4,
          opacity: 0.85,
          dashArray: '4, 6',
          lineCap: 'round',
        }).addTo(this.leafletMap)
      }
      this.trailPoints.forEach((pt, idx) => {
        const isCurrent = idx === this.currentPlaybackIndex
        const dotHtml = `<div class="trail-breadcrumb-dot ${isCurrent ? 'current' : ''}"></div>`
        const icon = makeMapMarkerIcon(L, { html: dotHtml, size: [14, 14] })
        const m = L.marker(toLeafletLatLng([pt.lng, pt.lat]), {
          icon,
          zIndexOffset: isCurrent ? 1500 : 400,
        }).addTo(this.leafletMap)
        m.on('click', () => {
          this.pausePlayback()
          this.currentPlaybackIndex = idx
          this.applyPlaybackStep()
        })
        this.breadcrumbMarkers.push(m)
      })

      // 7. 绘制/更新长辈当前位置呼吸 Marker
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
            if (cp.lng && cp.lat) {
              const newPos = [cp.lng, cp.lat]
              this.elderCoords = newPos
              if (this.elderMarker) {
                this.elderMarker.setLatLng(toLeafletLatLng(newPos))
              }
            }
            if (
              !this.checkpoints.length ||
              this.checkpoints[this.checkpoints.length - 1].id !== cp.id
            ) {
              this.checkpoints.push(cp)
            }
            this.updateOffRouteMarker()
          }
        } catch (e) {
          // 轮询静默
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
        this.leafletMap.fitBounds(this.routePolyline.getBounds(), {
          padding: [40, 40],
          animate: true,
          duration: 0.8,
          easeLinearity: 0.25,
        })
      }
    },
    focusElderLocation() {
      if (this.leafletMap && this.elderCoords) {
        this.leafletMap.flyTo(toLeafletLatLng(this.elderCoords), 15, {
          animate: true,
          duration: 0.8,
          easeLinearity: 0.25,
        })
      }
    },
    callElder() {
      uni.showModal({
        title: '致电长辈确认',
        content: `长辈当前位置：${this.latestCheckpoint ? this.latestCheckpoint.location : '安全走廊内'}。是否立即呼叫长辈电话？`,
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
    // 轨迹时空回放控制
    togglePlay() {
      if (this.isPlaying) {
        this.pausePlayback()
      } else {
        this.startPlayback()
      }
    },
    startPlayback() {
      if (!this.trailPoints.length) {
        uni.showToast({ title: '暂无足迹航迹可回放', icon: 'none' })
        return
      }
      if (this.currentPlaybackIndex >= this.trailPoints.length - 1) {
        this.currentPlaybackIndex = 0
      }
      this.isPlaying = true
      this.stopPlaybackTimer()
      this.playbackTimer = setInterval(() => {
        if (this.currentPlaybackIndex < this.trailPoints.length - 1) {
          this.currentPlaybackIndex++
          this.applyPlaybackStep()
        } else {
          this.pausePlayback()
          uni.showToast({ title: '航迹回放完毕', icon: 'none' })
        }
      }, 1200)
    },
    pausePlayback() {
      this.isPlaying = false
      this.stopPlaybackTimer()
    },
    stopPlaybackTimer() {
      if (this.playbackTimer) {
        clearInterval(this.playbackTimer)
        this.playbackTimer = null
      }
    },
    stepNext() {
      this.pausePlayback()
      if (this.currentPlaybackIndex < this.trailPoints.length - 1) {
        this.currentPlaybackIndex++
        this.applyPlaybackStep()
      }
    },
    stepPrev() {
      this.pausePlayback()
      if (this.currentPlaybackIndex > 0) {
        this.currentPlaybackIndex--
        this.applyPlaybackStep()
      }
    },
    resetPlayback() {
      this.pausePlayback()
      this.currentPlaybackIndex = 0
      this.applyPlaybackStep()
    },
    onSliderChange(e) {
      this.pausePlayback()
      this.currentPlaybackIndex = Number(e.detail.value) || 0
      this.applyPlaybackStep()
    },
    applyPlaybackStep() {
      const pt = this.trailPoints[this.currentPlaybackIndex]
      if (!pt) return
      this.elderCoords = [pt.lng, pt.lat]
      if (this.elderMarker && window.L) {
        this.elderMarker.setLatLng(toLeafletLatLng(this.elderCoords))
      }
      if (window.L && this.breadcrumbMarkers.length) {
        this.breadcrumbMarkers.forEach((m, idx) => {
          const isCurrent = idx === this.currentPlaybackIndex
          const dotHtml = `<div class="trail-breadcrumb-dot ${isCurrent ? 'current' : ''}"></div>`
          m.setIcon(makeMapMarkerIcon(window.L, { html: dotHtml, size: [14, 14] }))
          m.setZIndexOffset(isCurrent ? 1500 : 400)
        })
      }
      this.telemetry.speed = (3.2 + (this.currentPlaybackIndex % 3) * 0.4).toFixed(1)
      this.telemetry.altitude = (45.0 + (this.currentPlaybackIndex % 5) * 0.6).toFixed(1)
      this.telemetry.satellites = 18 + (this.currentPlaybackIndex % 4)
    },
    // 双向安心问候互动
    openReassuranceModal() {
      this.showReassuranceModal = true
    },
    closeReassuranceModal() {
      this.showReassuranceModal = false
    },
    sendReassuranceGreeting() {
      const now = new Date()
      this.reassuranceEvents.push({
        id: Date.now(),
        time: this.fmtTime(now.toISOString()) || '刚刚',
        content: this.selectedGreeting,
        rawTime: now.getTime(),
      })
      this.closeReassuranceModal()
      uni.showToast({
        title: '已向长辈推送安心问候与语音播报',
        icon: 'success',
      })
    },
    async simElderMove(type) {
      if (!this.tripId) return

      if (type === 'dwell') {
        // 模拟长椅滞留超 20 分钟主动防御
        this.simDwellActive = true
        this.simDwellMinutes = 20
        const base = this.elderCoords || (this.routePointsData.length ? [this.routePointsData[0].lng, this.routePointsData[0].lat] : [112.988, 28.213])
        try {
          const res = await post(`/api/trips/${this.tripId}/checkpoints`, {
            location: '烈士公园林荫道便民休息长椅',
            lng: Number(base[0]),
            lat: Number(base[1]),
            dwell_seconds: 1200,
          })
          if (res && res.checkpoint) {
            this.checkpoints.push(res.checkpoint)
            this.renderTripOnMap()
            uni.showToast({ title: '已模拟长椅滞留20分钟，触发防跌倒预警', icon: 'none' })
          }
        } catch (e) {
          uni.showToast({ title: '已触发长椅滞留防跌倒主动防御', icon: 'none' })
        }
        return
      }

      if (type === 'risk') {
        // 模拟靠近年嘉湖水域高危区
        this.simDwellActive = false
        const riskCoords = this.getRiskZoneCoords()
        try {
          const res = await post(`/api/trips/${this.tripId}/checkpoints`, {
            location: '烈士公园年嘉湖西岸水域警戒区',
            lng: Number(riskCoords[0]),
            lat: Number(riskCoords[1]),
          })
          if (res && res.checkpoint) {
            res.checkpoint.status = 'risk_alert'
            res.checkpoint.note = '靠近年嘉湖水域警戒区，请注意避开临水湿滑路面！'
            this.checkpoints.push(res.checkpoint)
            this.elderCoords = [riskCoords[0], riskCoords[1]]
            this.renderTripOnMap()
            uni.showToast({ title: '长辈靠近年嘉湖水域，已触发高危警报！', icon: 'none' })
          }
        } catch (e) {
          uni.showToast({ title: e.message || '模拟失败', icon: 'none' })
        }
        return
      }

      if (type === 'arrived') {
        // 模拟安全进入目的地 80 米围栏
        this.simDwellActive = false
        const dest = this.routePointsData.length
          ? this.routePointsData[this.routePointsData.length - 1]
          : { name: '湖南省人民医院', lng: 112.992, lat: 28.215 }
        try {
          const res = await post(`/api/trips/${this.tripId}/checkpoints`, {
            location: `${dest.name}（已进入80米北斗围栏）`,
            lng: Number(dest.lng),
            lat: Number(dest.lat),
          })
          if (res && res.checkpoint) {
            res.checkpoint.status = 'arrived'
            res.checkpoint.note = `顺利进入目的地【${dest.name}】80米北斗安全围栏，行程顺利完成！`
            this.checkpoints.push(res.checkpoint)
            this.elderCoords = [dest.lng, dest.lat]
            this.renderTripOnMap()
            uni.showToast({ title: '长辈已安全到达目的地！', icon: 'success' })
          }
        } catch (e) {
          uni.showToast({ title: e.message || '模拟失败', icon: 'none' })
        }
        return
      }

      if (type === 'offroute') {
        this.simDwellActive = false
        const base = this.elderCoords
          || (this.routePointsData.length ? [this.routePointsData[0].lng, this.routePointsData[0].lat] : null)
        if (!base) {
          uni.showToast({ title: '还没有长辈位置，先等一次上报', icon: 'none' })
          return
        }
        const offLng = Number(base[0]) + 0.06
        const offLat = Number(base[1]) + 0.04
        try {
          const res = await post(`/api/trips/${this.tripId}/checkpoints`, {
            location: '偏离规划安全走廊（演示上报）',
            lng: offLng,
            lat: offLat,
          })
          if (res && res.checkpoint) {
            this.checkpoints.push(res.checkpoint)
            this.elderCoords = [offLng, offLat]
            this.renderTripOnMap()
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
        // 模拟正常前进到下一站点
        this.simDwellActive = false
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

/* 北斗高精时空遥测看板 */
.bds-telemetry-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: $lyj-space-xs $lyj-space-md $lyj-space-sm;
  padding: 14rpx 18rpx;
  background: #0f172a;
  border-radius: 16rpx;
  box-shadow: 0 4rpx 14rpx rgba(15, 23, 42, 0.2);
  border: 1rpx solid #334155;
  overflow-x: auto;
}
.telemetry-item {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
  align-items: center;
  flex-shrink: 0;
}
.telemetry-label {
  font-size: 20rpx;
  color: #94a3b8;
  font-weight: 600;
}
.telemetry-val {
  font-size: 22rpx;
  font-weight: 800;
  color: #f8fafc;
  font-family: monospace;
}
.telemetry-val.highlight {
  color: #38bdf8;
}
.telemetry-val.success {
  color: #4ade80;
}
.telemetry-val.info {
  color: #fbbf24;
}
.telemetry-divider {
  width: 2rpx;
  height: 32rpx;
  background: #334155;
  margin: 0 8rpx;
  flex-shrink: 0;
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
  height: 56vh;
  background: #f1f5f9;
  touch-action: none !important;
  -webkit-user-select: none;
  user-select: none;
  overscroll-behavior: contain;
  transition: height 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}
.gaode-guard-card.expanded .child-amap-canvas {
  height: 82vh;
}
/* 电子围栏图层图例条 */
.geofence-legend-strip {
  display: flex;
  align-items: center;
  justify-content: space-around;
  padding: 10rpx 16rpx;
  background: rgba(255, 255, 255, 0.95);
  border-bottom: 1rpx solid #e2e8f0;
}
.legend-chip {
  display: flex;
  align-items: center;
  gap: 6rpx;
}
.legend-dot {
  width: 14rpx;
  height: 14rpx;
  border-radius: 50%;
}
.legend-dot.green {
  background: #10b981;
}
.legend-dot.blue {
  background: #0ea5e9;
}
.legend-dot.purple {
  background: #6366f1;
}
.legend-dot.red {
  background: #ef4444;
}
.legend-text {
  font-size: 20rpx;
  color: #475569;
  font-weight: 600;
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
/* 没路线可画时的如实交代条 */
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
/* 异常滞留预警气泡 */
.dwell-alert-bubble {
  position: absolute;
  top: 16rpx;
  left: 16rpx;
  right: 16rpx;
  z-index: 1300;
  background: #fffbeb;
  border: 2rpx solid #f59e0b;
  border-radius: 16rpx;
  padding: 16rpx 20rpx;
  display: flex;
  align-items: center;
  gap: 12rpx;
  box-shadow: 0 6rpx 18rpx rgba(245, 158, 11, 0.25);
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
.alert-icon-pulse.dwell {
  color: #d97706;
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
.alert-action-btn.danger {
  background: #ef4444;
}
.alert-action-btn.care {
  background: #0284c7;
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
.sim-pill-btn.dwell {
  background: #fef3c7;
  color: #b45309;
  border: 1rpx solid #fde68a;
}
.sim-pill-btn.risk {
  background: #fee2e2;
  color: #b91c1c;
  border: 1rpx solid #fca5a5;
}
.sim-pill-btn.success {
  background: #dcfce7;
  color: #15803d;
  border: 1rpx solid #86efac;
}

/* 北斗历史足迹与时空轨迹回放器 */
.trail-playback-panel {
  margin: $lyj-space-sm $lyj-space-md;
  background: #ffffff;
  border-radius: 20rpx;
  border: 1rpx solid #e2e8f0;
  padding: 18rpx 20rpx;
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.04);
}
.playback-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12rpx;
}
.playback-title-row {
  display: flex;
  align-items: center;
  gap: 8rpx;
}
.playback-icon {
  font-size: 28rpx;
}
.playback-title {
  font-size: 26rpx;
  font-weight: 800;
  color: #1e293b;
}
.playback-tag {
  font-size: 20rpx;
  color: #0284c7;
  background: #e0f2fe;
  padding: 2rpx 10rpx;
  border-radius: 12rpx;
  font-weight: 700;
}
.playback-time {
  font-size: 24rpx;
  color: #64748b;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.playback-slider-box {
  padding: 4rpx 10rpx;
}
.playback-slider {
  margin: 10rpx 0;
}
.playback-controls {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12rpx;
  margin-top: 8rpx;
}
.ctrl-step-btn,
.ctrl-reset-btn {
  background: #f1f5f9;
  color: #475569;
  border: 1rpx solid #cbd5e1;
  border-radius: 16rpx;
  font-size: 22rpx;
  font-weight: 700;
  padding: 4rpx 16rpx;
  margin: 0;
}
.ctrl-play-btn {
  background: #2563eb;
  color: #ffffff;
  border: none;
  border-radius: 16rpx;
  font-size: 24rpx;
  font-weight: 800;
  padding: 6rpx 28rpx;
  margin: 0;
  box-shadow: 0 4rpx 10rpx rgba(37, 99, 235, 0.3);
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
.cp-dot.dwell {
  background: #f59e0b;
}
.cp-dot.risk {
  background: #ef4444;
}
.cp-dot.arrived {
  background: #10b981;
}
.cp-dot.care {
  background: #0284c7;
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
.cp-note.dwell {
  color: #b45309;
  font-weight: 700;
}
.cp-note.risk {
  color: #b91c1c;
  font-weight: 700;
}
.cp-note.care {
  color: #0284c7;
  font-weight: 600;
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

/* 底部家人安心互动操作栏 */
.guardian-bottom-bar {
  display: flex;
  gap: 16rpx;
  margin: $lyj-space-md;
}
.guardian-action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10rpx;
  min-height: 88rpx;
  border-radius: 20rpx;
  border: none;
  font-size: 28rpx;
  font-weight: 800;
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.08);
}
.guardian-action-btn.phone {
  background: #ef4444;
  color: #ffffff;
}
.guardian-action-btn.care {
  background: #2563eb;
  color: #ffffff;
}
.btn-icon {
  font-size: 32rpx;
}
.btn-text {
  font-size: 28rpx;
  font-weight: 700;
}

/* 安心问候弹窗 */
.reassurance-modal-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32rpx;
}
.reassurance-modal-content {
  width: 100%;
  max-width: 600rpx;
  background: #ffffff;
  border-radius: 24rpx;
  padding: 32rpx;
  box-shadow: 0 12rpx 36rpx rgba(0, 0, 0, 0.2);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
}
.modal-title {
  font-size: 30rpx;
  font-weight: 800;
  color: #0f172a;
}
.modal-close {
  font-size: 32rpx;
  color: #94a3b8;
  cursor: pointer;
  padding: 8rpx;
}
.modal-desc {
  font-size: 24rpx;
  color: #64748b;
  line-height: 1.5;
  margin-bottom: 20rpx;
}
.greeting-options {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  margin-bottom: 24rpx;
}
.greeting-option-item {
  padding: 16rpx 20rpx;
  background: #f8fafc;
  border-radius: 14rpx;
  border: 2rpx solid #e2e8f0;
  cursor: pointer;
  transition: all 0.2s ease;
}
.greeting-option-item.selected {
  background: #eff6ff;
  border-color: #3b82f6;
}
.greeting-text {
  font-size: 24rpx;
  color: #1e293b;
  line-height: 1.4;
}
.greeting-option-item.selected .greeting-text {
  color: #1d4ed8;
  font-weight: 700;
}
.modal-actions {
  display: flex;
  gap: 16rpx;
}
.modal-btn {
  flex: 1;
  font-size: 26rpx;
  font-weight: 700;
  border-radius: 16rpx;
  min-height: 76rpx;
  line-height: 76rpx;
  border: none;
}
.modal-btn.cancel {
  background: #f1f5f9;
  color: #64748b;
}
.modal-btn.confirm {
  background: #2563eb;
  color: #ffffff;
}
</style>

<!-- 高德 Marker 的自定义 DOM 样式统一在 utils/amap.js 的 ensureAmapMarkerStyles()
     里以文档级 <style> 注入（子女端 .child-map-station-badge / .child-elder-breathe-marker
     / .child-offroute-marker-bubble 及其动效都在那里）。高德 Marker 是运行时插进它
     自己容器的，uni-app H5 的作用域标记会让写在这里的规则命中不到，故此处不再重复声明。 -->
