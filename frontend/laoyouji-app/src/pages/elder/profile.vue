<template>
  <view class="profile-page">
    <view class="topbar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">‹</text>
        <text class="back-text">首页</text>
      </view>
      <text class="title">我的</text>
    </view>

    <view class="user-card">
      <text class="avatar">👵</text>
      <view class="user-info">
        <text class="name">{{ user ? user.name : '' }}</text>
        <text class="city">{{ user ? user.city : '' }} · {{ dialectLabel }}</text>
        <text class="account">账号: {{ user ? user.username || '未设置' : '' }}</text>
      </view>
    </view>

    <!-- 家庭成员与绑定 -->
    <view class="section">
      <text class="section-title">👨‍👩‍👧‍👦 我的家人</text>
      <view class="bind-row">
        <input class="input" v-model="targetUsername" placeholder="输入子女账号关联" />
        <input class="input short" v-model="relation" placeholder="关系（如：儿子）" />
        <button class="mini-btn ok" size="mini" @tap="submitBind">绑定</button>
      </view>
      <view v-if="!members.length" class="empty-note"><text>暂无关联家人</text></view>
      <view v-for="m in members" :key="m.id" class="member-chip">
        <view class="m-left">
          <text class="m-name">{{ m.user ? m.user.name : '家人' }}（{{ m.relation }}）</text>
          <text class="m-status">{{ statusText(m.status) }}</text>
        </view>
        <view class="m-right">
          <button
            v-if="m.status === 'pending' && m.invited_by !== user.id"
            class="mini-btn ok"
            size="mini"
            @tap="acceptBind(m)"
          >
            同意
          </button>
          <button
            v-if="m.status === 'pending' && m.invited_by !== user.id"
            class="mini-btn no"
            size="mini"
            @tap="rejectBind(m)"
          >
            拒绝
          </button>
          <button
            v-if="m.status === 'active'"
            class="mini-btn no"
            size="mini"
            @tap="selectChildForPrivacy(m)"
          >
            设权限
          </button>
        </view>
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
    <view class="section" v-if="selectedChild">
      <text class="section-title">🔒 对【{{ selectedChild.name }}】开放权限</text>
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
      <button class="btn-ghost" @tap="logout">退出当前登录</button>
    </view>
  </view>
</template>

