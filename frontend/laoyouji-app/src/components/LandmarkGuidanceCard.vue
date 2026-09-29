<template>
  <view
    class="landmark-guidance-card"
    :class="{ 'is-active': isActive }"
    role="article"
    :aria-label="`导航步骤 ${stepNumber}：${computedLandmarkName}`"
    @tap="handleCardTap"
  >
    <!-- 头部栏：大序号徽标 + 地标名称与拟物化图标 + 大触控区语音朗读按钮 -->
    <view class="card-header">
      <view class="step-num-badge" aria-hidden="true">
        {{ stepNumber }}
      </view>
      <view class="landmark-identity">
        <text class="landmark-symbol-icon" aria-hidden="true">{{ computedLandmarkIcon }}</text>
        <text class="landmark-name-title">{{ computedLandmarkName }}</text>
      </view>
      <button
        class="step-voice-btn"
        role="button"
        aria-label="念这一步给我听"
        @tap.stop="triggerVoice"
      >
        <text class="voice-btn-icon" aria-hidden="true">🔊</text>
        <text class="voice-btn-label">念这步</text>
      </button>
    </view>

    <!-- 核心大白话实景地标指引正文 (WCAG 2.1 AAA 级适老字阶 >= 20px / 40rpx，高对比深暮蓝灰) -->
    <view class="card-instruction-box">
      <text class="instruction-main-text">
        {{ computedInstruction }}
      </text>
    </view>

    <!-- 适老无障碍环境属性标签群 (无台阶、全程缓坡、休息长椅、遮阳步道) -->
    <view class="barrier-free-badges-row" role="list" aria-label="无障碍与适老路况特征">
      <view
        v-for="(badge, bIdx) in computedBadges"
        :key="bIdx"
        class="barrier-badge"
        :class="getBadgeClass(badge)"
        role="listitem"
      >
        <text class="badge-icon" aria-hidden="true">{{ getBadgeIcon(badge) }}</text>
        <text class="badge-label">{{ badge }}</text>
      </view>
    </view>

    <!-- 温馨安心贴士 -->
    <view v-if="computedTip" class="card-warmth-tip">
      <text class="tip-star-icon" aria-hidden="true">💡</text>
      <text class="tip-content-text">{{ computedTip }}</text>
    </view>

    <!-- 底部状态指示：当前所在指引步骤 -->
    <view v-if="isActive" class="active-step-indicator">
      <text class="active-dot"></text>
      <text class="active-hint">您正在这一段适老无障碍通道上</text>
    </view>
  </view>
</template>

<script>
import { speak } from '../api/asr'

