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

page, uni-page-body, body, view, text, button, input, textarea {
  font-family: $lyj-font-family !important;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

page, uni-page-body, body {
  background-color: $lyj-bg;
  font-size: $lyj-font-md; /* 20px 正文地板 */
  color: $lyj-text;
}

/* 全局防单字孤儿折行与标题挤压保护 */
.title,
.name,
.role-name,
.role-tag,
.feat-pill,
.btn-text,
.tab-text,
.badge,
.tag,
.quick-label,
.sec-text {
  white-space: nowrap !important;
  word-break: keep-all !important;
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

/* 通用大按钮 */
.btn-main {
  min-height: $lyj-btn-main;
  border-radius: $lyj-radius;
  background: linear-gradient(135deg, #2A82E4 0%, #1967C2 100%);
  color: $lyj-text-on;
  font-size: $lyj-font-md;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 8rpx 24rpx rgba(42, 130, 228, 0.28);
  letter-spacing: 1rpx;
}

.btn-main:active {
  transform: scale(0.97);
  background: linear-gradient(135deg, $lyj-primary-dark 0%, $lyj-primary 100%);
  box-shadow: 0 4rpx 12rpx rgba(42, 130, 228, 0.2);
}

.btn-main.disabled {
  background: $lyj-disabled;
  box-shadow: none;
  transform: none;
  color: #7A8E9F;
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
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.btn-ghost:active {
  background: $lyj-primary-soft;
  transform: scale(0.97);
}

page, uni-page-body {
  height: 100%;
}

.card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  padding: $lyj-space-lg;
  margin: $lyj-space-md;
  box-shadow: 0 8rpx 28rpx rgba(42, 130, 228, 0.08);
  border: 2rpx solid $lyj-line;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.card:active {
  transform: translateY(2rpx);
  box-shadow: 0 4rpx 12rpx rgba(42, 130, 228, 0.08);
}

/* #ifdef H5 */
/* PC 桌面端：真机沙盒模拟容器（430px 居中标准手机比例，外围清爽灰蓝底，真机 100% 满屏原生适配） */
@media screen and (min-width: 481px) {
  body {
    background-color: #E2EAF4 !important;
    background-image: radial-gradient(#CBDCEE 1px, transparent 1px);
    background-size: 20px 20px;
    margin: 0;
    padding: 0;
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
  }
  uni-app {
    max-width: 430px;
    width: 100%;
    height: 100vh;
    max-height: 920px;
    margin: 16px auto;
    position: relative;
    transform: translate(0, 0); /* 确立包含块 (Containing Block)，锁定 position: fixed 子元素于手机沙盒内 */
    background-color: $lyj-bg;
    box-shadow: 0 20px 60px rgba(19, 36, 56, 0.16), 0 0 0 8px #D0DFEE;
    border-radius: 36px;
    overflow: hidden;
  }
  uni-page-head {
    max-width: 430px !important;
    left: 0 !important;
    right: 0 !important;
    margin: 0 auto !important;
  }
  uni-tabbar,
  .uni-tabbar {
    max-width: 430px !important;
    left: 0 !important;
    right: 0 !important;
    margin: 0 auto !important;
    border-top: 1px solid #E1ECF7 !important;
  }
}

/* 移动端真机 (<= 480px)：100% 满屏无缝贴合与安全区适配 */
@media screen and (max-width: 480px) {
  body {
    background-color: $lyj-bg;
    margin: 0;
    padding: 0;
  }
  uni-app {
    width: 100% !important;
    max-width: 100% !important;
    height: 100% !important;
    margin: 0 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
  }
  uni-page-head {
    max-width: 100% !important;
  }
  uni-tabbar,
  .uni-tabbar {
    max-width: 100% !important;
    padding-bottom: constant(safe-area-inset-bottom);
    padding-bottom: env(safe-area-inset-bottom);
  }
}
/* #endif */

/* 全局安全区工具类 */
.safe-area-bottom {
  padding-bottom: constant(safe-area-inset-bottom);
  padding-bottom: env(safe-area-inset-bottom);
}
</style>
