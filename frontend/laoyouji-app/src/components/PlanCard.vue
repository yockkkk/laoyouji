<template>
  <!--
    确定性交付物卡片 —— 吃 plan_builder 的 typed 输出。

    旧版的 card.body 是扁平 {k: v} 字典，模板直接 v-for 铺开。两个后果：
    页序不存在（"五页"在组件里根本不是一个概念），而且子 Agent 没填上的字段
    不会成为 key、于是静静消失 —— 而要求是显式渲染"待补"，绝不编造。

    现在缺失是一个**字段**（missing: true）而不是一个**缺席**，所以它占一行、
    看得见、还能被计数。
  -->
  <view class="card-wrap" :class="[{ compact }, { 'is-expanded': isExpanded }]">
    <view class="card-head" @tap="toggleExpand">
      <view class="card-head-left">
        <text class="card-title">{{ title }}</text>
        <view class="card-badges">
          <text v-if="sections && sections.length" class="page-badge">
            共 {{ sections.length }} 页
          </text>
          <text v-if="!complete && missingCount" class="card-todo">
            {{ missingCount }} 项待补
          </text>
          <text v-else class="card-ready">
            规划就绪
          </text>
        </view>
      </view>

      <view class="card-head-right">
        <view class="plan-toggle-btn" :class="{ open: isExpanded }">
          <text class="toggle-text">{{ isExpanded ? '收起' : '查看完整计划书' }}</text>
          <text class="toggle-arrow">{{ isExpanded ? '▲' : '▼' }}</text>
        </view>
      </view>
    </view>

    <!-- 适老高德路线规划醒目大字入口 (靶区 >= 48px) -->
    <view v-if="hasRouteAction" class="route-action-box" @tap.stop="goToRouteMap">
      <button class="btn-route-action" hover-class="btn-route-action-active">
        <text class="route-icon">🗺️</text>
        <text class="route-text">查看高德路线规划</text>
        <text class="route-badge">适老专线 ›</text>
      </button>
    </view>

    <!-- 可展开的完整计划书各页 -->
    <view v-show="isExpanded" class="card-body">
      <view v-for="(section, si) in sections" :key="si" class="section">
        <text v-if="!compact && section.heading" class="section-heading">
          {{ section.heading }}
        </text>
        <view v-for="(row, ri) in section.rows" :key="ri" class="row">
          <text class="key">{{ row.label }}</text>
          <text class="val" :class="{ missing: row.missing }">
            {{ row.missing ? '待补' : row.value }}
          </text>
        </view>
        <!-- 页内叮嘱属于这一页，不能被抽到卡片末尾去 -->
        <text
          v-for="(note, ni) in section.notes || []"
          :key="'n' + ni"
          class="section-note"
        >
          {{ note }}
        </text>
      </view>

      <view v-if="notes && notes.length" class="card-foot">
        <text v-for="(note, ni) in notes" :key="ni" class="footnote">{{ note }}</text>
      </view>

      <!-- 朗读入口 -->
      <view v-if="speech" class="replay" @tap.stop="replay">
        <text class="replay-icon">🔊</text>
        <text class="replay-text">念给我听</text>
      </view>
    </view>
  </view>
</template>

<script>
import { speak } from '../api/asr'
import { getCurrentUser } from '../store/user'

