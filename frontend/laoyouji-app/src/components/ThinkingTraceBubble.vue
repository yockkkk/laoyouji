<template>
  <view class="thinking-bubble" :style="{ borderColor: color + '40', background: color + '0D' }">
    <view class="thinking-header">
      <view class="agent-avatar-badge" :style="{ background: color }">
        <text class="agent-icon">{{ agentIcon }}</text>
      </view>
      <text class="agent-title" :style="{ color }">{{ agentTitle }}</text>
      <view class="pulse-spark" :style="{ background: color }"></view>
      <text class="thinking-status">正在深入思考与协同…</text>
    </view>
    <view class="thinking-body">
      <text class="elder-phrasing">{{ elderText || rawThought }}</text>
    </view>
  </view>
</template>

<script>
export default {
  name: 'ThinkingTraceBubble',
  props: {
    agent: {
      type: String,
      default: 'main',
    },
    delta: {
      type: String,
      default: '',
    },
    color: {
      type: String,
      default: '#E65100',
    },
    rawThought: {
      type: String,
      default: '',
    },
  },
  computed: {
    agentTitle() {
      const titles = {
        main: '康乐总管',
        health: '安康助手',
        bds_nav: '北斗导航',
        weather: '气象感知',
        guardian: '安澜卫士',
        travel: '银发导航',
        community: '邻里帮',
      }
      return titles[this.agent] || this.agent
    },
    agentIcon() {
      const icons = {
        main: '🧠',
        health: '🩺',
        bds_nav: '🛰️',
        weather: '🌤️',
        guardian: '🛡️',
        travel: '🚶',
        community: '🤝',
      }
      return icons[this.agent] || '🤖'
    },
    elderText() {
      if (this.delta) return this.delta
      const phr = {
        health: '正在为您调取近期体能与膝关节受力情况…',
        bds_nav: '北斗高精定位正在为您勘测沿途是否有陡坡与台阶…',
        weather: '正在感知沿途树荫覆盖与短临降雨湿度…',
        guardian: '正在为您规划全程安心步道并建立家人守护通道…',
        main: '正在统筹调度各领域专家为您制定出行方案…',
      }
      return phr[this.agent] || this.rawThought
    },
  },
}
</script>

<style scoped>
.thinking-bubble {
  margin: 12rpx 24rpx;
  padding: 16rpx 24rpx;
  border-radius: 20rpx;
  border: 2rpx solid #e2e8f0;
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.03);
  animation: fadeIn 0.3s ease-out;
}

.thinking-header {
  display: flex;
  align-items: center;
  margin-bottom: 8rpx;
}

.agent-avatar-badge {
  width: 36rpx;
  height: 36rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 12rpx;
}

.agent-icon {
  font-size: 20rpx;
}

.agent-title {
  font-size: 26rpx;
  font-weight: bold;
  margin-right: 12rpx;
}

.pulse-spark {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;
  margin-right: 12rpx;
  animation: pulseShimmer 1.5s infinite;
}

.thinking-status {
  font-size: 22rpx;
  color: #64748b;
}

.thinking-body {
  padding-left: 48rpx;
}

.elder-phrasing {
  font-size: 28rpx;
  color: #334155;
  line-height: 1.5;
}

@keyframes pulseShimmer {
  0% { transform: scale(0.9); opacity: 0.5; }
  50% { transform: scale(1.3); opacity: 1; }
  100% { transform: scale(0.9); opacity: 0.5; }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(6rpx); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
