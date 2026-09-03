<template>
  <view class="guardian">
    <LyjBack />
    <LyjSegment current="guardian" />

    <view v-if="trip" class="trip-head">
      <text class="trip-title">{{ trip.purpose }}</text>
      <text class="trip-sub">{{ statusText }} · {{ reportLine }}</text>
    </view>

    <!-- 位置只到城市级 / 完全未开放时，先把"为什么看不到细节"说清楚 -->
    <view v-if="precisionNote" class="precision-note">
      <text class="precision-text">🔒 {{ precisionNote }}</text>
    </view>

    <view v-if="!trip" class="empty-card">
      <text class="empty-text">{{ emptyText }}</text>
    </view>

    <template v-else-if="!locationOff">
      <!-- 路线示意（演示：静态折线关键点） -->
      <view class="map-card">
        <view class="route">
          <view v-for="(p, i) in route" :key="i" class="route-col">
            <view class="route-dot" :class="dotClass(p)"></view>
            <view v-if="i < route.length - 1" class="route-line" :class="lineClass(i)"></view>
          </view>
        </view>
        <view class="route-labels">
          <text
            v-for="(p, i) in route"
            :key="i"
            class="route-label"
            :class="{ passed: p.visited, abnormal: p.abnormal }"
          >{{ p.name }}</text>
        </view>
        <text class="map-note">📈 演示数据：位置由行程守护接口模拟上报</text>
      </view>

      <!-- 位置时间线 -->
      <view class="section">
        <text class="section-title">📍 位置记录</text>
        <view v-if="!checkpoints.length" class="empty-row">
          <text>老人还没出发（行程规划完成后开始记录）</text>
        </view>
        <view v-for="(cp, i) in checkpoints" :key="cp.id || i" class="cp">
          <view class="cp-left">
            <view class="cp-dot" :class="cp.status"></view>
            <view v-if="i < checkpoints.length - 1" class="cp-line"></view>
          </view>
          <view class="cp-body">
            <view class="cp-row">
              <text class="cp-location">{{ cp.location }}</text>
              <text class="cp-time">{{ fmtTime(cp.created_at) }}</text>
            </view>
            <text class="cp-note" :class="cp.status">{{ cp.note || cp.status }}</text>
          </view>
        </view>
      </view>
    </template>
  </view>
</template>

<script>
import LyjSegment from '../../components/LyjSegment.vue'
import { get } from '../../api/client'
import { getCurrentUser } from '../../store/user'

// 与后端 Mock 地图一致的演示途经点
const EXPECTED = ['家（南京鼓楼区）', '南京南站', '济南西站', '北京南站', '北京积水潭医院']

const PRECISION_NOTE = {
  city: '老人把位置开放到城市级，所以下面的地点是粗化过的，没有具体门牌号和坐标。',
  off: '老人没有开放位置共享。行程本身能看到，但途经地点和轨迹一项都不会给。',
}

