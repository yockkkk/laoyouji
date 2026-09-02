<template>
  <view class="privacy">
    <view class="head">
      <text class="title">隐私权限</text>
      <text class="sub">所有授权由老人在「我的」页面亲自设置，家人这一侧只能查看</text>
    </view>

    <LyjSegment current="privacy" />

    <view v-if="!privacy.bound" class="unbound-card">
      <text class="unbound-title">还没有绑定关系</text>
      <text class="unbound-text">
        在老人认下这层关系之前，位置和健康数据一项都不会给 —— 下面显示的就是"全关"，
        不是加载失败。
      </text>
    </view>

    <view class="card">
      <view class="row">
        <text class="label">📍 位置权限</text>
        <view class="levels">
          <view
            v-for="o in locationOptions"
            :key="o.value"
            class="level"
            :class="{ active: privacy.location_level === o.value }"
          >
            <text>{{ o.label }}</text>
          </view>
        </view>
        <text class="explain">{{ locationExplain }}</text>
      </view>

      <view class="divider"></view>

      <view class="row">
        <text class="label">🏥 健康权限</text>
        <view class="levels">
          <view
            v-for="o in healthOptions"
            :key="o.value"
            class="level"
            :class="{ active: privacy.health_level === o.value }"
          >
            <text>{{ o.label }}</text>
          </view>
        </view>
        <text class="explain">{{ healthExplain }}</text>
      </view>
    </view>

    <view class="note-card">
      <text class="note-title">🔒 我们的设计原则</text>
      <text class="note-line">· 降级是数据变粗，不是功能报错 —— 该有的提醒照旧到</text>
      <text class="note-line">· 权限只有老人本人能改，随时可收回</text>
      <text class="note-line">· 每次家人读取都写审计日志，老人可追溯"谁看过我"</text>
      <text class="note-line">· 数据不经第三方，仅家人之间可见</text>
    </view>
  </view>
</template>

<script>
import LyjSegment from '../../components/LyjSegment.vue'
import { get } from '../../api/client'
import { getCurrentUser } from '../../store/user'

/** 兜底必须是"全关"：后端没绑定时走提前返回，连 privacy 字段都不下发。 */
const DENIED = { location_level: 'off', health_level: 'off', bound: false }

export default {
  components: { LyjSegment },
  data() {
    return {
      user: null,
      elderId: null,
      privacy: DENIED,
      locationOptions: [
        { value: 'realtime', label: '实时位置' },
        { value: 'city', label: '只看城市' },
        { value: 'off', label: '不给看' },
      ],
      healthOptions: [
        { value: 'full', label: '全部' },
        { value: 'summary', label: '摘要' },
        { value: 'off', label: '不给看' },
      ],
    }
  },
  computed: {
    locationExplain() {
      return {
        realtime: '您可以看到老人的实时位置与行程轨迹（适合出行守护）',
        city: '您只能看到老人所在城市，看不到门牌号和坐标',
        off: '老人未开放位置信息给您。行程异常仍会通知您，但不含地点',
      }[this.privacy.location_level]
    },
    healthExplain() {
      return {
        full: '您可以看到老人的完整用药记录与体检解读原文',
        summary: '您只能看到"今天按时吃药了吗"，看不到药名与病历',
        off: '老人未开放健康信息给您',
      }[this.privacy.health_level]
    },
  },
  onShow() {
    this.user = getCurrentUser()
    if (!this.user || this.user.role !== 'child') {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.load()
  },
  methods: {
    async load() {
      try {
        const d = await get(`/api/child/${this.user.id}/dashboard`)
        this.elderId = d.elder ? d.elder.id : null
        // 没有 privacy 字段就是没有绑定 —— 绝不退回"默认全开"的假象
        this.privacy = d.privacy || DENIED
      } catch (e) {
        this.privacy = DENIED
        uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.privacy {
  min-height: 100vh;
  background: $lyj-child-bg;
  /* 子女端用原生导航栏，不需要自己让开状态栏 */
  padding: $lyj-space-lg 0 $lyj-space-xl;
  box-sizing: border-box;
}
.head {
  padding: 0 $lyj-space-lg $lyj-space-sm;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.title {
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-child-text;
}
.sub {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
  line-height: $lyj-line-height;
}
.unbound-card {
  margin: $lyj-space-xs $lyj-space-md;
  padding: $lyj-space-md;
  background: $lyj-warn-bg;
  border: 2rpx solid $lyj-warn;
  border-radius: $lyj-radius;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.unbound-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-warn-text;
}
.unbound-text {
  font-size: $lyj-font-sm;
  color: $lyj-warn-text;
  line-height: $lyj-line-height;
}
.card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-xs $lyj-space-md;
  padding: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
}
.row {
  display: flex;
  flex-direction: column;
  gap: $lyj-space-sm;
}
.label {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
}
.levels {
  display: flex;
  gap: $lyj-space-sm;
}
/* 只读展示（改档位在老人端），但仍按可点下限给高度 —— 一排矮得像装饰的格子
   会让人以为这里能按。高度一致才看得出"这是状态，不是开关"。 */
.level {
  min-height: $lyj-hit-min;
  display: flex;
  align-items: center;
  padding: 0 $lyj-space-md;
  border-radius: $lyj-radius;
  background: $lyj-child-line;
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
}
.level.active {
  background: $lyj-info-bg;
  color: $lyj-info;
  font-weight: 700;
  border: 2rpx solid $lyj-info;
}
.explain {
  font-size: $lyj-font-sm;
  color: $lyj-child-body;
  line-height: $lyj-line-height;
}
.divider {
  height: 2rpx;
  background: $lyj-child-line;
  margin: $lyj-space-lg 0;
}
.note-card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-sm;
  box-shadow: $lyj-shadow-card;
}
.note-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
}
.note-line {
  font-size: $lyj-font-sm;
  color: $lyj-child-body;
  line-height: $lyj-line-height;
}
</style>
