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
      <!-- 健康概览：这一屏的主结论。子女进来看的就是"我妈现在怎么样"。 -->
      <view class="section overview-section">
        <view class="section-head">
          <text class="section-title">🩺 健康概览</text>
          <text class="section-sub">老人最近的身体状况，来自康乐的记录</text>
        </view>

        <!-- 没有绑定 = 隐私层 fail-closed，一个字段都不给（与后端一致，不在这里放宽） -->
        <view v-if="!privacy.bound" class="empty-row">
          <text>还没有和老人建立绑定关系。绑定之前，健康数据一项都不会给。</text>
        </view>
        <!-- 老人把健康关到 off：连档位都不显示。要看得先请他本人打开，不在这一层绕 -->
        <view v-else-if="privacy.health_level === 'off'" class="empty-row">
          <text>老人未开放健康信息给您。指标、用药和分诊档位都不会显示 —— 这是老人自己的设置，只有他本人能改。</text>
        </view>
        <template v-else>
          <!-- 分诊档位横幅。四档配色不同，因为"要不要去医院"是子女从这一屏上
               唯一必须先读懂的一件事。 -->
          <view class="level-banner" :class="levelClass">
            <view class="level-row">
              <text class="level-word">{{ triageLevel }}</text>
              <text class="level-tag">当前分诊档位</text>
            </view>
            <text class="level-headline">{{ triageHeadline }}</text>
            <text class="level-advice">{{ triageAdvice }}</text>
          </view>

          <!-- 最近一次关键指标。血压 / 血糖是主线，别的指标这一屏不铺开。
               数值属"健康明细"，只有老人开到 full 档才取、才显示。 -->
          <view class="vitals">
            <text class="vitals-title">最近一次关键指标</text>
            <view v-if="!vitals.length" class="empty-row">
              <text>{{ vitalsEmptyText }}</text>
            </view>
            <view v-for="v in vitals" :key="v.metric_type" class="vital-item">
              <text class="vital-name">{{ v.label }}</text>
              <text class="vital-value" :class="levelClassOf(v.level)">{{ v.display }}</text>
              <view class="vital-side">
                <text class="vital-level" :class="levelClassOf(v.level)">{{ v.level }}</text>
                <text class="vital-time">{{ fmtTime(v.measured_at) }}</text>
              </view>
            </view>
          </view>

          <!-- R4：档位是分诊结论，免责声明由代码注入、跟着结论一起出现 -->
          <text v-if="triageDisclaimer" class="overview-disclaimer">{{ triageDisclaimer }}</text>
        </template>
      </view>

      <!-- 就医知会 —— 这块板子的灵魂：知会不审批。
           挂号办完那一刻后端写一条 type='appointment_notice' 的通知，**没有 task_id**、
           没有同意/拒绝、点不点都一样。这里只负责倒序列出来给子女"知道一件事"，
           不要在这儿加回任何待办入口。 -->
      <view class="section notice-section">
        <view class="section-head">
          <text class="section-title">📢 就医知会 ({{ appointmentNotices.length }})</text>
          <text class="section-sub">老人就医由他自己拿主意，这里只是让您知道</text>
        </view>
        <view v-if="!appointmentNotices.length" class="empty-row">
          <text>暂时没有就医知会。老人挂好号的那一刻，康乐会把完整情况发到这里。</text>
        </view>
        <view
          v-for="n in appointmentNotices"
          :key="n.id"
          class="notice-card"
          :class="{ unread: !n.is_read }"
          @tap="markNoticeRead(n)"
        >
          <view class="notice-head">
            <text class="notice-icon">📢</text>
            <view class="notice-main">
              <text class="notice-title">{{ n.title }}</text>
              <text class="notice-time" v-if="n.created_at">知会时间：{{ fmtTime(n.created_at) }}</text>
            </view>
            <text v-if="!n.is_read" class="notice-unread">未读</text>
          </view>
          <text class="notice-summary">{{ n.summary || '这条知会没带上详情' }}</text>
          <view class="notice-meta">
            <text v-if="noticeDate(n)" class="notice-meta-item">🗓️ {{ noticeDate(n) }}</text>
            <text v-if="noticeFee(n) !== ''" class="notice-meta-item">💴 挂号费 {{ noticeFee(n) }} 元</text>
            <text v-if="noticeLevel(n)" class="notice-level" :class="levelClassOf(noticeLevel(n))">
              分诊：{{ noticeLevel(n) }}
            </text>
          </view>
        </view>
        <!-- 把"这不是待办"明说出来 —— 否则子女第一反应还是找同意按钮 -->
        <view v-if="appointmentNotices.length" class="notice-foot">
          <text class="notice-foot-text">这些是「知道了一件事」，不是待办：没有同意 / 拒绝，也不用您点。老人看病不需要谁点头。</text>
        </view>
      </view>

      <!-- 就医与出行计划书（页数以计划数据为准：城际车票 / 异地酒店两页已砍） -->
      <view class="section">
        <view class="section-head">
          <text class="section-title">📋 就医与出行计划 ({{ consolidatedPlans.length }})</text>
        </view>
        <view v-if="!consolidatedPlans.length" class="empty-row">
          <text>暂无计划书（长辈提出就医或出行需求后由康乐生成）</text>
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

    <!-- 完整计划书查看弹窗 -->
    <view v-if="selectedPlan" class="plan-modal-mask" @tap="closePlan">
      <view class="plan-modal-content" @tap.stop>
        <view class="modal-head">
          <!-- 页数跟数据走：PlanCard 里自己会印「共 N 页」，这里的数字必须和它同一个来源，
               写死页数会让同一个弹窗上下两个数字对不上。 -->
          <text class="modal-head-title">{{ modalPageTitle }}</text>
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

