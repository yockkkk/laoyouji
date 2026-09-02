<template>
  <view class="med-page">
    <view class="topbar">
      <text class="title">今天的药</text>
      <text class="sub">吃完点一下，家人就放心了</text>
    </view>

    <view v-if="!meds.length" class="empty">
      <text class="empty-icon">💊</text>
      <text class="empty-text">今天没有要吃的药</text>
    </view>

    <view v-for="m in meds" :key="m.id" class="med-card">
      <view class="med-head">
        <text class="drug">{{ m.drug_name }}</text>
        <text class="dose">{{ m.dose }}</text>
      </view>
      <text v-if="m.notes" class="notes">💡 {{ m.notes }}</text>
      <view class="slots">
        <view
          v-for="t in m.times || []"
          :key="t"
          class="slot"
          :class="{ taken: isTaken(m, t) }"
          @tap="take(m, t)"
        >
          <text class="slot-time">{{ t }}</text>
          <text class="slot-state">{{ isTaken(m, t) ? '✓ 已吃' : '点我打卡' }}</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import { get, post } from '../../api/client'
import { getCurrentUser } from '../../store/user'
import { speak } from '../../api/asr'

export default {
  data() {
    return { user: null, meds: [] }
  },
  onShow() {
    this.user = getCurrentUser()
    if (!this.user) {
      // 换身份 —— 清栈是这里要的语义
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.load()
  },
  methods: {
    async load() {
      try {
        const d = await get('/api/medications', { elder_id: this.user.id, with_logs: true })
        this.meds = (d.items || []).filter((m) => m.active)
      } catch (e) {
        uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
    },
    isTaken(m, time) {
      return (m.logs || []).some((l) => l.scheduled_time === time && l.status === 'taken')
    },
    async take(m, time) {
      if (this.isTaken(m, time)) return
      try {
        await post(`/api/medications/${m.id}/taken?scheduled_time=${encodeURIComponent(time)}`)
        uni.showToast({ title: '真棒，吃过啦！', icon: 'success' })
        speak(`好样的，${m.drug_name}吃过了。`)
        this.load()
      } catch (e) {
        uni.showToast({ title: e.message, icon: 'none' })
      }
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.med-page {
  min-height: 100vh;
  background: $lyj-bg;
  padding-bottom: $lyj-space-xl;
  box-sizing: border-box;
}
.topbar {
  padding: calc(var(--status-bar-height) + #{$lyj-space-lg}) $lyj-space-lg $lyj-space-md;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.title {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.sub {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: $lyj-space-xl 0;
  gap: $lyj-space-md;
}
.empty-icon {
  font-size: 100rpx;
}
.empty-text {
  font-size: $lyj-font-md;
  color: $lyj-text-light;
}
.med-card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-md;
  padding: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
}
.med-head {
  display: flex;
  align-items: baseline;
  gap: $lyj-space-md;
}
.drug {
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-text;
}
.dose {
  font-size: $lyj-font-md;
  color: $lyj-text-light;
}
.notes {
  display: block;
  /* 服药注意事项是老人必须读到的正文，不是脚注 —— 原来是 28rpx（14px） */
  font-size: $lyj-font-md;
  color: $lyj-warn-text;
  line-height: $lyj-line-height;
  margin-top: $lyj-space-xs;
}
.slots {
  display: flex;
  gap: $lyj-space-md;
  margin-top: $lyj-space-md;
}
.slot {
  flex: 1;
  /* 打卡格是这页的主操作，按主按钮高度给 */
  min-height: $lyj-btn-main;
  border-radius: $lyj-radius;
  background: $lyj-field;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: $lyj-space-xs;
}
.slot.taken {
  background: $lyj-success-bg;
}
.slot-time {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.slot-state {
  font-size: $lyj-font-sm;
  color: $lyj-primary;
}
.slot.taken .slot-state {
  color: $lyj-success;
}
</style>
