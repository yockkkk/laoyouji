<template>
  <view class="handoff-card" :style="{ borderColor: toColor + '55', background: 'linear-gradient(135deg, ' + fromColor + '10 0%, ' + toColor + '18 100%)' }">
    <view class="handoff-flow-row">
      <!-- From Agent -->
      <view class="agent-chip" :style="{ borderColor: fromColor, background: fromColor + '20' }">
        <text class="agent-icon">{{ getIcon(fromAgent) }}</text>
        <text class="agent-name" :style="{ color: fromColor }">{{ getTitle(fromAgent) }}</text>
      </view>

      <!-- Animated Transfer Arrow -->
      <view class="handoff-connector">
        <text class="connector-arrow">▶</text>
        <view class="pulse-beam" :style="{ background: toColor }"></view>
      </view>

      <!-- To Agent -->
      <view class="agent-chip" :style="{ borderColor: toColor, background: toColor + '20' }">
        <text class="agent-icon">{{ getIcon(toAgent) }}</text>
        <text class="agent-name" :style="{ color: toColor }">{{ getTitle(toAgent) }}</text>
      </view>
    </view>

    <!-- Handoff Reason / Message Preview -->
    <view class="handoff-body" v-if="reason || detail">
      <text class="handoff-tag">协同磋商</text>
      <text class="handoff-text">{{ reason || detail }}</text>
    </view>
  </view>
</template>

<script>
export default {
  name: 'AgentHandoffCard',
  props: {
    fromAgent: {
      type: String,
      default: 'main',
    },
    toAgent: {
      type: String,
      default: 'bds_nav',
    },
    reason: {
      type: String,
      default: '',
    },
    detail: {
      type: String,
      default: '',
    },
  },
  data() {
    return {
      agentMeta: {
        main: { title: '康乐总管', icon: '🧠', color: '#E65100' },
        health: { title: '安康助手', icon: '🩺', color: '#2E7D32' },
        bds_nav: { title: '北斗导航', icon: '🛰️', color: '#1565C0' },
        weather: { title: '气象感知', icon: '🌤️', color: '#0288D1' },
        guardian: { title: '安澜卫士', icon: '🛡️', color: '#6A1B9A' },
        travel: { title: '银发导航', icon: '🚶', color: '#E65100' },
        community: { title: '邻里帮', icon: '🤝', color: '#C2185B' },
      },
    }
  },
  computed: {
    fromColor() {
      return (this.agentMeta[this.fromAgent] || {}).color || '#E65100'
    },
    toColor() {
      return (this.agentMeta[this.toAgent] || {}).color || '#1565C0'
    },
  },
  methods: {
    getTitle(agentKey) {
      return (this.agentMeta[agentKey] || {}).title || agentKey
    },
    getIcon(agentKey) {
      return (this.agentMeta[agentKey] || {}).icon || '🤖'
    },
  },
}
</script>

<style scoped>
.handoff-card {
  margin: 12rpx 24rpx;
  padding: 16rpx 20rpx;
  border-radius: 18rpx;
  border: 2rpx solid #e2e8f0;
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.04);
  animation: slideInDown 0.35s ease-out;
}

.handoff-flow-row {
  display: flex;
  align-items: center;
  justify-content: flex-start;
}

.agent-chip {
  display: flex;
  align-items: center;
  padding: 8rpx 16rpx;
  border-radius: 28rpx;
  border: 1.5rpx solid transparent;
}

.agent-icon {
  font-size: 24rpx;
  margin-right: 8rpx;
}

.agent-name {
  font-size: 24rpx;
  font-weight: 600;
}

.handoff-connector {
  display: flex;
  align-items: center;
  margin: 0 16rpx;
  position: relative;
}

.connector-arrow {
  font-size: 22rpx;
  color: #94a3b8;
  animation: bounceRight 1.2s infinite ease-in-out;
}

.pulse-beam {
  width: 8rpx;
  height: 8rpx;
  border-radius: 50%;
  margin-left: 6rpx;
  animation: pulseDot 1.2s infinite ease-in-out;
}

.handoff-body {
  margin-top: 12rpx;
  padding-top: 10rpx;
  border-top: 1rpx dashed rgba(148, 163, 184, 0.3);
  display: flex;
  align-items: flex-start;
}

.handoff-tag {
  font-size: 20rpx;
  color: #fff;
  background-color: #64748b;
  padding: 2rpx 10rpx;
  border-radius: 8rpx;
  margin-right: 12rpx;
  white-space: nowrap;
  line-height: 1.4;
}

.handoff-text {
  font-size: 24rpx;
  color: #334155;
  line-height: 1.4;
  flex: 1;
}

@keyframes bounceRight {
  0%, 100% { transform: translateX(0); }
  50% { transform: translateX(6rpx); }
}

@keyframes pulseDot {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.4); }
}

@keyframes slideInDown {
  from { opacity: 0; transform: translateY(-8rpx); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
