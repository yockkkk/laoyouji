<template>
  <view class="login">
    <view class="logo-area">
      <text class="logo">🤵</text>
      <text class="app-name">老友记</text>
      <text class="slogan">您的贴心生活管家</text>
    </view>

    <view class="form-card">
      <view class="input-row">
        <text class="label">账号</text>
        <input class="input" v-model="username" placeholder="请输入用户名/手机号" />
      </view>
      <view class="input-row">
        <text class="label">密码</text>
        <input class="input" v-model="password" password placeholder="请输入密码" />
      </view>
      <button class="btn-main login-btn" :loading="loading" @tap="submitLogin">登录</button>
      <button class="btn-ghost reg-btn" @tap="goRegister">没有账号？去注册</button>
    </view>

    <view class="demo-card">
      <text class="demo-title">演示账号快捷填入</text>
      <view class="demo-actions">
        <button class="demo-pill" size="mini" @tap="fillDemo('elder')">👵 张桂芳（老人）</button>
        <button class="demo-pill" size="mini" @tap="fillDemo('child')">👨 李明（家人）</button>
      </view>
    </view>
  </view>
</template>

<script>
import { post } from '../../api/client'
import { setAuthSession } from '../../store/user'

export default {
  data() {
    return {
      username: '',
      password: '',
      loading: false,
    }
  },
  methods: {
    fillDemo(role) {
      if (role === 'elder') {
        this.username = 'zhangguifang'
        this.password = 'elder123456'
      } else {
        this.username = 'liming'
        this.password = 'child123456'
      }
    },
    goRegister() {
      uni.navigateTo({ url: '/pages/login/register' })
    },
    async submitLogin() {
      if (!this.username.trim() || !this.password) {
        uni.showToast({ title: '请填写账号和密码', icon: 'none' })
        return
      }
      this.loading = true
      try {
        const res = await post('/api/auth/login', {
          username: this.username.trim(),
          password: this.password,
        })
        setAuthSession(res)
        const role = res.user ? res.user.role : 'elder'
        uni.showToast({ title: '登录成功', icon: 'success' })
        setTimeout(() => {
          uni.reLaunch({
            url: role === 'child' ? '/pages/child/dashboard' : '/pages/elder/home',
          })
        }, 300)
      } catch (err) {
        uni.showToast({ title: err.message || '登录失败', icon: 'none' })
      } finally {
        this.loading = false
      }
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
  justify-content: center;
  padding: 40rpx $lyj-space-lg;
  box-sizing: border-box;
}
.logo-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 40rpx;
}
.logo {
  font-size: 110rpx;
}
.app-name {
  font-size: 56rpx;
  font-weight: 800;
  color: $lyj-primary;
  margin-top: $lyj-space-xs;
}
.slogan {
  font-size: $lyj-font-md;
  color: $lyj-text-light;
  margin-top: $lyj-space-xs;
}
.form-card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  padding: $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-md;
}
.input-row {
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.label {
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-text;
}
.input {
  height: $lyj-hit-min;
  background: $lyj-field;
  border-radius: $lyj-radius;
  padding: 0 $lyj-space-md;
  font-size: $lyj-font-md;
}
.login-btn {
  margin-top: $lyj-space-sm;
}
.reg-btn {
  margin-top: $lyj-space-xs;
}
.demo-card {
  margin-top: $lyj-space-lg;
  background: rgba(255, 255, 255, 0.7);
  border-radius: $lyj-radius;
  padding: $lyj-space-md;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: $lyj-space-sm;
}
.demo-title {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.demo-actions {
  display: flex;
  width: 100%;
  gap: $lyj-space-sm;
  justify-content: center;
}
.demo-pill {
  flex: 1;
  font-size: $lyj-font-sm;
  background: $lyj-primary-soft;
  color: $lyj-primary;
  border: 2rpx solid $lyj-primary;
  border-radius: $lyj-radius-pill;
  padding: 0 $lyj-space-xs;
  height: 64rpx;
  line-height: 60rpx;
  text-align: center;
  white-space: nowrap;
  transition: transform 0.1s;
}
.demo-pill:active {
  transform: scale(0.96);
}
</style>
