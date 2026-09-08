<template>
  <view class="guardian">
    <LyjBack />
    <LyjSegment current="guardian" />

    <view v-if="trip" class="trip-head">
      <text class="trip-title">{{ trip.purpose }}</text>
      <text class="trip-sub">{{ statusText }} · {{ reportLine }}</text>
    </view>

    <!-- 位置只到城市级 / 完全未开放时，先把"为什么看不到细节"说清楚 -->
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

    <view v-if="!trip" class="empty-card">
      <text class="empty-text">{{ emptyText }}</text>
    </view>

    <template v-else-if="!locationOff">
      <!-- 路线示意（演示：静态折线关键点） -->
      <view class="map-card">
        <view class="route">
          <view v-for="(p, i) in route" :key="i" class="route-col">
            <view class="route-dot" :class="dotClass(p)"></view>
            <view v-if="i < route.length - 1" class="route-line" :class="lineClass(i)"></view>
          </view>
        </view>
        <view class="route-labels">
          <text
            v-for="(p, i) in route"
            :key="i"
            class="route-label"
            :class="{ passed: p.visited, abnormal: p.abnormal }"
          >{{ p.name }}</text>
        </view>
        <text class="map-note">📈 演示数据：位置由行程守护接口模拟上报</text>
      </view>

      <!-- 位置时间线 -->
      <view class="section">
        <text class="section-title">📍 位置记录</text>
        <view v-if="!checkpoints.length" class="empty-row">
          <text>老人还没出发（行程规划完成后开始记录）</text>
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
import { get, post } from '../../api/client'
import { getCurrentUser } from '../../store/user'
import { publishPendingCount } from '../../store/pendingBadge'

// 与后端 Mock 地图一致的演示途经点
const EXPECTED = ['家（南京鼓楼区）', '南京南站', '济南西站', '北京南站', '北京积水潭医院']

const PRECISION_NOTE = {
  city: '老人把位置开放到城市级，所以下面的地点是粗化过的，没有具体门牌号和坐标。',
  off: '老人没有开放位置共享。行程本身能看到，但途经地点和轨迹一项都不会给。',
}

