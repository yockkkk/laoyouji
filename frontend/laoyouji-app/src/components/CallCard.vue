<template>
  <!--
    一键拨号卡（康乐右翼）：把"想孩子了"变成"此刻听见他的声音"。

    这张卡只有一个动作，而且必须**绝对主导**：老人认知负荷已经很高，摊开一张有
    三个按钮的卡，他得先读、再选、再确认 —— 每一步都可能让他放弃。所以整张卡上
    最大的东西是那枚通栏按钮，号码只作核对（小字），不指望他读。

    号码是后端从家人绑定关系里取好塞进来的：卡上不出现"通讯录""选联系人"这类
    需要他再操作一步的东西。点一下就该通话。
  -->
  <view class="call-card">
    <text class="card-title">{{ title }}</text>

    <button
      class="btn-call"
      :class="{ disabled: !phone }"
      :disabled="!phone"
      :hover-class="phone ? 'btn-call-active' : 'none'"
      @tap="call"
    >
      <text class="btn-icon">📞</text>
      <text class="btn-text">{{ phone ? `给${relation}${name}打电话` : '号码还没存上' }}</text>
    </button>

    <text v-if="reason" class="reason">{{ reason }}</text>
    <text v-if="note" class="note">{{ note }}</text>
    <!-- 号码只作核对：老人（或旁边的子女）想对一遍时看得见，不指望他念数字 -->
    <text v-if="phone" class="phone">号码：{{ phone }}</text>
  </view>
</template>

<script>
export default {
  name: 'CallCard',
  props: {
    title: { type: String, default: '给家里人打个电话' },
    name: { type: String, default: '' },
    relation: { type: String, default: '家里人' },
    phone: { type: String, default: '' }, // 由后端从家人绑定关系里取，前端不拼不猜
    reason: { type: String, default: '' }, // 为什么想打这通电话（老人的原话）
    note: { type: String, default: '' },
  },
  methods: {
    call() {
      if (!this.phone) return
      uni.makePhoneCall({
        phoneNumber: this.phone,
        // 诚实降级：拨号失败（H5 桌面点 tel: 没反应是最常见的一种）时，
        // 先把号码复制进剪贴板再说一句人话。假装拨通了才是最坏的结果 ——
        // 老人会对着没人接的手机一直喂喂喂。
        fail: () => {
          uni.setClipboardData({
            data: this.phone,
            success: () => {
              uni.showToast({
                title: '拨号没成功，号码已经复制，让家人帮您拨',
                icon: 'none',
                duration: 3000,
              })
            },
          })
        },
      })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.call-card {
  background: $lyj-card;
  border: 2rpx solid $lyj-line;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
}

.card-title {
  display: block;
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-text;
  line-height: $lyj-line-height;
  margin-bottom: $lyj-space-md;
}

.btn-call {
  width: 100%;
  height: $lyj-btn-main; // 160rpx = 80px，一整个巴掌拍上去都按得中
  display: flex;
  align-items: center;
  justify-content: center;
  gap: $lyj-space-xs;
  background: linear-gradient(135deg, $lyj-primary 0%, $lyj-primary-light 100%);
  color: $lyj-text-on;
  border: none;
  border-radius: $lyj-radius-pill;
  box-shadow: $lyj-shadow-raised;
  padding: 0 $lyj-space-md;
  box-sizing: border-box;
}

.btn-call-active {
  background: linear-gradient(135deg, $lyj-primary-dark 0%, $lyj-primary 100%);
  transform: scale(0.98);
}

/* 置灰：没号码时按钮不能像能按的样子 —— 可点但没反应比不给按钮更伤 */
.btn-call.disabled {
  background: $lyj-disabled;
  box-shadow: none;
}

.btn-icon {
  font-size: $lyj-font-xl;
}

.btn-text {
  font-size: $lyj-font-lg;
  font-weight: 700;
  letter-spacing: 2rpx;
  color: $lyj-text-on;
}

.reason {
  display: block;
  margin-top: $lyj-space-md;
  font-size: $lyj-font-md;
  color: $lyj-text;
  line-height: $lyj-line-height;
}

.note {
  display: block;
  margin-top: $lyj-space-xs;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  line-height: $lyj-line-height;
}

.phone {
  display: block;
  margin-top: $lyj-space-xs;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  font-variant-numeric: tabular-nums;
}
</style>
