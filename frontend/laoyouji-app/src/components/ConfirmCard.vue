<template>
  <!--
    挂起提示卡：高危操作已发家人确认。
    主标题与状态常驻显现，具体内容默认折叠，提供清晰的展开/收起交互，避免冗余拉长对话排版。
  -->
  <view class="suspend-card" :class="['s-' + status, { 'is-expanded': isExpanded }]">
    <view class="head" @tap="toggleExpand">
      <view class="head-left">
        <text class="icon">{{ head.icon }}</text>
        <view class="title-group">
          <text class="title">{{ head.title }}</text>
          <text v-if="summary && !isExpanded" class="brief-summary">{{ summary }}</text>
        </view>
        <text v-if="amount && !isExpanded" class="amount-badge">¥{{ amount }}</text>
      </view>
      <view class="head-right">
        <text class="status-tag" :class="status">{{ statusBadgeText }}</text>
        <view class="toggle-btn" :class="{ open: isExpanded }">
          <text class="toggle-text">{{ isExpanded ? '收起' : '详情' }}</text>
          <text class="toggle-arrow">{{ isExpanded ? '▲' : '▼' }}</text>
        </view>
      </view>
    </view>

    <!-- 可展开的具体内容 -->
    <view v-show="isExpanded" class="card-body">
      <text class="desc">{{ message }}</text>

      <view class="meta">
        <text v-if="summary" class="fact">{{ summary }}</text>
        <text v-if="amount" class="amount">金额：{{ amount }} 元</text>
        <text class="waiting">{{ head.foot }}</text>
        <text v-if="status === 'pending' && validMinutes" class="expire">
          {{ validMinutes }} 分钟内有效
        </text>
      </view>
    </view>
  </view>
</template>

<script>
/**
 * 四态文案。**"家人不同意"和"家人同意了但没办成"是两件不同的事**，
 * 后端 confirmation_resolved 的 status 把它们分开发过来（executed /
 * rejected / failed），这里就不许合成一句"没成功" —— 那会让老人以为
 * 家人拒绝了他，而实际上家人点了同意。
 */
const HEADS = {
  pending: {
    icon: '✋',
    title: '这一步要家人点头',
    foot: '⏳ 已经发给家人，等他点同意',
  },
  executed: {
    icon: '✅',
    title: '家人同意了，已经办好',
    foot: '✅ 这一步不用再等了',
  },
  rejected: {
    icon: '🚫',
    title: '家人这次先不办',
    foot: '🚫 家人没同意。有疑问给他打个电话商量商量',
  },
  failed: {
    icon: '⚠️',
    title: '家人同意了，但这步没办成',
    foot: '⚠️ 家人已同意，是办的时候出了问题。我再试试',
  },
}

export default {
  name: 'ConfirmCard',
  props: {
    message: { type: String, default: '已经发给家人确认啦' }, // 老人看的那句话
    summary: { type: String, default: '' }, // 事实摘要（车次/项目）
    amount: { type: Number, default: 0 },
    expiresAt: { type: String, default: '' }, // ISO 时间串
    status: { type: String, default: 'pending' },
    defaultExpanded: { type: Boolean, default: false },
  },
  data() {
    return {
      isExpanded: this.defaultExpanded,
    }
  },
  computed: {
    head() {
      return HEADS[this.status] || HEADS.pending
    },
    statusBadgeText() {
      const map = {
        pending: '待确认',
        executed: '已执行',
        rejected: '已拒绝',
        failed: '执行失败',
      }
      return map[this.status] || '待确认'
    },
    validMinutes() {
      if (!this.expiresAt) return 0
      const left = new Date(this.expiresAt).getTime() - Date.now()
      if (!Number.isFinite(left) || left <= 0) return 0
      return Math.ceil(left / 60000)
    },
  },
  methods: {
    toggleExpand() {
      this.isExpanded = !this.isExpanded
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.suspend-card {
  background: $lyj-warn-bg;
  border: 3rpx solid $lyj-warn;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md $lyj-space-lg;
  transition: all 0.2s ease;
}

.s-executed {
  background: $lyj-success-bg;
  border-color: $lyj-success;
  .title,
  .waiting {
    color: $lyj-success;
  }
}
.s-rejected {
  background: $lyj-muted-bg;
  border-color: $lyj-line;
  .title,
  .waiting {
    color: $lyj-text-light;
  }
}
.s-failed {
  border-color: $lyj-danger;
  .title,
  .waiting {
    color: $lyj-danger;
  }
}

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 72rpx;
  cursor: pointer;
}

.head-left {
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
  flex: 1;
  min-width: 0;
}

.title-group {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.icon {
  font-size: $lyj-font-lg;
  flex-shrink: 0;
}

.title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-warn-text;
  white-space: nowrap;
}

.brief-summary {
  font-size: $lyj-font-xs;
  color: $lyj-text-light;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 320rpx;
}

.amount-badge {
  font-size: $lyj-font-xs;
  font-weight: 700;
  color: #dc2626;
  background: #fee2e2;
  padding: 2rpx 12rpx;
  border-radius: 999rpx;
  margin-left: 8rpx;
  flex-shrink: 0;
}

.head-right {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-shrink: 0;
  margin-left: 12rpx;
}

.status-tag {
  font-size: $lyj-font-xs;
  padding: 4rpx 16rpx;
  border-radius: $lyj-radius-pill;
  font-weight: 600;
}
.status-tag.pending {
  background: #fef3c7;
  color: #b45309;
}
.status-tag.executed {
  background: #dcfce7;
  color: #15803d;
}
.status-tag.rejected {
  background: #f1f5f9;
  color: #64748b;
}
.status-tag.failed {
  background: #fee2e2;
  color: #b91c1c;
}

.toggle-btn {
  display: flex;
  align-items: center;
  gap: 4rpx;
  padding: 6rpx 14rpx;
  border-radius: 8rpx;
  background: rgba(0, 0, 0, 0.04);
  color: $lyj-text-light;
  font-size: $lyj-font-xs;
}

.toggle-arrow {
  font-size: 18rpx;
}

.card-body {
  margin-top: $lyj-space-sm;
  padding-top: $lyj-space-sm;
  border-top: 1rpx dashed rgba(0, 0, 0, 0.08);
}

.desc {
  display: block;
  font-size: $lyj-font-md;
  color: $lyj-text;
  line-height: $lyj-line-height;
}

.meta {
  margin-top: $lyj-space-sm;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}

.fact {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}

.amount {
  font-size: $lyj-font-md;
  color: $lyj-danger;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.waiting {
  font-size: $lyj-font-sm;
  color: $lyj-warn-text;
}

.expire {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  font-variant-numeric: tabular-nums;
}
</style>