export default {
  components: { LyjSegment },
  data() {
    return {
      user: null,
      tripId: '',
      trip: null,
      checkpoints: [],
      precision: '',
      loaded: false,
      pendingConfirmations: [],
      actionLoading: {},
    }
  },
  computed: {
    statusText() {
      const s = this.trip ? this.trip.status : ''
      return { planned: '已规划', ongoing: '进行中', completed: '已完成' }[s] || s
    },
    locationOff() {
      return this.precision === 'off'
    },
    precisionNote() {
      return PRECISION_NOTE[this.precision] || ''
    },
    reportLine() {
      if (this.locationOff) return '位置未开放'
      return `共 ${this.checkpoints.length} 次位置上报`
    },
    emptyText() {
      if (!this.loaded) return '加载中…'
      return '还没有行程。老人说一句"我想去哪儿"，规划好了就会出现在这里。'
    },
    route() {
      return EXPECTED.map((name) => {
        // 粗化后的地点是原名的前缀（privacy.coarse_place），所以两边都要试一次
        const matched = this.checkpoints.find(
          (c) => c.location && (c.location.includes(name) || name.includes(c.location)),
        )
        return {
          name,
          visited: !!matched && matched.status !== 'off_route',
          abnormal: !!matched && matched.status === 'off_route',
        }
      })
    },
  },
  onLoad(opts) {
    // 两条来路：看板下钻会带 trip_id；顶部分段控件切过来不带，得自己挑一个行程
    this.tripId = (opts && opts.trip_id) || ''
  },
  onShow() {
    this.user = getCurrentUser()
    if (!this.user || this.user.role !== 'child') {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.load()
  },
  methods: {
    async load() {
      try {
        if (!this.tripId) this.tripId = await this._latestTripId()
        const promises = [
          get(`/api/child/${this.user.id}/dashboard`).catch(() => null),
        ]
        if (this.tripId) {
          promises.unshift(get(`/api/trips/${this.tripId}`, { child_id: this.user.id }))
        }
        const results = await Promise.all(promises)
        const tripRes = this.tripId ? results[0] : null
        const dashRes = this.tripId ? results[1] : results[0]

        if (tripRes) {
          this.trip = tripRes.trip
          this.checkpoints = tripRes.checkpoints || []
          this.precision = tripRes.precision || ''
        }
        if (dashRes && Array.isArray(dashRes.pending_confirmations)) {
          this.pendingConfirmations = dashRes.pending_confirmations
          publishPendingCount(this.pendingConfirmations.filter((x) => !x.status || x.status === 'pending').length)
        }
      } catch (e) {
        uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
      this.loaded = true
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
      if (typeof this.$set === 'function') {
        this.$set(this.actionLoading, t.id, 'approve')
      } else {
        this.actionLoading[t.id] = 'approve'
      }
      try {
        const res = await post(`/api/confirmations/${t.id}/approve?child_id=${this.user.id}`)
        const nextStatus = res.status || (res.ok ? 'executed' : 'failed')
        if (typeof this.$set === 'function') {
          this.$set(t, 'status', nextStatus)
        } else {
          t.status = nextStatus
        }
        publishPendingCount(this.pendingConfirmations.filter((x) => !x.status || x.status === 'pending').length)
        uni.showToast({ title: '已同意并办理', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '操作失败', icon: 'none' })
      } finally {
        if (typeof this.$delete === 'function') {
          this.$delete(this.actionLoading, t.id)
        } else {
          delete this.actionLoading[t.id]
        }
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
      if (typeof this.$set === 'function') {
        this.$set(this.actionLoading, t.id, 'reject')
      } else {
        this.actionLoading[t.id] = 'reject'
      }
      try {
        const res = await post(`/api/confirmations/${t.id}/reject?child_id=${this.user.id}`)
        const nextStatus = res.status || 'rejected'
        if (typeof this.$set === 'function') {
          this.$set(t, 'status', nextStatus)
        } else {
          t.status = nextStatus
        }
        publishPendingCount(this.pendingConfirmations.filter((x) => !x.status || x.status === 'pending').length)
        uni.showToast({ title: '已拒绝', icon: 'none' })
      } catch (err) {
        uni.showToast({ title: err.message || '操作失败', icon: 'none' })
      } finally {
        if (typeof this.$delete === 'function') {
          this.$delete(this.actionLoading, t.id)
        } else {
          delete this.actionLoading[t.id]
        }
      }
    },
    async _latestTripId() {
      const d = await get(`/api/child/${this.user.id}/dashboard`)
      const trips = d.trips || []
      // 看板已按 -created_at 排好，第一条就是最近的
      return trips.length ? trips[0].id : ''
    },
    dotClass(p) {
      if (p.abnormal) return 'abnormal'
      return p.visited ? 'visited' : ''
    },
    lineClass(i) {
      return this.route[i] && this.route[i].visited ? 'visited' : ''
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
  background: $lyj-child-bg;
  /* 子女端用原生导航栏，不需要自己让开状态栏 */
  padding: $lyj-space-md 0 $lyj-space-xl;
  box-sizing: border-box;
}
.trip-head {
  padding: $lyj-space-sm $lyj-space-lg;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.trip-title {
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-child-text;
}
.trip-sub {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
}
.precision-note {
  margin: $lyj-space-xs $lyj-space-md;
  padding: $lyj-space-md;
  background: $lyj-info-bg;
  border: 2rpx solid $lyj-info-line;
  border-radius: $lyj-radius;
}
.precision-text {
  font-size: $lyj-font-sm;
  color: $lyj-info;
  line-height: $lyj-line-height;
}
.empty-card {
  margin: $lyj-space-md;
  padding: $lyj-space-xl $lyj-space-md;
  background: $lyj-card;
  border-radius: $lyj-radius;
  text-align: center;
}
.empty-text {
  font-size: $lyj-font-md;
  color: $lyj-child-muted;
  line-height: $lyj-line-height;
}
.map-card {
  margin: $lyj-space-sm $lyj-space-md;
  background: linear-gradient(150deg, $lyj-weather-from, $lyj-card);
  border: 2rpx solid $lyj-weather-line;
  border-radius: $lyj-radius;
  padding: $lyj-space-lg $lyj-space-md;
}
.route {
  display: flex;
  align-items: center;
  padding: 0 $lyj-space-xs;
}
.route-col {
  flex: 1;
  display: flex;
  align-items: center;
}
.route-dot {
  width: 26rpx;
  height: 26rpx;
  border-radius: 50%;
  background: $lyj-dot-idle;
  border: 4rpx solid $lyj-card;
  box-shadow: 0 0 0 2rpx $lyj-dot-idle;
  flex-shrink: 0;
}
.route-dot.visited {
  background: $lyj-info;
  box-shadow: 0 0 0 2rpx $lyj-info;
}
.route-dot.abnormal {
  background: $lyj-danger;
  box-shadow: 0 0 0 2rpx $lyj-danger;
}
.route-line {
  flex: 1;
  height: 6rpx;
  background: $lyj-dot-idle;
  margin: 0 6rpx;
  border-radius: 3rpx;
}
.route-line.visited {
  background: $lyj-info;
}
.route-labels {
  display: flex;
  margin-top: $lyj-space-sm;
  padding: 0 $lyj-space-xs;
}
/* 途经点标签是密排的 5 列，$lyj-font-sm 也放不下 —— 这是图例，不承载唯一信息
   （同一份地点在下面"位置记录"里按正文字号完整列了一遍）。 */
.route-label {
  flex: 1;
  text-align: center;
  font-size: $lyj-font-nav;
  color: $lyj-child-muted;
  line-height: $lyj-line-height;
}
.route-label.passed {
  color: $lyj-info;
  font-weight: 700;
}
.route-label.abnormal {
  color: $lyj-danger;
  font-weight: 700;
}
.map-note {
  display: block;
  text-align: center;
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
  margin-top: $lyj-space-md;
}
.section {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
}
.section-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
}
.empty-row {
  padding: $lyj-space-md 0;
}
.empty-row text {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
  line-height: $lyj-line-height;
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
  width: 22rpx;
  height: 22rpx;
  border-radius: 50%;
  background: $lyj-success;
  flex-shrink: 0;
  margin-top: $lyj-space-xs;
}
.cp-dot.off_route {
  background: $lyj-danger;
}
.cp-line {
  flex: 1;
  width: 4rpx;
  background: $lyj-child-line;
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
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-child-text;
}
.cp-time {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
}
.cp-note {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-child-body;
  line-height: $lyj-line-height;
  margin-top: $lyj-space-xs;
}
.cp-note.off_route {
  color: $lyj-danger;
}

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
</style>
