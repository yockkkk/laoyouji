<template>
  <view class="dash">
    <view class="head">
      <view class="head-info">
        <text class="title">家人看板</text>
        <text class="sub">{{ elderLine }}</text>
      </view>
      <view class="head-actions">
        <button class="refresh" size="mini" @tap="loadAll">刷新</button>
        <button class="logout-btn" size="mini" @tap="logout">退出登录</button>
      </view>
    </view>

    <LyjSegment current="dashboard" />

    <!-- 隐私档位说明。看板"薄"往往不是坏了，而是老人只开放到这一档 —— 说清楚。 -->
    <view v-if="privacyNote" class="privacy-note">
      <text class="privacy-note-text">🔒 {{ privacyNote }}</text>
    </view>

    <!-- 响应式铺砌布局 -->
    <view class="sections-grid">
      <!-- 父母实时位置动态卡片 -->
      <view v-if="privacy.bound && privacy.location_level !== 'off'" class="section elder-location-section">
        <view class="section-head location-head">
          <view class="location-title-wrap">
            <view class="pulse-beacon"></view>
            <text class="section-title location-title">📍 父母实时位置动态</text>
          </view>
          <text v-if="latestLocationTime" class="location-refresh-time">{{ latestLocationTime }}</text>
        </view>

        <view v-if="latestLocation" class="location-card-content">
          <view class="loc-main-row">
            <view class="loc-icon-badge">👴</view>
            <view class="loc-text-block">
              <view class="loc-name-row">
                <text class="loc-name">{{ latestLocation.location || '已在途中' }}</text>
                <text class="loc-tag" :class="latestLocation.is_off_route ? 'alert' : 'normal'">
                  {{ latestLocation.is_off_route ? '⚠️ 偏航预警' : latestLocation.trip_status === 'completed' ? '🏁 已到达' : '🟢 正常行进' }}
                </text>
              </view>
              <text v-if="latestLocation.purpose" class="loc-purpose">
                当前行程：{{ latestLocation.purpose }}
              </text>
              <text v-if="latestLocation.note" class="loc-note">
                {{ latestLocation.note }}
              </text>
            </view>
          </view>
          <view class="loc-btn-wrap">
            <button class="loc-map-btn" size="mini" @tap="openGuardianMap(latestLocation.trip_id)">
              🗺️ 查看高德大地图实时轨迹与守护 ›
            </button>
          </view>
        </view>

        <view v-else class="location-empty-box">
          <text class="location-empty-hint">长辈开启路线规划后，将在此自动同步其实时行进坐标与偏航预警。</text>
          <button class="loc-map-btn-sm" size="mini" @tap="openGuardianMap()">
            🗺️ 进入行程守护大地图
          </button>
        </view>
      </view>

      <!-- 待我审批事项 -->
      <view v-if="pendingConfirmations.length" class="section pending-section">
        <view class="section-head">
          <text class="section-title pending-title">✋ 待我审批事项 ({{ pendingCount }})</text>
        </view>
        <view v-for="t in pendingConfirmations" :key="t.id" class="pending-card">
          <view class="pending-card-top">
            <view class="pending-icon">{{ taskIcon(t) }}</view>
            <view class="pending-main">
              <view class="pending-summary-row">
                <text class="pending-summary">{{ taskSummary(t) }}</text>
                <text v-if="t.amount" class="pending-cost">¥{{ t.amount }}</text>
              </view>
              <text class="pending-reason" v-if="taskReason(t)">原因：{{ taskReason(t) }}</text>
              <text class="pending-time" v-if="t.created_at">申请时间：{{ fmtTime(t.created_at) }}</text>
            </view>
          </view>
          <view class="pending-action-bar">
            <view v-if="t.status === 'executed' || t.status === 'approved'" class="inline-status success">
              <text>✅ 已同意并办理</text>
            </view>
            <view v-else-if="t.status === 'rejected'" class="inline-status rejected">
              <text>🚫 已拒绝</text>
            </view>
            <view v-else-if="t.status === 'failed'" class="inline-status failed">
              <text>⚠️ 执行失败</text>
            </view>
            <view v-else class="pending-btns">
              <button
                class="approve-btn"
                :loading="actionLoading[t.id] === 'approve'"
                :disabled="!!actionLoading[t.id]"
                size="mini"
                @tap.stop="approveTask(t)"
              >
                同意
              </button>
              <button
                class="reject-btn"
                :loading="actionLoading[t.id] === 'reject'"
                :disabled="!!actionLoading[t.id]"
                size="mini"
                @tap.stop="rejectTask(t)"
              >
                拒绝
              </button>
            </view>
          </view>
        </view>
      </view>

      <!-- 完整5页计划书（出行与就医） -->
      <view class="section">
        <view class="section-head">
          <text class="section-title">📋 出行与就医计划 ({{ consolidatedPlans.length }})</text>
        </view>
        <view v-if="!consolidatedPlans.length" class="empty-row">
          <text>暂无计划书（长辈提出就医或出行需求后由老友记生成）</text>
        </view>
        <view
          v-for="p in consolidatedPlans"
          :key="p.id || p.trip_id"
          class="plan-card-item"
        >
          <view class="plan-item-main" @tap="openPlan(p)">
            <view class="plan-item-title-row">
              <text class="plan-badge" :class="isMedical(p) ? 'medical_plan' : 'trip_plan'">
                {{ isMedical(p) ? '就医计划' : '出行计划' }}
              </text>
              <text class="plan-item-title">{{ p.title }}</text>
              <text class="plan-status-badge" :class="p.status || 'planned'">
                {{ statusText(p.status || 'planned') }}
              </text>
            </view>
            <view class="plan-item-meta-row">
              <text v-if="getDestination(p)" class="plan-dest">📍 目的地：{{ getDestination(p) }}</text>
              <text class="plan-meta-time" v-if="p.created_at">规划时间：{{ fmtTime(p.created_at) }}</text>
            </view>
          </view>
          <view class="plan-actions">
            <button class="plan-btn plan" size="mini" @tap.stop="openPlan(p)">📖 计划书</button>
            <button class="plan-btn guardian" size="mini" @tap.stop="goGuardian(p)">🛡️ 守护</button>
          </view>
        </view>
      </view>

      <!-- 今日用药 -->
      <view class="section">
        <view class="section-head">
          <text class="section-title">💊 今日用药</text>
        </view>
        <view v-if="!medications.length" class="empty-row">
          <text>{{ medEmptyText }}</text>
        </view>
        <view v-for="(m, i) in medications" :key="i" class="med-item">
          <text class="med-drug" :class="{ masked: m.precision === 'summary' }">
            {{ drugLabel(m) }}
          </text>
          <text class="med-taken">今日 {{ takenCount(m) }}/{{ (m.times || []).length }} 次</text>
        </view>
      </view>
    </view>

    <!-- 5页完整计划书查看弹窗 -->
    <view v-if="selectedPlan" class="plan-modal-mask" @tap="closePlan">
      <view class="plan-modal-content" @tap.stop>
        <view class="modal-head">
          <text class="modal-head-title">📖 完整计划书（共5页）</text>
          <button class="modal-close-btn" size="mini" @tap="closePlan">✕</button>
        </view>
        <scroll-view scroll-y class="modal-body-scroll">
          <PlanCard
            v-if="selectedPlanCard"
            :title="selectedPlanCard.title"
            :sections="selectedPlanCard.sections"
            :notes="selectedPlanCard.notes"
            :complete="selectedPlanCard.complete"
            :compact="false"
            :trip-id="selectedPlan ? selectedPlan.id : ''"
          />
        </scroll-view>
      </view>
    </view>
  </view>
