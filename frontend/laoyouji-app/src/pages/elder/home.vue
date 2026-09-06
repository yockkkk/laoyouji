<template>
  <view class="home">
    <!-- 顶部问候：一行字，不占掉首屏 -->
    <view class="header">
      <view class="greet">
        <text class="hello">{{ greetText }}，{{ user ? user.name : '' }}</text>
        <text class="sub">{{ todayText }}</text>
      </view>
      <text class="header-logo">🤵</text>
    </view>

    <!-- 响应式铺砌容器：手机端纵向排列，电脑端大屏两列自适应平铺 -->
    <view class="home-grid">
      <view class="home-col">
        <!-- 首屏第一件事 = 按住说话 -->
        <view class="mic-zone">
          <LyjMic
            :dialect="user ? user.dialect : ''"
            hint="想办什么事，按住上面的大按钮说给我听"
            @text="onSpoken"
          />
        </view>

        <!-- 快捷入口 -->
        <view class="quick">
          <view
            v-for="q in quicks"
            :key="q.label"
            class="quick-item"
            @tap="quick(q.text)"
          >
            <text class="quick-icon">{{ q.icon }}</text>
            <text class="quick-label">{{ q.label }}</text>
          </view>
        </view>
      </view>

      <view class="home-col">
        <!-- 今日提醒大卡片 -->
        <view class="reminder-card">
          <view class="reminder-head">
            <text class="reminder-title">⏰ 今天的提醒</text>
          </view>
          <view v-if="!meds.length" class="reminder-empty">
            <text class="reminder-empty-text">今天没有要吃的药，好好休息～</text>
          </view>
          <view v-for="m in meds" :key="m.id" class="med-row">
            <text class="med-drug">{{ m.drug_name }}</text>
            <text class="med-times">{{ (m.times || []).join(' / ') }}</text>
            <text class="med-status" :class="takenCount(m) === (m.times || []).length ? 'ok' : 'todo'">
              {{ takenCount(m) }}/{{ (m.times || []).length }} 次
            </text>
          </view>
          <button class="btn-main go-med" @tap="goMed">去吃药打卡</button>
        </view>

        <!-- 天气卡片 -->
        <view class="weather-card" v-if="weather">
          <text class="weather-icon">{{ weather.icon }}</text>
          <view class="weather-info">
            <text class="weather-main">{{ weather.text }}</text>
            <text class="weather-tip">{{ weather.tip }}</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import LyjMic from '../../components/LyjMic.vue'
import { get } from '../../api/client'
import { getCurrentUser } from '../../store/user'
import { putUtterance } from '../../store/handoff'

const QUICKS = [
  { icon: '🏥', label: '看病挂号', text: '我想去北京看腿疼的老毛病' },
  { icon: '🚄', label: '买票出门', text: '帮我查一下明天去北京的高铁票' },
  { icon: '🍱', label: '订餐送饭', text: '帮我订一份中午的软食套餐' },
  { icon: '🛡️', label: '防骗问问', text: '有人给我打电话说我中奖了，让我先交钱' },
]