<script>
import { get, put, post } from '../../api/client'
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
      members: [],
      selectedChild: null,
      targetUsername: '',
      relation: '',
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
    try {
      uni.showTabBar({ animation: false })
    } catch (e) {}
    this.user = getCurrentUser()
    if (!this.user) {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.dialect = this.user.dialect || 'mandarin'
    this.loadMembers()
  },
  methods: {
    statusText(s) {
      return { active: '已绑定', pending: '待确认', rejected: '已拒绝', revoked: '已解除' }[s] || s
    },
    async loadMembers() {
      try {
        const res = await get('/api/family/members')
        this.members = res.items || []
        const firstActive = this.members.find((m) => m.status === 'active')
        if (firstActive && firstActive.user) {
          this.selectedChild = firstActive.user
          this.loadPrivacy(firstActive.user.id)
        }
      } catch (err) {
        /* ignore */
      }
    },
    selectChildForPrivacy(m) {
      if (!m.user) return
      this.selectedChild = m.user
      this.loadPrivacy(m.user.id)
    },
    async submitBind() {
      if (!this.targetUsername.trim() || !this.relation.trim()) {
        uni.showToast({ title: '请填写子女账号与关系', icon: 'none' })
        return
      }
      try {
        await post('/api/family/requests', {
          target_username: this.targetUsername.trim(),
          relation: this.relation.trim(),
        })
        uni.showToast({ title: '已发送关联申请', icon: 'success' })
        this.targetUsername = ''
        this.relation = ''
        this.loadMembers()
      } catch (e) {
        uni.showToast({ title: e.message || '申请失败', icon: 'none' })
      }
    },
    async acceptBind(m) {
      try {
        await post(`/api/family/requests/${m.binding_id}/accept`, {})
        uni.showToast({ title: '已确认绑定', icon: 'success' })
        this.loadMembers()
      } catch (e) {
        uni.showToast({ title: e.message || '操作失败', icon: 'none' })
      }
    },
    async rejectBind(m) {
      try {
        await post(`/api/family/requests/${m.binding_id}/reject`, {})
        uni.showToast({ title: '已拒绝', icon: 'none' })
        this.loadMembers()
      } catch (e) {
        uni.showToast({ title: e.message || '操作失败', icon: 'none' })
      }
    },
    setDialect(value) {
      this.dialect = value
      this.user.dialect = value
      setCurrentUser(this.user)
      uni.showToast({ title: '好嘞，我记住了', icon: 'success' })
    },
    async loadPrivacy(childId) {
      if (!childId) return
      try {
        const d = await get(`/api/privacy/${this.user.id}`, { child_id: childId })
        if (d) this.privacy = d
      } catch (e) {
        /* ignore */
      }
    },
    async setPrivacy(field, value) {
      if (!this.selectedChild) {
        uni.showToast({ title: '请先绑定家人', icon: 'none' })
        return
      }
      const before = this.privacy[field]
      this.privacy[field] = value
      try {
        await put(`/api/privacy/${this.user.id}`, {
          child_id: this.selectedChild.id,
          location_level: this.privacy.location_level,
          health_level: this.privacy.health_level,
        })
        uni.showToast({ title: '已更新', icon: 'success' })
      } catch (e) {
        this.privacy[field] = before
        uni.showToast({ title: e.message || '修改失败', icon: 'none' })
      }
    },
    goBack() {
      const pages = getCurrentPages()
      if (pages && pages.length > 1) {
        uni.navigateBack()
      } else {
        uni.switchTab({ url: '/pages/elder/home' })
      }
    },
    logout() {
      clearCurrentUser()
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
  padding: 24rpx $lyj-space-lg;
  display: flex;
  align-items: center;
  gap: $lyj-space-md;
}
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4rpx;
  padding: 10rpx 20rpx;
  background: $lyj-card;
  border: 2rpx solid $lyj-line;
  border-radius: $lyj-radius-pill;
  cursor: pointer;
  flex-shrink: 0;
  transition: opacity 0.15s;
}
.back-btn:active {
  opacity: 0.7;
}
.back-icon {
  font-size: 38rpx;
  line-height: 1;
  color: $lyj-primary;
  font-weight: 800;
}
.back-text {
  font-size: $lyj-font-sm;
  color: $lyj-primary;
  font-weight: 700;
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
.city, .account {
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
.bind-row {
  display: flex;
  gap: $lyj-space-xs;
  margin-top: $lyj-space-sm;
}
.input {
  flex: 1;
  height: $lyj-hit-min;
  background: $lyj-field;
  border-radius: $lyj-radius;
  padding: 0 $lyj-space-sm;
  font-size: $lyj-font-sm;
}
.input.short {
  flex: 0.8;
}
.member-chip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-line;
}
.m-name {
  font-size: $lyj-font-md;
  font-weight: 600;
}
.m-status {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.m-right {
  display: flex;
  gap: $lyj-space-xs;
}
.mini-btn {
  font-size: $lyj-font-sm;
  margin: 0;
}
.mini-btn.ok {
  background: $lyj-success;
  color: #fff;
}
.mini-btn.no {
  background: $lyj-muted-bg;
  color: $lyj-text;
}
.empty-note {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  padding: $lyj-space-sm 0;
}
.options {
  display: flex;
  flex-wrap: wrap;
  gap: $lyj-space-sm;
  margin-top: $lyj-space-md;
}
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

@media screen and (min-width: 768px) {
  .profile-page {
    max-width: 900px;
    margin: 0 auto;
    padding: 20rpx 40rpx 120rpx;
  }
}
</style>
