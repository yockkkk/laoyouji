<template>
  <view class="dash">
    <view class="head">
      <view class="head-info">
        <text class="title">家人看板</text>
        <text class="sub">{{ elderLine }}</text>
      </view>
      <button class="refresh" size="mini" @tap="loadAll">刷新</button>
    </view>

    <LyjSegment current="dashboard" />

    <!-- 隐私档位说明。看板"薄"往往不是坏了，而是老人只开放到这一档 —— 说清楚。 -->
    <view v-if="privacyNote" class="privacy-note">
      <text class="privacy-note-text">🔒 {{ privacyNote }}</text>
    </view>

    <!-- 响应式铺砌布局 -->
    <view class="sections-grid">
      <!-- 行程状态 -->
      <view class="section">
        <view class="section-head">
          <text class="section-title">🧭 出行行程</text>
        </view>
        <view v-if="!trips.length" class="empty-row"><text>暂无行程</text></view>
        <view v-for="t in trips" :key="t.id" class="trip-item" @tap="goGuardian(t)">
          <text class="trip-purpose">{{ t.purpose }}</text>
          <text class="trip-status" :class="t.status">{{ statusText(t.status) }}</text>
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
  </view>
</template>

<script>
import LyjSegment from '../../components/LyjSegment.vue'
import { get } from '../../api/client'
import { getCurrentUser } from '../../store/user'
import { publishPendingCount } from '../../store/pendingBadge'

/** 没绑定时后端会走提前返回、连 privacy 字段都不给 —— 前端的兜底必须是"全关"。 */
const DENIED = { location_level: 'off', health_level: 'off', bound: false }

export default {
  components: { LyjSegment },
  data() {
    return {
      user: null,
      trips: [],
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
    /**
     * 一次请求拿全部。
     * 原来这里额外拉了一遍 /confirmations?status=pending —— 而看板响应里的
     * pending_confirmations 就是同一个查询（routes_child.py:45 也传 status="pending"）。
     * 5 秒一轮的轮询里，那是白发一半的请求。
     */
    async loadAll(silent) {
      try {
        const d = await get(`/api/child/${this.user.id}/dashboard`)
        // 5s 轮询天然是"有新待审批"的最早发现者：角标与震动由它驱动，
        // 列表本身已搬去通知页（pendingBadge.js 头注有完整背景）。
        publishPendingCount((d.pending_confirmations || []).length)
        this.privacy = d.privacy || DENIED
        this.elderName = d.elder ? d.elder.name : ''
        this.elderCity = d.elder ? d.elder.city || '' : ''
        this.trips = d.trips || []
        this.medications = d.medications || []
        this.lastRefresh = this.fmtClock(new Date())
      } catch (e) {
        if (!silent) uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
    },


    /**
     * summary 档下后端把药名替换成了"老人未开放此项"（privacy.py 的 MASKED）。
     * 把它原样摆在药名位上会读成一条奇怪的药 —— 换成一句说得通的话。
     */
    drugLabel(m) {
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
