<template>
  <!--
    办事计划步骤条 —— 吃后端 todo 事件的快照。

    这个组件**只渲染**传进来的快照，自己不推进任何状态。旧版由页面用
    tool_call / tool_result 启发式地推进"第一个未完成步骤"，工具数和步骤数
    一旦不一致就立刻错位，而且刷新即丢。现在进度是后端事件日志里的事实。
  -->
  <view class="plan-card">
    <view class="plan-head">
      <text class="plan-title">📋 老友记的办事计划</text>
      <text v-if="progress && progress.total" class="plan-count">
        {{ progress.done || 0 }}/{{ progress.total }}
      </text>
    </view>

    <view v-for="(item, index) in todos" :key="index" class="step">
      <view class="step-dot" :class="item.status">
        <text class="step-num">{{ item.status === 'completed' ? '✓' : index + 1 }}</text>
      </view>
      <text class="step-title" :class="item.status">{{ item.content }}</text>
      <text v-if="item.status === 'in_progress'" class="step-spinner">⏳</text>
    </view>
  </view>
</template>

<script>
export default {
  name: 'StepTimeline',
  props: {
    // [{ content: String, status: 'pending' | 'in_progress' | 'completed' }]
    // 注意：后端的 TodoItem 刻意没有 id、没有 priority，序号用下标渲染。
    todos: { type: Array, default: () => [] },
    // { total, done, doing }
    progress: { type: Object, default: () => ({}) },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.plan-card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
}
.plan-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $lyj-space-md;
}
.plan-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-text;
}
.plan-count {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.step {
  display: flex;
  align-items: center;
  padding: $lyj-space-sm 0;
  gap: $lyj-space-md;
}
.step-dot {
  width: 64rpx;
  height: 64rpx;
  border-radius: 50%;
  background: $lyj-line;
  color: $lyj-text-light;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.step-dot.in_progress {
  background: $lyj-primary-soft;
  color: $lyj-primary;
}
.step-dot.completed {
  background: $lyj-success;
  color: $lyj-text-on;
}
.step-num {
  font-size: $lyj-font-sm;
  font-weight: 700;
}
.step-title {
  flex: 1;
  font-size: $lyj-font-md;
  color: $lyj-text;
  line-height: $lyj-line-height;
}
.step-title.completed {
  color: $lyj-text-light;
  text-decoration: line-through;
}
.step-spinner {
  font-size: $lyj-font-md;
}
</style>
