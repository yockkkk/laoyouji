<template>
  <view class="notification-page">
    <view class="head">
      <view class="head-info">
        <text class="title">通知中心</text>
        <text class="sub">待处理事项与系统告警</text>
      </view>
      <button class="refresh" size="mini" @tap="loadAll">刷新</button>
    </view>

    <LyjSegment current="notification" />

    <view class="sections-grid">
      <!-- 待我确认 -->
      <view class="section">
        <view class="section-head">
          <text class="section-title">✋ 待我确认的付款 ({{ pendingCount }})</text>
        </view>
        <view v-if="!pending.length" class="empty-row">
          <text>暂无待您确认的付款事项</text>
        </view>
        <view v-for="t in pending" :key="t.id" class="confirm-card" @tap="goDetail(t)">
          <view class="confirm-card-top">
            <view class="confirm-icon">{{ taskIcon(t) }}</view>
            <view class="confirm-main">
              <view class="confirm-title-row">
                <text class="confirm-summary">{{ taskSummary(t) }}</text>
                <text v-if="t.amount" class="confirm-amount">¥{{ t.amount }}</text>
              </view>
              <text class="confirm-reason" v-if="taskReason(t)">原因：{{ taskReason(t) }}</text>
              <text class="confirm-time" v-if="t.created_at">申请时间：{{ fmtTime(t.created_at) }}</text>
            </view>
          </view>
          <view class="confirm-action-bar">
            <text class="confirm-go" @tap.stop="goDetail(t)">查看详情 ›</text>
            <view v-if="t.status === 'executed' || t.status === 'approved'" class="inline-status success">
              <text>✅ 已同意并办理</text>
            </view>
            <view v-else-if="t.status === 'rejected'" class="inline-status rejected">
              <text>🚫 已拒绝</text>
            </view>
            <view v-else-if="t.status === 'failed'" class="inline-status failed">
              <text>⚠️ 执行失败</text>
            </view>
            <view v-else class="pending-btns">
              <button
                class="approve-btn"
                :loading="actionLoading[t.id] === 'approve'"
                :disabled="!!actionLoading[t.id]"
                size="mini"
                @tap.stop="approveTask(t)"
              >
                同意
              </button>
              <button
                class="reject-btn"
                :loading="actionLoading[t.id] === 'reject'"
                :disabled="!!actionLoading[t.id]"
                size="mini"
                @tap.stop="rejectTask(t)"
              >
                拒绝
              </button>
            </view>
          </view>
        </view>
      </view>

      <!-- 长辈动态通知 -->
      <view class="section">
        <view class="section-head">
          <text class="section-title">📢 长辈动态通知 ({{ elderNotifications.length }})</text>
        </view>
        <view v-if="!elderNotifications.length" class="empty-row">
          <text>暂无动态通知</text>
        </view>
        <view
          v-for="n in elderNotifications"
          :key="n.id"
          class="notif-item"
          :class="{ unread: !n.is_read }"
          @tap="markRead(n)"
        >
          <view class="notif-icon">📋</view>
          <view class="notif-content">
            <view class="notif-title-row">
              <text class="notif-title">{{ n.title }}</text>
              <text v-if="!n.is_read" class="unread-badge">未读</text>
            </view>
            <text class="notif-body">{{ n.summary || n.content }}</text>
            <text class="notif-time" v-if="n.created_at">{{ fmtTime(n.created_at) }}</text>
          </view>
        </view>
      </view>

      <!-- 家庭绑定申请 -->
      <view class="section">
        <view class="section-head">
          <text class="section-title">👨‍👩‍👧‍👦 家庭邀请 ({{ pendingMembers.length }})</text>
        </view>
        <view v-if="!pendingMembers.length" class="empty-row"><text>暂无待处理邀请</text></view>
        <view v-for="m in pendingMembers" :key="m.id" class="member-item">
          <view class="member-main">
            <text class="member-name">{{ m.user ? m.user.name : '未知' }}（{{ m.relation }}）</text>
            <text class="member-sub">账号: {{ m.user ? m.user.username : '' }}</text>
          </view>
          <view class="member-actions">
            <button class="mini-btn ok" size="mini" @tap="accept(m)">同意</button>
            <button class="mini-btn no" size="mini" @tap="reject(m)">拒绝</button>
          </view>
        </view>
      </view>

      <!-- 守护告警 -->
      <view class="section">
        <view class="section-head">
          <text class="section-title">🔔 最近告警</text>
        </view>
        <view v-if="!alerts.length" class="empty-row"><text>一切正常，没有告警</text></view>
        <view v-for="(a, i) in alerts" :key="a.id || i" class="alert-item">
          <text class="alert-icon">⚠️</text>
          <view class="alert-body">
            <text class="alert-note">{{ a.note }}</text>
            <text class="alert-meta">
              {{ a.location }}<text v-if="a.created_at"> · {{ fmtTime(a.created_at) }}</text>
            </text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import LyjSegment from '../../components/LyjSegment.vue'
