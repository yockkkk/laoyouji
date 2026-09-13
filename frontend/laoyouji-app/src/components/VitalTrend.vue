<template>
  <view class="vital-trend">
    <view class="trend-head">
      <text class="trend-label">{{ label }}</text>
      <text class="trend-tag" :class="trendClass">{{ trendText }}</text>
    </view>

    <view class="trend-body">
      <view class="bars">
        <view
          v-for="(p, i) in points"
          :key="i"
          class="bar-slot"
        >
          <view
            class="bar"
            :class="trendClass"
            :style="{ height: barHeight(p) }"
          ></view>
        </view>
      </view>
      <!-- 读数与走向各说一半：柱子给人"一眼看走势"，这行大字给人"到底多少"。 -->
      <view class="trend-readout">
        <text class="trend-value">{{ latestText }}</text>
        <text class="trend-normal">正常范围：{{ normal }}</text>
      </view>
    </view>
  </view>
</template>

<script>
/**
 * 一条指标的近 N 次走向。
 *
 * 刻意用 view 柱子而不是 canvas / SVG：这是个跨端（App + H5 兜底）的项目，
 * canvas 在两端的行为差异要单独调一遍，而"最近几次是升是降"这件事，柱子高度
 * 的比例就够读了 —— 要精确读数，右边那行大字就是这个用途。
 */
export default {
  name: 'VitalTrend',
  props: {
    label: { type: String, default: '' },
    unit: { type: String, default: '' },
    normal: { type: String, default: '' },
    trend: { type: String, default: '平稳' },
    // 每项形如 { value, display, measured_at, level }
    points: { type: Array, default: () => [] },
  },
  computed: {
    trendText() {
      if (this.trend === '上升') return '↑ 上升'
      if (this.trend === '下降') return '↓ 下降'
      return '→ 平稳'
    },
    // 上升用红、下降用蓝、平稳用绿 —— 都是既有语义色，不另造颜色。
    // 注意这里读的是"走向"不是"好坏"：血压降下来通常是好事，但下降仍是"在动"，
    // 用冷色只是把"变化"和"稳定"区分开，不替医生判断这个变化是好是坏。
    trendClass() {
      if (this.trend === '上升') return 'rising'
      if (this.trend === '下降') return 'falling'
      return 'steady'
    },
    latestText() {
      const last = this.points[this.points.length - 1]
      return last ? last.display : '—'
    },
    // 柱高按 points 内部的 min/max 归一化：看的是相对走向，不是绝对刻度。
    bounds() {
      const vals = this.points
        .map((p) => Number(p.value))
        .filter((v) => !Number.isNaN(v))
      if (!vals.length) return { min: 0, max: 0 }
      return { min: Math.min(...vals), max: Math.max(...vals) }
    },
  },
  methods: {
    barHeight(p) {
      const v = Number(p.value)
      if (Number.isNaN(v)) return '20%' // 这条没测到数，给个最矮的底座，不假装它有值
      const { min, max } = this.bounds
      // 只有一个点、或几次都测出同一个数：没有跨度可比，给个居中偏上的固定高度。
      // 若按 max===min 去算比例会除零，若给 0 高又会让"稳定"看起来像"没有数据"。
      if (max === min) return '60%'
      return 20 + 80 * ((v - min) / (max - min)) + '%'
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.vital-trend {
  background: $lyj-card;
  border: 2rpx solid $lyj-line;
  border-radius: $lyj-radius;
  padding: $lyj-space-md;
  margin-bottom: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
}
.trend-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.trend-label {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.trend-tag {
  font-size: $lyj-font-md;
  font-weight: 700;
  padding: 4rpx 16rpx;
  border-radius: $lyj-radius-pill;
  white-space: nowrap;
  word-break: keep-all;
  flex-shrink: 0;
}
.trend-tag.rising {
  color: $lyj-danger;
  background: $lyj-warn-bg;
}
.trend-tag.falling {
  color: $lyj-info;
  background: $lyj-info-bg;
}
.trend-tag.steady {
  color: $lyj-success;
  background: $lyj-success-bg;
}

.trend-body {
  display: flex;
  align-items: flex-end;
  gap: $lyj-space-md;
  margin-top: $lyj-space-md;
}
.bars {
  display: flex;
  align-items: flex-end;
  gap: $lyj-space-xs;
  flex: 1;
  /* 定高容器是柱高百分比成立的前提：柱子按容器高度算比例，容器自己不能由内容撑高。 */
  height: 220rpx;
}
.bar-slot {
  flex: 1;
  height: 100%;
  display: flex;
  align-items: flex-end;
}
.bar {
  width: 100%;
  border-radius: 8rpx;
  background: $lyj-success;
}
.bar.rising {
  background: $lyj-danger;
}
.bar.falling {
  background: $lyj-info;
}
.bar.steady {
  background: $lyj-success;
}

.trend-readout {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: $lyj-space-xs;
  min-width: 240rpx;
}
.trend-value {
  /* 这是这一行的主信息，按大字给 —— 老人要能一眼读到数。 */
  font-size: $lyj-font-xl;
  font-weight: 800;
  color: $lyj-text;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.trend-normal {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
</style>