/** 概览只铺这两项：血压 / 血糖是康乐的主线，其余指标不在子女首页展开。 */
const KEY_METRICS = ['bp', 'glucose']

export default {
  components: { LyjSegment, PlanCard },
  data() {
    return {
      user: null,
      elderId: '',
      trips: [],
      plans: [],
      pendingConfirmations: [],
      selectedPlan: null,
      selectedPlanCard: null,
      medications: [],
      privacy: DENIED,
      elderName: '',
      elderCity: '',
      // 健康概览：overview 是分诊档位结论，readings 是指标读数。
      // 都可能是 null / 空 —— 那时候宁可说"读不到/还没量过"，也不给宽心话。
      overview: null,
      readings: [],
      appointmentNotices: [],
      cachedNotifications: [],
      timer: null,
      lastRefresh: '',
    }
  },
  computed: {
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
    // 分诊档位：读到了就是后端的结论，读不到时**不给"保健"这种宽心兜底**
    // —— 把没有数据说成"没事"，方向错了不可逆。这里换一句中性的话。
    triageLevel() {
      return this.overview && this.overview.level ? this.overview.level : '暂未算出'
    },
    triageHeadline() {
      const h = this.summarySafeHeadline
      if (h) return h
      if (this.privacy.health_level === 'summary') return '老人只开放到「健康摘要」档，档位细节未共享。'
      return '暂时读不到老人的分诊档位。'
    },
    // 摘要档的第二道闸。headline 是后端拼的（形如「血压 178/105，中重度偏高」），
    // 这一档的规矩是后端把它重建成**不含数的一句**。这里再兜一道：万一哪天降级没
    // 生效、headline 里还夹着数值，宁可退回中性文案 —— 绝不能让横幅印着 178/105、
    // 底下又写着"看不到数"这两个自相矛盾的句子同时出现在一屏上（R6）。
    // 只在 summary 档做这件事：full 档的 headline 本就允许带数值，不裁剪。
    summarySafeHeadline() {
      const h = (this.overview && this.overview.headline) || ''
      if (this.privacy.health_level === 'summary' && /\d/.test(String(h))) return ''
      return h
    },
    triageAdvice() {
      if (this.overview && this.overview.advice) return this.overview.advice
      if (this.privacy.health_level === 'summary') {
        return '档位这一层可以看，具体是哪条指标把它抬上去的，需要老人把健康开放到"完整"档。'
      }
      return '要不要紧，得让医生看了才算数 —— 康乐不给没有数据支撑的宽心话。'
    },
    triageDisclaimer() {
      return (this.overview && this.overview.disclaimer) || ''
    },
    // 四档配色。前两档是"在家照顾好"的暖调，后两档才逐渐转重：
    // "建议就医"是一次进展而不是错误，所以用暖橙而非报警红。
    levelClass() {
      return this.levelClassOf(this.overview && this.overview.level)
    },
    // 指标读数按隐私档裁剪：数值属"健康明细"，只有 full 档才取回来。
    // summary 档连请求都不发 —— 取回来再不显示，等于把闸门开在客户端。
    vitals() {
      if (this.privacy.health_level !== 'full') return []
      const out = []
      for (const mtype of KEY_METRICS) {
        const row = (this.readings || []).find((r) => r.metric_type === mtype)
        if (!row) continue
        const pts = row.points || []
        const last = pts.length ? pts[pts.length - 1] : {}
        out.push({
          metric_type: mtype,
          label: row.label || mtype,
          display: row.display || '',
          level: row.level || '',
          measured_at: last.measured_at || '',
        })
      }
      return out
    },
    vitalsEmptyText() {
      if (this.privacy.health_level === 'summary') {
        return '具体数值未开放：老人只把健康开放到「摘要」档，能看到档位，看不到血压 / 血糖的数。'
      }
      // full 档但一条都没有 —— 明说"还没量过"，不拿一个数字糊上
      return '还没量过 —— 老人还没记过血压或血糖。'
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
    // 弹窗标题里的页数，取自当前这张卡真正的 sections —— 与 PlanCard 内「共 N 页」
    // 同源，所以两处永远同数。没挂到卡时（弹窗还没开）不显示页数，
    // 与 PlanCard 在 sections 为空时不印页码一致。
    modalPageTitle() {
      const card = this.selectedPlanCard
      const n = card && card.sections ? card.sections.length : 0
      return n ? `📖 完整计划书（共 ${n} 页）` : '📖 完整计划书'
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
        title: d.title || d.purpose || '就医与出行计划书',
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
        this.elderId = d.elder ? d.elder.id : ''
        this.trips = d.trips || []
        this.plans = d.plans || []
        this.medications = d.medications || []
        this.cachedNotifications = d.notifications || []

        // 首页不再摆审批的板子，但待确认计数仍要报给通知页的角标
        // （金融类审批按设计保留，那是另一条线的事，不在这一屏展开）。
        this.pendingConfirmations = d.pending_confirmations || []
        publishPendingCount(
          this.pendingConfirmations.filter((t) => !t.status || t.status === 'pending').length
        )

        this.lastRefresh = this.fmtClock(new Date())
        await Promise.all([this.loadHealth(), this.loadAppointmentNotices()])
      } catch (e) {
        if (!silent) uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
    },

    /** 健康概览取数。按 privacy.health_level 分级取，越级的数据连请求都不发。 */
    async loadHealth() {
      if (!this.privacy.bound || this.privacy.health_level === 'off' || !this.elderId) {
        this.overview = null
        this.readings = []
        return
      }
      const jobs = [get('/api/health/overview', { elder_id: this.elderId })]
      // 数值（血压/血糖的数）是"明细"档的数据：summary 档不取，避免把不该给的
      // 东西先拉到客户端再靠前端藏起来 —— 藏在前端等于没藏。
      if (this.privacy.health_level === 'full') {
        jobs.push(get('/api/health/readings', { elder_id: this.elderId }))
      }
      try {
        const [overview, readings] = await Promise.all(jobs)
        this.overview = overview || null
        this.readings = readings ? readings.items || [] : []
      } catch (e) {
        // 取不到就留空，横幅会走中性文案，不拿"保健"兜底
        this.overview = null
        this.readings = []
      }
    },

    /** 就医知会：后端已按 created_at 倒序返回，这里只负责展示。 */
    async loadAppointmentNotices() {
      try {
        const res = await get(`/api/child/${this.user.id}/notifications`, {
          type: 'appointment_notice',
        })
        this.appointmentNotices = res.items || []
      } catch (e) {
        // 兜底：看板响应里也带一份通知，从里面筛出知会 —— 单这一个请求失败
        // 不该让整块知会空掉。
        this.appointmentNotices = (this.cachedNotifications || []).filter(
          (n) => n.type === 'appointment_notice'
        )
      }
    },

    async markNoticeRead(n) {
      if (!n || n.is_read) return
      try {
        await post(`/api/child/notifications/${n.id}/read`)
        if (typeof this.$set === 'function') this.$set(n, 'is_read', true)
        else n.is_read = true
      } catch (e) {
        // 标不上已读不该打断"看知会"这件事
      }
    },

    /** 知会里那几项结构化细节：后端 data 里带的（jsonb，兜底按字符串解析一遍）。 */
    noticeData(n) {
      let d = n && n.data
      if (typeof d === 'string') {
        try {
          d = JSON.parse(d)
        } catch (e) {
          d = null
        }
      }
      return d && typeof d === 'object' ? d : {}
    },
    noticeDate(n) {
      const d = this.noticeData(n)
      const day = d.date || ''
      const slot = d.time || ''
      if (!day) return ''
      return slot ? `${day} ${slot}` : String(day)
    },
    noticeFee(n) {
      const d = this.noticeData(n)
      return d.fee === undefined || d.fee === null ? '' : d.fee
    },
    noticeLevel(n) {
      return this.noticeData(n).level || ''
    },

    levelClassOf(level) {
      if (level === '紧急') return 'lv-emergency'
      if (level === '建议就医') return 'lv-see-doctor'
      if (level === '观察') return 'lv-watch'
      if (level === '保健') return 'lv-care'
      return 'lv-unknown'
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
        // 只认天气那页的城市。这里原来还有个 `plan.body['去程车票 + 返程建议/到达']` ——
        // 那是已被砍掉的"城际车票"页的字段名，那个页面连同跨城出行一起没了，
        // 这行永远取不到值。（计划书四页见 backend/app/agents/plan_builder.py）
        const bodyVal = plan.body['天气与穿衣/城市']
        if (bodyVal) {
          const cleanVal = String(bodyVal).replace(/南站|东站|西站|北站|虹桥|站/g, '').trim()
          return cleanVal.endsWith('市') && cleanVal.length > 2 ? cleanVal.slice(0, -1) : cleanVal
        }
      }
      // 再往下原来有两张表：一张 13 个旅游城市（北京/上海/杭州/黄山…）、一张景区→城市
      // （西湖/故宫/长城/迪士尼/兵马俑/协和…）。它们服务的是"跨城旅游/异地就医"那套
      // 已经砍掉的产品形态 —— 康乐只做本市出行，计划书的目的地就是老人所在的城市，
      // 由 plan_builder 随计划一起给出来，上面几支已经覆盖。留着这两张表，等于在代码里
      // 留着一份"我们会去北京上海"的声明。
      const title = p.title || p.purpose || ''
      const match = title.match(/·\s*([^·就医出行计划书]+)/)
      if (match && match[1]) {
        const cleaned = match[1].replace(/两日游|三日游|游玩|出游/g, '').trim()
        return cleaned.endsWith('市') && cleaned.length > 2 ? cleaned.slice(0, -1) : cleaned
      }
      return ''
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
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.section-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-child-text;
}
.section-sub {
  font-size: $lyj-font-xs;
  color: $lyj-child-muted;
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

/* ---------- 健康概览 ---------- */
.overview-section {
  /* 这一块是首页的主结论，给它一条主色左边线，一眼能和下面几块区分开 */
  border-left: 8rpx solid $lyj-primary;
}
.level-banner {
  border-radius: $lyj-radius;
  padding: $lyj-space-md;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
  border: 2rpx solid transparent;
}
.level-row {
  display: flex;
  align-items: baseline;
  gap: $lyj-space-sm;
}
.level-word {
  font-size: $lyj-font-lg;
  font-weight: 700;
}
.level-tag {
  font-size: $lyj-font-xs;
  color: $lyj-child-muted;
}
.level-headline {
  font-size: $lyj-font-sm;
  color: $lyj-child-text;
  line-height: $lyj-line-height;
}
.level-advice {
  font-size: $lyj-font-sm;
  color: $lyj-child-body;
  line-height: $lyj-line-height;
}
/* 四档：前两档暖，后两档转重。"建议就医"是进展不是错误，故暖橙不报警红。 */
.level-banner.lv-care {
  background: $lyj-success-bg;
  border-color: rgba(46, 139, 87, 0.25);
}
.level-banner.lv-care .level-word {
  color: $lyj-success;
}
.level-banner.lv-watch {
  background: $lyj-warn-bg;
  border-color: rgba(240, 178, 90, 0.4);
}
.level-banner.lv-watch .level-word {
  color: $lyj-warn-text;
}
.level-banner.lv-see-doctor {
  background: $lyj-primary-soft;
  border-color: rgba(255, 107, 53, 0.35);
}
.level-banner.lv-see-doctor .level-word {
  color: $lyj-primary-dark;
}
.level-banner.lv-emergency {
  background: rgba(217, 48, 37, 0.1);
  border-color: rgba(217, 48, 37, 0.35);
}
.level-banner.lv-emergency .level-word {
  color: $lyj-danger;
}
/* 读不到档位：中性灰，不做任何倾向性着色 */
.level-banner.lv-unknown {
  background: $lyj-child-line;
  border-color: $lyj-info-line;
}
.level-banner.lv-unknown .level-word {
  color: $lyj-child-muted;
}
.vitals {
  margin-top: $lyj-space-md;
  display: flex;
  flex-direction: column;
}
.vitals-title {
  font-size: $lyj-font-sm;
  font-weight: 600;
  color: $lyj-child-text;
  margin-bottom: $lyj-space-xs;
}
.vital-item {
  display: flex;
  align-items: center;
  gap: $lyj-space-sm;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-child-line;
}
.vital-item:last-child {
  border-bottom: none;
}
.vital-name {
  flex: 1;
  font-size: $lyj-font-md;
  color: $lyj-child-text;
}
.vital-value {
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-child-text;
}
.vital-side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2rpx;
  min-width: 120rpx;
}
.vital-level {
  font-size: $lyj-font-xs;
  font-weight: 600;
  padding: 2rpx 12rpx;
  border-radius: $lyj-radius-pill;
  background: $lyj-child-line;
  color: $lyj-child-body;
}
.vital-time {
  font-size: $lyj-font-xs;
  color: $lyj-child-muted;
}
/* 指标数值按档位染色，读数一眼能看出轻重 */
.vital-value.lv-care,
.vital-level.lv-care {
  color: $lyj-success;
}
.vital-value.lv-watch,
.vital-level.lv-watch {
  color: $lyj-warn-text;
}
.vital-value.lv-see-doctor,
.vital-level.lv-see-doctor {
  color: $lyj-primary-dark;
}
.vital-value.lv-emergency,
.vital-level.lv-emergency {
  color: $lyj-danger;
}
.vital-level.lv-care {
  background: $lyj-success-bg;
}
.vital-level.lv-watch {
  background: $lyj-warn-bg;
}
.vital-level.lv-see-doctor {
  background: $lyj-primary-soft;
}
.vital-level.lv-emergency {
  background: rgba(217, 48, 37, 0.1);
}
.overview-disclaimer {
  display: block;
  margin-top: $lyj-space-md;
  font-size: $lyj-font-xs;
  color: $lyj-child-muted;
  line-height: $lyj-line-height;
}

/* ---------- 就医知会 ---------- */
.notice-section {
  border-left: 8rpx solid $lyj-info;
}
.notice-card {
  background: $lyj-info-bg;
  border: 2rpx solid $lyj-info-line;
  border-radius: $lyj-radius;
  padding: $lyj-space-md;
  margin-bottom: $lyj-space-sm;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.notice-card:last-child {
  margin-bottom: 0;
}
/* 未读只是"还没看过"，不做红点催促 —— 它是知会，不是待办 */
.notice-card.unread {
  border-color: $lyj-info;
}
.notice-head {
  display: flex;
  align-items: flex-start;
  gap: $lyj-space-sm;
}
.notice-icon {
  font-size: 36rpx;
  line-height: 1.2;
}
.notice-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2rpx;
}
.notice-title {
  font-size: $lyj-font-sm;
  font-weight: 700;
  color: $lyj-child-text;
}
.notice-time {
  font-size: $lyj-font-xs;
  color: $lyj-child-muted;
}
.notice-unread {
  font-size: $lyj-font-xs;
  font-weight: 600;
  color: $lyj-info;
  border: 2rpx solid $lyj-info;
  border-radius: $lyj-radius-pill;
  padding: 0 12rpx;
}
.notice-summary {
  font-size: $lyj-font-sm;
  color: $lyj-child-body;
  line-height: $lyj-line-height;
}
.notice-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: $lyj-space-sm;
}
.notice-meta-item {
  font-size: $lyj-font-xs;
  color: $lyj-child-body;
}
.notice-level {
  font-size: $lyj-font-xs;
  font-weight: 600;
  padding: 2rpx 12rpx;
  border-radius: $lyj-radius-pill;
  background: $lyj-child-line;
  color: $lyj-child-body;
}
.notice-level.lv-care {
  background: $lyj-success-bg;
  color: $lyj-success;
}
.notice-level.lv-watch {
  background: $lyj-warn-bg;
  color: $lyj-warn-text;
}
.notice-level.lv-see-doctor {
  background: $lyj-primary-soft;
  color: $lyj-primary-dark;
}
.notice-level.lv-emergency {
  background: rgba(217, 48, 37, 0.1);
  color: $lyj-danger;
}
.notice-foot {
  margin-top: $lyj-space-sm;
  padding-top: $lyj-space-sm;
  border-top: 2rpx dashed $lyj-info-line;
}
.notice-foot-text {
  font-size: $lyj-font-xs;
  color: $lyj-child-muted;
  line-height: $lyj-line-height;
}

/* ---------- 计划书 ---------- */
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

/* ---------- 今日用药 ---------- */
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

/* 电脑端宽屏自适应：单列限宽居中，避免每张卡被压成半宽长条。 */
@media screen and (min-width: 768px) {
  .dash {
    max-width: 960px;
    margin: 0 auto;
    padding: 30rpx 32rpx 100rpx;
  }
}
</style>
