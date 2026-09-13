<template>
  <view class="segment">
    <view
      v-for="item in items"
      :key="item.key"
      class="seg-item"
      :class="{ active: current === item.key }"
      @tap="go(item)"
    >
      <text class="seg-text">{{ item.label }}</text>
      <text
        v-if="item.key === 'notification' && pendingCount"
        class="seg-badge"
      >{{ pendingCount > 99 ? '99+' : pendingCount }}</text>
    </view>
  </view>
</template>

<script>
import { PENDING_EVENT, readPendingCount } from '../store/pendingBadge'

const VIEWS = [
  { key: 'dashboard', path: '/pages/child/dashboard', label: '看板' },
  { key: 'family', path: '/pages/child/family', label: '家人' },
  { key: 'notification', path: '/pages/child/notification', label: '通知' },
  { key: 'guardian', path: '/pages/child/guardian', label: '守护' },
  { key: 'privacy', path: '/pages/child/privacy', label: '隐私' },
]

export default {
  name: 'LyjSegment',
  props: {
    current: { type: String, default: 'dashboard' }, // dashboard | family | guardian | privacy
  },
  data() {
    return { pendingCount: 0, _onPending: null }
  },
  created() {
    this.pendingCount = readPendingCount()
    this._onPending = (n) => {
      this.pendingCount = Number(n) || 0
    }
    uni.$on(PENDING_EVENT, this._onPending)
  },
  beforeUnmount() {
    if (this._onPending) uni.$off(PENDING_EVENT, this._onPending)
  },
  computed: {
    items() {
      return VIEWS
    },
  },
  methods: {
    go(item) {
      if (this.current === item.key) return
      uni.redirectTo({ url: item.path })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.segment {
  display: flex;
  margin: $lyj-space-md;
  padding: $lyj-space-xs;
  background: $lyj-line;
  border-radius: $lyj-radius-pill;
}
.seg-item {
  flex: 1;
  height: $lyj-hit-min;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: $lyj-radius-pill;
  position: relative;
}
/* 未读角标：有新的高危操作待审批时顶在"通知"项右上角。
   老人端硬指标（字号地板）不约束这个徽标 —— 它不承载正文信息，
   与正文并列的还有"通知"两个字。 */
.seg-badge {
  position: absolute;
  top: 4rpx;
  right: 12rpx;
  min-width: 32rpx;
  height: 32rpx;
  line-height: 32rpx;
  padding: 0 8rpx;
  border-radius: $lyj-radius-pill;
  background: $lyj-danger;
  color: $lyj-text-on;
  font-size: $lyj-font-nav;
  font-weight: 700;
  text-align: center;
  box-sizing: border-box;
}
.seg-item.active {
  background: $lyj-primary-soft;
}
.seg-text {
  font-size: $lyj-font-md;
  color: $lyj-text-light;
  white-space: nowrap !important;
  word-break: keep-all !important;
}
.seg-item.active .seg-text {
  color: $lyj-primary;
  font-weight: 700;
}
</style>
