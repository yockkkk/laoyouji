<template>
  <view class="med-page">
    <view class="topbar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">‹</text>
        <text class="back-text">首页</text>
      </view>
      <view class="topbar-info">
        <text class="title">今天的药</text>
        <text class="sub">吃完点一下，家人就放心了</text>
      </view>
    </view>

    <view v-if="!meds.length" class="empty">
      <text class="empty-icon">💊</text>
      <text class="empty-text">今天没有要吃的药</text>
    </view>

    <view v-for="m in meds" :key="m.id" class="med-card">
      <view class="med-head">
        <text class="drug">{{ m.drug_name }}</text>
        <text class="dose">{{ m.dose }}</text>
      </view>
      <text v-if="m.notes" class="notes">💡 {{ m.notes }}</text>
      <view class="slots">
        <view
          v-for="t in m.times || []"
          :key="t"
          class="slot"
          :class="{ taken: isTaken(m, t), taking: isTaking(m, t) }"
          @tap="take(m, t)"
        >
          <text class="slot-time">{{ t }}</text>
          <text class="slot-state">
            <template v-if="isTaking(m, t)">打卡中...</template>
            <template v-else-if="isTaken(m, t)">✓ 已吃</template>
            <template v-else>点我打卡</template>
          </text>
        </view>
      </view>
      <view class="del-btn-wrap">
        <text class="del-btn" :class="{ busy: deleting }" @tap="deleteMed(m)">🗑️ 删除此药</text>
      </view>
    </view>
    
    <view class="add-btn-wrap">
      <view class="add-btn" @tap="showAdd = true">➕ 添加新药</view>
    </view>

    <!-- 简单的添加弹窗 -->
    <view v-if="showAdd" class="modal-mask">
      <view class="modal">
        <view class="modal-header">添加新药</view>
        <input class="modal-input" v-model="newMed.drug_name" placeholder="药品名称 (如：阿司匹林)" />
        <input class="modal-input" v-model="newMed.dose" placeholder="剂量 (如：1片)" />
        <input class="modal-input" v-model="newMed.times" placeholder="时间 (如：08:00,12:00)" />
        <input class="modal-input" v-model="newMed.notes" placeholder="医嘱 (如：饭后服用)" />
        <view class="modal-footer">
          <view class="modal-btn cancel" @tap="showAdd = false">取消</view>
          <view class="modal-btn confirm" @tap="addMed">确定</view>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import { get, post, del } from '../../api/client'
import { getCurrentUser } from '../../store/user'
import { speak } from '../../api/asr'
import { syncAll } from '../../utils/native'