import { get, post } from '../../api/client'
import { getCurrentUser } from '../../store/user'
import { publishPendingCount } from '../../store/pendingBadge'

export default {
  components: { LyjSegment },
  data() {
    return {
      user: null,
      pending: [],
      alerts: [],
      pendingMembers: [],
      elderNotifications: [],
      actionLoading: {},
      timer: null,
    }
  },
  computed: {
    pendingCount() {
      return this.pending.filter((t) => !t.status || t.status === 'pending').length
    },
  },
  onShow() {
    this.user = getCurrentUser()
    if (!this.user || this.user.role !== 'child') {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.loadAll()
    this.startPolling()
  },
  onHide() {
    this.stopPolling()
  },
  onUnload() {
    this.stopPolling()
  },
  methods: {
    startPolling() {
      this.stopPolling()
      this.timer = setInterval(() => this.loadAll(true), 5000)
    },
    stopPolling() {
      if (this.timer) {
        clearInterval(this.timer)
        this.timer = null
      }
    },
    async loadAll(silent) {
      try {
        const [dashRes, famRes, notifRes] = await Promise.all([
          get(`/api/child/${this.user.id}/dashboard`),
          get('/api/family/members'),
          get(`/api/child/${this.user.id}/notifications`).catch(() => null),
        ])

        const rawPending = dashRes.pending_confirmations || []
        const serverIds = new Set(rawPending.map((x) => x.id))
        const now = Date.now()
        const kept = []
        for (const local of this.pending) {
          if (serverIds.has(local.id)) {
            const fresh = rawPending.find((x) => x.id === local.id)
            if (local.status && local.status !== 'pending') {
              kept.push(local)
            } else {
              kept.push(fresh)
            }
          } else {
            // If local was already resolved and this is silent refresh, keep it temporarily (10s)
            if (silent && local.status && local.status !== 'pending' && (!local.resolvedAt || now - local.resolvedAt < 10000)) {
              kept.push(local)
            }
          }
        }
        for (const fresh of rawPending) {
          if (!kept.some((x) => x.id === fresh.id)) {
            kept.push(fresh)
          }
        }
        this.pending = kept
        this.alerts = dashRes.alerts || []
        this.elderNotifications = (notifRes && notifRes.items) || dashRes.notifications || []

        publishPendingCount(this.pendingCount)

        const allMembers = famRes.items || []
        this.pendingMembers = allMembers.filter(
          (m) => m.status === 'pending' && m.invited_by !== this.user.id
        )
      } catch (e) {
        if (!silent) uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
    },
    taskIcon(t) {
      // 只留**在册**的工具（现役 22 个，见后端装配）。book_ticket / search_train /
      // book_hotel / order_service 都已随产品收敛删掉，留着图标会让后来人以为
      // 这产品还在订票订酒店。register_appointment 不在 HIGH_RISK_TOOLS 里、
      // 不会走到这一屏，留着只为兜旧会话的历史挂起记录。
      const map = {
        register_appointment: '🏥',
        search_hospital: '🏥',
        pay: '💸',
      }
      return map[t.tool_name] || '✋'
    },
    cardOf(task) {
      return task.summary_for_child || {}
    },
    taskSummary(t) {
      const card = t.summary_for_child || {}
      return card.summary || t.tool_name || '需要您确认的事项'
    },
    taskReason(t) {
      const card = t.summary_for_child || {}
      return card.reason || ''
    },
    fmtTime(iso) {
      if (!iso) return ''
      const d = new Date(iso)
      if (!Number.isFinite(d.getTime())) return ''
      const pad = (n) => String(n).padStart(2, '0')
      return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
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
        t.resolvedAt = Date.now()
        publishPendingCount(this.pendingCount)
        uni.showToast({ title: '已同意并办理', icon: 'success' })
      } catch (err) {
        const msg = err.message || ''
        if (msg.includes('executed') || msg.includes('已执行')) {
          if (typeof this.$set === 'function') this.$set(t, 'status', 'executed')
          else t.status = 'executed'
          t.resolvedAt = Date.now()
          publishPendingCount(this.pendingCount)
        } else if (msg.includes('rejected') || msg.includes('已拒绝')) {
          if (typeof this.$set === 'function') this.$set(t, 'status', 'rejected')
          else t.status = 'rejected'
          t.resolvedAt = Date.now()
          publishPendingCount(this.pendingCount)
        } else if (msg.includes('已处理') || msg.includes('不存在')) {
          this.loadAll(true)
        }
        uni.showToast({ title: msg || '操作失败', icon: 'none' })
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
      if (this.actionLoading[t.id]) return
      if (t.status && t.status !== 'pending') return
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
        t.resolvedAt = Date.now()
        publishPendingCount(this.pendingCount)
        uni.showToast({ title: '已拒绝', icon: 'none' })
      } catch (err) {
        const msg = err.message || ''
        if (msg.includes('rejected') || msg.includes('已拒绝')) {
          if (typeof this.$set === 'function') this.$set(t, 'status', 'rejected')
          else t.status = 'rejected'
          t.resolvedAt = Date.now()
          publishPendingCount(this.pendingCount)
        } else if (msg.includes('executed') || msg.includes('已执行')) {
          if (typeof this.$set === 'function') this.$set(t, 'status', 'executed')
          else t.status = 'executed'
          t.resolvedAt = Date.now()
          publishPendingCount(this.pendingCount)
        } else if (msg.includes('已处理') || msg.includes('不存在')) {
          this.loadAll(true)
        }
        uni.showToast({ title: msg || '操作失败', icon: 'none' })
      } finally {
        if (typeof this.$delete === 'function') {
          this.$delete(this.actionLoading, t.id)
        } else {
          delete this.actionLoading[t.id]
        }
      }
    },
    async markRead(n) {
      if (!n.is_read) {
        n.is_read = true
        try {
          await post(`/api/child/notifications/${n.id}/read`)
        } catch (e) {
          // silent
        }
      }
      // 1. 若为待审批通知，直接跳转至详情页审批
      let taskId = n.task_id || null
      if (!taskId && n.data) {
        if (typeof n.data === 'object' && n.data !== null) {
          taskId = n.data.task_id || n.data.id
        } else if (typeof n.data === 'string') {
          try {
            const parsed = JSON.parse(n.data)
            taskId = parsed.task_id || parsed.id
          } catch (e) {}
        }
      }
      if (taskId || n.type === 'confirmation_request') {
        const targetId = taskId || (this.pending.length > 0 ? this.pending[0].id : '')
        if (targetId) {
          uni.navigateTo({
            url: `/pages/child/confirm-detail?id=${targetId}&child_id=${this.user.id}`,
          })
          return
        }
      }

      // 2. 若为计划书生成通知，跳转至行程守护页
      if (n.type === 'plan_created') {
        let tripId = n.trip_id || null
        if (!tripId && n.data) {
          if (typeof n.data === 'object' && n.data !== null) {
            tripId = n.data.trip_id
          } else if (typeof n.data === 'string') {
            try {
              tripId = JSON.parse(n.data).trip_id
            } catch (e) {}
          }
        }
        if (tripId) {
          uni.navigateTo({ url: `/pages/child/guardian?trip_id=${tripId}` })
        }
      }
    },
    async accept(m) {
      try {
        await post(`/api/family/requests/${m.binding_id}/accept`, {})
        uni.showToast({ title: '已同意绑定', icon: 'success' })
        this.loadAll()
      } catch (err) {
        uni.showToast({ title: err.message || '操作失败', icon: 'none' })
      }
    },
    async reject(m) {
      try {
        await post(`/api/family/requests/${m.binding_id}/reject`, {})
        uni.showToast({ title: '已拒绝申请', icon: 'none' })
        this.loadAll()
      } catch (err) {
        uni.showToast({ title: err.message || '操作失败', icon: 'none' })
      }
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.notification-page {
  min-height: 100vh;
  background: $lyj-child-bg;
  padding-bottom: $lyj-space-xl;
  box-sizing: border-box;
}
.head {
  background: $lyj-child-head;
  padding: $lyj-space-lg $lyj-space-lg $lyj-space-md;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.head-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.title {
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-text-on;
}
.sub {
  font-size: $lyj-font-sm;
  color: $lyj-child-head-sub;
  white-space: nowrap;
}
.refresh {
  min-height: 88rpx;
  line-height: 88rpx;
  display: flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.15);
  color: $lyj-text-on;
  font-size: $lyj-font-sm;
  border-radius: $lyj-radius;
  margin: 0 0 0 $lyj-space-md;
  padding: 0 28rpx;
  white-space: nowrap;
  word-break: keep-all;
  flex-shrink: 0;
}
.sections-grid {
  display: flex;
  flex-direction: column;
}
.section {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md;
  border: 2rpx solid $lyj-line;
  box-shadow: $lyj-shadow-card;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.section-head {
  margin-bottom: $lyj-space-sm;
}
.section-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
}
.empty-row {
  padding: $lyj-space-md 0;
  text-align: center;
}
.empty-row text {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
}
/* 待确认卡片 */
.confirm-card {
  background: #fffbeb;
  border: 2rpx solid #fde68a;
  border-radius: $lyj-radius;
  padding: $lyj-space-md;
  margin-bottom: $lyj-space-sm;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-sm;
  transition: all 0.2s ease;
}
.confirm-card:last-child {
  margin-bottom: 0;
}
.confirm-card-top {
  display: flex;
  align-items: flex-start;
}
.confirm-icon {
  font-size: 40rpx;
  line-height: 1;
  margin-right: $lyj-space-sm;
  padding-top: 4rpx;
}
.confirm-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.confirm-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.confirm-summary {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
}
.confirm-amount {
  font-size: $lyj-font-md;
  font-weight: 800;
  color: $lyj-danger;
  font-variant-numeric: tabular-nums;
}
.confirm-reason {
  font-size: $lyj-font-sm;
  color: #4b5563;
  margin-top: 2rpx;
}
.confirm-time {
  font-size: $lyj-font-xs;
  color: $lyj-child-muted;
  margin-top: 2rpx;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.confirm-action-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: $lyj-space-xs;
  border-top: 1rpx dashed #fcd34d;
}
.confirm-go {
  font-size: $lyj-font-sm;
  color: $lyj-primary;
  cursor: pointer;
  white-space: nowrap;
}
.pending-btns {
  display: flex;
  align-items: center;
  gap: $lyj-space-sm;
}
.approve-btn {
  background: #16a34a !important;
  color: #fff !important;
  font-size: $lyj-font-sm;
  font-weight: 600;
  border-radius: $lyj-radius;
  padding: 0 32rpx;
  min-height: 88rpx;
  line-height: 88rpx;
  margin: 0;
  white-space: nowrap;
  word-break: keep-all;
  flex-shrink: 0;
}
.reject-btn {
  background: #e5e7eb !important;
  color: #4b5563 !important;
  font-size: $lyj-font-sm;
  font-weight: 600;
  border-radius: $lyj-radius;
  padding: 0 32rpx;
  min-height: 88rpx;
  line-height: 88rpx;
  margin: 0;
  white-space: nowrap;
  word-break: keep-all;
  flex-shrink: 0;
}
.inline-status {
  display: flex;
  align-items: center;
  font-size: $lyj-font-sm;
  font-weight: 600;
  padding: 8rpx 20rpx;
  border-radius: $lyj-radius-pill;
  min-height: 88rpx;
  white-space: nowrap;
  word-break: keep-all;
  flex-shrink: 0;
}
.inline-status.success {
  background: #dcfce7;
  color: #15803d;
}
.inline-status.rejected {
  background: #f3f4f6;
  color: #6b7280;
}
.inline-status.failed {
  background: #fee2e2;
  color: #b91c1c;
}

/* 长辈动态通知 */
.notif-item {
  display: flex;
  align-items: flex-start;
  gap: $lyj-space-sm;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-child-line;
}
.notif-item:last-child {
  border-bottom: none;
}
.notif-item.unread {
  background: #fafafa;
}
.notif-icon {
  font-size: 36rpx;
  line-height: 1.2;
}
.notif-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.notif-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.notif-title {
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-child-text;
}
.unread-badge {
  font-size: $lyj-font-xs;
  font-weight: 600;
  padding: 2rpx 12rpx;
  border-radius: $lyj-radius-pill;
  background: #fee2e2;
  color: #dc2626;
}
.notif-body {
  font-size: $lyj-font-sm;
  color: #4b5563;
  line-height: 1.4;
}
.notif-time {
  font-size: $lyj-font-xs;
  color: $lyj-child-muted;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
/* 告警条 */
.alert-item {
  display: flex;
  gap: $lyj-space-sm;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-child-line;
}
.alert-item:last-child {
  border-bottom: none;
}
.alert-icon {
  font-size: $lyj-font-md;
}
.alert-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.alert-note {
  font-size: $lyj-font-md;
  color: $lyj-danger;
}
.alert-meta {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
  font-variant-numeric: tabular-nums;
}
/* 家庭邀请条 */
.member-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-child-line;
}
.member-item:last-child {
  border-bottom: none;
}
.member-name {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
  display: block;
}
.member-sub {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
}
.member-actions {
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
}
.mini-btn {
  font-size: $lyj-font-sm;
  font-weight: 600;
  margin: 0;
  border-radius: $lyj-radius;
  min-height: 88rpx;
  line-height: 88rpx;
  padding: 0 32rpx;
  white-space: nowrap;
  word-break: keep-all;
  flex-shrink: 0;
}
.mini-btn.ok {
  background: $lyj-success;
  color: #fff;
}
.mini-btn.no {
  background: $lyj-field;
  color: $lyj-text;
  border: 1rpx solid $lyj-line;
}
</style>
