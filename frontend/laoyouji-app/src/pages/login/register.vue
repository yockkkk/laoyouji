<template>
  <view class="register-page">
    <view class="topbar">
      <text class="title">新用户注册</text>
    </view>

    <view class="form-card">
      <view class="role-selector">
        <text class="label">我的身份</text>
        <view class="role-options">
          <view
            class="role-pill"
            :class="{ active: form.role === 'elder' }"
            @tap="form.role = 'elder'"
          >
            <text>👵 我是老人</text>
          </view>
          <view
            class="role-pill"
            :class="{ active: form.role === 'child' }"
            @tap="form.role = 'child'"
          >
            <text>👨 我是家人</text>
          </view>
        </view>
      </view>

      <view class="input-row">
        <text class="label">账号名</text>
        <input class="input" v-model="form.username" placeholder="英文/数字，3-32位" />
      </view>

      <view class="input-row">
        <text class="label">登录密码</text>
        <input class="input" v-model="form.password" password placeholder="至少8位密码" />
      </view>

      <view class="input-row">
        <text class="label">姓名/称呼</text>
        <input class="input" v-model="form.name" placeholder="例如：张桂芳 / 李明" />
      </view>

      <view class="input-row">
        <text class="label">手机号（选填）</text>
        <input class="input" v-model="form.phone" type="number" placeholder="便于家人联系" />
      </view>

      <view class="input-row">
        <text class="label">居住城市</text>
        <input class="input" v-model="form.city" placeholder="例如：南京 / 北京" />
      </view>

      <button class="btn-main submit-btn" :loading="loading" @tap="submitRegister">
        完成注册并登录
      </button>
    </view>
  </view>
</template>

<script>
import { post } from '../../api/client'
import { setAuthSession } from '../../store/user'

export default {
  data() {
    return {
      form: {
        role: 'elder',
        username: '',
        password: '',
        name: '',
        phone: '',
        city: '南京',
        dialect: 'mandarin',
      },
      loading: false,
    }
  },
  methods: {
    async submitRegister() {
      if (!this.form.username.trim() || !this.form.password || !this.form.name.trim()) {
        uni.showToast({ title: '请填写账号、密码和姓名', icon: 'none' })
        return
      }
      if (this.form.password.length < 8) {
        uni.showToast({ title: '密码至少需要8位', icon: 'none' })
        return
      }
      this.loading = true
      try {
        const res = await post('/api/auth/register', {
          ...this.form,
          username: this.form.username.trim(),
          name: this.form.name.trim(),
        })
        setAuthSession(res)
        uni.showToast({ title: '注册成功', icon: 'success' })
        setTimeout(() => {
          uni.reLaunch({
            url: this.form.role === 'child' ? '/pages/child/dashboard' : '/pages/elder/home',
          })
        }, 300)
      } catch (err) {
        uni.showToast({ title: err.message || '注册失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.register-page {
  min-height: 100vh;
  background: $lyj-bg;
  padding: 40rpx $lyj-space-lg;
  box-sizing: border-box;
}
.topbar {
  margin-bottom: $lyj-space-md;
}
.title {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
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
.role-options {
  display: flex;
  gap: $lyj-space-md;
  margin-top: $lyj-space-xs;
}
.role-pill {
  flex: 1;
  height: $lyj-hit-min;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: $lyj-radius;
  background: $lyj-field;
  font-size: $lyj-font-md;
  color: $lyj-text;
  border: 3rpx solid transparent;
}
.role-pill.active {
  background: $lyj-primary-soft;
  color: $lyj-primary;
  border-color: $lyj-primary;
  font-weight: 700;
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
.submit-btn {
  margin-top: $lyj-space-sm;
}
</style>
