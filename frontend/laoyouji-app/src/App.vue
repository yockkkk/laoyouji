<script>
export default {
  onLaunch() {
    console.log('老友记 App Launch')
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
  font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

button {
  font-size: $lyj-font-md;
}

/* 通用大按钮。高度按硬指标给到 80px —— 原来是 96rpx（48px），不够。 */
.btn-main {
  min-height: $lyj-btn-main;
  border-radius: $lyj-radius;
  background: $lyj-primary;
  color: $lyj-text-on;
  font-size: $lyj-font-md;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.btn-main.disabled {
  background: $lyj-disabled;
}

.btn-ghost {
  min-height: $lyj-btn-main;
  border-radius: $lyj-radius;
  background: $lyj-card;
  color: $lyj-primary;
  border: 3rpx solid $lyj-primary;
  font-size: $lyj-font-md;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  padding: $lyj-space-lg;
  margin: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
}
</style>
