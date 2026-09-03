<template>
  <view class="family-page">
    <view class="head">
      <view class="head-info">
        <text class="title">家庭成员管理</text>
        <text class="sub">与长辈建立看护与审批关联</text>
      </view>
    </view>

    <LyjSegment current="family" />

    <!-- 发起绑定申请 -->
    <view class="section">
      <text class="section-title">➕ 关联新长辈/家人</text>
      <view class="form-row">
        <input class="input" v-model="targetUsername" placeholder="请输入对方账号（用户名）" />
        <input class="input short" v-model="relation" placeholder="关系（如：儿子/女儿）" />
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
          <text class="member-name">{{ m.user ? m.user.name : '家庭成员' }}（{{ m.relation }}）</text>
          <text class="member-sub">账号: {{ m.user ? m.user.username : '' }} · 状态: {{ statusText(m.status) }}</text>
        </view>
        <view class="member-actions">
          <button
            v-if="m.status === 'pending' && m.invited_by !== currentUserId"
            class="mini-btn ok"
            size="mini"
            @tap="accept(m)"
          >
            同意
          </button>
          <button
            v-if="m.status === 'pending' && m.invited_by !== currentUserId"
            class="mini-btn no"
            size="mini"
            @tap="reject(m)"
          >
            拒绝
          </button>
          <button
            v-if="m.status === 'active'"
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
import { getCurrentUser } from '../../store/user'

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
    if (!user) {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.currentUserId = user.id
    this.loadMembers()
  },
  methods: {
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
    async accept(m) {
      try {
        await post(`/api/family/requests/${m.binding_id}/accept`, {})
        uni.showToast({ title: '已同意绑定', icon: 'success' })
        this.loadMembers()
      } catch (err) {
        uni.showToast({ title: err.message || '操作失败', icon: 'none' })
      }
    },
    async reject(m) {
      try {
        await post(`/api/family/requests/${m.binding_id}/reject`, {})
        uni.showToast({ title: '已拒绝申请', icon: 'none' })
        this.loadMembers()
      } catch (err) {
        uni.showToast({ title: err.message || '操作失败', icon: 'none' })
      }
    },
    unbind(m) {
      uni.showModal({
        title: '确认解除绑定',
        content: `确定解除与 ${m.user ? m.user.name : ''} 的关联吗？解除后将无法查看数据与代审批。`,
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
.member-name {
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-child-text;
  display: block;
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
  padding: $lyj-space-sm 0;
}
</style>
