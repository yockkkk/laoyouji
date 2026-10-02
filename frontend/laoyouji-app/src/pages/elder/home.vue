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
            @error="onMicError"
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

        <!-- 健康页入口：快捷区那套是发语音（quick(text)），填不进导航，
             所以健康页单给一个能 navigateTo 的大入口 -->
        <view class="health-entry" @tap="goHealth">
          <text class="health-entry-icon">❤️</text>
          <view class="health-entry-text">
            <text class="health-entry-title">我的健康</text>
            <text class="health-entry-sub">量血压、看分诊</text>
          </view>
          <text class="health-entry-arrow">›</text>
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
import { syncAll, consumePendingRoute } from '../../utils/native'

/**
 * 快捷入口的文案与离线剧本的意图词是配套的（app/providers/llm/mock.py）。
 * 改这几句话之前先去核对 _wants_medical_trip / _wants_community /
 * _wants_call / _wants_recipe —— 文案改了而意图词不认，点了就没反应。
 * 已经砍掉的入口（买票出门 / 订餐送饭 / 防骗问问）不再摆出来：留着点了没反应，
 * 比不给入口更让人犯嘀咕。
 */
const QUICKS = [
  // "血压"命中 _wants_health（vital）→ 安康助手分诊
  { icon: '🩺', label: '量个血压', text: '帮我记一下血压，高压 138 低压 86' },
  // "医院"命中 _wants_medical_trip → 挂号 + 就近路线 + 计划书
  { icon: '🏥', label: '看病挂号', text: '我想去鼓楼医院看腿疼的老毛病' },
  // "心里闷"命中 _wants_community，进 _community 后 "心里闷" 又命中
  // _wants_call → 先落一张一键拨号卡（不是先推活动）
  { icon: '💬', label: '心里闷', text: '我心里闷得慌，一个人没意思' },
  // "教我做"命中 _wants_community，进 _community 后命中 _wants_recipe → 菜谱卡
  { icon: '🍲', label: '今天吃啥', text: '教我做一道软烂清淡的家常菜' },
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
    // 进入长辈端首屏即按后端用药计划同步一次闹钟（声明式全量覆盖，重复调安全）。
    // 没有桥时 syncAll 立即返回，纯浏览器里等于什么都没发生。
    syncAll()
    // 冷启动点通知进 App 时，onLaunch 那一刻页面栈还没建立、跳不动，目标被存成了
    // 待跳路由；这里是首个落地页，onShow 到点把它领走重跳（没有待跳路由时无副作用）。
    consumePendingRoute()
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
        const d = await get('/api/weather', { city: this.user.city || '长沙' })
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

    /** 健康页不是 tab 页，用 navigateTo（健康页有自己的返回）。 */
    goHealth() {
      uni.navigateTo({ url: '/pages/elder/health' })
    },

    /** 说完的话：老人自己说的，直接执行。 */
    onSpoken(text) {
      putUtterance(text, true)
      uni.switchTab({ url: '/pages/elder/chat' })
    },

    /** 麦克风在 HTTP 或不可用环境报错时，友好引导到聊天页打字 */
    onMicError() {
      setTimeout(() => {
        uni.switchTab({ url: '/pages/elder/chat' })
      }, 1500)
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
  padding-bottom: calc(#{$lyj-tabbar-h} + #{$lyj-space-lg} + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
}
.header {
  /* 自定义导航：状态栏高度交给 uni-app 的内置变量，不写死 */
  padding: calc(var(--status-bar-height) + 16rpx) $lyj-space-lg 12rpx;
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
  white-space: nowrap !important;
  word-break: keep-all !important;
}
.sub {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  white-space: nowrap !important;
  word-break: keep-all !important;
}
.header-logo {
  font-size: 90rpx;
}
.mic-zone {
  display: flex;
  justify-content: center;
  padding: 12rpx 0 16rpx;
}
.reminder-card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: 12rpx $lyj-space-md $lyj-space-md;
  padding: $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
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
  white-space: nowrap;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}
.med-status.ok {
  color: $lyj-success;
}
.med-status.todo {
  color: $lyj-primary;
}
.go-med {
  margin-top: $lyj-space-md;
  white-space: nowrap;
  word-break: keep-all;
}
.quick {
  display: flex;
  flex-wrap: wrap;
  padding: 8rpx $lyj-space-md;
  gap: $lyj-space-sm;
}
.quick-item {
  /* 两列：宽度要让出半个 gap，否则第二列换行 */
  width: calc(50% - #{$lyj-space-xs});
  box-sizing: border-box;
  background: $lyj-card;
  border-radius: $lyj-radius;
  padding: 18rpx 20rpx;
  display: flex;
  align-items: center;
  gap: 16rpx;
  box-shadow: $lyj-shadow-card;
  min-height: 104rpx;
}
.quick-icon {
  font-size: 52rpx;
  line-height: 1;
  flex-shrink: 0;
}
.quick-label {
  font-size: 38rpx;
  font-weight: 700;
  color: $lyj-text;
  white-space: nowrap;
  word-break: keep-all;
  flex-shrink: 0;
}
/* 健康页入口：老人端字号，触控区不低于 44px（$lyj-hit-min） */
.health-entry {
  display: flex;
  align-items: center;
  gap: $lyj-space-md;
  margin: 8rpx $lyj-space-md;
  padding: 16rpx 24rpx;
  background: $lyj-card;
  border: 2rpx solid $lyj-line;
  border-radius: $lyj-radius;
  box-shadow: $lyj-shadow-card;
  min-height: 104rpx;
}
.health-entry-icon {
  font-size: 64rpx;
  flex-shrink: 0;
}
.health-entry-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.health-entry-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-text;
  white-space: nowrap;
}
.health-entry-sub {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  white-space: nowrap;
  word-break: keep-all;
}
.health-entry-arrow {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text-light;
  flex-shrink: 0;
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
  gap: $lyj-space-md;
}
.home-col {
  width: 100%;
}
</style>
