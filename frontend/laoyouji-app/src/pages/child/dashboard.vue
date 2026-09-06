<template>
  <view class="dash">
    <view class="head">
      <view class="head-info">
        <text class="title">家人看板</text>
        <text class="sub">{{ elderLine }}</text>
      </view>
      <view class="head-actions">
        <button class="refresh" size="mini" @tap="loadAll">刷新</button>
        <button class="logout-btn" size="mini" @tap="logout">退出登录</button>
      </view>
    </view>

    <LyjSegment current="dashboard" />

    <!-- 隐私档位说明。看板"薄"往往不是坏了，而是老人只开放到这一档 —— 说清楚。 -->
    <view v-if="privacyNote" class="privacy-note">
      <text class="privacy-note-text">🔒 {{ privacyNote }}</text>
    </view>

    <!-- 响应式铺砌布局 -->
    <view class="sections-grid">
      <!-- 完整5页计划书（出行与就医） -->
      <view class="section">
        <view class="section-head">
          <text class="section-title">📋 出行与就医计划 ({{ plans.length }})</text>
        </view>
        <view v-if="!plans.length" class="empty-row">
          <text>暂无计划书（长辈提出就医或出行需求后由老友记生成）</text>
        </view>
        <view
          v-for="p in plans"
          :key="p.id"
          class="plan-item"
          @tap="openPlan(p)"
        >
          <view class="plan-item-main">
            <view class="plan-item-title-row">
              <text class="plan-badge" :class="p.type">{{ p.type === 'medical_plan' || (p.title && p.title.includes('就医')) ? '就医计划' : '出行计划' }}</text>
              <text class="plan-item-title">{{ p.title }}</text>
            </view>
            <text class="plan-item-meta">{{ p.status ? statusText(p.status) : '已规划' }} · 点击查看完整5页计划书 ›</text>
          </view>
        </view>
      </view>

      <!-- 行程状态 -->
      <view class="section">
        <view class="section-head">
          <text class="section-title">🧭 出行行程</text>
        </view>
        <view v-if="!trips.length" class="empty-row"><text>暂无行程</text></view>
        <view v-for="t in trips" :key="t.id" class="trip-item">
          <view class="trip-info" @tap="t.plan ? openPlan(t) : goGuardian(t)">
            <text class="trip-purpose">{{ t.purpose }}</text>
            <text class="trip-status" :class="t.status">{{ statusText(t.status) }}</text>
          </view>
          <view class="trip-actions">
            <button v-if="t.plan" class="trip-btn plan" size="mini" @tap="openPlan(t)">计划书</button>
            <button class="trip-btn guardian" size="mini" @tap="goGuardian(t)">守护</button>
          </view>
        </view>
      </view>

      <!-- 今日用药 -->
      <view class="section">
        <view class="section-head">
          <text class="section-title">💊 今日用药</text>
        </view>
        <view v-if="!medications.length" class="empty-row">
          <text>{{ medEmptyText }}</text>
        </view>
        <view v-for="(m, i) in medications" :key="i" class="med-item">
          <text class="med-drug" :class="{ masked: m.precision === 'summary' }">
            {{ drugLabel(m) }}
          </text>
          <text class="med-taken">今日 {{ takenCount(m) }}/{{ (m.times || []).length }} 次</text>
        </view>
      </view>
    </view>

    <!-- 5页完整计划书查看弹窗 -->
    <view v-if="selectedPlan" class="plan-modal-mask" @tap="closePlan">
      <view class="plan-modal-content" @tap.stop>
        <view class="modal-head">
          <text class="modal-head-title">📖 完整计划书（共5页）</text>
          <button class="modal-close-btn" size="mini" @tap="closePlan">✕</button>
        </view>
        <scroll-view scroll-y class="modal-body-scroll">
          <PlanCard
            v-if="selectedPlanCard"
            :title="selectedPlanCard.title"
            :sections="selectedPlanCard.sections"
            :notes="selectedPlanCard.notes"
            :complete="selectedPlanCard.complete"
            :compact="false"
          />
        </scroll-view>
      </view>
    </view>
  </view>
</template>

<script>
import LyjSegment from '../../components/LyjSegment.vue'
import PlanCard from '../../components/PlanCard.vue'
import { get } from '../../api/client'
import { getCurrentUser, clearCurrentUser } from '../../store/user'
import { publishPendingCount } from '../../store/pendingBadge'

/** 没绑定时后端会走提前返回、连 privacy 字段都不给 —— 前端的兜底必须是"全关"。 */
const DENIED = { location_level: 'off', health_level: 'off', bound: false }

