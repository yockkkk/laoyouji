<template>
  <view class="detail">
    <LyjBack />
    <view v-if="task" class="detail-card">
      <!-- 大白话确认卡 -->
      <view class="head">
        <text class="head-icon">{{ icon }}</text>
        <text class="head-title">{{ card.title }}</text>
      </view>
      <text class="summary">{{ card.summary }}</text>
      <view class="meta">
        <view class="meta-row">
          <text class="meta-key">原因</text>
          <text class="meta-val">{{ card.reason }}</text>
        </view>
        <view class="meta-row">
          <text class="meta-key">金额</text>
          <text class="meta-val amount">¥ {{ task.amount || 0 }}</text>
        </view>
        <view class="meta-row">
          <text class="meta-key">发起人</text>
          <text class="meta-val">{{ card.relation || '家人' }}为老人办的事</text>
        </view>
        <view class="meta-row">
          <text class="meta-key">状态</text>
          <text class="meta-val">{{ statusText }}</text>
        </view>
        <view class="meta-row">
          <text class="meta-key">操作参数</text>
          <text class="meta-val mono">{{ argsText }}</text>
        </view>
        <view class="meta-row">
          <text class="meta-key">有效期至</text>
          <text class="meta-val">{{ fmtTime(task.expires_at) }}</text>
        </view>
      </view>

      <!-- 参数是挂起那一刻冻结下来的，同意就按这份原样重放；改一个字都会被拒。 -->
      <text class="frozen-note">
        上面这份参数在拦截时已冻结。同意后系统按它原样执行，中途被改过就会被拒绝。
      </text>

      <view v-if="task.status === 'pending'" class="actions">
        <button class="btn-reject" :disabled="busy" @tap="reject">拒绝</button>
        <button class="btn-approve" :disabled="busy" @tap="approve">同意</button>
      </view>
      <view v-else class="result-bar">
        <text :class="['result-text', task.status]">{{ resultText }}</text>
      </view>

      <view v-if="announce" class="announce">
        <text class="announce-label">办理结果（已同步给老人）：</text>
        <text class="announce-text">{{ announce }}</text>
      </view>
    </view>

    <view v-else class="loading">
      <text>{{ loaded ? '没有找到这条确认事项' : '加载中…' }}</text>
    </view>
  </view>
</template>

<script>
import { get, post } from '../../api/client'
import { getCurrentUser } from '../../store/user'

const ICONS = {
  // 只留在册工具（现役 22 个）。book_ticket / book_hotel / order_service 已随
  // 产品收敛删掉，留着图标等于给不存在的工具留门。
  // 这一页服务的是**金融高危动作的确认**（risk_rules.HIGH_RISK_TOOLS = {"pay"}），
  // 不是就医审批 —— 挂号在 NON_PAYMENT_TOOLS 里，当场办好、只发知会。
  register_appointment: '🏥',
  pay: '💸',
}

const RESULTS = {
  executed: '✅ 已同意并办理完成',
  rejected: '🚫 已拒绝',
  expired: '⌛ 已超时失效',
  failed: '⚠️ 已同意，但执行没成功',
}

const STATUS = {
  pending: '待确认',
  approved: '已同意',
  executed: '已办理',
  rejected: '已拒绝',
  expired: '已过期',
  failed: '执行失败',
}