export default {
  components: { LyjSegment },
  data() {
    return {
      user: null,
      tripId: '',
      trip: null,
      checkpoints: [],
      precision: '',
      loaded: false,
    }
  },
  computed: {
    statusText() {
      const s = this.trip ? this.trip.status : ''
      return { planned: '已规划', ongoing: '进行中', completed: '已完成' }[s] || s
    },
    locationOff() {
      return this.precision === 'off'
    },
    precisionNote() {
      return PRECISION_NOTE[this.precision] || ''
    },
    reportLine() {
      if (this.locationOff) return '位置未开放'
      return `共 ${this.checkpoints.length} 次位置上报`
    },
    emptyText() {
      if (!this.loaded) return '加载中…'
      return '还没有行程。老人说一句"我想去哪儿"，规划好了就会出现在这里。'
    },
    route() {
      return EXPECTED.map((name) => {
        // 粗化后的地点是原名的前缀（privacy.coarse_place），所以两边都要试一次
        const matched = this.checkpoints.find(
          (c) => c.location && (c.location.includes(name) || name.includes(c.location)),
        )
        return {
          name,
          visited: !!matched && matched.status !== 'off_route',
          abnormal: !!matched && matched.status === 'off_route',
        }
      })
    },
  },
  onLoad(opts) {
    // 两条来路：看板下钻会带 trip_id；顶部分段控件切过来不带，得自己挑一个行程
    this.tripId = (opts && opts.trip_id) || ''
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
        if (!this.tripId) this.tripId = await this._latestTripId()
        if (!this.tripId) {
          this.loaded = true
          return
        }
        // child_id 必须带上：不带就是"老人看自己的行程"，后端会原样返回全量轨迹，
        // 绕过隐私分级（routes_guardian.py:40）。子女端一律带。
        const d = await get(`/api/trips/${this.tripId}`, { child_id: this.user.id })
        this.trip = d.trip
        this.checkpoints = d.checkpoints || []
        this.precision = d.precision || ''
      } catch (e) {
        uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
      this.loaded = true
    },
    async _latestTripId() {
      const d = await get(`/api/child/${this.user.id}/dashboard`)
      const trips = d.trips || []
      // 看板已按 -created_at 排好，第一条就是最近的
      return trips.length ? trips[0].id : ''
    },
    dotClass(p) {
      if (p.abnormal) return 'abnormal'
      return p.visited ? 'visited' : ''
    },
    lineClass(i) {
      return this.route[i] && this.route[i].visited ? 'visited' : ''
    },
    fmtTime(iso) {
      if (!iso) return ''
      const d = new Date(iso)
      if (!Number.isFinite(d.getTime())) return ''
      const pad = (n) => String(n).padStart(2, '0')
      return `${pad(d.getHours())}:${pad(d.getMinutes())}`
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.guardian {
  min-height: 100vh;
  background: $lyj-child-bg;
  /* 子女端用原生导航栏，不需要自己让开状态栏 */
  padding: $lyj-space-md 0 $lyj-space-xl;
  box-sizing: border-box;
}
.trip-head {
  padding: $lyj-space-sm $lyj-space-lg;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.trip-title {
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-child-text;
}
.trip-sub {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
}
.precision-note {
  margin: $lyj-space-xs $lyj-space-md;
  padding: $lyj-space-md;
  background: $lyj-info-bg;
  border: 2rpx solid $lyj-info-line;
  border-radius: $lyj-radius;
}
.precision-text {
  font-size: $lyj-font-sm;
  color: $lyj-info;
  line-height: $lyj-line-height;
}
.empty-card {
  margin: $lyj-space-md;
  padding: $lyj-space-xl $lyj-space-md;
  background: $lyj-card;
  border-radius: $lyj-radius;
  text-align: center;
}
.empty-text {
  font-size: $lyj-font-md;
  color: $lyj-child-muted;
  line-height: $lyj-line-height;
}
.map-card {
  margin: $lyj-space-sm $lyj-space-md;
  background: linear-gradient(150deg, $lyj-weather-from, $lyj-card);
  border: 2rpx solid $lyj-weather-line;
  border-radius: $lyj-radius;
  padding: $lyj-space-lg $lyj-space-md;
}
.route {
  display: flex;
  align-items: center;
  padding: 0 $lyj-space-xs;
}
.route-col {
  flex: 1;
  display: flex;
  align-items: center;
}
.route-dot {
  width: 26rpx;
  height: 26rpx;
  border-radius: 50%;
  background: $lyj-dot-idle;
  border: 4rpx solid $lyj-card;
  box-shadow: 0 0 0 2rpx $lyj-dot-idle;
  flex-shrink: 0;
}
.route-dot.visited {
  background: $lyj-info;
  box-shadow: 0 0 0 2rpx $lyj-info;
}
.route-dot.abnormal {
  background: $lyj-danger;
  box-shadow: 0 0 0 2rpx $lyj-danger;
}
.route-line {
  flex: 1;
  height: 6rpx;
  background: $lyj-dot-idle;
  margin: 0 6rpx;
  border-radius: 3rpx;
}
.route-line.visited {
  background: $lyj-info;
}
.route-labels {
  display: flex;
  margin-top: $lyj-space-sm;
  padding: 0 $lyj-space-xs;
}
/* 途经点标签是密排的 5 列，$lyj-font-sm 也放不下 —— 这是图例，不承载唯一信息
   （同一份地点在下面"位置记录"里按正文字号完整列了一遍）。 */
.route-label {
  flex: 1;
  text-align: center;
  font-size: $lyj-font-nav;
  color: $lyj-child-muted;
  line-height: $lyj-line-height;
}
.route-label.passed {
  color: $lyj-info;
  font-weight: 700;
}
.route-label.abnormal {
  color: $lyj-danger;
  font-weight: 700;
}
.map-note {
  display: block;
  text-align: center;
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
  margin-top: $lyj-space-md;
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
}
.empty-row {
  padding: $lyj-space-md 0;
}
.empty-row text {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
  line-height: $lyj-line-height;
}
.cp {
  display: flex;
  gap: $lyj-space-md;
  padding: $lyj-space-sm 0;
}
.cp-left {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.cp-dot {
  width: 22rpx;
  height: 22rpx;
  border-radius: 50%;
  background: $lyj-success;
  flex-shrink: 0;
  margin-top: $lyj-space-xs;
}
.cp-dot.off_route {
  background: $lyj-danger;
}
.cp-line {
  flex: 1;
  width: 4rpx;
  background: $lyj-child-line;
  margin: $lyj-space-xs 0;
}
.cp-body {
  flex: 1;
  padding-bottom: $lyj-space-sm;
}
.cp-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: $lyj-space-sm;
}
.cp-location {
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-child-text;
}
.cp-time {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
}
.cp-note {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-child-body;
  line-height: $lyj-line-height;
  margin-top: $lyj-space-xs;
}
.cp-note.off_route {
  color: $lyj-danger;
}
</style>