export default {
  name: 'PlanCard',
  props: {
    title: { type: String, default: '' },
    // [{ heading: String, rows: [{ label, value, missing }], notes: [String] }]
    sections: { type: Array, default: () => [] },
    notes: { type: Array, default: () => [] },
    complete: { type: Boolean, default: true },
    // 紧凑模式：两张轻量卡片（用药与复查安排 / 社区服务预约单）共用本组件
    compact: { type: Boolean, default: false },
    // 朗读文本的**覆盖**位。留空则由 speech 从卡面内容自己拼。
    announce: { type: String, default: '' },
    defaultExpanded: { type: Boolean, default: false },
    tripId: { type: String, default: '' },
  },
  data() {
    return {
      isExpanded: this.defaultExpanded,
    }
  },
  computed: {
    hasRouteAction() {
      if (this.compact) return false
      const str = (this.title || '') + JSON.stringify(this.sections || [])
      // 判据是"这份计划书讲的是不是一次要去某处的就医/出行"，与**哪座城市无关** ——
      // 康乐在哪个城市都该工作，按"标题里有没有北京/上海/南京"来开关按钮，
      // 等于把这个产品焊死在演示用的那座城上。
      // 原来的 '车票' 也一并去掉：那是已砍掉的城际车票页留下的词，现在没有计划书
      // 会提到它（对照 backend/app/agents/plan_builder.py 的四页）。
      return (
        str.includes('就医') ||
        str.includes('出行') ||
        str.includes('路线') ||
        str.includes('医院')
      )
    },
    missingCount() {
      return this.sections.reduce(
        (n, s) => n + (s.rows || []).filter((r) => r.missing).length,
        0,
      )
    },
    speech() {
      if (this.announce) return this.announce
      const parts = this.title ? [this.title] : []
      for (const s of this.sections) {
        if (s.heading) parts.push(s.heading)
        for (const r of s.rows || []) {
          parts.push(`${r.label}：${r.missing ? '待补' : r.value}`)
        }
        for (const n of s.notes || []) parts.push(n)
      }
      for (const n of this.notes || []) parts.push(n)
      return parts.join('。')
    },
  },
  methods: {
    toggleExpand() {
      this.isExpanded = !this.isExpanded
    },
    replay() {
      const ok = speak(this.speech)
      if (!ok) uni.showToast({ title: '当前设备不支持语音播报', icon: 'none' })
    },
    goToRouteMap() {
      // 出发地只写"家"，不写"家（南京鼓楼区）"—— 城市由后端按老人档案解析
      // （见 app/providers/external/amap_service.py 的 home_coords/city_of，
      // 裸"家"会落到这位老人所在城市的住址）。在这里写死城市，等于把所有老人的
      // 家都搬到了南京。
      let origin = '家'
      let hospital = ''
      let destination = ''

      for (const s of this.sections || []) {
        for (const r of s.rows || []) {
          if ((r.label === '出发' || r.label === '出发站' || r.label === '起点') && r.value && !r.missing) {
            origin = r.value
          }
          if ((r.label === '医院' || r.label === '就诊医院') && r.value && !r.missing) {
            hospital = r.value
          }
          if ((r.label === '到达' || r.label === '目的地' || r.label === '到达站') && r.value && !r.missing) {
            if (!destination) {
              destination = r.value
            }
          }
        }
      }

      if (hospital) {
        destination = hospital
      }

      // 原来这里有一串"标题里出现哪个城市名就凑哪家医院"的推断，最后兜底写死
      // "北京积水潭医院"。那是个真 bug：计划书里根本没给出医院时（比如挂号那步
      // 还没跑），点"查看路线"会把老人导去一个**本市产品够不到的城市**，而且
      // 是静默的 —— 屏幕上会显示一条去北京的路线，看起来像真的。
      // 拿不到目的地就不跳转：说清楚缺了什么，让老人回到能补上它的那一步。
      if (!destination) {
        uni.showToast({ title: '这份计划书里还没有目的地，先让康乐挂好号再来看路线', icon: 'none' })
        return
      }

      const currentUser = getCurrentUser()
      let city = (currentUser && currentUser.city) || ''
      if (!city) {
        for (const c of ['南京', '北京', '上海', '杭州', '苏州']) {
          if ((this.title + destination + origin).includes(c)) {
            city = c
            break
          }
        }
      }
      city = city || '南京'

      uni.navigateTo({
        url: `/pages/elder/route-map?title=${encodeURIComponent(this.title || '就医出行路线规划')}&origin=${encodeURIComponent(origin)}&destination=${encodeURIComponent(destination)}&city=${encodeURIComponent(city)}&trip_id=${encodeURIComponent(this.tripId || '')}`,
      })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.card-wrap {
  background: $lyj-card;
  border: 2rpx solid $lyj-line;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
  transition: all 0.2s ease;
}
.card-wrap.compact {
  padding: $lyj-space-md;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  cursor: pointer;
  min-height: 72rpx;
}
.card-wrap.is-expanded .card-head {
  margin-bottom: $lyj-space-md;
  padding-bottom: $lyj-space-sm;
  border-bottom: 2rpx solid $lyj-line;
}
.card-head-left {
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  min-width: 0;
  flex: 1;
}
.card-title {
  display: block;
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-text;
  line-height: $lyj-line-height;
  white-space: nowrap !important;
  word-break: keep-all !important;
}
.card-badges {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-wrap: nowrap;
}
.page-badge {
  font-size: $lyj-font-xs;
  padding: 2rpx 14rpx;
  border-radius: 999rpx;
  background: #eff6ff;
  color: #2563eb;
  font-weight: 600;
  white-space: nowrap !important;
  word-break: keep-all !important;
  flex-shrink: 0;
}
.card-todo {
  font-size: $lyj-font-xs;
  color: $lyj-warn-text;
  font-weight: 600;
  white-space: nowrap !important;
  word-break: keep-all !important;
  flex-shrink: 0;
}
.card-ready {
  font-size: $lyj-font-xs;
  color: $lyj-success;
  font-weight: 600;
  white-space: nowrap !important;
  word-break: keep-all !important;
  flex-shrink: 0;
}
.card-head-right {
  flex-shrink: 0;
  margin-left: 16rpx;
}
.plan-toggle-btn {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 8rpx 18rpx;
  border-radius: $lyj-radius-pill;
  background: #f1f5f9;
  color: $lyj-primary;
  font-size: $lyj-font-xs;
  font-weight: 600;
  white-space: nowrap !important;
  word-break: keep-all !important;
}
.plan-toggle-btn.open {
  background: $lyj-primary-soft;
}
.toggle-arrow {
  font-size: 20rpx;
}
.card-body {
  animation: fadeIn 0.25s ease;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(-6rpx); }
  to { opacity: 1; transform: translateY(0); }
}
.section {
  margin-bottom: $lyj-space-md;
}
.section-heading {
  display: block;
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-primary;
  margin: $lyj-space-sm 0;
}
.section-note {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  line-height: $lyj-line-height;
  margin-top: $lyj-space-xs;
}
.row {
  display: flex;
  padding: $lyj-space-xs 0;
  gap: $lyj-space-sm;
}
.key {
  width: 180rpx;
  flex-shrink: 0;
  font-size: $lyj-font-md;
  color: $lyj-text-light;
}
.val {
  flex: 1;
  font-size: $lyj-font-md;
  color: $lyj-text;
  line-height: $lyj-line-height;
}
/* 待补：看得见，但不假装是内容 */
.val.missing {
  color: $lyj-text-light;
  font-style: italic;
}
.card-foot {
  margin-top: $lyj-space-sm;
  padding-top: $lyj-space-sm;
  border-top: 2rpx solid $lyj-line;
}
.footnote {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  line-height: $lyj-line-height;
}
.replay {
  margin-top: $lyj-space-md;
  height: $lyj-hit-min;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: $lyj-space-xs;
  background: $lyj-primary-soft;
  border-radius: $lyj-radius-pill;
}
.replay-icon {
  font-size: $lyj-font-md;
}
.replay-text {
  font-size: $lyj-font-md;
  color: $lyj-primary;
  font-weight: 700;
}

.route-action-box {
  margin: $lyj-space-sm 0;
}
.btn-route-action {
  width: 100%;
  min-height: 96rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
  background: linear-gradient(135deg, #2A82E4 0%, #3B99FC 100%);
  color: #ffffff;
  border: none;
  border-radius: 48rpx;
  box-shadow: 0 6rpx 16rpx rgba(42, 130, 228, 0.28);
  cursor: pointer;
  padding: 0 32rpx;
  box-sizing: border-box;
  transition: all 0.2s ease;
}
.btn-route-action-active {
  transform: scale(0.98);
  background: linear-gradient(135deg, $lyj-primary-dark 0%, $lyj-primary 100%);
  box-shadow: 0 4rpx 12rpx rgba(42, 130, 228, 0.25);
}
.route-icon {
  font-size: 38rpx;
}
.route-text {
  font-size: 34rpx;
  font-weight: 700;
  letter-spacing: 1rpx;
  color: #ffffff;
}
.route-badge {
  font-size: 24rpx;
  background: rgba(255, 255, 255, 0.25);
  color: #ffffff;
  padding: 4rpx 16rpx;
  border-radius: 20rpx;
  font-weight: 600;
}
</style>
