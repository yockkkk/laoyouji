<template>
  <!--
    确定性交付物卡片 —— 吃 plan_builder 的 typed 输出。

    旧版的 card.body 是扁平 {k: v} 字典，模板直接 v-for 铺开。两个后果：
    页序不存在（"五页"在组件里根本不是一个概念），而且子 Agent 没填上的字段
    不会成为 key、于是静静消失 —— 而要求是显式渲染"待补"，绝不编造。

    现在缺失是一个**字段**（missing: true）而不是一个**缺席**，所以它占一行、
    看得见、还能被计数。
  -->
  <view class="card-wrap" :class="{ compact }">
    <view class="card-head">
      <text class="card-title">{{ title }}</text>
      <text v-if="!complete && missingCount" class="card-todo">
        还有 {{ missingCount }} 项待补
      </text>
    </view>

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

    <!-- 朗读入口。后端的 announce 通道不会随 card 事件下来（card 事件只带卡片本身），
         所以这里默认**把卡上写的念出来** —— 包括脚注里的免责声明。 -->
    <view v-if="speech" class="replay" @tap="replay">
      <text class="replay-icon">🔊</text>
      <text class="replay-text">念给我听</text>
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
  },
  computed: {
    missingCount() {
      return this.sections.reduce(
        (n, s) => n + (s.rows || []).filter((r) => r.missing).length,
        0,
      )
    },
    /**
     * 念给老人听的那段话。
     *
     * 为什么要在前端拼：后端把 R4 免责声明注进的是工具结果的 summary / announce
     * 两个字段，而 `card` 事件推的只是卡片本身（session.py 只 emit
     * result["card"]）—— announce 根本到不了这里。卡上写着的（含脚注里的免责
     * 声明）就是唯一可靠的信源，所以念卡面，不念一个不存在的字段。
     *
     * 待补的行照念"待补"：听的人也有权知道哪一项还没定下来。
     */
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
  padding: $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
}
.card-wrap.compact {
  padding: $lyj-space-md;
}
.card-head {
  margin-bottom: $lyj-space-md;
  padding-bottom: $lyj-space-sm;
  border-bottom: 2rpx solid $lyj-line;
}
.card-title {
  display: block;
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-text;
  line-height: $lyj-line-height;
}
.card-todo {
  display: block;
  margin-top: $lyj-space-xs;
  font-size: $lyj-font-sm;
  color: $lyj-warn-text;
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
