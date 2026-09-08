<template>
  <view class="login-page">
    <!-- 顶部环境光装饰 -->
    <view class="ambient-glow"></view>

    <view class="login-container">
      <!-- 品牌徽标与温馨标题 -->
      <view class="brand-header">
        <view class="brand-badge-wrap">
          <view class="brand-badge">
            <text class="brand-emoji">🤝</text>
          </view>
          <view class="brand-badge-ring"></view>
        </view>
        <text class="brand-name">老友记</text>
        <view class="brand-slogan-wrap">
          <text class="brand-slogan">长辈生活助手</text>
          <text class="slogan-divider">·</text>
          <text class="brand-slogan">儿女远程守护</text>
        </view>
        <text class="brand-desc">看得清 · 听得懂 · 办得快 · 家人放心</text>
      </view>

      <!-- 核心登录主卡片 -->
      <view class="login-card">
        <!-- 登录模式切换 Tab -->
        <view class="mode-tabs">
          <view
            class="tab-item"
            :class="{ active: activeTab === 'quick' }"
            @tap="activeTab = 'quick'"
          >
            <text class="tab-text">演示一键直达</text>
          </view>
          <view
            class="tab-item"
            :class="{ active: activeTab === 'account' }"
            @tap="activeTab = 'account'"
          >
            <text class="tab-text">账号密码登录</text>
          </view>
        </view>

        <!-- 模式一：演示一键快捷登录（真实家庭角色直达，极度接地气） -->
        <view v-if="activeTab === 'quick'" class="quick-login-section">
          <text class="section-tip">选择您的家庭角色，免密秒级体验：</text>

          <!-- 长辈卡片 -->
          <view class="role-card role-elder" @tap="quickLogin('elder')">
            <view class="role-card-left">
              <view class="role-avatar-wrap elder-avatar">
                <text class="role-avatar">👵</text>
              </view>
              <view class="role-info">
                <view class="role-title-row">
                  <text class="role-name">张桂芳</text>
                  <text class="role-tag elder-tag">长辈模式</text>
                </view>
                <text class="role-desc">72岁 · 母亲 · 适老陪伴管家</text>
                <view class="role-features">
                  <text class="feat-pill">大字语音</text>
                  <text class="feat-pill">就医买票</text>
                  <text class="feat-pill">食堂居家</text>
                </view>
              </view>
            </view>
            <view class="role-enter-btn elder-btn">
              <text class="btn-text">长辈进入</text>
              <text class="btn-arrow">›</text>
            </view>
          </view>

          <!-- 子女卡片 -->
          <view class="role-card role-child" @tap="quickLogin('child')">
            <view class="role-card-left">
              <view class="role-avatar-wrap child-avatar">
                <text class="role-avatar">👨</text>
              </view>
              <view class="role-info">
                <view class="role-title-row">
                  <text class="role-name">李明</text>
                  <text class="role-tag child-tag">家属守护</text>
                </view>
                <text class="role-desc">42岁 · 儿子 · 跨城远程看板</text>
                <view class="role-features">
                  <text class="feat-pill">高危审批</text>
                  <text class="feat-pill">轨迹守护</text>
                  <text class="feat-pill">健康用药</text>
                </view>
              </view>
            </view>
            <view class="role-enter-btn child-btn">
              <text class="btn-text">家属进入</text>
              <text class="btn-arrow">›</text>
            </view>
          </view>
        </view>

        <!-- 模式二：传统表单登录 -->
        <view v-else class="form-login-section">
          <view class="input-group">
            <text class="input-label">登录账号</text>
            <view class="input-wrapper" :class="{ focused: focusedField === 'username' }">
              <text class="input-icon">👤</text>
              <input
                class="native-input"
                v-model="username"
                placeholder="请输入用户名或手机号"
                placeholder-class="input-placeholder"
                @focus="focusedField = 'username'"
                @blur="focusedField = ''"
              />
              <text v-if="username" class="clear-btn" @tap="username = ''">✕</text>
            </view>
          </view>

          <view class="input-group">
            <view class="label-row">
              <text class="input-label">登录密码</text>
            </view>
            <view class="input-wrapper" :class="{ focused: focusedField === 'password' }">
              <text class="input-icon">🔒</text>
              <input
                class="native-input"
                v-model="password"
                :password="!showPassword"
                placeholder="请输入登录密码"
                placeholder-class="input-placeholder"
                @focus="focusedField = 'password'"
                @blur="focusedField = ''"
                @confirm="submitLogin"
              />
              <text class="eye-btn" @tap="showPassword = !showPassword">
                {{ showPassword ? '👁️' : '🙈' }}
              </text>
            </view>
          </view>

          <!-- 登录大按钮 -->
          <button
            class="submit-button"
            :loading="loading"
            :disabled="loading"
            @tap="submitLogin"
          >
            <text class="submit-text">{{ loading ? '正在验证…' : '登 录 老 友 记' }}</text>
          </button>

          <!-- 注册引导 -->
          <view class="register-prompt">
            <text class="prompt-text">还没有老友记账号？</text>
            <text class="prompt-link" @tap="goRegister">新用户快速注册 ›</text>
          </view>
        </view>
      </view>

      <!-- 底部安全与适老背书 -->
      <view class="security-footer">
        <view class="security-badge">
          <text class="sec-icon">🛡️</text>
          <text class="sec-text">国家适老标准规范体验 · 家庭数据隐私安全加密</text>
        </view>
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
      activeTab: 'quick', // 'quick' | 'account'
      username: '',
      password: '',
      loading: false,
      focusedField: '',
      showPassword: false,
    }
  },
  methods: {
    async quickLogin(role) {
      if (this.loading) return
      let uname = ''
      let pwd = ''
      let welcomeTitle = ''
      if (role === 'elder') {
        uname = 'zhangguifang'
        pwd = 'elder123456'
        welcomeTitle = '长辈张桂芳已就绪'
      } else {
        uname = 'liming'
        pwd = 'child123456'
        welcomeTitle = '家属李明已就绪'
      }

      this.loading = true
      uni.showLoading({ title: '正在连接服务…' })
      try {
        const res = await post('/api/auth/login', {
          username: uname,
          password: pwd,
        })
        setAuthSession(res)
        uni.hideLoading()
        uni.showToast({ title: welcomeTitle, icon: 'success', duration: 1500 })
        const dest = role === 'child' ? '/pages/child/dashboard' : '/pages/elder/home'
        setTimeout(() => {
          uni.reLaunch({ url: dest })
        }, 300)
      } catch (err) {
        uni.hideLoading()
        uni.showToast({ title: err.message || '快捷登录失败', icon: 'none' })
      } finally {
        this.loading = false
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
      uni.showLoading({ title: '正在登录…' })
      try {
        const res = await post('/api/auth/login', {
          username: this.username.trim(),
          password: this.password,
        })
        setAuthSession(res)
        const role = res.user ? res.user.role : 'elder'
        uni.hideLoading()
        uni.showToast({ title: '登录成功', icon: 'success' })
        setTimeout(() => {
          uni.reLaunch({
            url: role === 'child' ? '/pages/child/dashboard' : '/pages/elder/home',
          })
        }, 300)
      } catch (err) {
        uni.hideLoading()
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

.login-page {
  min-height: 100vh;
  background: linear-gradient(180deg, #FAF7F2 0%, #F5ECE3 100%);
  position: relative;
  overflow-x: hidden;
  box-sizing: border-box;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 40rpx 28rpx;
}

/* 顶部柔和暖阳微光 */
.ambient-glow {
  position: absolute;
  top: -100rpx;
  left: 50%;
  transform: translateX(-50%);
  width: 720rpx;
  height: 480rpx;
  background: radial-gradient(circle, rgba(255, 122, 61, 0.22) 0%, rgba(255, 220, 180, 0.08) 60%, transparent 100%);
  border-radius: 50%;
  pointer-events: none;
  filter: blur(48rpx);
}

.login-container {
  width: 100%;
  max-width: 460px;
  margin: 0 auto;
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: 28rpx;
}

/* ---------------- 品牌区 ---------------- */
.brand-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 10rpx 0;
}

.brand-badge-wrap {
  position: relative;
  width: 136rpx;
  height: 136rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16rpx;
}

.brand-badge {
  width: 116rpx;
  height: 116rpx;
  background: linear-gradient(135deg, #FF7A3D 0%, #E85D04 100%);
  border-radius: 38rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 14rpx 32rpx rgba(232, 93, 4, 0.28);
  border: 4rpx solid #FFFFFF;
}

.brand-emoji {
  font-size: 58rpx;
}

.brand-badge-ring {
  position: absolute;
  width: 136rpx;
  height: 136rpx;
  border: 2rpx dashed rgba(255, 107, 53, 0.38);
  border-radius: 46rpx;
  animation: rotateRing 24s linear infinite;
}

@keyframes rotateRing {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.brand-name {
  font-size: 58rpx;
  font-weight: 900;
  color: #1E293B;
  letter-spacing: 4rpx;
  line-height: 1.2;
}

.brand-slogan-wrap {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-top: 10rpx;
}

.brand-slogan {
  font-size: 32rpx;
  font-weight: 800;
  color: #D9480F;
  letter-spacing: 1rpx;
}

.slogan-divider {
  font-size: 28rpx;
  color: #FFB38A;
}

.brand-desc {
  font-size: 26rpx;
  color: #78716C;
  margin-top: 8rpx;
  letter-spacing: 1rpx;
}

/* ---------------- 登录卡片 ---------------- */
.login-card {
  background: #FFFFFF;
  border-radius: 36rpx;
  padding: 36rpx 32rpx;
  box-shadow: 0 16rpx 48rpx rgba(71, 55, 41, 0.08), 0 2rpx 8rpx rgba(0, 0, 0, 0.03);
  border: 2rpx solid #EFE6DA;
}

/* 模式 Tabs */
.mode-tabs {
  display: flex;
  background: #F5EFE8;
  border-radius: 20rpx;
  padding: 6rpx;
  margin-bottom: 32rpx;
}

.tab-item {
  flex: 1;
  text-align: center;
  padding: 18rpx 0;
  border-radius: 16rpx;
  font-size: 30rpx;
  font-weight: 700;
  color: #78716C;
  position: relative;
  transition: all 0.2s ease;
  cursor: pointer;
}

.tab-item.active {
  background: #FFFFFF;
  color: #D9480F;
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.06);
}

/* ---------------- 一键直达角色卡 ---------------- */
.quick-login-section {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.section-tip {
  font-size: 26rpx;
  color: #8C827A;
  margin-bottom: 4rpx;
  padding-left: 4rpx;
}

.role-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx;
  border-radius: 24rpx;
  border: 2rpx solid transparent;
  transition: all 0.2s ease;
  cursor: pointer;
}

.role-card:active {
  transform: translateY(2rpx) scale(0.99);
}

.role-elder {
  background: linear-gradient(135deg, #FFF9F3 0%, #FFF2E3 100%);
  border-color: #FED7AA;
}

.role-elder:hover {
  border-color: #FDBA74;
  box-shadow: 0 8rpx 20rpx rgba(255, 107, 53, 0.12);
}

.role-child {
  background: linear-gradient(135deg, #F8FAFC 0%, #EDF2F7 100%);
  border-color: #CBD5E1;
}

.role-child:hover {
  border-color: #94A3B8;
  box-shadow: 0 8rpx 20rpx rgba(30, 41, 59, 0.08);
}

.role-card-left {
  display: flex;
  align-items: center;
  gap: 20rpx;
  flex: 1;
}

.role-avatar-wrap {
  width: 96rpx;
  height: 96rpx;
  border-radius: 24rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.elder-avatar {
  background: #FFE8D6;
  border: 2rpx solid #FED7AA;
}

.child-avatar {
  background: #E2E8F0;
  border: 2rpx solid #CBD5E1;
}

.role-avatar {
  font-size: 48rpx;
}

.role-info {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
  min-width: 0;
}

.role-title-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.role-name {
  font-size: 34rpx;
  font-weight: 800;
  color: #1E293B;
}

.role-tag {
  font-size: 22rpx;
  font-weight: 700;
  padding: 2rpx 12rpx;
  border-radius: 999rpx;
}

.elder-tag {
  background: #FFEDD5;
  color: #C2410C;
}

.child-tag {
  background: #E2E8F0;
  color: #334155;
}

.role-desc {
  font-size: 24rpx;
  color: #64748B;
}

.role-features {
  display: flex;
  gap: 10rpx;
  margin-top: 6rpx;
}

.feat-pill {
  font-size: 20rpx;
  color: #78716C;
  background: rgba(255, 255, 255, 0.85);
  padding: 2rpx 10rpx;
  border-radius: 8rpx;
  border: 1rpx solid rgba(0, 0, 0, 0.05);
}

.role-enter-btn {
  display: flex;
  align-items: center;
  gap: 4rpx;
  padding: 14rpx 22rpx;
  border-radius: 16rpx;
  font-size: 26rpx;
  font-weight: 700;
  flex-shrink: 0;
}

.elder-btn {
  background: #FF6B35;
  color: #FFFFFF;
  box-shadow: 0 4rpx 12rpx rgba(255, 107, 53, 0.25);
}

.child-btn {
  background: #334155;
  color: #FFFFFF;
  box-shadow: 0 4rpx 12rpx rgba(51, 65, 85, 0.2);
}

.btn-arrow {
  font-size: 32rpx;
  line-height: 1;
}

/* ---------------- 传统表单登录 ---------------- */
.form-login-section {
  display: flex;
  flex-direction: column;
  gap: 28rpx;
}

.input-group {
  display: flex;
  flex-direction: column;
  gap: 10rpx;
}

.label-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.input-label {
  font-size: 28rpx;
  font-weight: 700;
  color: #334155;
}

.input-wrapper {
  height: 100rpx;
  background: #F8FAFC;
  border: 2rpx solid #E2E8F0;
  border-radius: 20rpx;
  display: flex;
  align-items: center;
  padding: 0 24rpx;
  gap: 16rpx;
  transition: all 0.2s ease;
}

.input-wrapper.focused {
  background: #FFFFFF;
  border-color: #FF6B35;
  box-shadow: 0 0 0 6rpx rgba(255, 107, 53, 0.14);
}

.input-icon {
  font-size: 36rpx;
  flex-shrink: 0;
}

.native-input {
  flex: 1;
  height: 100%;
  font-size: 30rpx;
  color: #1E293B;
  background: transparent;
}

.input-placeholder {
  color: #94A3B8;
  font-size: 28rpx;
}

.clear-btn,
.eye-btn {
  font-size: 32rpx;
  color: #94A3B8;
  padding: 8rpx;
  cursor: pointer;
}

.submit-button {
  width: 100%;
  height: 104rpx;
  background: linear-gradient(135deg, #FF7A3D 0%, #E85D04 100%);
  border-radius: 22rpx;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8rpx 24rpx rgba(232, 93, 4, 0.3);
  margin-top: 10rpx;
  cursor: pointer;
  transition: all 0.2s ease;
}

.submit-button:active {
  transform: translateY(2rpx);
  box-shadow: 0 4rpx 12rpx rgba(232, 93, 4, 0.25);
}

.submit-text {
  font-size: 34rpx;
  font-weight: 800;
  color: #FFFFFF;
  letter-spacing: 4rpx;
}

.register-prompt {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  padding-top: 10rpx;
}

.prompt-text {
  font-size: 28rpx;
  color: #64748B;
}

.prompt-link {
  font-size: 28rpx;
  font-weight: 700;
  color: #FF6B35;
  cursor: pointer;
}

/* ---------------- 底部背书 ---------------- */
.security-footer {
  display: flex;
  justify-content: center;
  margin-top: 8rpx;
}

.security-badge {
  display: flex;
  align-items: center;
  gap: 10rpx;
  padding: 10rpx 20rpx;
  background: rgba(255, 255, 255, 0.65);
  border: 1rpx solid #E7DFD5;
  border-radius: 999rpx;
}

.sec-icon {
  font-size: 24rpx;
}

.sec-text {
  font-size: 22rpx;
  color: #78716C;
}
</style>
