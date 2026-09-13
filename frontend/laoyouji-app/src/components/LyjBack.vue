<template>
  <!--
    顶部返回箭头（全局注册，非根页顶部用）：
    navigateBack 优先 —— 有栈就回上一屏（下钻详情页）；无栈（tab / redirectTo 换入的
    页面）回退到本角色首页：老人→首页 tab，子女→家人看板。老人/子女共用一颗按钮，
    不用每页写不同的跳转目标。
  -->
  <view class="lyj-back" :hover-class="hover ? 'pressed' : ''" @tap="goBack">
    <text class="arrow">‹</text>
    <text class="label">{{ label }}</text>
  </view>
</template>

<script>
import { getCurrentUser } from '../store/user'

export default {
  name: 'LyjBack',
  props: {
    label: { type: String, default: '返回' },
    hover: { type: Boolean, default: true },
  },
  methods: {
    goBack() {
      uni.navigateBack({
        fail: () => {
          // 无栈可退（tab / redirectTo）→ 回本角色首页
          const u = getCurrentUser()
          const url =
            u && u.role === 'child' ? '/pages/child/dashboard' : '/pages/elder/home'
          uni.reLaunch({ url })
        },
      })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.lyj-back {
  display: inline-flex;
  align-items: center;
  gap: $lyj-space-xs;
  margin: $lyj-space-xs $lyj-space-md 0;
  padding: 10rpx 22rpx 10rpx 18rpx;
  border-radius: $lyj-radius-pill;
  background: rgba(42, 130, 228, 0.08);
  color: $lyj-text-light;
  align-self: flex-start;
}
.lyj-back.pressed {
  background: rgba(42, 130, 228, 0.18);
}
.arrow {
  font-size: 52rpx;
  line-height: 0.8;
}
.label {
  font-size: 26rpx;
}
</style>
