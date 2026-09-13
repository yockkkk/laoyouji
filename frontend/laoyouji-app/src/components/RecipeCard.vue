<template>
  <!--
    菜谱卡（康乐右翼·饮食）：家常做法，不是营养处方。

    R4 的落点是卡脚那句 `note`（免责声明）：它**不折叠、不被 v-if 摘掉**。
    一张卡片上唯一不能省的东西就是它 —— 老人照着做出偏差时，得有句话提醒他
    "这不能替代医生"。所以别的都可以紧凑，这一行必须常驻。

    版式按"边看边做"来排：要准备的东西一行一项（前置 · ），怎么做用序号带大字，
    两步之间留够空。老人是站在灶台边上看这行字的，不是坐在沙发上读文章。
  -->
  <view class="recipe-card">
    <text class="card-title">{{ title }}</text>

    <view class="pills">
      <text v-if="minutes" class="pill time">{{ minutes }} 分钟</text>
      <text v-for="(tag, i) in tags" :key="i" class="pill">{{ tag }}</text>
    </view>

    <view v-if="ingredients && ingredients.length" class="block">
      <text class="block-head">要准备</text>
      <text v-for="(ing, i) in ingredients" :key="i" class="ingredient">· {{ ing }}</text>
    </view>

    <view v-if="steps && steps.length" class="block">
      <text class="block-head">怎么做</text>
      <view v-for="(step, i) in steps" :key="i" class="step">
        <text class="step-no">{{ i + 1 }}</text>
        <text class="step-text">{{ step }}</text>
      </view>
    </view>

    <view v-if="tips && tips.length" class="block">
      <text v-for="(tip, i) in tips" :key="i" class="tip">{{ tip }}</text>
    </view>

    <!-- R4：免责声明常驻卡脚，不折叠 -->
    <text v-if="note" class="disclaimer">{{ note }}</text>

    <view v-if="speech" class="replay" @tap.stop="replay">
      <text class="replay-icon">🔊</text>
      <text class="replay-text">念给我听</text>
    </view>
  </view>
</template>

<script>
import { speak } from '../api/asr'

export default {
  name: 'RecipeCard',
  props: {
    title: { type: String, default: '' },
    dish: { type: String, default: '' },
    minutes: { type: Number, default: 0 },
    tags: { type: Array, default: () => [] },
    ingredients: { type: Array, default: () => [] },
    steps: { type: Array, default: () => [] },
    tips: { type: Array, default: () => [] },
    note: { type: String, default: '' }, // 免责声明，由后端拼好，前端原样显示
    announce: { type: String, default: '' },
  },
  computed: {
    /**
     * 朗读文本从卡面内容自己拼（同 PlanCard 的做法）。
     * 免责声明**必须念进去**：语音是这张卡的另一半出口，
     * 屏幕上带着声明、耳朵里没有，等于没有。
     */
    speech() {
      const parts = this.title ? [this.title] : []
      if (this.ingredients.length) {
        parts.push('要准备：' + this.ingredients.join('，'))
      }
      this.steps.forEach((s, i) => parts.push(`第 ${i + 1} 步：${s}`))
      for (const t of this.tips) parts.push(t)
      if (this.note) parts.push(this.note)
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

.recipe-card {
  background: $lyj-card;
  border: 2rpx solid $lyj-line;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
}

.card-title {
  display: block;
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-text;
  line-height: $lyj-line-height;
}

.pills {
  display: flex;
  flex-wrap: wrap;
  gap: $lyj-space-xs;
  margin-top: $lyj-space-sm;
}

.pill {
  font-size: $lyj-font-sm;
  padding: 4rpx 20rpx;
  border-radius: $lyj-radius-pill;
  background: $lyj-primary-soft;
  color: $lyj-primary-dark;
  font-weight: 600;
}

.block {
  margin-top: $lyj-space-md;
}

.block-head {
  display: block;
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-primary;
  margin-bottom: $lyj-space-xs;
}

.ingredient {
  display: block;
  font-size: $lyj-font-md;
  color: $lyj-text;
  line-height: $lyj-line-height;
}

.step {
  display: flex;
  align-items: flex-start;
  gap: $lyj-space-xs;
  margin-bottom: $lyj-space-xs;
}

.step-no {
  flex-shrink: 0;
  width: 48rpx;
  height: 48rpx;
  line-height: 48rpx;
  text-align: center;
  border-radius: 50%;
  background: $lyj-primary-soft;
  color: $lyj-primary-dark;
  font-size: $lyj-font-sm;
  font-weight: 700;
}

.step-text {
  flex: 1;
  font-size: $lyj-font-md;
  color: $lyj-text;
  line-height: $lyj-line-height;
}

.tip {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  line-height: $lyj-line-height;
}

/* R4 的落点：这一行永不被折叠、永不被隐藏 */
.disclaimer {
  display: block;
  margin-top: $lyj-space-md;
  padding-top: $lyj-space-sm;
  border-top: 2rpx solid $lyj-line;
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