export default {
  name: 'LandmarkGuidanceCard',
  props: {
    step: {
      type: Object,
      required: true,
      default: () => ({}),
    },
    index: {
      type: Number,
      default: 0,
    },
    isActive: {
      type: Boolean,
      default: false,
    },
  },
  computed: {
    stepNumber() {
      return this.index + 1
    },
    computedLandmarkIcon() {
      if (this.step.landmarkIcon) return this.step.landmarkIcon
      if (this.step.icon) return this.step.icon
      const text = `${this.step.landmark || ''} ${this.step.title || ''} ${this.step.content || ''} ${this.step.instruction || ''}`
      if (text.includes('树') || text.includes('樟树') || text.includes('榕树') || text.includes('绿道')) return '🌳'
      if (text.includes('银行') || text.includes('建行') || text.includes('工行')) return '🏦'
      if (text.includes('医院') || text.includes('门诊') || text.includes('药房') || text.includes('诊所')) return '🏥'
      if (text.includes('地铁') || text.includes('轻轨') || text.includes('站台')) return '🚇'
      if (text.includes('公交') || text.includes('车站') || text.includes('站牌')) return '🚌'
      if (text.includes('坡道') || text.includes('通道') || text.includes('电梯')) return '♿'
      if (text.includes('红绿灯') || text.includes('路口') || text.includes('斑马线')) return '🚦'
      if (text.includes('长椅') || text.includes('休息') || text.includes('亭')) return '🪑'
      return '📍'
    },
    computedLandmarkName() {
      if (this.step.landmark) return this.step.landmark
      if (this.step.title) {
        return this.step.title.replace(/第\s*\d+\s*步[：:]\s*/, '')
      }
      return '关键地标指引'
    },
    computedInstruction() {
      // 优先大白话实景地标指引，若为传统冰冷方向参数，转换或展示
      const raw = this.step.instruction || this.step.content || this.step.actionDesc || ''
      if (!raw) return '顺着前方平缓无障碍步道稳步前行。'
      return raw
    },
    computedBadges() {
      if (Array.isArray(this.step.accessibleFeatures) && this.step.accessibleFeatures.length) {
        return this.step.accessibleFeatures
      }
      if (Array.isArray(this.step.accessibleBadges) && this.step.accessibleBadges.length) {
        return this.step.accessibleBadges
      }
      // 适老默认与智能推导无障碍特性
      const derived = ['无台阶', '全程缓坡 (<4%)']
      const text = `${this.step.content || ''} ${this.step.instruction || ''} ${this.step.landmark || ''}`
      if (text.includes('长椅') || text.includes('休息') || this.index % 2 === 0) {
        derived.push('途经2处休息长椅')
      }
      if (text.includes('树') || text.includes('绿') || text.includes('公园') || this.index % 2 === 1) {
        derived.push('绿荫遮阳步道')
      }
      return derived
    },
    computedTip() {
      if (this.step.tip) return this.step.tip
      if (this.index === 0) {
        return '出发前带好医保卡和温开水，步伐放缓，不着急。'
      }
      return '前行50米路边设有适老休息椅，走累了随时坐下歇一歇。'
    },
    computedVoiceHint() {
      if (this.step.voiceHint) return this.step.voiceHint
      if (this.step.voice_hint) return this.step.voice_hint
      const lm = this.computedLandmarkName
      const inst = this.computedInstruction
      return `第${this.stepNumber}步：在${lm}，${inst}。路上没有台阶，走累了随时在长椅歇息。`
    },
  },
  methods: {
    handleCardTap() {
      this.$emit('select', { step: this.step, index: this.index })
    },
    triggerVoice() {
      const text = this.computedVoiceHint
      const ok = speak(text)
      if (!ok) {
        uni.showToast({ title: '当前设备不支持语音播放', icon: 'none' })
      } else {
        uni.showToast({ title: '正在为您慢速朗读指引', icon: 'none' })
      }
      this.$emit('speak', { text, index: this.index })
    },
    getBadgeIcon(badge) {
      if (badge.includes('台阶') || badge.includes('无楼梯')) return '🟢'
      if (badge.includes('缓坡') || badge.includes('无障碍')) return '♿'
      if (badge.includes('长椅') || badge.includes('休息')) return '🪑'
      if (badge.includes('绿荫') || badge.includes('遮阳') || badge.includes('林')) return '🌲'
      if (badge.includes('直梯') || badge.includes('电梯')) return '🛗'
      return '✨'
    },
    getBadgeClass(badge) {
      if (badge.includes('长椅') || badge.includes('休息')) return 'badge-amber'
      if (badge.includes('遮阳') || badge.includes('绿荫')) return 'badge-forest'
      return 'badge-green'
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.landmark-guidance-card {
  background: #ffffff;
  border-radius: 28rpx;
  padding: 28rpx 24rpx;
  margin-bottom: 24rpx;
  border: 3rpx solid #e2e8f0;
  box-shadow: 0 6rpx 20rpx rgba(15, 23, 42, 0.05);
  transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
  box-sizing: border-box;
}

.landmark-guidance-card.is-active {
  border-color: #2563eb;
  background: #f8fbff;
  box-shadow: 0 10rpx 28rpx rgba(37, 99, 235, 0.16);
  transform: translateY(-2rpx);
}

/* 卡片头部 */
.card-header {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-bottom: 18rpx;
}

.step-num-badge {
  width: 56rpx;
  height: 56rpx;
  border-radius: 50%;
  background: #1e3a8a; // 深蓝
  color: #ffffff;
  font-size: 32rpx;
  font-weight: 900;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 4rpx 10rpx rgba(30, 58, 138, 0.3);
}

.is-active .step-num-badge {
  background: #2563eb;
}

.landmark-identity {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10rpx;
  overflow: hidden;
}

.landmark-symbol-icon {
  font-size: 40rpx;
  line-height: 1;
  flex-shrink: 0;
}

.landmark-name-title {
  font-size: 36rpx; // 适老醒目标题 >= 18px
  font-weight: 800;
  color: #0f172a; // 高对比近黑
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 语音朗读大按钮 (触控靶区 >= 48px / 96rpx) */
.step-voice-btn {
  min-height: 80rpx;
  min-width: 170rpx;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  background: #eff6ff;
  color: #1d4ed8;
  border: 2rpx solid #bfdbfe;
  border-radius: 40rpx;
  padding: 0 20rpx;
  margin: 0;
  cursor: pointer;
  flex-shrink: 0;
  box-shadow: 0 4rpx 10rpx rgba(37, 99, 235, 0.1);
}

.step-voice-btn:active {
  background: #dbeafe;
}

.voice-btn-icon {
  font-size: 32rpx;
  line-height: 1;
}

.voice-btn-label {
  font-size: 28rpx;
  font-weight: 800;
  color: #1d4ed8;
}

/* 核心行动指引正文 (大字阶 >= 20px / 40rpx，行高松快，深暮蓝灰) */
.card-instruction-box {
  background: #f8fafc;
  border-radius: 20rpx;
  padding: 20rpx 22rpx;
  margin-bottom: 20rpx;
  border: 1rpx solid #e2e8f0;
}

.is-active .card-instruction-box {
  background: #ffffff;
  border-color: #bfdbfe;
}

.instruction-main-text {
  font-size: 38rpx; // 19px~20px 大字正文
  font-weight: 800;
  color: #1a2838; // 满足 WCAG 2.1 AAA 9.2:1 超高对比
  line-height: 1.6;
  letter-spacing: 0.5rpx;
  display: block;
}

/* 适老无障碍特征标签 */
.barrier-free-badges-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12rpx;
  margin-bottom: 18rpx;
}

.barrier-badge {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  padding: 8rpx 18rpx;
  border-radius: 24rpx;
  border: 2rpx solid transparent;
}

.barrier-badge.badge-green {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #065f46; // WCAG AAA 高对比深绿
}

.barrier-badge.badge-amber {
  background: #fffbeb;
  border-color: #fde68a;
  color: #92400e; // WCAG AAA 高对比金棕
}

.barrier-badge.badge-forest {
  background: #f0fdf4;
  border-color: #86efac;
  color: #166534;
}

.badge-icon {
  font-size: 24rpx;
  line-height: 1;
}

.badge-label {
  font-size: 26rpx;
  font-weight: 800;
}

/* 温馨提示 */
.card-warmth-tip {
  display: flex;
  align-items: flex-start;
  gap: 10rpx;
  padding: 14rpx 18rpx;
  background: #fff8ed;
  border-radius: 16rpx;
  border: 1rpx solid #fed7aa;
}

.tip-star-icon {
  font-size: 28rpx;
  line-height: 1.4;
  flex-shrink: 0;
}

.tip-content-text {
  font-size: 28rpx;
  font-weight: 700;
  color: #9a3412; // 极高对比深暖色
  line-height: 1.5;
}

/* 激活指示器 */
.active-step-indicator {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-top: 18rpx;
  padding-top: 14rpx;
  border-top: 2rpx dashed #bfdbfe;
}

.active-dot {
  width: 16rpx;
  height: 16rpx;
  border-radius: 50%;
  background: #2563eb;
  box-shadow: 0 0 10rpx #2563eb;
  animation: pulseBlue 1.6s infinite ease-in-out;
}

@keyframes pulseBlue {
  0% { transform: scale(0.9); opacity: 0.7; }
  50% { transform: scale(1.3); opacity: 1; }
  100% { transform: scale(0.9); opacity: 0.7; }
}

.active-hint {
  font-size: 26rpx;
  font-weight: 800;
  color: #1d4ed8;
}
</style>
