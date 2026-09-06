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
          <text class="section-title">✋ 待我确认 ({{ pending.length }})</text>
        </view>
        <view v-if="!pending.length" class="empty-row">
          <text>暂无待确认事项</text>
        </view>
        <view v-for="t in pending" :key="t.id" class="confirm-item" @tap="goDetail(t)">
          <view class="confirm-main">
            <text class="confirm-summary">{{ cardOf(t).summary }}</text>
            <text class="confirm-reason">{{ cardOf(t).reason }}</text>
          </view>
          <view class="confirm-side">
            <text v-if="t.amount" class="confirm-amount">¥{{ t.amount }}</text>
            <text class="confirm-go">去处理 ›</text>
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
    }
  },
  onShow() {
    this.user = getCurrentUser()
    if (!this.user || this.user.role !== 'child') {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.loadAll()
  },
  methods: {
    async loadAll() {
      try {
        const [dashRes, famRes] = await Promise.all([
          get(`/api/child/${this.user.id}/dashboard`),
          get('/api/family/members')
        ])
        
        this.pending = dashRes.pending_confirmations || []
        this.alerts = dashRes.alerts || []
        // 通知页也是发现者之一（手动刷新时）。数量变多的震动在 publish 内部。
        publishPendingCount(this.pending.length)
        
        const allMembers = famRes.items || []
        this.pendingMembers = allMembers.filter(m => m.status === 'pending' && m.invited_by !== this.user.id)
      } catch (e) {
        uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
    },
    cardOf(task) {
      return task.summary_for_child || {}
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
}
.refresh {
  min-height: $lyj-hit-min;
  display: flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.15);
  color: $lyj-text-on;
  font-size: $lyj-font-sm;
  border-radius: $lyj-radius;
  margin: 0 0 0 $lyj-space-md;
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
/* 待确认条 */
.confirm-item {
  display: flex;
  align-items: center;
  gap: $lyj-space-md;
  min-height: $lyj-hit-min;
  padding: $lyj-space-md;
  background: $lyj-warn-bg;
  border: 2rpx solid $lyj-warn;
  border-radius: $lyj-radius;
  margin-bottom: $lyj-space-sm;
  transition: all 0.2s ease;
}
.confirm-item:active {
  transform: scale(0.98);
}
.confirm-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.confirm-summary {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-text;
}
.confirm-reason {
  font-size: $lyj-font-sm;
  color: $lyj-warn-text;
}
.confirm-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: $lyj-space-xs;
}
.confirm-amount {
  font-size: $lyj-font-md;
  font-weight: 800;
  color: $lyj-danger;
}
.confirm-go {
  font-size: $lyj-font-sm;
  color: $lyj-primary;
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
  gap: $lyj-space-xs;
}
.mini-btn {
  font-size: $lyj-font-sm;
  margin: 0;
  border-radius: $lyj-radius-pill;
}
.mini-btn.ok {
  background: $lyj-success;
  color: #fff;
}
.mini-btn.no {
  background: $lyj-muted-bg;
  color: $lyj-text;
}

@media screen and (min-width: 768px) {
  .notification-page {
    max-width: 960px;
    margin: 0 auto;
    padding: 30rpx 32rpx 100rpx;
  }
  .sections-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 24rpx;
    align-items: start;
  }
  .section {
    margin: 0;
  }
}
</style>
