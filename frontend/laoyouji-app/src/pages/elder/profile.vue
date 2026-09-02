<template>
  <view class="profile-page">
    <view class="topbar">
      <text class="title">我的</text>
    </view>

    <view class="user-card">
      <text class="avatar">👵</text>
      <view class="user-info">
        <text class="name">{{ user ? user.name : '' }}</text>
        <text class="city">{{ user ? user.city : '' }} · {{ dialectLabel }}</text>
      </view>
    </view>

    <!-- 方言选择（传给后端 ASR Provider） -->
    <view class="section">
      <text class="section-title">🗣️ 我说话的口音</text>
      <view class="options">
        <view
          v-for="d in dialects"
          :key="d.value"
          class="option"
          :class="{ active: dialect === d.value }"
          @tap="setDialect(d.value)"
        >
          <text>{{ d.label }}</text>
        </view>
      </view>
      <text class="section-note">选准口音，我听得更清楚</text>
    </view>

    <!-- 隐私分级（老人自己掌控授权） -->
    <view class="section">
      <text class="section-title">🔒 家人能看到什么（由您决定）</text>
      <view class="privacy-row">
        <text class="privacy-label">我的位置</text>
        <view class="options">
          <view
            v-for="o in locationOptions"
            :key="o.value"
            class="option"
            :class="{ active: privacy.location_level === o.value }"
            @tap="setPrivacy('location_level', o.value)"
          >
            <text>{{ o.label }}</text>
          </view>
        </view>
      </view>
      <view class="privacy-row">
        <text class="privacy-label">我的健康</text>
        <view class="options">
          <view
            v-for="o in healthOptions"
            :key="o.value"
            class="option"
            :class="{ active: privacy.health_level === o.value }"
            @tap="setPrivacy('health_level', o.value)"
          >
            <text>{{ o.label }}</text>
          </view>
        </view>
      </view>
    </view>

    <view class="section">
      <button class="btn-ghost" @tap="logout">切换身份</button>
    </view>
  </view>
</template>

<script>
import { get, put } from '../../api/client'
import { getCurrentUser, setCurrentUser, clearCurrentUser } from '../../store/user'

const DIALECTS = [
  { value: 'southwestern', label: '西南官话' },
  { value: 'cantonese', label: '粤语' },
  { value: 'wu', label: '吴语' },
  { value: 'mandarin', label: '普通话' },
]

export default {
  data() {
    return {
      user: null,
      dialect: 'mandarin',
      privacy: { location_level: 'realtime', health_level: 'summary' },
      dialects: DIALECTS,
      locationOptions: [
        { value: 'realtime', label: '实时位置' },
        { value: 'city', label: '只看城市' },
        { value: 'off', label: '不给看' },
      ],
      healthOptions: [
        { value: 'full', label: '全部' },
        { value: 'summary', label: '只看摘要' },
        { value: 'off', label: '不给看' },
      ],
    }
  },
  computed: {
    dialectLabel() {
      const d = DIALECTS.find((x) => x.value === this.dialect)
      return d ? d.label : '普通话'
    },
  },
  onShow() {
    this.user = getCurrentUser()
    if (!this.user) {
      // 换身份 —— 清栈是这里要的语义
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.dialect = this.user.dialect || 'mandarin'
    this.loadPrivacy()
  },
  methods: {
    setDialect(value) {
      this.dialect = value
      this.user.dialect = value
      setCurrentUser(this.user)
      uni.showToast({ title: '好嘞，我记住了', icon: 'success' })
    },
    async loadPrivacy() {
      try {
        const child = this._boundChild()
        if (!child) return
        const d = await get(`/api/privacy/${this.user.id}`, { child_id: child.id })
        if (d) this.privacy = d
      } catch (e) {
        /* 隐私可选 */
      }
    },
    async setPrivacy(field, value) {
      const child = this._boundChild()
      if (!child) {
        // 后端 PrivacyIn.child_id 是必填的，没绑家人就没有"给谁看"这回事。
        // 悄悄发一个 child_id=undefined 只会换回一个 422，老人看到的是"已更新"。
        uni.showToast({ title: '还没有绑定家人，先让家人扫码绑定', icon: 'none' })
        return
      }
      const before = this.privacy[field]
      this.privacy[field] = value
      try {
        await put(`/api/privacy/${this.user.id}`, {
          child_id: child.id,
          location_level: this.privacy.location_level,
          health_level: this.privacy.health_level,
          // 谁在改。这一页只有老人能到，所以 actor 就是他自己 ——
          // 带上它，审计里记的才是真 actor，而不是后端替所有人签的名。
          actor_id: this.user.id,
        })
        uni.showToast({ title: '已更新', icon: 'success' })
      } catch (e) {
        // 没存上就得退回去：开关的位置必须是服务端的事实
        this.privacy[field] = before
        uni.showToast({ title: e.message, icon: 'none' })
      }
    },
    _boundChild() {
      try {
        const raw = uni.getStorageSync('lyj_family')
        const family = raw ? JSON.parse(raw) : {}
        return family.child || null
      } catch (e) {
        return null
      }
    },
    logout() {
      clearCurrentUser()
      // 退出登录：整个页面栈都属于上一个身份，必须清掉
      uni.reLaunch({ url: '/pages/login/login' })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.profile-page {
  min-height: 100vh;
  background: $lyj-bg;
  padding-bottom: $lyj-space-xl;
  box-sizing: border-box;
}
.topbar {
  padding: calc(var(--status-bar-height) + #{$lyj-space-lg}) $lyj-space-lg $lyj-space-md;
}
.title {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.user-card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-xs $lyj-space-md $lyj-space-md;
  padding: $lyj-space-lg;
  display: flex;
  align-items: center;
  gap: $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
}
.avatar {
  font-size: 100rpx;
}
.user-info {
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.name {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.city {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.section {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-md;
  padding: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
}
.section-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-text;
}
.options {
  display: flex;
  flex-wrap: wrap;
  gap: $lyj-space-sm;
  margin-top: $lyj-space-md;
}
/* 隐私档位是老人自己按的开关，命中区不能缩水 —— 原来 .options.small
   把字号压到 29rpx（14.5px）、内边距压到 14rpx，那是"看得见但按不准"。 */
.option {
  min-height: $lyj-hit-min;
  display: flex;
  align-items: center;
  padding: 0 $lyj-space-lg;
  border-radius: $lyj-radius;
  background: $lyj-field;
  font-size: $lyj-font-md;
  color: $lyj-text;
}
.option.active {
  background: $lyj-primary-soft;
  color: $lyj-primary;
  font-weight: 700;
  border: 3rpx solid $lyj-primary;
}
.section-note {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  margin-top: $lyj-space-sm;
}
.privacy-row {
  margin-top: $lyj-space-md;
}
.privacy-label {
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-text;
}
</style>