</template>

<script>
import LyjSegment from '../../components/LyjSegment.vue'
import PlanCard from '../../components/PlanCard.vue'
import { get, post } from '../../api/client'
import { getCurrentUser, clearCurrentUser } from '../../store/user'
import { publishPendingCount } from '../../store/pendingBadge'

/** 没绑定时后端会走提前返回、连 privacy 字段都不给 —— 前端的兜底必须是"全关"。 */
const DENIED = { location_level: 'off', health_level: 'off', bound: false }

export default {
  components: { LyjSegment, PlanCard },
  data() {
    return {
      user: null,
      trips: [],
      plans: [],
      pendingConfirmations: [],
      actionLoading: {},
      selectedPlan: null,
      selectedPlanCard: null,
      medications: [],
      privacy: DENIED,
      elderName: '',
      elderCity: '',
      latestLocation: null,
      timer: null,
      lastRefresh: '',
    }
  },
  computed: {
    latestLocationTime() {
      if (!this.latestLocation || !this.latestLocation.created_at) return ''
      try {
        const d = new Date(this.latestLocation.created_at)
        const hh = String(d.getHours()).padStart(2, '0')
        const mm = String(d.getMinutes()).padStart(2, '0')
        const ss = String(d.getSeconds()).padStart(2, '0')
        return `最近上报 ${hh}:${mm}:${ss}`
      } catch (e) {
        return ''
      }
    },
    elderLine() {
      if (!this.privacy.bound) return '尚未绑定老人'
      const who = [this.elderName, this.elderCity].filter(Boolean).join(' · ')
      return this.lastRefresh ? `${who}｜已更新 ${this.lastRefresh}` : who
    },
    privacyNote() {
      const p = this.privacy
      if (!p.bound) {
        return '还没有和老人建立绑定关系。在绑定之前，位置和健康数据一项都不会给。'
      }
      const parts = []
      if (p.location_level === 'off') parts.push('位置未开放')
      else if (p.location_level === 'city') parts.push('位置只到城市级')
      if (p.health_level === 'off') parts.push('健康未开放')
      else if (p.health_level === 'summary') parts.push('健康只给摘要')
      if (!parts.length) return ''
      return `${parts.join('、')}。这是老人自己的设置，只有他本人能改。`
    },
    medEmptyText() {
      if (this.privacy.health_level === 'off') return '老人未开放健康信息给您'
      return '暂无用药计划'
    },
    pendingCount() {
      return this.pendingConfirmations.filter((t) => !t.status || t.status === 'pending').length
    },
    consolidatedPlans() {
      const list = []
      const seenIds = new Set()
      const seenActive = new Set()
      const source = [...(this.plans || []), ...(this.trips || [])]
      for (const item of source) {
        const id = item.id || item.trip_id
        let planObj = item.plan
        if (typeof planObj === 'string') {
          try {
            planObj = JSON.parse(planObj)
          } catch (e) {
            planObj = null
          }
        }
        const title = item.title || (planObj && planObj.title) || item.purpose || ''
        if (!title) continue
        if (id && seenIds.has(id)) continue

        const status = item.status || 'planned'
        const type = item.type || ((planObj && planObj.type) || (title.includes('就医') ? 'medical_plan' : 'trip_plan'))
        const dest = item.destination || (planObj && planObj.city) || (planObj && planObj.destination) || this.getDestination({ ...item, plan: planObj }) || ''

        if (status === 'planned' || status === 'ongoing') {
          const activeKey = dest ? `dest:${dest}:${type}` : `title:${title}`
          if (seenActive.has(activeKey)) continue
          seenActive.add(activeKey)
        }

        if (id) seenIds.add(id)
        list.push({
          id: id || `plan-${list.length}`,
          trip_id: item.trip_id || id,
          title,
          type,
          status,
          destination: dest,
          created_at: item.created_at,
          plan: planObj || item.plan,
        })
      }
      return list
    },
  },
  onShow() {
    this.user = getCurrentUser()
    if (!this.user || this.user.role !== 'child') {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.loadAll()
    this.startPolling()
  },
  onHide() {
    this.stopPolling()
  },
  onUnload() {
    this.stopPolling()
  },
  methods: {
    startPolling() {
      this.stopPolling()
      this.timer = setInterval(() => this.loadAll(true), 5000)
    },
    stopPolling() {
      if (this.timer) {
        clearInterval(this.timer)
        this.timer = null
      }
    },
    logout() {
      clearCurrentUser()
      uni.reLaunch({ url: '/pages/login/login' })
    },
    openPlan(p) {
      this.selectedPlan = p
      let planObj = p.plan
      if (typeof planObj === 'string') {
        try {
          planObj = JSON.parse(planObj)
        } catch (e) {
          planObj = null
        }
      }
      this.selectedPlanCard = this._toCard(planObj ? { ...p, ...planObj } : p)
    },
    closePlan() {
      this.selectedPlan = null
      this.selectedPlanCard = null
    },
    _toCard(d) {
      if (!d) return null
      const pages = d.pages || []
      const notes = []
      if (d.subtitle) notes.push(d.subtitle)
      if (d.disclaimer) notes.push(d.disclaimer)
      if (d.footnote) notes.push(d.footnote)
      let sections = pages.map((p) => ({
        heading: p.title || '',
        rows: p.rows || [],
        notes: p.notes || [],
      }))
      if (!sections.length) {
        if (d.body && typeof d.body === 'object') {
          const rows = Object.entries(d.body).map(([label, value]) => ({
            label,
            value: String(value),
            missing: false,
          }))
          sections = [{ heading: d.title || '详情', rows, notes: [] }]
        } else {
          const rows = []
          if (d.destination || d.city) rows.push({ label: '目的地', value: d.destination || d.city })
          if (d.purpose) rows.push({ label: '行程目的', value: d.purpose })
          if (d.status) rows.push({ label: '状态', value: this.statusText(d.status) })
          if (d.created_at) rows.push({ label: '规划时间', value: this.fmtTime(d.created_at) })
          sections = [{ heading: '行程与计划概要', rows, notes: [] }]
        }
      }
      return {
        kind: 'card',
        title: d.title || d.purpose || '出行与就医计划书',
        sections,
        notes,
        complete: d.complete !== false,
        compact: false,
      }
    },
    async loadAll(silent) {
      try {
        const d = await get(`/api/child/${this.user.id}/dashboard`)
        this.privacy = d.privacy || DENIED
        this.elderName = d.elder ? d.elder.name : ''
        this.elderCity = d.elder ? d.elder.city || '' : ''
        this.trips = d.trips || []
        this.plans = d.plans || []
        if (d.latest_location) {
          this.latestLocation = d.latest_location
        }

        const serverPending = d.pending_confirmations || []
        const serverIds = new Set(serverPending.map((x) => x.id))
        const now = Date.now()
        const kept = []
        for (const local of this.pendingConfirmations) {
          if (serverIds.has(local.id)) {
            const fresh = serverPending.find((x) => x.id === local.id)
            if (local.status && local.status !== 'pending') {
              kept.push(local)
            } else {
              kept.push(fresh)
            }
          } else {
            // Keep locally resolved items temporarily during background polling (10s)
            if (silent && local.status && local.status !== 'pending' && (!local.resolvedAt || now - local.resolvedAt < 10000)) {
              kept.push(local)
            }
          }
        }
        for (const fresh of serverPending) {
          if (!kept.some((x) => x.id === fresh.id)) {
            kept.push(fresh)
          }
        }
        this.pendingConfirmations = kept
        publishPendingCount(this.pendingCount)

        this.medications = d.medications || []
        this.lastRefresh = this.fmtClock(new Date())
      } catch (e) {
        if (!silent) uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
    },

    taskIcon(t) {
      const map = {
        book_ticket: '🚄',
        search_train: '🚄',
        register_appointment: '🏥',
        search_hospital: '🏥',
        book_hotel: '🏨',
        order_service: '🧹',
        pay: '💸',
      }
      return map[t.tool_name] || '✋'
    },
    taskSummary(t) {
      const card = t.summary_for_child || {}
      return card.summary || t.tool_name || '需要您确认的事项'
    },
    taskReason(t) {
      const card = t.summary_for_child || {}
      return card.reason || ''
    },
    isMedical(p) {
      if (p.type === 'medical_plan') return true
      if (p.type === 'trip_plan') return false
      return !!(
        (p.title && p.title.includes('就医')) ||
        (p.purpose && p.purpose.includes('就医'))
      )
    },
    getDestination(p) {
      if (p.destination) {
        const d = String(p.destination).trim()
        return d.endsWith('市') && d.length > 2 ? d.slice(0, -1) : d
      }
      const plan = (typeof p.plan === 'object' && p.plan) ? p.plan : {}
      const cityOrDest = plan.city || plan.destination
      if (cityOrDest) {
        const d = String(cityOrDest).trim()
        return d.endsWith('市') && d.length > 2 ? d.slice(0, -1) : d
      }
      if (plan.body && typeof plan.body === 'object') {
        const bodyVal = plan.body['天气与穿衣/城市'] || plan.body['去程车票 + 返程建议/到达']
        if (bodyVal) {
          const cleanVal = String(bodyVal).replace(/南站|东站|西站|北站|虹桥|站/g, '').trim()
          return cleanVal.endsWith('市') && cleanVal.length > 2 ? cleanVal.slice(0, -1) : cleanVal
        }
      }
      const title = p.title || p.purpose || ''
      for (const city of ['北京', '上海', '杭州', '南京', '苏州', '广州', '深圳', '成都', '重庆', '武汉', '西安', '青岛', '黄山']) {
        if (title.includes(city)) return city
      }
      const scenicMap = {
        '西湖': '杭州', '故宫': '北京', '长城': '北京', '天安门': '北京',
        '外滩': '上海', '东方明珠': '上海', '迪士尼': '上海',
        '夫子庙': '南京', '玄武湖': '南京', '中山陵': '南京',
        '兵马俑': '西安', '大雁塔': '西安', '协和': '北京', '积水潭': '北京'
      }
      for (const [spot, cName] of Object.entries(scenicMap)) {
        if (title.includes(spot)) return cName
      }
      const match = title.match(/·\s*([^·就医出行计划书]+)/)
      if (match && match[1]) {
        const cleaned = match[1].replace(/两日游|三日游|游玩|出游/g, '').trim()
        return cleaned.endsWith('市') && cleaned.length > 2 ? cleaned.slice(0, -1) : cleaned
      }
      return ''
    },
    async approveTask(t) {
      if (this.actionLoading[t.id]) return
      if (t.status && t.status !== 'pending') return
      if (typeof this.$set === 'function') {
        this.$set(this.actionLoading, t.id, 'approve')
      } else {
        this.actionLoading[t.id] = 'approve'
      }
      try {
        const res = await post(`/api/confirmations/${t.id}/approve?child_id=${this.user.id}`)
        const nextStatus = res.status || (res.ok ? 'executed' : 'failed')
        if (typeof this.$set === 'function') {
          this.$set(t, 'status', nextStatus)
        } else {
          t.status = nextStatus
        }
        t.resolvedAt = Date.now()
        publishPendingCount(this.pendingCount)
        uni.showToast({ title: '已同意并办理', icon: 'success' })
      } catch (err) {
        const msg = err.message || ''
        if (msg.includes('executed') || msg.includes('已执行')) {
          if (typeof this.$set === 'function') this.$set(t, 'status', 'executed')
          else t.status = 'executed'
          t.resolvedAt = Date.now()
          publishPendingCount(this.pendingCount)
        } else if (msg.includes('rejected') || msg.includes('已拒绝')) {
          if (typeof this.$set === 'function') this.$set(t, 'status', 'rejected')
          else t.status = 'rejected'
          t.resolvedAt = Date.now()
          publishPendingCount(this.pendingCount)
        } else if (msg.includes('已处理') || msg.includes('不存在')) {
          this.loadAll(true)
        }
        uni.showToast({ title: msg || '审批失败', icon: 'none' })
      } finally {
        if (typeof this.$delete === 'function') {
          this.$delete(this.actionLoading, t.id)
        } else {
          delete this.actionLoading[t.id]
        }
      }
    },
    async rejectTask(t) {
      if (this.actionLoading[t.id]) return
      if (t.status && t.status !== 'pending') return
      const confirmed = await new Promise((resolve) => {
        uni.showModal({
          title: '确认拒绝',
          content: '确定要拒绝该事项吗？老人端将收到相应提示。',
          success: (r) => resolve(!!r.confirm),
          fail: () => resolve(false),
        })
      })
      if (!confirmed) return
      if (this.actionLoading[t.id]) return
      if (t.status && t.status !== 'pending') return
      if (typeof this.$set === 'function') {
        this.$set(this.actionLoading, t.id, 'reject')
      } else {
        this.actionLoading[t.id] = 'reject'
      }
      try {
        const res = await post(`/api/confirmations/${t.id}/reject?child_id=${this.user.id}`)
        const nextStatus = res.status || 'rejected'
        if (typeof this.$set === 'function') {
          this.$set(t, 'status', nextStatus)
        } else {
          t.status = nextStatus
        }
        t.resolvedAt = Date.now()
        publishPendingCount(this.pendingCount)
        uni.showToast({ title: '已拒绝', icon: 'none' })
      } catch (err) {
        const msg = err.message || ''
        if (msg.includes('rejected') || msg.includes('已拒绝')) {
          if (typeof this.$set === 'function') this.$set(t, 'status', 'rejected')
          else t.status = 'rejected'
          t.resolvedAt = Date.now()
          publishPendingCount(this.pendingCount)
        } else if (msg.includes('executed') || msg.includes('已执行')) {
          if (typeof this.$set === 'function') this.$set(t, 'status', 'executed')
          else t.status = 'executed'
          t.resolvedAt = Date.now()
          publishPendingCount(this.pendingCount)
        } else if (msg.includes('已处理') || msg.includes('不存在')) {
          this.loadAll(true)
        }
        uni.showToast({ title: msg || '操作失败', icon: 'none' })
      } finally {
        if (typeof this.$delete === 'function') {
          this.$delete(this.actionLoading, t.id)
        } else {
          delete this.actionLoading[t.id]
        }
      }
    },

    drugLabel(m) {
      if (m.drug && m.drug !== '老人未开放此项') return m.drug
      return m.precision === 'summary' ? '用药情况（药名未开放）' : m.drug
    },
    takenCount(m) {
      return Object.values(m.taken_today || {}).filter((s) => s === 'taken').length
    },
    statusText(s) {
      return { planned: '已规划', ongoing: '进行中', completed: '已完成' }[s] || s
    },
    fmtTime(iso) {
      if (!iso) return ''
      const d = new Date(iso)
      if (!Number.isFinite(d.getTime())) return ''
      return `${d.getMonth() + 1}/${d.getDate()} ${this.fmtClock(d, false)}`
    },
    fmtClock(d, withSeconds = true) {
      const pad = (n) => String(n).padStart(2, '0')
      const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
      return withSeconds ? `${hm}:${pad(d.getSeconds())}` : hm
    },

    goGuardian(t) {
      uni.navigateTo({ url: `/pages/child/guardian?trip_id=${t.trip_id || t.id}` })
    },
    openGuardianMap(tripId) {
      const url = tripId ? `/pages/child/guardian?trip_id=${tripId}` : '/pages/child/guardian'
      uni.navigateTo({ url })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.dash {
  min-height: 100vh;
  background: $lyj-child-bg;
  padding-bottom: $lyj-space-xl;
  box-sizing: border-box;
}
.head {
  /* 子女端保留原生导航栏（pages.json 未设 custom），所以这里**不能**再让一次
     状态栏 —— 那会在标题栏下面多顶出一条空白。导航栏底色已调成同一个深色，
     两块拼起来读成一整个头。 */
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
  gap: $lyj-space-xs;
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
.refresh {
  min-height: $lyj-hit-min;
  display: flex;
  align-items: center;
  background: rgba(255, 255, 255, 0.15);
  color: $lyj-text-on;
  font-size: $lyj-font-sm;
  border-radius: $lyj-radius;
  margin: 0 0 0 $lyj-space-md;
}
.privacy-note {
  margin: 0 $lyj-space-md $lyj-space-sm;
  padding: $lyj-space-md;
  background: $lyj-info-bg;
  border: 2rpx solid $lyj-info-line;
  border-radius: $lyj-radius;
}
.privacy-note-text {
  font-size: $lyj-font-sm;
  color: $lyj-info;
  line-height: $lyj-line-height;
}
.section {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-sm $lyj-space-md;
  padding: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
}
.section-head {
  margin-bottom: $lyj-space-sm;
}
.section-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
}
.empty-row {
  padding: $lyj-space-md 0;
  text-align: center;
}
.empty-row text {
  font-size: $lyj-font-sm;
  color: $lyj-child-muted;
  line-height: $lyj-line-height;
}
.elder-location-section {
  background: #ffffff;
  border: 2rpx solid #bfdbfe;
  border-left: 8rpx solid #2563eb;
  border-radius: $lyj-radius-lg;
  box-shadow: 0 4rpx 16rpx rgba(37, 99, 235, 0.08);
}
.location-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.location-title-wrap {
  display: flex;
  align-items: center;
  gap: 12rpx;
}
.pulse-beacon {
  width: 18rpx;
  height: 18rpx;
  border-radius: 50%;
  background: #10b981;
  box-shadow: 0 0 0 6rpx rgba(16, 185, 129, 0.25);
  animation: beaconPulse 1.8s infinite ease-in-out;
}
@keyframes beaconPulse {
  0% { transform: scale(0.9); opacity: 0.7; }
  50% { transform: scale(1.2); opacity: 1; box-shadow: 0 0 0 10rpx rgba(16, 185, 129, 0); }
  100% { transform: scale(0.9); opacity: 0.7; }
}
.location-title {
  color: #1e3a8a;
  font-weight: 800;
}
.location-refresh-time {
  font-size: 22rpx;
  color: #64748b;
}
.location-card-content {
  padding: 12rpx 0 0;
}
.loc-main-row {
  display: flex;
  align-items: flex-start;
  gap: 16rpx;
}
.loc-icon-badge {
  width: 68rpx;
  height: 68rpx;
  border-radius: 50%;
  background: #eff6ff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 36rpx;
  flex-shrink: 0;
}
.loc-text-block {
  flex: 1;
  min-width: 0;
}
.loc-name-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-wrap: wrap;
}
.loc-name {
  font-size: 32rpx;
  font-weight: 800;
  color: #0f172a;
}
.loc-tag {
  font-size: 22rpx;
  font-weight: 700;
  padding: 2rpx 14rpx;
  border-radius: 12rpx;
  background: #dcfce7;
  color: #15803d;
}
.loc-tag.alert {
  background: #fee2e2;
  color: #b91c1c;
}
.loc-purpose {
  display: block;
  font-size: 24rpx;
  color: #475569;
  margin-top: 6rpx;
}
.loc-note {
  display: block;
  font-size: 24rpx;
  color: #0284c7;
  margin-top: 6rpx;
  background: #f0f9ff;
  padding: 8rpx 14rpx;
  border-radius: 10rpx;
}
.loc-btn-wrap {
  margin-top: 20rpx;
}
.loc-map-btn {
  width: 100%;
  background: #2563eb;
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 700;
  border-radius: 40rpx;
  border: none;
  padding: 12rpx 0;
  cursor: pointer;
  box-shadow: 0 4rpx 12rpx rgba(37, 99, 235, 0.25);
}
.location-empty-box {
  padding: 16rpx 0;
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}
.location-empty-hint {
  font-size: 26rpx;
  color: #64748b;
  line-height: 1.5;
}
.loc-map-btn-sm {
  background: #f1f5f9;
  color: #2563eb;
  border: 2rpx solid #bfdbfe;
  font-size: 26rpx;
  font-weight: 700;
  border-radius: 30rpx;
  align-self: flex-start;
  padding: 6rpx 20rpx;
  cursor: pointer;
}

.pending-section {
  border-left: 8rpx solid #f59e0b;
}
.pending-card {
  background: #fffbeb;
  border: 2rpx solid #fde68a;
  border-radius: $lyj-radius;
  padding: $lyj-space-md;
  margin-bottom: $lyj-space-sm;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-sm;
}
.pending-card:last-child {
  margin-bottom: 0;
}
.pending-card-top {
  display: flex;
  align-items: flex-start;
  gap: $lyj-space-sm;
}
.pending-icon {
  font-size: 40rpx;
  line-height: 1.2;
}
.pending-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.pending-summary-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.pending-summary {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
}
.pending-cost {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: #dc2626;
}
.pending-reason {
  font-size: $lyj-font-sm;
  color: #4b5563;
  margin-top: 2rpx;
}
.pending-time {
  font-size: $lyj-font-xs;
  color: $lyj-child-muted;
  margin-top: 2rpx;
}
.pending-action-bar {
  display: flex;
  justify-content: flex-end;
  padding-top: $lyj-space-xs;
  border-top: 1rpx dashed #fcd34d;
}
.pending-btns {
  display: flex;
  align-items: center;
  gap: $lyj-space-sm;
}
.approve-btn {
  background: #16a34a !important;
  color: #fff !important;
  font-size: $lyj-font-sm;
  font-weight: 600;
  border-radius: $lyj-radius;
  padding: 0 24rpx;
  min-height: 60rpx;
  line-height: 60rpx;
  margin: 0;
}
.reject-btn {
  background: #e5e7eb !important;
  color: #4b5563 !important;
  font-size: $lyj-font-sm;
  font-weight: 600;
  border-radius: $lyj-radius;
  padding: 0 24rpx;
  min-height: 60rpx;
  line-height: 60rpx;
  margin: 0;
}
.inline-status {
  display: flex;
  align-items: center;
  font-size: $lyj-font-sm;
  font-weight: 600;
  padding: 6rpx 16rpx;
  border-radius: $lyj-radius-pill;
}
.inline-status.success {
  background: #dcfce7;
  color: #15803d;
}
.inline-status.rejected {
  background: #f3f4f6;
  color: #6b7280;
}
.inline-status.failed {
  background: #fee2e2;
  color: #b91c1c;
}

.plan-card-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: $lyj-space-md 0;
  border-bottom: 2rpx solid $lyj-child-line;
  gap: $lyj-space-sm;
}
.plan-card-item:last-child {
  border-bottom: none;
}
.plan-item-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  cursor: pointer;
}
.plan-item-title-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: $lyj-space-xs;
}
.plan-badge {
  font-size: $lyj-font-xs;
  font-weight: 600;
  padding: 2rpx 10rpx;
  border-radius: $lyj-radius-pill;
  background: #e0f2fe;
  color: #0369a1;
}
.plan-badge.medical_plan {
  background: #fef3c7;
  color: #b45309;
}
.plan-badge.trip_plan {
  background: #e0f2fe;
  color: #0369a1;
}
.plan-item-title {
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-child-text;
}
.plan-status-badge {
  font-size: $lyj-font-xs;
  font-weight: 600;
  padding: 2rpx 12rpx;
  border-radius: $lyj-radius-pill;
  background: $lyj-info-bg;
  color: $lyj-info;
  margin-left: auto;
}
.plan-status-badge.ongoing {
  background: $lyj-primary-soft;
  color: $lyj-primary;
}
.plan-status-badge.completed {
  background: $lyj-success-bg;
  color: $lyj-success;
}
.plan-item-meta-row {
  display: flex;
  align-items: center;
  gap: $lyj-space-md;
  font-size: $lyj-font-xs;
  color: $lyj-child-muted;
}
.plan-dest {
  color: $lyj-child-text;
  font-weight: 500;
}
.plan-meta-time {
  color: $lyj-child-muted;
}
.plan-actions {
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
  flex-shrink: 0;
}
.plan-btn {
  min-height: 56rpx;
  line-height: 56rpx;
  font-size: $lyj-font-xs;
  padding: 0 16rpx;
  border-radius: $lyj-radius;
  margin: 0;
}
.plan-btn.plan {
  background: #0284c7;
  color: #fff;
}
.plan-btn.guardian {
  background: $lyj-primary;
  color: #fff;
}

.med-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $lyj-space-sm;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-child-line;
}
.med-drug {
  flex: 1;
  font-size: $lyj-font-md;
  color: $lyj-child-text;
}
/* 降级后的那一行：看得见，但不假装是药名 */
.med-drug.masked {
  color: $lyj-child-muted;
  font-style: italic;
}
.med-taken {
  font-size: $lyj-font-sm;
  color: $lyj-success;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
  margin-left: auto;
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

.plan-modal-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: $lyj-space-md;
}
.plan-modal-content {
  width: 100%;
  max-width: 680px;
  max-height: 85vh;
  background: #fff;
  border-radius: $lyj-radius-lg;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
}
.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: $lyj-space-md $lyj-space-lg;
  border-bottom: 2rpx solid $lyj-child-line;
  background: #f8fafc;
}
.modal-head-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
}
.modal-close-btn {
  min-height: 48rpx;
  line-height: 48rpx;
  background: transparent;
  color: $lyj-child-muted;
  font-size: $lyj-font-lg;
  padding: 0 16rpx;
  border: none;
}
.modal-body-scroll {
  flex: 1;
  max-height: calc(85vh - 100rpx);
  padding: $lyj-space-md;
  box-sizing: border-box;
}

.sections-grid {
  display: flex;
  flex-direction: column;
}

/* 电脑端宽屏自适应：只剩 2 个 section 后两列网格会把每张卡压成半宽长条，
   布局失衡 —— 大屏维持单列、限宽居中即可。 */
@media screen and (min-width: 768px) {
  .dash {
    max-width: 960px;
    margin: 0 auto;
    padding: 30rpx 32rpx 100rpx;
  }
}
</style>
