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
    </view>
  </view>
</template>

<script>
const VIEWS = [
  { key: 'dashboard', path: '/pages/child/dashboard', label: '看板' },
  { key: 'family', path: '/pages/child/family', label: '家人' },
  { key: 'guardian', path: '/pages/child/guardian', label: '守护' },
  { key: 'privacy', path: '/pages/child/privacy', label: '隐私' },
]

export default {
  name: 'LyjSegment',
  props: {
    current: { type: String, default: 'dashboard' }, // dashboard | family | guardian | privacy
  },
  computed: {
    items() {
      return VIEWS
    },
  },
  methods: {
    go(item) {
      if (this.current === item.key) return
      uni.reLaunch({ url: item.path })
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
}
.seg-item.active {
  background: $lyj-primary-soft;
}
.seg-text {
  font-size: $lyj-font-md;
  color: $lyj-text-light;
}
.seg-item.active .seg-text {
  color: $lyj-primary;
  font-weight: 700;
}
</style>