export default {
  components: { LyjMic },
  data() {
    return { user: null, meds: [], weather: null, quicks: QUICKS }
  },
  computed: {
    greetText() {
      const h = new Date().getHours()
      if (h < 6) return '夜深了'
      if (h < 11) return '早上好'
      if (h < 14) return '中午好'
      if (h < 18) return '下午好'
      return '晚上好'
    },
    todayText() {
      const d = new Date()
      const week = ['日', '一', '二', '三', '四', '五', '六'][d.getDay()]
      return `${d.getMonth() + 1}月${d.getDate()}日 星期${week}`
    },
  },
  onShow() {
    try {
      uni.showTabBar({ animation: false })
    } catch (e) {}
    this.user = getCurrentUser()
    if (!this.user) {
      // 换身份 —— 清栈是这里要的语义
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.loadMeds()
    this.loadWeather()
  },
  methods: {
    async loadMeds() {
      try {
        const d = await get('/api/medications', {
          elder_id: this.user.id,
          with_logs: true,
        })
        this.meds = (d.items || []).filter((m) => m.active)
      } catch (e) {
        console.warn('用药加载失败', e.message)
      }
    },
    async loadWeather() {
      try {
        const d = await get('/api/weather', { city: this.user.city || '南京' })
        if (!d || !d.ok) return
        const icons = { 晴: '☀️', 多云: '⛅', 阴: '☁️', 小雨: '🌦️', 雨: '🌧️' }
        const icon = Object.keys(icons).find((k) => (d.condition || '').includes(k))
        this.weather = {
          icon: icon ? icons[icon] : '🌤️',
          text: `${d.city}今天 ${d.condition}，${d.temp_low}~${d.temp_high}℃`,
          tip: d.advice + (d.umbrella ? ' 记得带伞。' : ''),
        }
      } catch (e) {
        /* 天气可选 */
      }
    },
    takenCount(m) {
      return (m.logs || []).filter((l) => l.status === 'taken').length
    },
    goMed() {
      uni.switchTab({ url: '/pages/elder/medications' })
    },

    /** 说完的话：老人自己说的，直接执行。 */
    onSpoken(text) {
      putUtterance(text, true)
      uni.switchTab({ url: '/pages/elder/chat' })
    },

    /**
     * 快捷入口：**填进输入框等老人自己按发送**，不自动发。
     * 老人点的是"看病挂号"四个字，卡片背后那句"我想去北京看腿疼的老毛病"
     * 带着症状细节 —— 那是替老人编的话，不能悄悄替他说出去。
     */
    quick(text) {
      putUtterance(text, false)
      uni.switchTab({ url: '/pages/elder/chat' })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.home {
  min-height: 100vh;
  background: $lyj-bg;
  padding-bottom: $lyj-space-xl;
  box-sizing: border-box;
}
.header {
  /* 自定义导航：状态栏高度交给 uni-app 的内置变量，不写死 */
  padding: calc(var(--status-bar-height) + #{$lyj-space-lg}) $lyj-space-lg $lyj-space-md;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.greet {
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.hello {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.sub {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.header-logo {
  font-size: 90rpx;
}
.mic-zone {
  display: flex;
  justify-content: center;
  padding: $lyj-space-md 0 $lyj-space-lg;
}
.reminder-card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-xs $lyj-space-md;
  padding: $lyj-space-lg;
  box-shadow: $lyj-shadow-raised;
}
.reminder-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-text;
}
.reminder-empty {
  padding: $lyj-space-md 0;
  text-align: center;
}
.reminder-empty-text {
  font-size: $lyj-font-md;
  color: $lyj-text-light;
}
.med-row {
  display: flex;
  align-items: center;
  gap: $lyj-space-md;
  padding: $lyj-space-md 0;
  border-bottom: 2rpx dashed $lyj-line;
}
.med-drug {
  flex: 1;
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-text;
}
.med-times {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.med-status {
  font-size: $lyj-font-sm;
  font-weight: 700;
}
.med-status.ok {
  color: $lyj-success;
}
.med-status.todo {
  color: $lyj-primary;
}
.go-med {
  margin-top: $lyj-space-md;
}
.quick {
  display: flex;
  flex-wrap: wrap;
  padding: $lyj-space-xs $lyj-space-md;
  gap: $lyj-space-sm;
}
.quick-item {
  /* 两列：宽度要让出半个 gap，否则第二列换行 */
  width: calc(50% - #{$lyj-space-xs});
  box-sizing: border-box;
  background: $lyj-card;
  border-radius: $lyj-radius;
  padding: $lyj-space-lg;
  display: flex;
  align-items: center;
  gap: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
  min-height: $lyj-hit-min;
}
.quick-icon {
  font-size: 64rpx;
}
.quick-label {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-text;
}
.weather-card {
  background: linear-gradient(140deg, $lyj-weather-from, $lyj-card);
  border-radius: $lyj-radius;
  margin: $lyj-space-md;
  padding: $lyj-space-md;
  display: flex;
  align-items: center;
  gap: $lyj-space-md;
  border: 2rpx solid $lyj-weather-line;
}
.weather-icon {
  font-size: 64rpx;
}
.weather-info {
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.weather-main {
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-text;
}
.weather-tip {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}

.home-grid {
  display: flex;
  flex-direction: column;
}
.home-col {
  width: 100%;
}

/* 电脑端宽屏铺砌自适应：大屏两列栅格平铺，卡片饱满铺开 */
@media screen and (min-width: 768px) {
  .home {
    max-width: 960px;
    margin: 0 auto;
    padding: 30rpx 32rpx 120rpx;
  }
  .header {
    padding: 20rpx 0 40rpx;
  }
  .home-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 32rpx;
    align-items: start;
  }
  .reminder-card {
    margin: 0 0 24rpx;
  }
  .weather-card {
    margin: 0;
  }
  .quick {
    padding: 0;
  }
}
</style>
