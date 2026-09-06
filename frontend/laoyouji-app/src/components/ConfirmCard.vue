<template>
  <!--
    挂起提示卡：高危操作已发家人确认。

    挂起对老人是**一次进展**，不是一个错误 —— 文案与配色都不许读成报错
    （所以用暖黄而不是红色，标题说"要家人点头"而不是"操作被拦截"）。

    正文用的是后端的 message 字段，不是 summary。后端同时给两句话：
    message 写给老人（已过黑话检查），summary 写给子女（含车次金额等事实）。
    旧版把 summary 当老人正文渲染，等于让老人读子女那份工单。

    这张卡会**就地变**：家人在手机上点完，chat.vue 按 confirmation_id 找回
    这一张、改它的 status。原来它一直停在"等他点同意"，于是家人早就同意了，
    老人屏幕上那张黄卡还在催 —— 老人会以为自己还得等，或者再说一遍。
  -->
  <view class="suspend-card" :class="'s-' + status">
    <view class="head">
      <text class="icon">{{ head.icon }}</text>
      <text class="title">{{ head.title }}</text>
      <text class="status-tag" :class="status">{{ statusBadgeText }}</text>
    </view>

    <text class="desc">{{ message }}</text>

    <view class="meta">
      <text v-if="summary" class="fact">{{ summary }}</text>
      <text v-if="amount" class="amount">金额：{{ amount }} 元</text>
      <text class="waiting">{{ head.foot }}</text>
      <text v-if="status === 'pending' && validMinutes" class="expire">
        {{ validMinutes }} 分钟内有效
      </text>
    </view>
  </view>
</template>

<script>
/**
 * 四态文案。**"家人不同意"和"家人同意了但没办成"是两件不同的事**，
 * 后端 confirmation_resolved 的 status 把它们分开发过来（executed /
 * rejected / failed），这里就不许合成一句"没成功" —— 那会让老人以为
 * 家人拒绝了他，而实际上家人点了同意。
 */
const HEADS = {
  pending: {
    icon: '✋',
    title: '这一步要家人点头',
    foot: '⏳ 已经发给家人，等他点同意',
  },
  executed: {
    icon: '✅',
    title: '家人同意了，已经办好',
    foot: '✅ 这一步不用再等了',
  },
  rejected: {
    icon: '🚫',
    title: '家人这次先不办',
    foot: '🚫 家人没同意。有疑问给他打个电话商量商量',
  },
  failed: {
    icon: '⚠️',
    title: '家人同意了，但这步没办成',
    foot: '⚠️ 家人已同意，是办的时候出了问题。我再试试',
  },
}

export default {
  name: 'ConfirmCard',
  props: {
    message: { type: String, default: '已经发给家人确认啦' }, // 老人看的那句话
    summary: { type: String, default: '' }, // 事实摘要（车次/项目）
    amount: { type: Number, default: 0 },
    expiresAt: { type: String, default: '' }, // ISO 时间串
    // 后端 confirmation_tasks.status 的同一套词，不另造一套
    status: { type: String, default: 'pending' },
  },
  computed: {
    /** 认不出的状态按"还在等"处理：宁可让老人多等，不可替家人宣布结果。 */
    head() {
      return HEADS[this.status] || HEADS.pending
    },
    statusBadgeText() {
      const map = {
        pending: '待确认',
        executed: '已执行',
        rejected: '已拒绝',
        failed: '执行失败',
      }
      return map[this.status] || '待确认'
    },
    /** 还剩多少分钟。算不出来就不显示 —— 不编一个数字给老人。 */
    validMinutes() {
      if (!this.expiresAt) return 0
      const left = new Date(this.expiresAt).getTime() - Date.now()
      if (!Number.isFinite(left) || left <= 0) return 0
      return Math.ceil(left / 60000)
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.suspend-card {
  background: $lyj-warn-bg;
  border: 3rpx solid $lyj-warn;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-lg;
}

/**
 * 结果三态换底色，等于把"还要不要等"画出来 —— 老人不必逐字读文案，
 * 一眼就知道这张卡还归自己管不管。黄 = 还在等，绿 = 妥了，
 * 灰 = 家人说先不办，红边 = 同意了但没办成（这一档才允许读成异常）。
 */
.s-executed {
  background: $lyj-success-bg;
  border-color: $lyj-success;
  .title,
  .waiting {
    color: $lyj-success;
  }
}
.s-rejected {
  background: $lyj-muted-bg;
  border-color: $lyj-line;
  .title,
  .waiting {
    color: $lyj-text-light;
  }
}
.s-failed {
  border-color: $lyj-danger;
  .title,
  .waiting {
    color: $lyj-danger;
  }
}
.head {
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
  margin-bottom: $lyj-space-sm;
}
.icon {
  font-size: $lyj-font-lg;
}
.title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-warn-text;
}
.status-tag {
  margin-left: auto;
  font-size: $lyj-font-xs;
  padding: 4rpx 16rpx;
  border-radius: $lyj-radius-pill;
  font-weight: 600;
}
.status-tag.pending {
  background: #fef3c7;
  color: #b45309;
}
.status-tag.executed {
  background: #dcfce7;
  color: #15803d;
}
.status-tag.rejected {
  background: #f1f5f9;
  color: #64748b;
}
.status-tag.failed {
  background: #fee2e2;
  color: #b91c1c;
}
.desc {
  display: block;
  font-size: $lyj-font-md;
  color: $lyj-text;
  line-height: $lyj-line-height;
}
.meta {
  margin-top: $lyj-space-sm;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.fact {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.amount {
  font-size: $lyj-font-md;
  color: $lyj-danger;
  font-weight: 700;
}
.waiting {
  font-size: $lyj-font-sm;
  color: $lyj-warn-text;
}
.expire {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
</style>
