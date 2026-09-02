<template>
  <!--
    子女端顶部分段控件（看板 / 守护 / 隐私）。

    为什么子女端用它而不是底栏：子女的动线是"收到通知 → 看详情 → 按确认"，
    不是浏览 tab；而且 uni-app 的原生 tabBar 无法按角色切换、H5 端条目隐藏
    支持不全。三个视图互为平级根视图，所以切换用 reLaunch（栈里只该有一个），
    下钻详情才用 navigateTo —— 这样返回键永远回到"上一个有意义的地方"。
  -->
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
  { key: 'guardian', path: '/pages/child/guardian', label: '守护' },
  { key: 'privacy', path: '/pages/child/privacy', label: '隐私' },
]

export default {
  name: 'LyjSegment',
  props: {
    current: { type: String, default: 'dashboard' }, // dashboard | guardian | privacy
  },
  computed: {
    items() {
      return VIEWS
    },
  },
  methods: {
    go(item) {
      if (this.current === item.key) return
      // 平级视图之间切换：清栈，避免"看板→守护→看板"越按越深
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
