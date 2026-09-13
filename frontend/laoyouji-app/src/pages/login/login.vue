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
        <text class="brand-name">康乐</text>
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
                  <!-- 原来写"就医买票""食堂居家"：买车票（跨城车票）和社区食堂订餐 /
                       居家上门服务都已随康乐收敛砍掉，留着就是把已删的能力当卖点。
                       换成现在真会做的事：挂号、线下活动、家常菜谱。 -->
                  <text class="feat-pill">就医挂号</text>
                  <text class="feat-pill">活动菜谱</text>
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
                  <!-- 「高危审批」撤掉：就医不需要子女审批（康乐"知会不审批"，挂号当场办好、
                       同一步发知会），而现役工具里也没有任何付费动作会走到审批那一条。
                       摆一个产品里不存在的能力在登录页上，是当着评委的面许一个没实现的诺。
                       换成子女在这端真能干的三件事。 -->
                  <text class="feat-pill">健康概况</text>
                  <text class="feat-pill">轨迹守护</text>
                  <text class="feat-pill">就医知会</text>
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
            <text class="submit-text">{{ loading ? '正在验证…' : '登 录 康 乐' }}</text>
          </button>

          <!-- 注册引导 -->
          <view class="register-prompt">
            <text class="prompt-text">还没有康乐账号？</text>
            <text class="prompt-link" @tap="goRegister">新用户快速注册 ›</text>
          </view>
        </view>
      </view>

      <!-- 安卓 APK 快捷下载入口 -->
      <view class="apk-download-bar" @tap="downloadApk">
        <view class="apk-download-left">
          <text class="apk-icon">📱</text>
          <view class="apk-info">
            <text class="apk-title">安装老友记安卓手机客户端</text>
            <text class="apk-sub">超轻量原生封装 · 支持长辈语音与实时守护</text>
          </view>
        </view>
        <view class="apk-btn">
          <text class="apk-btn-text">立即下载</text>
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
import { syncAll } from '../../utils/native'

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
        // 长辈端登录成功后立刻排一次闹钟（契约 §10.3）。不 await —— 别拖慢跳转；
        // 落点 home.vue 的 onShow 还会兜一次，这里先发出去是为了不在 300ms 跳转窗口里空着。
        if (role === 'elder') syncAll()
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

    downloadApk() {
      // #ifdef H5
      window.location.href = '/laoyouji.apk'
      // #endif
      // #ifndef H5
      uni.showToast({ title: '当前已是安装版客户端', icon: 'none' })
      // #endif
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
        // 同 quickLogin：长辈端登录后立刻排闹钟（契约 §10.3），不 await 拖慢跳转。
        if (role === 'elder') syncAll()
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
  background: linear-gradient(180deg, #F2F7FD 0%, #EBF4FE 100%);
  position: relative;
  overflow-x: hidden;
  box-sizing: border-box;
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 40rpx 28rpx;
}

/* 顶部柔和晴空微光 */
.ambient-glow {
  position: absolute;
  top: -100rpx;
  left: 50%;
  transform: translateX(-50%);
  width: 720rpx;
  height: 480rpx;
  background: radial-gradient(circle, rgba(42, 130, 228, 0.18) 0%, rgba(235, 244, 254, 0.08) 60%, transparent 100%);
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
  background: linear-gradient(135deg, #2A82E4 0%, #1967C2 100%);
  border-radius: 38rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 14rpx 32rpx rgba(42, 130, 228, 0.28);
  border: 4rpx solid #FFFFFF;
}

.brand-emoji {
  font-size: 58rpx;
}

.brand-badge-ring {
  position: absolute;
  width: 136rpx;
  height: 136rpx;
  border: 2rpx dashed rgba(42, 130, 228, 0.38);
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
  color: #1967C2;
  letter-spacing: 1rpx;
  white-space: nowrap !important;
  word-break: keep-all !important;
}

.slogan-divider {
  font-size: 28rpx;
  color: #93C5FD;
  white-space: nowrap !important;
}

.brand-desc {
  font-size: 24rpx;
  color: #78716C;
  margin-top: 8rpx;
  letter-spacing: 1rpx;
  white-space: nowrap !important;
  word-break: keep-all !important;
}

/* ---------------- 登录卡片 ---------------- */
.login-card {
  background: #FFFFFF;
  border-radius: 36rpx;
  padding: 36rpx 32rpx;
  box-shadow: 0 16rpx 48rpx rgba(71, 55, 41, 0.08), 0 2rpx 8rpx rgba(0, 0, 0, 0.03);
  border: 2rpx solid #E1ECF7;
}

/* 模式 Tabs */
.mode-tabs {
  display: flex;
  background: #F2F7FD;
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
  color: #2A82E4;
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
  background: linear-gradient(135deg, #F8FAFC 0%, #EDF4FB 100%);
  border-color: #CCE2F8;
}

.role-elder:hover {
  border-color: #93C5FD;
  box-shadow: 0 8rpx 20rpx rgba(42, 130, 228, 0.12);
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
  background: #EBF4FE;
  border: 2rpx solid #CCE2F8;
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
  gap: 10rpx;
  flex-wrap: nowrap;
}

.role-name {
  font-size: 32rpx;
  font-weight: 800;
  color: #1E293B;
  white-space: nowrap !important;
  word-break: keep-all !important;
  flex-shrink: 0;
}

.role-tag {
  font-size: 22rpx;
  font-weight: 700;
  padding: 2rpx 12rpx;
  border-radius: 999rpx;
  white-space: nowrap !important;
  word-break: keep-all !important;
  flex-shrink: 0;
}

.elder-tag {
  background: #EBF4FE;
  color: #1967C2;
}

.child-tag {
  background: #E2E8F0;
  color: #334155;
}

.role-desc {
  font-size: 24rpx;
  color: #64748B;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.role-features {
  display: flex;
  align-items: center;
  gap: 8rpx;
  margin-top: 6rpx;
  flex-wrap: nowrap;
  overflow: hidden;
}

.feat-pill {
  font-size: 20rpx;
  color: #5F758E;
  background: rgba(255, 255, 255, 0.9);
  padding: 2rpx 8rpx;
  border-radius: 8rpx;
  border: 1rpx solid #CCE2F8;
  white-space: nowrap !important;
  word-break: keep-all !important;
  flex-shrink: 0;
}

.role-enter-btn {
  display: flex;
  align-items: center;
  gap: 4rpx;
  padding: 12rpx 18rpx;
  border-radius: 16rpx;
  font-size: 24rpx;
  font-weight: 700;
  flex-shrink: 0;
  white-space: nowrap !important;
  word-break: keep-all !important;
}

.elder-btn {
  background: #2A82E4;
  color: #FFFFFF;
  box-shadow: 0 4rpx 12rpx rgba(42, 130, 228, 0.25);
}

.child-btn {
  background: #132438;
  color: #FFFFFF;
  box-shadow: 0 4rpx 12rpx rgba(19, 36, 56, 0.2);
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
  border-color: #2A82E4;
  box-shadow: 0 0 0 6rpx rgba(42, 130, 228, 0.14);
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
  background: linear-gradient(135deg, #2A82E4 0%, #1967C2 100%);
  border-radius: 22rpx;
  border: none;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8rpx 24rpx rgba(42, 130, 228, 0.28);
  margin-top: 10rpx;
  cursor: pointer;
  transition: all 0.2s ease;
}

.submit-button:active {
  transform: translateY(2rpx);
  box-shadow: 0 4rpx 12rpx rgba(42, 130, 228, 0.25);
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
  color: #2A82E4;
  cursor: pointer;
}

.btn-text {
  white-space: nowrap !important;
  word-break: keep-all !important;
}

/* ---------------- 底部背书 ---------------- */
.security-footer {
  display: flex;
  justify-content: center;
  margin-top: 12rpx;
  padding: 0 10rpx;
}

.security-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  padding: 8rpx 16rpx;
  background: rgba(255, 255, 255, 0.75);
  border: 1rpx solid #E1ECF7;
  border-radius: 999rpx;
  max-width: 100%;
  box-sizing: border-box;
}

.sec-icon {
  font-size: 24rpx;
  flex-shrink: 0;
}

.sec-text {
  font-size: 20rpx;
  color: #78716C;
  white-space: nowrap !important;
  word-break: keep-all !important;
  text-align: center;
}
</style>
