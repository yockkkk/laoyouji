<script>
import { initNative } from './utils/native'

export default {
  onLaunch() {
    console.log('康乐 App Launch')
    // 提醒层的唯一入口：注册通知点击回流 + 冷启动补课 + 已登录则同步一次闹钟。
    // 浏览器里没有 window.KangleNative，initNative 内部整体静默降级，不影响启动。
    initNative()
  },
}
</script>

<style lang="scss">
/**
 * 全局适老化基线。这里只放"没有别的地方可放"的东西：page 默认字号、
 * 原生 button 字号、两个通用按钮类、一个通用卡片类。
 * 具体页面的样子归各自的 scoped style，颜色字号一律取 uni.scss 的 token。
 */
@import './uni.scss';

page {
  background-color: $lyj-bg;
  font-size: $lyj-font-md; /* 20px 正文地板 */
  color: $lyj-text;
  font-family: 'Nunito', 'Rounded Mplus 1c', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

button {
  font-size: $lyj-font-md;
  touch-action: manipulation;
  min-height: 44px;
  min-width: 44px;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

button:active {
  transform: translateY(1px) scale(0.99);
}

button:focus-visible, input:focus-visible, textarea:focus-visible {
  outline: 4rpx solid $lyj-primary;
  outline-offset: 2rpx;
}

input, textarea {
  font-size: $lyj-font-sm; /* 18px >= 16px to prevent iOS auto-zoom */
}

.tabular-num, [tabular-nums] {
  font-variant-numeric: tabular-nums;
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}

/* 通用大按钮。高度按硬指标给到 80px —— 原来是 96rpx（48px），不够。 */
.btn-main {
  min-height: $lyj-btn-main;
  border-radius: $lyj-radius;
  background: $lyj-primary;
  color: $lyj-text-on;
  font-size: $lyj-font-md;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 8rpx 24rpx rgba(255, 107, 53, 0.25);
}

.btn-main:active {
  transform: scale(0.96);
  box-shadow: 0 4rpx 12rpx rgba(255, 107, 53, 0.2);
}

.btn-main.disabled {
  background: $lyj-disabled;
  box-shadow: none;
  transform: none;
}

.btn-ghost {
  min-height: $lyj-btn-main;
  border-radius: $lyj-radius;
  background: $lyj-card;
  color: $lyj-primary;
  border: 3rpx solid $lyj-primary;
  font-size: $lyj-font-md;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.btn-ghost:active {
  background: $lyj-primary-soft;
  transform: scale(0.96);
}

page, uni-page-body {
  height: 100%;
}

.card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  padding: $lyj-space-lg;
  margin: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.card:active {
  transform: translateY(2rpx);
  box-shadow: 0 4rpx 12rpx rgba(43, 45, 66, 0.04);
}

/* #ifdef H5 */
/* PC 桌面端宽屏自适应：统摄在 960px 舒适操作与阅读区，消除大面积空洞留白与背景撕裂 */
@media screen and (min-width: 768px) {
  body {
    background-color: #ede7de !important;
  }
  uni-app {
    max-width: 960px;
    margin: 0 auto;
    min-height: 100vh;
    position: relative;
    background-color: $lyj-bg;
    box-shadow: 0 0 30px rgba(0, 0, 0, 0.06);
  }
  uni-page-head {
    max-width: 960px;
    left: 0 !important;
    right: 0 !important;
    margin: 0 auto !important;
  }
  uni-tabbar,
  .uni-tabbar {
    max-width: 960px;
    left: 0 !important;
    right: 0 !important;
    margin: 0 auto !important;
  }
}
/* #endif */
</style>