export default {
  components: { LyjSegment, PlanCard },
  data() {
    return {
      user: null,
      trips: [],
      plans: [],
      selectedPlan: null,
      selectedPlanCard: null,
      medications: [],
      privacy: DENIED,
      elderName: '',
      elderCity: '',
      timer: null,
      lastRefresh: '',
    }
  },
  computed: {
    elderLine() {
      if (!this.privacy.bound) return '尚未绑定老人'
      const who = [this.elderName, this.elderCity].filter(Boolean).join(' · ')
      return this.lastRefresh ? `${who}｜已更新 ${this.lastRefresh}` : who
    },
    /**
     * 隐私档位的一句话解释。
     *
     * 为什么要显式写出来：分级降级在后端是"数据变形"（privacy.py 的设计第 1 条），
     * 界面上看到的就是一份**更粗**的事实。不解释一句，子女会当成功能坏了，
     * 转头去催老人"把权限全开"—— 那正好把这套分级机制废掉。
     */
    privacyNote() {
      const p = this.privacy
      if (!p.bound) {
        return '还没有和老人建立绑定关系。在绑定之前，位置和健康数据一项都不会给。'
      }
      const parts = []
      if (p.location_level === 'off') parts.push('位置未开放')
      else if (p.location_level === 'city') parts.push('位置只到城市级')
      if (p.health_level === 'off') parts.push('健康未开放')
      else if (p.health_level === 'summary') parts.push('健康只给摘要')
      if (!parts.length) return ''
      return `${parts.join('、')}。这是老人自己的设置，只有他本人能改。`
    },
    medEmptyText() {
      if (this.privacy.health_level === 'off') return '老人未开放健康信息给您'
      return '暂无用药计划'
    },
  },
  onShow() {
    this.user = getCurrentUser()
    if (!this.user || this.user.role !== 'child') {
      // 身份不对 —— 换身份该清栈
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
    logout() {
      clearCurrentUser()
      uni.reLaunch({ url: '/pages/login/login' })
    },
    openPlan(p) {
      this.selectedPlan = p
      this.selectedPlanCard = this._toCard(p.plan || p)
    },
    closePlan() {
      this.selectedPlan = null
      this.selectedPlanCard = null
    },
    _toCard(d) {
      if (!d) return null
      const pages = d.pages || []
      const notes = []
      if (d.subtitle) notes.push(d.subtitle)
      if (d.disclaimer) notes.push(d.disclaimer)
      if (d.footnote) notes.push(d.footnote)
      return {
        kind: 'card',
        title: d.title || '',
        sections: pages.map((p) => ({
          heading: p.title || '',
          rows: p.rows || [],
          notes: p.notes || [],
        })),
        notes,
        complete: d.complete !== false,
        compact: false,
      }
    },
    /**
     * 一次请求拿全部。
     */
    async loadAll(silent) {
      try {
        const d = await get(`/api/child/${this.user.id}/dashboard`)
        publishPendingCount((d.pending_confirmations || []).length)
        this.privacy = d.privacy || DENIED
        this.elderName = d.elder ? d.elder.name : ''
        this.elderCity = d.elder ? d.elder.city || '' : ''
        this.trips = d.trips || []
        this.plans = d.plans || []
        if (!this.plans.length && this.trips.length) {
          this.plans = this.trips.filter((t) => t.plan).map((t) => ({
            id: t.id,
            trip_id: t.id,
            title: (t.plan && t.plan.title) || t.purpose,
            type: (t.plan && t.plan.type) || (t.purpose && t.purpose.includes('就医') ? 'medical_plan' : 'trip_plan'),
            status: t.status,
            created_at: t.created_at,
            plan: t.plan,
          }))
        }
        this.medications = d.medications || []
        this.lastRefresh = this.fmtClock(new Date())
      } catch (e) {
        if (!silent) uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
    },

    drugLabel(m) {
      if (m.drug && m.drug !== '老人未开放此项') return m.drug
      return m.precision === 'summary' ? '用药情况（药名未开放）' : m.drug
    },
    takenCount(m) {
      return Object.values(m.taken_today || {}).filter((s) => s === 'taken').length
    },
    statusText(s) {
      return { planned: '已规划', ongoing: '进行中', completed: '已完成' }[s] || s
    },
    fmtTime(iso) {
      if (!iso) return ''
      const d = new Date(iso)
      if (!Number.isFinite(d.getTime())) return ''
      return `${d.getMonth() + 1}/${d.getDate()} ${this.fmtClock(d, false)}`
    },
    fmtClock(d, withSeconds = true) {
      const pad = (n) => String(n).padStart(2, '0')
      const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
      return withSeconds ? `${hm}:${pad(d.getSeconds())}` : hm
    },

    goGuardian(t) {
      uni.navigateTo({ url: `/pages/child/guardian?trip_id=${t.id}` })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.dash {
  min-height: 100vh;
  background: $lyj-child-bg;
  padding-bottom: $lyj-space-xl;
  box-sizing: border-box;
}
.head {
  /* 子女端保留原生导航栏（pages.json 未设 custom），所以这里**不能**再让一次
     状态栏 —— 那会在标题栏下面多顶出一条空白。导航栏底色已调成同一个深色，
     两块拼起来读成一整个头。 */
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
.privacy-note {
  margin: 0 $lyj-space-md $lyj-space-sm;
  padding: $lyj-space-md;
  background: $lyj-info-bg;
  border: 2rpx solid $lyj-info-line;
  border-radius: $lyj-radius;
}
.privacy-note-text {
  font-size: $lyj-font-sm;
  color: $lyj-info;
  line-height: $lyj-line-height;
}
.section {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
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
  line-height: $lyj-line-height;
}
.trip-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: $lyj-hit-min;
  border-bottom: 2rpx solid $lyj-child-line;
}
.trip-purpose {
  flex: 1;
  font-size: $lyj-font-md;
  color: $lyj-child-text;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trip-status {
  font-size: $lyj-font-sm;
  font-weight: 600;
  padding: $lyj-space-xs $lyj-space-md;
  border-radius: $lyj-radius-pill;
  background: $lyj-info-bg;
  color: $lyj-info;
  margin-left: $lyj-space-sm;
}
.trip-status.ongoing {
  background: $lyj-primary-soft;
  color: $lyj-primary;
}
.trip-status.completed {
  background: $lyj-success-bg;
  color: $lyj-success;
}
.med-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $lyj-space-sm;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-child-line;
}
.med-drug {
  flex: 1;
  font-size: $lyj-font-md;
  color: $lyj-child-text;
}
/* 降级后的那一行：看得见，但不假装是药名 */
.med-drug.masked {
  color: $lyj-child-muted;
  font-style: italic;
}
.med-taken {
  font-size: $lyj-font-sm;
  color: $lyj-success;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
  margin-left: auto;
}
.logout-btn {
  min-height: $lyj-hit-min;
  display: flex;
  align-items: center;
  background: rgba(239, 68, 68, 0.25);
  color: #fff;
  border: 1px solid rgba(239, 68, 68, 0.4);
  font-size: $lyj-font-sm;
  font-weight: 600;
  border-radius: $lyj-radius;
  padding: 0 $lyj-space-sm;
}
.trip-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
  overflow: hidden;
}
.trip-actions {
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
}
.trip-btn {
  min-height: 56rpx;
  line-height: 56rpx;
  font-size: $lyj-font-xs;
  padding: 0 16rpx;
  border-radius: $lyj-radius;
}
.trip-btn.plan {
  background: #0284c7;
  color: #fff;
}
.trip-btn.guardian {
  background: $lyj-primary;
  color: #fff;
}

.plan-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-child-line;
  cursor: pointer;
}
.plan-item:last-child {
  border-bottom: none;
}
.plan-item-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.plan-item-title-row {
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
}
.plan-badge {
  font-size: $lyj-font-xs;
  font-weight: 600;
  padding: 2rpx 10rpx;
  border-radius: $lyj-radius-pill;
  background: #e0f2fe;
  color: #0369a1;
}
.plan-badge.medical_plan {
  background: #fef3c7;
  color: #b45309;
}
.plan-item-title {
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-child-text;
}
.plan-item-meta {
  font-size: $lyj-font-xs;
  color: $lyj-primary;
  margin-top: 2rpx;
}

.plan-modal-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: $lyj-space-md;
}
.plan-modal-content {
  width: 100%;
  max-width: 680px;
  max-height: 85vh;
  background: #fff;
  border-radius: $lyj-radius-lg;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: $lyj-space-md $lyj-space-lg;
  border-bottom: 2rpx solid $lyj-child-line;
  background: #f8fafc;
}
.modal-head-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
}
.modal-close-btn {
  min-height: 48rpx;
  line-height: 48rpx;
  background: transparent;
  color: $lyj-child-muted;
  font-size: $lyj-font-lg;
  padding: 0 16rpx;
  border: none;
}
.modal-body-scroll {
  flex: 1;
  max-height: calc(85vh - 100rpx);
  padding: $lyj-space-md;
  box-sizing: border-box;
}

.sections-grid {
  display: flex;
  flex-direction: column;
}

/* 电脑端宽屏自适应：只剩 2 个 section 后两列网格会把每张卡压成半宽长条，
   布局失衡 —— 大屏维持单列、限宽居中即可。 */
@media screen and (min-width: 768px) {
  .dash {
    max-width: 960px;
    margin: 0 auto;
    padding: 30rpx 32rpx 100rpx;
  }
}
</style>
