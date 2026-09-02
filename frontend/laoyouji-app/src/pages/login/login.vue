<template>
  <view class="login">
    <view class="logo-area">
      <text class="logo">🤵</text>
      <text class="app-name">老友记</text>
      <text class="slogan">您的贴心生活管家</text>
    </view>

    <view class="role-card" @tap="pick('elder')">
      <text class="role-icon">👵</text>
      <view class="role-info">
        <text class="role-name">我是老人</text>
        <text class="role-desc">语音说话，啥事都帮我办</text>
      </view>
      <text class="arrow">›</text>
    </view>

    <view class="role-card child" @tap="pick('child')">
      <text class="role-icon">👨</text>
      <view class="role-info">
        <text class="role-name">我是家人</text>
        <text class="role-desc">帮爸妈把关，随时看护</text>
      </view>
      <text class="arrow">›</text>
    </view>

    <view class="tip">
      <text>演示账号自动登录：{{ tipText }}</text>
    </view>
  </view>
</template>

<script>
import { get } from '../../api/client'
import { loadDemoFamily, setCurrentUser } from '../../store/user'

export default {
  data() {
    return { tipText: '正在连接服务…' }
  },
  async onLoad() {
    try {
      const family = await loadDemoFamily(get)
      const elder = family.elders[0]
      const child = family.children[0]
      uni.setStorageSync('lyj_family', JSON.stringify({ elder, child }))
      this.tipText = `${elder ? elder.name : '老人'} / ${child ? child.name : '家人'}`
    } catch (e) {
      this.tipText = '后端未连接（请先启动后端服务）'
    }
  },
  methods: {
    pick(role) {
      const raw = uni.getStorageSync('lyj_family')
      let user = null
      try {
        const family = raw ? JSON.parse(raw) : {}
        user = role === 'child' ? family.child : family.elder
      } catch (e) {
        /* ignore */
      }
      if (!user) {
        uni.showToast({ title: '未获取到演示家庭，请先启动后端', icon: 'none' })
        return
      }
      user.role = role
      setCurrentUser(user)
      // 登录成功 —— 页面栈里只有登录页，而它不该能被返回键找回来
      uni.reLaunch({
        url: role === 'child' ? '/pages/child/dashboard' : '/pages/elder/home',
      })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.login {
  min-height: 100vh;
  background: $lyj-bg;
  display: flex;
  flex-direction: column;
  padding: 120rpx $lyj-space-xl 60rpx;
  box-sizing: border-box;
}
.logo-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 100rpx;
}
.logo {
  font-size: 140rpx;
}
.app-name {
  font-size: 64rpx;
  font-weight: 800;
  color: $lyj-primary;
  margin-top: $lyj-space-sm;
  letter-spacing: $lyj-space-xs;
}
.slogan {
  font-size: $lyj-font-md;
  color: $lyj-text-light;
  margin-top: $lyj-space-xs;
}
/* 选身份是这页唯一的操作，整张卡就是按钮 —— 按主按钮高度给 */
.role-card {
  background: $lyj-card;
  border-radius: $lyj-radius-lg;
  min-height: $lyj-btn-main;
  padding: $lyj-space-xl $lyj-space-lg;
  display: flex;
  align-items: center;
  gap: $lyj-space-lg;
  margin-bottom: 36rpx;
  box-shadow: $lyj-shadow-raised;
  border: 4rpx solid transparent;
}
.role-card.child {
  border-color: $lyj-info-line;
}
.role-icon {
  font-size: 88rpx;
}
.role-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.role-name {
  font-size: 44rpx;
  font-weight: 700;
  color: $lyj-text;
}
.role-desc {
  font-size: $lyj-font-md;
  color: $lyj-text-light;
}
.arrow {
  font-size: 56rpx;
  color: $lyj-line;
}
.tip {
  margin-top: auto;
  text-align: center;
}
.tip text {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
</style>
