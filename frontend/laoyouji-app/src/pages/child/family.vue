<template>
  <view class="family-page">
    <LyjBack />
    <view class="head">
      <view class="head-info">
        <text class="title">家庭成员管理</text>
        <text class="sub">与长辈建立看护与知会关联</text>
      </view>
      <view class="head-actions">
        <button class="logout-btn" size="mini" @tap="logout">退出登录</button>
      </view>
    </view>

    <LyjSegment current="family" />

    <!-- 发起绑定申请 -->
    <view class="section">
      <text class="section-title">➕ 关联新长辈/家人</text>
      <view class="form-row">
        <input class="input" v-model="targetUsername" placeholder="对方账号（如: zhangguifang）" />
        <input class="input short" v-model="relation" placeholder="您与对方关系（如: 儿子/女儿）" />
      </view>
      <button class="btn-main bind-btn" :loading="binding" @tap="submitBindRequest">
        发送绑定申请
      </button>
    </view>

    <!-- 已绑定与待处理列表 -->
    <view class="section">
      <text class="section-title">👨‍👩‍👧‍👦 当前关联成员</text>
      <view v-if="!members.length" class="empty"><text>暂无关联成员</text></view>
      <view v-for="m in members" :key="m.id" class="member-item">
        <view class="member-main">
          <view class="member-name-row">
            <text class="member-name">{{ m.user ? m.user.name : '家庭成员' }}</text>
            <text class="role-badge elder" v-if="m.user && m.user.role === 'elder'">👵 长辈</text>
            <text class="role-badge child" v-else>👨 家人</text>
          </view>
          <text class="member-sub">
            绑定身份：{{ formatRelation(m) }} · 账号: {{ m.user ? m.user.username : '' }} · 状态: {{ statusText(m.status) }}
          </text>
        </view>
        <!-- 删掉 accept/reject 后这里一度剩个空 flex 容器：非 active 成员
             渲染一条什么都没有的占位，列表对不齐。有动作才渲染容器。 -->
        <view v-if="m.status === 'active'" class="member-actions">
          <button
            class="mini-btn danger"
            size="mini"
            @tap="unbind(m)"
          >
            解除
          </button>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import LyjSegment from '../../components/LyjSegment.vue'
import { get, post, del } from '../../api/client'
import { getCurrentUser, clearCurrentUser } from '../../store/user'

export default {
  components: { LyjSegment },
  data() {
    return {
      members: [],
      targetUsername: '',
      relation: '',
      binding: false,
      currentUserId: '',
    }
  },
  onShow() {
    const user = getCurrentUser()
    if (!user || user.role !== 'child') {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.currentUserId = user.id
    this.loadMembers()
  },
  methods: {
    logout() {
      clearCurrentUser()
      uni.reLaunch({ url: '/pages/login/login' })
    },
    async loadMembers() {
      try {
        const res = await get('/api/family/members')
        this.members = res.items || []
      } catch (err) {
        uni.showToast({ title: err.message || '加载成员失败', icon: 'none' })
      }
    },
    statusText(s) {
      return { active: '已绑定', pending: '待确认', rejected: '已拒绝', revoked: '已解除' }[s] || s
    },
    formatRelation(m) {
      const rel = (m.relation || '').trim()
      if (!rel) return '家人'
      if (['儿子', '女儿', '孙子', '孙女', '儿媳', '女婿'].includes(rel)) {
        return `我是长辈的【${rel}】`
      }
      if (['母亲', '父亲', '妈妈', '爸爸', '爷爷', '奶奶', '姥姥', '姥爷'].includes(rel)) {
        return `长辈是我的【${rel}】`
      }
      return `关系: ${rel}`
    },
    async submitBindRequest() {
      if (!this.targetUsername.trim() || !this.relation.trim()) {
        uni.showToast({ title: '请填写对方账号和关系', icon: 'none' })
        return
      }
      this.binding = true
      try {
        await post('/api/family/requests', {
          target_username: this.targetUsername.trim(),
          relation: this.relation.trim(),
        })
        uni.showToast({ title: '申请已发送，等待确认', icon: 'success' })
        this.targetUsername = ''
        this.relation = ''
        this.loadMembers()
      } catch (err) {
        uni.showToast({ title: err.message || '申请失败', icon: 'none' })
      } finally {
        this.binding = false
      }
    },

    unbind(m) {
      uni.showModal({
        title: '确认解除绑定',
        content: `确定解除与 ${m.user ? m.user.name : ''} 的关联吗？解除后将无法查看长辈的健康与位置概况，也收不到就医知会。`,
        success: async (res) => {
          if (res.confirm) {
            try {
              await del(`/api/family/bindings/${m.binding_id}`)
              uni.showToast({ title: '已解除绑定', icon: 'success' })
              this.loadMembers()
            } catch (err) {
              uni.showToast({ title: err.message || '解除失败', icon: 'none' })
            }
          }
        },
      })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.family-page {
  min-height: 100vh;
  background: $lyj-child-bg;
  padding-bottom: $lyj-space-xl;
  box-sizing: border-box;
}
.head {
  background: $lyj-child-head;
  padding: $lyj-space-lg $lyj-space-lg $lyj-space-md;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.head-info {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.head-actions {
  margin-left: $lyj-space-md;
}
.logout-btn {
  min-height: $lyj-hit-min;
  display: flex;
  align-items: center;
  background: rgba(239, 68, 68, 0.25);
  color: #fff;
  border: 1px solid rgba(239, 68, 68, 0.4);
  font-size: $lyj-font-sm;
  font-weight: 600;
  border-radius: $lyj-radius;
  padding: 0 $lyj-space-sm;
}
.title {
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-text-on;
}
.sub {
  font-size: $lyj-font-sm;
  color: $lyj-child-head-sub;
}
.section {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
}
.section-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
  margin-bottom: $lyj-space-sm;
  display: block;
}
.form-row {
  display: flex;
  gap: $lyj-space-sm;
}
.input {
  flex: 1;
  height: $lyj-hit-min;
  background: $lyj-field;
  border-radius: $lyj-radius;
  padding: 0 $lyj-space-md;
  font-size: $lyj-font-md;
}
.input.short {
  flex: 0.6;
}
.bind-btn {
  margin-top: $lyj-space-sm;
}
.member-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-child-line;
}
.member-name-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 6rpx;
}
.role-badge {
  font-size: 20rpx;
  padding: 2rpx 14rpx;
  border-radius: 20rpx;
  font-weight: 500;
  &.elder {
    background: rgba(33, 150, 243, 0.12);
    color: #1976d2;
    border: 1rpx solid rgba(25, 118, 210, 0.3);
  }
  &.child {
    background: rgba(76, 175, 80, 0.12);
    color: #388e3c;
    border: 1rpx solid rgba(56, 142, 60, 0.3);
  }
}
.member-name {
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-child-text;
}
.member-sub {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
}
.member-actions {
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
.mini-btn.danger {
  background: $lyj-danger;
  color: #fff;
}
.empty {
  color: $lyj-child-muted;
  font-size: $lyj-font-sm;
  padding: $lyj-space-md 0;
  text-align: center;
}
</style>
