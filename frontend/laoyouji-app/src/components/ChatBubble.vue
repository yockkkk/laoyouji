<template>
  <!-- 会话气泡：文字消息（含语音播报按钮） -->
  <view class="bubble-row" :class="isUser ? 'right' : 'left'">
    <view class="avatar" v-if="!isUser">{{ agentIcon }}</view>
    <view class="bubble" :class="isUser ? 'user' : 'bot'" @tap="!isUser && replay()">
      <text class="text">{{ text }}</text>
      <view v-if="!isUser && text" class="replay" @tap.stop="replay">
        <text class="replay-icon">🔊</text>
        <text class="replay-text">再念一遍</text>
      </view>
    </view>
  </view>
</template>

<script>
import { speak } from '../api/asr'

export default {
  name: 'ChatBubble',
  props: {
    text: { type: String, default: '' },
    isUser: { type: Boolean, default: false },
    agent: { type: String, default: 'main' }, // main/travel/health/community
  },
  computed: {
    agentIcon() {
      return { main: '🤵', travel: '🧭', health: '🏥', community: '🏘️' }[this.agent] || '🤵'
    },
  },
  methods: {
    replay() {
      const ok = speak(this.text)
      if (!ok) uni.showToast({ title: '当前设备不支持语音播报', icon: 'none' })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.bubble-row {
  display: flex;
  margin: $lyj-space-sm $lyj-space-md;
  align-items: flex-start;
}
.bubble-row.right {
  justify-content: flex-end;
}
.avatar {
  font-size: $lyj-font-lg;
  margin-right: $lyj-space-xs;
  margin-top: $lyj-space-xs;
}
.bubble {
  max-width: 78%;
  border-radius: $lyj-radius-lg;
  padding: $lyj-space-md $lyj-space-lg;
}
.bubble.bot {
  background: $lyj-card;
  box-shadow: $lyj-shadow-card;
}
.bubble.user {
  background: $lyj-primary;
  color: $lyj-text-on;
}
.text {
  /* 正文地板 20px —— 老人要读的字一律不低于此值 */
  font-size: $lyj-font-md;
  line-height: $lyj-line-height;
  overflow-wrap: break-word;
  word-break: normal;
  white-space: pre-wrap;
}
.replay {
  /* 可点区域按硬指标给到 44px，不是只把字撑大 */
  margin-top: $lyj-space-xs;
  min-height: $lyj-hit-min;
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
}
.replay-icon {
  font-size: $lyj-font-md;
}
.replay-text {
  font-size: $lyj-font-sm;
  color: $lyj-primary;
}
</style>