export default {
  data() {
    return { 
      user: null, 
      meds: [],
      taking: {}, // { 'm.id-time': true }
      deleting: false,
      adding: false,
      showAdd: false,
      newMed: { drug_name: '', dose: '', times: '08:00', notes: '' }
    }
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
    this.load()
    // 进这一页也同步一次闹钟（契约 §10.3）。首页 onShow 那次可能刚过去几秒，
    // 会被 30 秒防抖挡掉，所以这里只是兜底；真正要紧的是下面增删成功后那次强制同步。
    syncAll()
  },
  methods: {
    goBack() {
      const pages = getCurrentPages()
      if (pages && pages.length > 1) {
        uni.navigateBack()
      } else {
        uni.switchTab({ url: '/pages/elder/home' })
      }
    },
    async load() {
      try {
        const d = await get('/api/medications', { elder_id: this.user.id, with_logs: true })
        this.meds = (d.items || []).filter((m) => m.active)
      } catch (e) {
        uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
    },
    isTaken(m, time) {
      return (m.logs || []).some((l) => l.scheduled_time === time && l.status === 'taken')
    },
    isTaking(m, time) {
      return this.taking[`${m.id}-${time}`]
    },
    async take(m, time) {
      if (this.isTaken(m, time) || this.isTaking(m, time)) return
      
      this.taking[`${m.id}-${time}`] = true
      try {
        await post(`/api/medications/${m.id}/taken?scheduled_time=${encodeURIComponent(time)}`)
        uni.showToast({ title: '真棒，吃过啦！', icon: 'success' })
        speak(`好样的，${m.drug_name}吃过了。`)
        await this.load()
      } catch (e) {
        uni.showToast({ title: e.message, icon: 'none' })
      } finally {
        this.taking[`${m.id}-${time}`] = false
      }
    },
    deleteMed(m) {
      if (this.deleting) return
      uni.showModal({
        title: '删除药品',
        content: `确定不再吃「${m.drug_name}」了吗？以前的打卡记录会保留。`,
        confirmText: '删除',
        cancelText: '先留着',
        success: async (res) => {
          if (!res.confirm) return
          this.deleting = true
          uni.showLoading({ title: '正在删除…' })
          try {
            await del(`/api/medications/${m.id}`)
            uni.showToast({ title: '已删除', icon: 'success' })
            await this.load()
            // 删药是用户的显式改动：强制重排，不让 30 秒防抖把这次覆盖掉，
            // 否则已删的这条提醒会继续在原生副本里响（契约 §10.3"用药计划变动后"）。
            await syncAll({ force: true })
          } catch (e) {
            uni.showToast({ title: e.message || '删除失败', icon: 'none' })
          } finally {
            uni.hideLoading()
            this.deleting = false
          }
        },
      })
    },
    async addMed() {
      if (this.adding) return
      const name = (this.newMed.drug_name || '').trim()
      if (!name) {
        return uni.showToast({ title: '请输入药品名称', icon: 'none' })
      }
      // 老人（或帮忙填的子女）很可能用中文逗号、顿号，甚至空格分隔，都收下
      const times = (this.newMed.times || '')
        .split(/[,，、;；\s]+/)
        .map((t) => t.trim())
        .filter(Boolean)
      if (!times.length) {
        return uni.showToast({ title: '请填服药时间，如 08:00', icon: 'none' })
      }
      const bad = times.find((t) => !/^([01]?\d|2[0-3]):[0-5]\d$/.test(t))
      if (bad) {
        return uni.showToast({ title: `时间「${bad}」看不懂，请写成 08:00`, icon: 'none' })
      }
      this.adding = true
      try {
        await post('/api/medications', {
          elder_id: this.user.id,
          drug_name: name,
          dose: (this.newMed.dose || '').trim(),
          times,
          notes: (this.newMed.notes || '').trim(),
        })
        uni.showToast({ title: '添加成功', icon: 'success' })
        this.showAdd = false
        this.newMed = { drug_name: '', dose: '', times: '08:00', notes: '' }
        await this.load()
        // 加药同理：必须强制重排，否则"刚加的提醒死活不响"—— 防抖窗口内
        // syncAll() 只会复用首页那次的结果，这条新药根本进不了原生副本（契约 §10.3）。
        await syncAll({ force: true })
      } catch (e) {
        uni.showToast({ title: e.message || '添加失败', icon: 'none' })
      } finally {
        this.adding = false
      }
    }
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.med-page {
  min-height: 100vh;
  background: $lyj-bg;
  padding-bottom: calc(#{$lyj-tabbar-h} + #{$lyj-space-xl} + env(safe-area-inset-bottom, 0px));
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
.topbar-info {
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.title {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.sub {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: $lyj-space-xl 0;
  gap: $lyj-space-md;
}
.empty-icon {
  font-size: 100rpx;
}
.empty-text {
  font-size: $lyj-font-md;
  color: $lyj-text-light;
}
.med-card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-md;
  padding: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
}
.med-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $lyj-space-sm;
}
.drug {
  flex: 1;
  min-width: 0;
  font-size: 40rpx;
  font-weight: 700;
  color: $lyj-text;
  word-break: break-word;
}
.dose {
  flex-shrink: 0;
  white-space: nowrap;
  word-break: keep-all;
  font-size: $lyj-font-sm;
  color: $lyj-primary;
  background: $lyj-primary-soft;
  border-radius: 12rpx;
  padding: 4rpx 16rpx;
  font-weight: 600;
}
.notes {
  display: block;
  /* 服药注意事项是老人必须读到的正文，不是脚注 —— 原来是 28rpx（14px） */
  font-size: $lyj-font-md;
  color: $lyj-warn-text;
  line-height: $lyj-line-height;
  margin-top: $lyj-space-xs;
}
.slots {
  display: flex;
  gap: $lyj-space-md;
  margin-top: $lyj-space-md;
}
.slot {
  flex: 1;
  /* 打卡格是这页的主操作，按主按钮高度给 */
  min-height: $lyj-btn-main;
  border-radius: $lyj-radius;
  background: $lyj-field;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: $lyj-space-xs;
}
.slot.taken {
  background: $lyj-success-bg;
}
.slot.taking {
  opacity: 0.6;
}
.slot-time {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
  white-space: nowrap;
}
.slot-state {
  font-size: $lyj-font-sm;
  color: $lyj-primary;
  white-space: nowrap;
  word-break: keep-all;
}
.slot.taken .slot-state {
  color: $lyj-success;
}

.del-btn-wrap {
  margin-top: $lyj-space-md;
  text-align: right;
}
.del-btn {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  padding: 10rpx;
  white-space: nowrap;
  word-break: keep-all;
}
.del-btn.busy {
  opacity: 0.5;
}

.add-btn-wrap {
  margin: $lyj-space-xl $lyj-space-md;
}
.add-btn {
  background: $lyj-primary;
  color: white;
  text-align: center;
  padding: $lyj-space-md;
  border-radius: $lyj-radius-pill;
  font-size: $lyj-font-lg;
  font-weight: 700;
  white-space: nowrap;
  word-break: keep-all;
}

/* Modal styles */
.modal-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
}
.modal {
  background: white;
  width: 80%;
  border-radius: $lyj-radius;
  padding: $lyj-space-lg;
}
.modal-header {
  font-size: $lyj-font-lg;
  font-weight: bold;
  text-align: center;
  margin-bottom: $lyj-space-md;
}
.modal-input {
  background: $lyj-bg;
  padding: 20rpx;
  border-radius: $lyj-radius;
  margin-bottom: $lyj-space-sm;
}
.modal-footer {
  display: flex;
  gap: $lyj-space-sm;
  margin-top: $lyj-space-md;
}
.modal-btn {
  flex: 1;
  text-align: center;
  padding: 20rpx;
  border-radius: $lyj-radius-pill;
  font-weight: bold;
}
.modal-btn.cancel {
  background: $lyj-bg;
  color: $lyj-text;
}
.modal-btn.confirm {
  background: $lyj-primary;
  color: white;
}
</style>