export default {
  data() {
    return { task: null, announce: '', busy: false, loaded: false, childId: '' }
  },
  computed: {
    card() {
      return (this.task && this.task.summary_for_child) || {}
    },
    icon() {
      return ICONS[this.task ? this.task.tool_name : ''] || '📋'
    },
    statusText() {
      const s = this.task ? this.task.status : ''
      return STATUS[s] || s
    },
    resultText() {
      const s = this.task ? this.task.status : ''
      return RESULTS[s] || this.statusText
    },
    /** 模板里不用 JSON.* —— 小程序端的模板表达式拿不到宿主全局对象。 */
    argsText() {
      try {
        return JSON.stringify((this.task && this.task.tool_args) || {})
      } catch (e) {
        return '（参数无法显示）'
      }
    },
  },
  onLoad(opts) {
    const user = getCurrentUser()
    this.childId = (opts && opts.child_id) || (user ? user.id : '')
    this.taskId = (opts && opts.id) || ''
    if (!this.childId) {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.load()
  },
  methods: {
    /**
     * 不带 status 就是全部状态（routes_confirm.py:13 的 status 是可选的），
     * 所以一次就够 —— 原来这里连着发了两个**完全一样**的请求当"兜底"。
     */
    async load() {
      try {
        const d = await get(`/api/child/${this.childId}/confirmations`)
        this.task = (d.items || []).find((t) => t.id === this.taskId) || null
      } catch (e) {
        uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
      this.loaded = true
    },
    async approve() {
      if (this.busy) return
      this.busy = true
      uni.showLoading({ title: '正在办理…' })
      try {
        // 带上 child_id：审计日志的 actor 就是按下这一下的人（routes_confirm.py:22）
        const r = await post(`/api/confirmations/${this.taskId}/approve${this._q()}`)
        this.announce = (r.result && (r.result.announce || r.result.summary)) || '已办理'
        await this.load()
        uni.hideLoading()
        uni.showToast({ title: r.ok ? '已同意并办理' : '已同意，执行未成功', icon: 'none' })
      } catch (e) {
        uni.hideLoading()
        uni.showModal({ title: '办理失败', content: e.message, showCancel: false })
        this.load()
      }
      this.busy = false
    },
    async reject() {
      if (this.busy) return
      const confirmed = await new Promise((res) =>
        uni.showModal({
          title: '确认拒绝？',
          content: '拒绝后老人端会收到温和的提示',
          success: (r) => res(r.confirm),
        }),
      )
      if (!confirmed) return
      this.busy = true
      try {
        await post(`/api/confirmations/${this.taskId}/reject${this._q()}`)
        await this.load()
        uni.showToast({ title: '已拒绝', icon: 'success' })
      } catch (e) {
        uni.showModal({ title: '操作失败', content: e.message, showCancel: false })
        this.load()
      }
      this.busy = false
    },
    _q() {
      return `?child_id=${encodeURIComponent(this.childId)}`
    },
    fmtTime(iso) {
      if (!iso) return ''
      const d = new Date(iso)
      if (!Number.isFinite(d.getTime())) return ''
      const pad = (n) => String(n).padStart(2, '0')
      return `${d.getMonth() + 1}/${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.detail {
  min-height: 100vh;
  background: $lyj-child-bg;
  padding: $lyj-space-md;
  box-sizing: border-box;
}
.detail-card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  padding: $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
}
.head {
  display: flex;
  align-items: center;
  gap: $lyj-space-sm;
  padding-bottom: $lyj-space-md;
  border-bottom: 2rpx solid $lyj-child-line;
}
.head-icon {
  font-size: 60rpx;
}
.head-title {
  flex: 1;
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-child-text;
  line-height: $lyj-line-height;
}
.summary {
  display: block;
  font-size: $lyj-font-md;
  color: $lyj-text;
  line-height: $lyj-line-height;
  padding: $lyj-space-md 0;
}
.meta {
  background: $lyj-child-line;
  border-radius: $lyj-radius;
  padding: $lyj-space-xs $lyj-space-md;
}
.meta-row {
  display: flex;
  padding: $lyj-space-sm 0;
  gap: $lyj-space-md;
  border-bottom: 2rpx dashed $lyj-card;
}
.meta-row:last-child {
  border-bottom: none;
}
.meta-key {
  width: 160rpx;
  flex-shrink: 0;
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
}
.meta-val {
  flex: 1;
  font-size: $lyj-font-sm;
  color: $lyj-child-text;
  line-height: $lyj-line-height;
  word-break: break-all;
}
.meta-val.amount {
  font-size: $lyj-font-md;
  font-weight: 800;
  color: $lyj-danger;
}
.meta-val.mono {
  color: $lyj-child-body;
}
.frozen-note {
  display: block;
  margin-top: $lyj-space-sm;
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
  line-height: $lyj-line-height;
}
.actions {
  display: flex;
  gap: $lyj-space-md;
  margin-top: $lyj-space-lg;
}
/* 全项目最有后果的两个按钮 —— 按主按钮高度给，不缩水 */
.btn-approve,
.btn-reject {
  flex: 1;
  height: $lyj-btn-main;
  line-height: $lyj-btn-main;
  font-size: $lyj-font-md;
  font-weight: 700;
  border-radius: $lyj-radius;
  padding: 0;
  margin: 0;
}
.btn-approve {
  background: $lyj-success;
  color: $lyj-text-on;
}
.btn-reject {
  background: $lyj-card;
  color: $lyj-danger;
  border: 3rpx solid $lyj-danger;
}
.btn-approve[disabled],
.btn-reject[disabled] {
  opacity: 0.5;
}
.result-bar {
  margin-top: $lyj-space-lg;
  text-align: center;
}
.result-text {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
}
.result-text.executed {
  color: $lyj-success;
}
.result-text.rejected {
  color: $lyj-danger;
}
.result-text.failed {
  color: $lyj-danger;
}
.result-text.expired {
  color: $lyj-warn-text;
}
.announce {
  margin-top: $lyj-space-md;
  background: $lyj-success-bg;
  border-radius: $lyj-radius;
  padding: $lyj-space-md;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.announce-label {
  font-size: $lyj-font-sm;
  color: $lyj-success;
}
.announce-text {
  font-size: $lyj-font-md;
  color: $lyj-text;
  line-height: $lyj-line-height;
}
.loading {
  text-align: center;
  padding: 120rpx 0;
}
.loading text {
  color: $lyj-child-muted;
  font-size: $lyj-font-md;
}
</style>
