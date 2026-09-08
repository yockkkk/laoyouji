<template>
  <!--
    确定性交付物卡片 —— 吃 plan_builder 的 typed 输出。

    旧版的 card.body 是扁平 {k: v} 字典，模板直接 v-for 铺开。两个后果：
    页序不存在（"五页"在组件里根本不是一个概念），而且子 Agent 没填上的字段
    不会成为 key、于是静静消失 —— 而要求是显式渲染"待补"，绝不编造。

    现在缺失是一个**字段**（missing: true）而不是一个**缺席**，所以它占一行、
    看得见、还能被计数。
  -->
  <view class="card-wrap" :class="[{ compact }, { 'is-expanded': isExpanded }]">
    <view class="card-head" @tap="toggleExpand">
      <view class="card-head-left">
        <text class="card-title">{{ title }}</text>
        <view class="card-badges">
          <text v-if="sections && sections.length" class="page-badge">
            共 {{ sections.length }} 页
          </text>
          <text v-if="!complete && missingCount" class="card-todo">
            {{ missingCount }} 项待补
          </text>
          <text v-else class="card-ready">
            规划就绪
          </text>
        </view>
      </view>

      <view class="card-head-right">
        <view class="plan-toggle-btn" :class="{ open: isExpanded }">
          <text class="toggle-text">{{ isExpanded ? '收起' : '查看完整计划书' }}</text>
          <text class="toggle-arrow">{{ isExpanded ? '▲' : '▼' }}</text>
        </view>
      </view>
    </view>

    <!-- 可展开的完整计划书各页 -->
    <view v-show="isExpanded" class="card-body">
      <view v-for="(section, si) in sections" :key="si" class="section">
        <text v-if="!compact && section.heading" class="section-heading">
          {{ section.heading }}
        </text>
        <view v-for="(row, ri) in section.rows" :key="ri" class="row">
          <text class="key">{{ row.label }}</text>
          <text class="val" :class="{ missing: row.missing }">
            {{ row.missing ? '待补' : row.value }}
          </text>
        </view>
        <!-- 页内叮嘱属于这一页，不能被抽到卡片末尾去 -->
        <text
          v-for="(note, ni) in section.notes || []"
          :key="'n' + ni"
          class="section-note"
        >
          {{ note }}
        </text>
      </view>

      <view v-if="notes && notes.length" class="card-foot">
        <text v-for="(note, ni) in notes" :key="ni" class="footnote">{{ note }}</text>
      </view>

      <!-- 朗读入口 -->
      <view v-if="speech" class="replay" @tap.stop="replay">
        <text class="replay-icon">🔊</text>
        <text class="replay-text">念给我听</text>
      </view>
    </view>
  </view>
</template>

<script>
import { speak } from '../api/asr'

export default {
  name: 'PlanCard',
  props: {
    title: { type: String, default: '' },
    // [{ heading: String, rows: [{ label, value, missing }], notes: [String] }]
    sections: { type: Array, default: () => [] },
    notes: { type: Array, default: () => [] },
    complete: { type: Boolean, default: true },
    // 紧凑模式：两张轻量卡片（用药与复查安排 / 社区服务预约单）共用本组件
    compact: { type: Boolean, default: false },
    // 朗读文本的**覆盖**位。留空则由 speech 从卡面内容自己拼。
    announce: { type: String, default: '' },
    defaultExpanded: { type: Boolean, default: false },
  },
  data() {
    return {
      isExpanded: this.defaultExpanded,
    }
  },
  computed: {
    missingCount() {
      return this.sections.reduce(
        (n, s) => n + (s.rows || []).filter((r) => r.missing).length,
        0,
      )
    },
    speech() {
      if (this.announce) return this.announce
      const parts = this.title ? [this.title] : []
      for (const s of this.sections) {
        if (s.heading) parts.push(s.heading)
        for (const r of s.rows || []) {
          parts.push(`${r.label}：${r.missing ? '待补' : r.value}`)
        }
        for (const n of s.notes || []) parts.push(n)
      }
      for (const n of this.notes || []) parts.push(n)
      return parts.join('。')
    },
  },
  methods: {
    toggleExpand() {
      this.isExpanded = !this.isExpanded
    },
    replay() {
      const ok = speak(this.speech)
      if (!ok) uni.showToast({ title: '当前设备不支持语音播报', icon: 'none' })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.card-wrap {
  background: $lyj-card;
  border: 2rpx solid $lyj-line;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
  transition: all 0.2s ease;
}
.card-wrap.compact {
  padding: $lyj-space-md;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  min-height: 72rpx;
}
.card-wrap.is-expanded .card-head {
  margin-bottom: $lyj-space-md;
  padding-bottom: $lyj-space-sm;
  border-bottom: 2rpx solid $lyj-line;
}
.card-head-left {
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  min-width: 0;
  flex: 1;
}
.card-title {
  display: block;
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-text;
  line-height: $lyj-line-height;
}
.card-badges {
  display: flex;
  align-items: center;
  gap: 12rpx;
}
.page-badge {
  font-size: $lyj-font-xs;
  padding: 2rpx 14rpx;
  border-radius: 999rpx;
  background: #eff6ff;
  color: #2563eb;
  font-weight: 600;
}
.card-todo {
  font-size: $lyj-font-xs;
  color: $lyj-warn-text;
  font-weight: 600;
}
.card-ready {
  font-size: $lyj-font-xs;
  color: $lyj-success;
  font-weight: 600;
}
.card-head-right {
  flex-shrink: 0;
  margin-left: 16rpx;
}
.plan-toggle-btn {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 8rpx 18rpx;
  border-radius: $lyj-radius-pill;
  background: #f1f5f9;
  color: $lyj-primary;
  font-size: $lyj-font-xs;
  font-weight: 600;
}
.plan-toggle-btn.open {
  background: $lyj-primary-soft;
}
.toggle-arrow {
  font-size: 20rpx;
}
.card-body {
  animation: fadeIn 0.25s ease;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-6rpx); }
  to { opacity: 1; transform: translateY(0); }
}
.section {
  margin-bottom: $lyj-space-md;
}
.section-heading {
  display: block;
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-primary;
  margin: $lyj-space-sm 0;
}
.section-note {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  line-height: $lyj-line-height;
  margin-top: $lyj-space-xs;
}
.row {
  display: flex;
  padding: $lyj-space-xs 0;
  gap: $lyj-space-sm;
}
.key {
  width: 180rpx;
  flex-shrink: 0;
  font-size: $lyj-font-md;
  color: $lyj-text-light;
}
.val {
  flex: 1;
  font-size: $lyj-font-md;
  color: $lyj-text;
  line-height: $lyj-line-height;
}
/* 待补：看得见，但不假装是内容 */
.val.missing {
  color: $lyj-text-light;
  font-style: italic;
}
.card-foot {
  margin-top: $lyj-space-sm;
  padding-top: $lyj-space-sm;
  border-top: 2rpx solid $lyj-line;
}
.footnote {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  line-height: $lyj-line-height;
}
.replay {
  margin-top: $lyj-space-md;
  height: $lyj-hit-min;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: $lyj-space-xs;
  background: $lyj-primary-soft;
  border-radius: $lyj-radius-pill;
}
.replay-icon {
  font-size: $lyj-font-md;
}
.replay-text {
  font-size: $lyj-font-md;
  color: $lyj-primary;
  font-weight: 700;
}
</style>
