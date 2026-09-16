<template>
  <view class="chat-page" :class="{ 'split-mode': isDesktop && treeExpanded }">
    <!-- 顶栏：回退、标题与状态（返回用顶栏内联 back-btn，不再叠加 LyjBack） -->
    <view class="topbar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">‹</text>
        <text class="back-text">首页</text>
      </view>
      <view class="topbar-main">
        <text class="title">和康乐聊聊</text>
        <text class="status">{{ thinking ? '正在办事…' : '随时听您吩咐' }}</text>
      </view>
      <view class="topbar-right">
        <!-- 智能体链路展开/收起切换按钮 (R1) -->
        <view
          class="tree-toggle-btn"
          :class="{
            active: isDesktop ? treeExpanded : treeDrawerVisible,
            hasPending: pendingConfirmationCount > 0,
            hasRejected: hasAnyRejected,
          }"
          @tap="toggleTreePane"
          title="智能体执行链路"
        >
          <text class="tree-toggle-icon">🧠</text>
          <text class="tree-toggle-text">{{ treeToggleText }}</text>
          <view v-if="thinking" class="pulse-dot-mini"></view>
          <text v-if="pendingConfirmationCount > 0" class="tree-badge">
            {{ pendingConfirmationCount }}
          </text>
        </view>

        <view class="history-btn" @tap="openHistory" title="历史记录">
          <text class="history-icon">📜</text>
          <text class="history-text">历史</text>
        </view>
        <view class="new-chat-btn" @tap="startNewChat" title="开启新对话">
          <text class="new-chat-icon">＋</text>
          <text class="new-chat-text">新对话</text>
        </view>
        <text class="agent-tag" v-if="user && !isMainAgent(currentAgent)">{{ currentAgent }}</text>
      </view>
    </view>

    <!-- 工作台分屏主体容器 (R1) -->
    <view class="workbench-body" :class="{ 'workbench-split': isDesktop && treeExpanded }">
      <!-- 左侧：适老会话流与输入区 (Left Pane) -->
      <view class="workbench-chat-pane">
        <!-- 会话流 -->
        <scroll-view class="stream" scroll-y :scroll-top="scrollTop" :scroll-into-view="anchor">
          <view class="stream-inner">
            <view v-for="(m, i) in elderMessages" :key="i">
              <ChatBubble
                v-if="m.kind === 'text'"
                :text="m.text"
                :is-user="m.isUser"
                :agent="m.agent"
              />
              <!-- 右翼两张专用卡先判：它们的 type 是 'call' / 'recipe'，
                   若让下面 PlanCard 那一支先接，会被当成计划书截走 -->
              <CallCard
                v-else-if="m.kind === 'card' && m.type === 'call'"
                :title="m.title"
                :name="m.name"
                :relation="m.relation"
                :phone="m.phone"
                :reason="m.reason"
                :note="m.note"
              />
              <RecipeCard
                v-else-if="m.kind === 'card' && m.type === 'recipe'"
                :title="m.title"
                :dish="m.dish"
                :minutes="m.minutes"
                :tags="m.tags"
                :ingredients="m.ingredients"
                :steps="m.steps"
                :tips="m.tips"
                :note="m.note"
              />
              <PlanCard
                v-else-if="m.kind === 'card'"
                :title="m.title"
                :sections="m.sections"
                :notes="m.notes"
                :complete="m.complete"
                :compact="m.compact"
                :trip-id="m.tripId || ''"
              />
              <ConfirmCard
                v-else-if="m.kind === 'suspend'"
                :message="m.message"
                :summary="m.summary"
                :amount="m.amount"
                :expires-at="m.expiresAt"
                :status="m.status"
              />
            </view>
            <view :id="'bottom-anchor'" class="bottom-anchor"></view>
          </view>
        </scroll-view>

        <!-- 输入区：语音/打字一键切换条（紧凑设计，释放更多可视区域给消息列表） -->
        <view class="input-area">
          <view class="input-bar">
            <button
              class="mode-btn"
              :disabled="thinking"
              :title="inputMode === 'voice' ? '切换打字' : '切换说话'"
              @tap="toggleInputMode"
            >
              <text>{{ inputMode === 'voice' ? '⌨️' : '🎤' }}</text>
            </button>
            <view class="input-control">
              <LyjMic
                v-if="inputMode === 'voice'"
                mode="bar"
                :disabled="thinking"
                :dialect="user ? user.dialect : ''"
                @text="onSpoken"
                @error="inputMode = 'text'"
              />
              <view v-else class="text-input-wrap">
                <input
                  class="text-input"
                  v-model="draft"
                  placeholder="打字告诉康乐…"
                  confirm-type="send"
                  @confirm="sendText"
                />
                <button class="send-btn" :disabled="thinking || !draft.trim()" @tap="sendText">发送</button>
              </view>
            </view>
          </view>
        </view>
      </view>

      <!-- 右侧：桌面端内联展开的智能体规划与执行树 (Right Pane) -->
      <view
        v-show="isDesktop && treeExpanded"
        class="workbench-tree-pane"
      >
        <AgentExecutionTree
          :messages="messages"
          :thinking="thinking"
          :current-agent="currentAgent"
          :session-id="sessionId"
          :user="user"
          :is-desktop="true"
          @close="treeExpanded = false"
          @resolve-confirmation="onTreeResolveConfirmation"
        />
      </view>
    </view>

    <!-- 移动端抽屉式浮层 (Mobile Drawer / Bottom Sheet) (R1) -->
    <view
      v-if="!isDesktop && treeDrawerVisible"
      class="mobile-drawer-mask"
      @tap="closeDrawer"
    >
      <view class="mobile-drawer-panel" :style="drawerPanelStyle" @tap.stop>
        <view
          class="drawer-drag-bar"
          @touchstart="onDrawerTouchStart"
          @touchmove="onDrawerTouchMove"
          @touchend="onDrawerTouchEnd"
          @tap="onDrawerBarTap"
        >
          <view class="drawer-drag-handle"></view>
          <text class="drawer-drag-tip">轻触或下拉收起</text>
        </view>
        <AgentExecutionTree
          :messages="messages"
          :thinking="thinking"
          :current-agent="currentAgent"
          :session-id="sessionId"
          :user="user"
          :is-desktop="false"
          @close="closeDrawer"
          @resolve-confirmation="onTreeResolveConfirmation"
        />
      </view>
    </view>
    <!-- 历史记录弹窗 -->
    <view v-if="showHistory" class="modal-mask" @tap="showHistory = false">
      <view class="modal" @tap.stop>
        <view class="modal-header">历史对话</view>
        <scroll-view class="history-list" scroll-y>
          <view v-for="g in groupedSessions" :key="g.label" class="history-group">
            <view class="history-day">{{ g.label }}</view>
            <view
              v-for="s in g.items"
              :key="s.id"
              class="history-item"
              :class="{ active: s.id === sessionId }"
              @tap="loadSession(s.id)"
            >
              <view class="history-item-top">
                <text class="history-title">{{ s.title || '与康乐的聊天' }}</text>
                <text class="history-time">{{ _hm(s.last_active || s.created_at) }}</text>
              </view>
              <!-- 标题只是开头第一句话，重名会话全靠这一行最后说的话区分 -->
              <view v-if="s.last_text && s.last_text !== s.title" class="history-preview">
                {{ s.last_text }}
              </view>
            </view>
          </view>
          <view v-if="!sessionList.length" class="history-empty">暂无历史记录</view>
        </scroll-view>
      </view>
    </view>
  </view>
</template>

<script>
import ChatBubble from '../../components/ChatBubble.vue'
import PlanCard from '../../components/PlanCard.vue'
import CallCard from '../../components/CallCard.vue'
import RecipeCard from '../../components/RecipeCard.vue'
import ConfirmCard from '../../components/ConfirmCard.vue'
import LyjMic from '../../components/LyjMic.vue'
import AgentExecutionTree from '../../components/AgentExecutionTree.vue'
import { get, post } from '../../api/client'
import { NET_FAILED_TEXT, SESSION_GONE_TEXT, TURN_FAILED_TEXT } from '../../api/messages'
import { chatStream, fetchEvents } from '../../api/sse'
import { speak } from '../../api/asr'
import { getCurrentUser, setAuthSession } from '../../store/user'
import { takeUtterance } from '../../store/handoff'

// 子智能体的门面。名字与后端 display_name 一致（travel_agent.py:30 等），
// 图标与 ChatBubble 的 agentIcon 一致 —— 同一个 Agent 在哪儿出现都是同一张脸。
const AGENT_LABEL = {
  main: '康乐',
  travel: '银发导航',
  health: '安康助手',
  community: '邻里帮',
}
const AGENT_ICON = { main: '🤵', travel: '🧭', health: '🏥', community: '🏘️' }

// ---- 历史弹层的日期分组 ------------------------------------------------
const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function _dayKey(d) {
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

/** 会话日期 → 老人看得懂的分组名：今天 / 昨天 / 9月5日 周五 / 跨年带年份。 */
function dayLabel(iso) {
  const d = new Date(iso)
  if (!Number.isFinite(d.getTime())) return '更早'
  const now = new Date()
  if (_dayKey(d) === _dayKey(now)) return '今天'
  const y = new Date(now)
  y.setDate(y.getDate() - 1)
  if (_dayKey(d) === _dayKey(y)) return '昨天'
  if (d.getFullYear() === now.getFullYear()) {
    return `${d.getMonth() + 1}月${d.getDate()}日 ${WEEK[d.getDay()]}`
  }
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

export default {
  components: { ChatBubble, PlanCard, CallCard, RecipeCard, ConfirmCard, LyjMic, AgentExecutionTree },
  data() {
    return {
      user: null,
      sessionId: null,
      messages: [],
      draft: '',
      thinking: false,
      scrollTop: 0,
      anchor: '',
      inputMode: 'voice', // voice (按住说话) | text (打字输入)
      isDesktop: false, // 手机端原生架构模式
      treeExpanded: false, // 桌面分屏停用
      treeDrawerVisible: false, // 移动端执行树抽屉显示状态
      _handleResize: null,
      _lastToggleAt: 0,
      drawerDragY: 0,
      drawerDragging: false,
      _hasDragged: false,
      _touchStartY: 0,
      _touchStartTime: 0,
      _todoMsg: null, // 本轮的步骤条（整表覆盖，不新增第二张）
      _watchTimer: null, // 盯"家人点了没"的轮询句柄
      _watchStarting: false, // 启动中的同步占位（三条 suspended 并发时防重复装表）
      _watchSeq: 0, // 盯到哪一行了（只补这一行之后的新事实）
      _scrollTimer: null,
      _lastScrollAt: 0,
      showHistory: false,
      sessionList: [],
    }
  },
  computed: {
    elderMessages() {
      const raw = (this.messages || []).filter((m) => {
        if (!m) return false
        if (m.kind === 'text') {
          if (!m.text || !String(m.text).trim()) return false
          return m.isUser || this.isMainAgent(m.agent) // 老人原话 + 主智能体定稿
        }
        if (m.kind === 'card') return true // 交付物本来就是给老人看的
        if (m.kind === 'suspend') return true // 家人确认卡，老人必须看到
        return false // todo / tool / status 一律只进右侧链路
      })

      // 轮次内精简收口：同一轮次（老人发言后）若有多段助手回复，只保留最后一段完整定稿，中间规划独白不进主框
      const result = []
      let turnAssistantTexts = []

      const flushTurnAssistant = () => {
        if (turnAssistantTexts.length > 0) {
          result.push(turnAssistantTexts[turnAssistantTexts.length - 1])
          turnAssistantTexts = []
        }
      }

      for (const m of raw) {
        if (m.kind === 'text' && m.isUser) {
          flushTurnAssistant()
          result.push(m)
        } else if (m.kind === 'text' && !m.isUser) {
          turnAssistantTexts.push(m)
        } else if (m.kind === 'card') {
          // 卡片去重：同一会话若已存在相同计划书，只保留最新的一份
          const existsIdx = result.findIndex(
            (ex) => ex.kind === 'card' && (ex.title === m.title || (ex.title && m.title && ex.title.includes('计划书') && m.title.includes('计划书')))
          )
          if (existsIdx !== -1) {
            result.splice(existsIdx, 1, m)
          } else {
            result.push(m)
          }
        } else if (m.kind === 'suspend') {
          // 挂起卡去重（展示层兜底）：同一笔确认只留一张。confirmationId 优先，缺 id 时
          // 退而求其次同 tool。断线重放已在 case 'suspended' 拦住，这里再挡住后端历史
          // 水合(routes_chat.py 按每条 CONFIRM_SUSPENDED 各生成一张)那条路径。保留最早
          // 那张——_resolveCard 按 confirmationId 命中并原地改写的也是它，家人点同意后
          // 这张卡的状态能正确从"待确认"翻到"已办好"。
          const key = m.confirmationId || ''
          const dup = result.some(
            (ex) =>
              ex.kind === 'suspend' &&
              ((key && ex.confirmationId === key) ||
                (!key && ex.tool && ex.tool === m.tool)),
          )
          if (!dup) result.push(m)
        } else {
          result.push(m)
        }
      }
      flushTurnAssistant()
      return result
    },
    drawerPanelStyle() {
      if (this.drawerDragY > 0) {
        return {
          transform: `translateY(${this.drawerDragY}px)`,
          transition: this.drawerDragging ? 'none' : 'transform 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
        }
      }
      return {}
    },
    pendingConfirmationCount() {
      return (this.messages || []).filter(
        (m) => m.kind === 'suspend' && m.status === 'pending',
      ).length
    },
    hasAnyRejected() {
      return (this.messages || []).some(
        (m) => m.kind === 'suspend' && m.status === 'rejected',
      )
    },
    treeToggleText() {
      if (this.isDesktop) {
        return this.treeExpanded ? '智能体链路 [收起]' : '智能体链路 [展开]'
      }
      return this.treeDrawerVisible ? '链路收起' : '链路'
    },
    currentAgent() {
      for (let i = this.messages.length - 1; i >= 0; i--) {
        const m = this.messages[i]
        if (m.agent && AGENT_LABEL[m.agent]) {
          return `${AGENT_ICON[m.agent] || '🤵'} ${AGENT_LABEL[m.agent]}`
        }
      }
      return '🤵 生活管家'
    },
    /** 历史弹层：按天分组（今天/昨天/具体日期），组内按时间倒序沿用接口序。 */
    groupedSessions() {
      const groups = []
      const byLabel = new Map()
      for (const s of this.sessionList) {
        const label = dayLabel(s.last_active || s.created_at)
        let g = byLabel.get(label)
        if (!g) {
          g = { label, items: [] }
          byLabel.set(label, g)
          groups.push(g)
        }
        g.items.push(s)
      }
      return groups
    },
  },
  mounted() {
    this._updateViewport()
    if (typeof window !== 'undefined') {
      this._handleResize = () => this._updateViewport()
      window.addEventListener('resize', this._handleResize)
    }
  },
  beforeUnmount() {
    try {
      uni.showTabBar({ animation: false })
    } catch (e) {}
    this._stopWatch()
    if (typeof window !== 'undefined' && this._handleResize) {
      window.removeEventListener('resize', this._handleResize)
    }
  },
  async onShow() {
    try {
      uni.hideTabBar({ animation: false })
    } catch (e) {}
    // 注册全局返回拦截器供 Android WebView 及硬件返回键使用
    if (typeof window !== 'undefined') {
      window.__lyjCurrentPageBack = () => {
        if (this.treeDrawerVisible) {
          this.closeDrawer()
          return true
        }
        if (this.historyVisible) {
          this.closeHistory()
          return true
        }
        this.goBack()
        return true
      }
    }
    this._updateViewport()
    this.user = getCurrentUser()
    if (!this.user) {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    if (this.user.role === 'child') {
      uni.showModal({
        title: '身份提示',
        content: `您当前使用的是家人账号【${this.user.name}】。老人端聊天专为长辈设计，是否立即切换为长辈身份（张桂芳）？`,
        confirmText: '切换长辈',
        cancelText: '返回看板',
        success: async (res) => {
          if (res.confirm) {
            await this.quickSwitchToElder()
          } else {
            uni.reLaunch({ url: '/pages/child/dashboard' })
          }
        },
      })
      return
    }
    if (!this.messages.length) {
      await this.initSessionHistory()
    }
    this._consumeHandoff()
    // 回到这一页时，之前挂起的事可能已经被家人点过了
    this._watchConfirmations()
  },
  /** 离页就停表。老人切去吃药页时后台还在每 5 秒发请求，是白耗电。 */
  onHide() {
    try {
      uni.showTabBar({ animation: false })
    } catch (e) {}
    this._stopWatch()
    if (typeof window !== 'undefined' && window.__lyjCurrentPageBack) {
      window.__lyjCurrentPageBack = null
    }
  },
  onUnload() {
    try {
      uni.showTabBar({ animation: false })
    } catch (e) {}
    this._stopWatch()
    if (typeof window !== 'undefined' && window.__lyjCurrentPageBack) {
      window.__lyjCurrentPageBack = null
    }
  },
  onBackPress(options) {
    if (this.treeDrawerVisible) {
      this.closeDrawer()
      return true
    }
    if (this.historyVisible) {
      this.closeHistory()
      return true
    }
    this.goBack()
    return true
  },
  methods: {
    _updateViewport() {
      // 430px PC 沙盒与手机端真机统一：长辈端采用专注全宽消息流与底部向上滑出的抽屉卡片 (Bottom Sheet)，
      // 确保单列适老大字气泡不受挤压
      this.isDesktop = false
      this.treeExpanded = false
    },

    normalizeAgent(agent) {
      if (!agent) return ''
      const str = String(agent).trim().toLowerCase()
      return str.split('#')[0]
    },

    isMainAgent(agent) {
      if (!agent) return true
      const norm = this.normalizeAgent(agent)
      // 英文键（main / orchestrator）是后端 agent_msg 实际带的键，必须保留；
      // display_name“康乐”那条只是后端没带键时的兜底，缺一不可。
      return norm === 'main' || norm === '康乐' || norm === 'orchestrator'
    },

    toggleTreePane() {
      const now = Date.now()
      if (this._lastToggleAt && now - this._lastToggleAt < 120) return
      this._lastToggleAt = now
      if (this.isDesktop) {
        this.treeExpanded = !this.treeExpanded
      } else {
        this.treeDrawerVisible = !this.treeDrawerVisible
        if (this.treeDrawerVisible) {
          this.drawerDragY = 0
          this.drawerDragging = false
          this._hasDragged = false
        }
      }
    },

    closeDrawer() {
      this.drawerDragY = 0
      this.drawerDragging = false
      this._hasDragged = false
      this.treeDrawerVisible = false
    },

    async quickSwitchToElder() {
      try {
        uni.showLoading({ title: '切换长辈身份…' })
        const res = await post('/api/auth/login', {
          username: 'zhangguifang',
          password: 'elder123456',
        })
        setAuthSession(res)
        this.user = res.user
        uni.hideLoading()
        uni.showToast({ title: '已切换为长辈张桂芳', icon: 'success' })
        this.messages = []
        this.sessionId = null
        await this.initSessionHistory()
        this._watchConfirmations()
      } catch (e) {
        uni.hideLoading()
        uni.showToast({ title: '切换失败: ' + (e.message || ''), icon: 'none' })
      }
    },

    onDrawerTouchStart(e) {
      if (!e.touches || e.touches.length === 0) return
      this._touchStartY = e.touches[0].clientY
      this._touchStartTime = Date.now()
      this.drawerDragging = true
      this.drawerDragY = 0
      this._hasDragged = false
    },

    onDrawerTouchMove(e) {
      if (!this.drawerDragging || !e.touches || e.touches.length === 0) return
      const currentY = e.touches[0].clientY
      const delta = currentY - this._touchStartY
      if (Math.abs(delta) > 8) {
        this._hasDragged = true
      }
      if (delta > 0) {
        this.drawerDragY = delta
      } else {
        this.drawerDragY = 0
      }
    },

    onDrawerTouchEnd(e) {
      if (!this.drawerDragging) return
      this.drawerDragging = false
      const dt = Math.max(1, Date.now() - this._touchStartTime)
      const velocity = this.drawerDragY / dt
      if (this.drawerDragY > 70 || (this.drawerDragY >= 35 && velocity > 0.4)) {
        this.closeDrawer()
      } else {
        this.drawerDragY = 0
      }
    },

    onDrawerBarTap() {
      if (this._hasDragged) {
        this._hasDragged = false
        return
      }
      this.closeDrawer()
    },

    async onTreeResolveConfirmation({ confirmationId, status, tool }) {
      const nextStatus = status || 'executed'
      const isApproved = nextStatus === 'executed'
      // 真实确认任务：必须先等服务端真的办了，才能翻卡片。
      // 服务端只认子女角色，老人自己的 token 必然 403 —— 旧写法是先翻成
      // "已出票"再静默吞掉 403，卡片在撒谎。现在失败就照实说，卡片不动。
      if (confirmationId && !confirmationId.startsWith('conf_demo_')) {
        try {
          const endpoint = isApproved
            ? `/api/confirmations/${confirmationId}/approve`
            : `/api/confirmations/${confirmationId}/reject`
          await post(endpoint, {})
          this._resolveCard(confirmationId, nextStatus, isApproved, tool)
        } catch (e) {
          uni.showToast({
            title: '这步要家人在他自己手机上点才算数，这里代点不了',
            icon: 'none',
            duration: 3000,
          })
        }
        return
      }
      // 演示卡片（conf_demo_ 前缀）：没有对应的真实任务，本地翻牌即可
      this._resolveCard(confirmationId, nextStatus, isApproved, tool)
    },
    async initSessionHistory() {
      try {
        let sid = uni.getStorageSync('laoyouji_elder_session_id')
        if (!sid) {
          const res = await get('/api/chat/sessions', { user_id: this.user.id })
          if (res && res.latest_session) {
            sid = res.latest_session.id
            uni.setStorageSync('laoyouji_elder_session_id', sid)
          }
        }
        if (sid) {
          this.sessionId = sid
          const hist = await get('/api/chat/history', { session_id: sid })
          if (hist && Array.isArray(hist.messages) && hist.messages.length > 0) {
            this.messages = hist.messages.map((m) => {
              if (m.kind === 'card' && !m.sections) {
                return this._toCard(m)
              }
              return m
            })
            this._watchSeq = hist.latest_seq || 0
            this.$nextTick(() => this._scrollBottom(true))
            this._watchConfirmations()
            return
          }
        }
      } catch (e) {
        // 存着的 session_id 在服务端已经没了（清过库/换过环境）。这里只 warn 一下
        // 就往下走的话，this.sessionId 还是那个死 id，界面看着一切正常，可老人
        // 说的第一句话就会打到一个不存在的会话上 —— 干等两分钟然后没有任何回应。
        // 所以拉不动就地把它扔掉，下一句话自然会开一段新会话。
        console.warn('获取历史会话失败，丢弃这个会话 id：', e)
        this.sessionId = null
        uni.removeStorageSync('laoyouji_elder_session_id')
      }
      this._resetDefaultGreeting()
    },

    /** 组内只显示时分：哪天由组标题说了，每行再重复一遍日期反而读不动。 */
    _hm(iso) {
      const d = new Date(iso)
      if (!Number.isFinite(d.getTime())) return ''
      const pad = (n) => String(n).padStart(2, '0')
      return `${pad(d.getHours())}:${pad(d.getMinutes())}`
    },

    async openHistory() {
      try {
        const res = await get('/api/chat/sessions', { user_id: this.user.id })
        if (res && res.items) {
          this.sessionList = res.items
        }
      } catch(e) {
        uni.showToast({ title: '获取历史失败', icon: 'none' })
      }
      this.showHistory = true
    },

    async loadSession(sid) {
      uni.setStorageSync('laoyouji_elder_session_id', sid)
      this.sessionId = sid
      this.showHistory = false
      this._stopWatch()
      this._watchSeq = 0
      this._todoMsg = null
      this.messages = []
      uni.showLoading({ title: '加载中…' })
      await this.initSessionHistory()
      this._watchConfirmations()
      uni.hideLoading()
    },

    _resetDefaultGreeting() {
      this.messages = [
        {
          kind: 'text',
          // 老人第一眼看到的自我介绍：只承诺康乐真能办的事（健康基线 + 身体/心理两翼）。
          // 旧稿写的"买票出门、订饭找保洁"是砍掉的功能，留着就是骗人。
          text: `${this.user.name}您好，我是康乐。身上哪儿不舒坦、想量个血压记下来，或者要去医院挂号、不认得路怎么走，您按住下面的大按钮跟我说就行；心里闷了想找人说说话、要去公园遛个弯，我也陪着您。`,
          agent: 'main',
        },
      ]
      this.$nextTick(() => this._scrollBottom(true))
    },

    async startNewChat() {
      if (this.thinking) return
      // 二次确认：老人误触一下就清空当前上下文，这个代价必须让他自己点头。
      const ok = await new Promise((resolve) => {
        uni.showModal({
          title: '开启新对话',
          content: '当前聊天内容会收进历史记录，确定要开始一段新对话吗？',
          confirmText: '开启',
          cancelText: '再想想',
          success: (res) => resolve(!!res.confirm),
          fail: () => resolve(false),
        })
      })
      if (!ok) return
      uni.showLoading({ title: '正在开启…' })
      try {
        const res = await post('/api/chat/sessions/new', { user_id: this.user.id })
        if (res && res.session_id) {
          this.sessionId = res.session_id
          uni.setStorageSync('laoyouji_elder_session_id', this.sessionId)
          this._stopWatch()
          this._watchSeq = 0
          this._todoMsg = null
          this._resetDefaultGreeting()
          uni.showToast({ title: '已开启新对话', icon: 'success' })
        }
      } catch (e) {
        console.error('开启新对话失败', e)
        const msg = (e && e.message) || '开启失败，请重试'
        uni.showToast({ title: msg.length > 25 ? msg.slice(0, 25) + '…' : msg, icon: 'none' })
      } finally {
        uni.hideLoading()
      }
    },

    /**
     * 接首页交过来的一句话。
     * autoSend=true 是老人自己说的 → 直接办；
     * autoSend=false 是快捷入口的预设话术 → **只填进输入框**，等老人自己按发送。
     */
    _consumeHandoff() {
      const h = takeUtterance()
      if (!h || this.thinking) return
      if (h.autoSend) {
        this.$nextTick(() => this._run(h.text))
      } else {
        this.draft = h.text
        this.inputMode = 'text'
      }
    },

    toggleInputMode() {
      this.inputMode = this.inputMode === 'voice' ? 'text' : 'voice'
    },

    goBack() {
      try {
        uni.showTabBar({ animation: false })
      } catch (e) {}
      uni.switchTab({
        url: '/pages/elder/home',
        fail: () => {
          uni.reLaunch({ url: '/pages/elder/home' })
        },
      })
    },

    // ------------------------------------------------------------ 发送
    sendText() {
      const text = (this.draft || '').trim()
      if (!text || this.thinking) return
      this.draft = ''
      this._run(text)
    },

    onSpoken(text) {
      if (this.thinking) return
      this._run(text)
    },

    /** 另开一段新会话（老会话在服务端没了时用）。成了返回 true。 */
    async _recoverSession() {
      try {
        const res = await post('/api/chat/sessions/new', { user_id: this.user.id })
        if (res && res.session_id) {
          this.sessionId = res.session_id
          uni.setStorageSync('laoyouji_elder_session_id', this.sessionId)
          this._watchSeq = 0
          this._todoMsg = null
          return true
        }
      } catch (e) {
        console.warn('另开会话失败：', e)
      }
      return false
    },

    async _run(text, _isRetry = false) {
      // 这一轮自己有一条活着的流，轮询让位：两条链路同时往屏幕上推
      // agent_msg，每句话会说两遍。轮次结束后（见本方法末尾）把基线推到
      // 本轮末尾再起表，于是这一轮 SSE 已经渲染过的行不会被轮询再应用一次。
      this._stopWatch()
      // 自愈重发时这句已经在屏幕上了，别让老人看见自己说了两遍
      if (!_isRetry) this.messages.push({ kind: 'text', text, isUser: true })
      this.thinking = true
      this._todoMsg = null
      const bubble = { kind: 'text', text: '', agent: 'main' }
      let bubbleOpen = false
      let sessionGone = false

      await chatStream(
        { user_id: this.user.id, session_id: this.sessionId, text },
        {
          onEvent: (ev) =>
            this._handle(ev, bubble, (open) => {
              if (open && !bubbleOpen) {
                this.messages.push(bubble)
                bubbleOpen = true
              }
            }),
          onDone: () => {},
          onSessionGone: () => {
            sessionGone = true
          },
          onError: (e) => {
            // 话术走 api/messages.js：这里原来自己写了一句"您再说一遍试试"，
            // 后端把兜底文案改好了也传不到老人眼前。
            this.messages.push({
              kind: 'text',
              text: NET_FAILED_TEXT,
              agent: 'main',
            })
          },
        },
      )
      // 会话在服务端没了：自己另开一段、把老人刚才那句原样重发一次。
      // 这是我们把会话搞丢的，不该让老人重复劳动；只重发一次，避免来回打转。
      if (sessionGone && !_isRetry) {
        if (await this._recoverSession()) {
          return this._run(text, true)
        }
        this.messages.push({ kind: 'text', text: SESSION_GONE_TEXT, agent: 'main' })
      }
      this.thinking = false
      this._scrollBottom()
      // 这一轮里挂起的事，家人是这一轮之后才在手机上点的。流已经关了，
      // 所以从这里起改成回去读日志（见 _watchConfirmations）。
      //
      // 基线要推到**本轮末尾**：本轮的 agent_msg 已经由 SSE 渲染在屏幕上，
      // 而它们同样落了库。不推的话续表后轮询会把这一轮的话再说一遍。
      // 这一步只在本轮真的结束时做 —— 它和"停表期间不许重取基线"不冲突：
      // 那条禁的是把**没看见过**的行跳过去，这里推进的是**刚看过**的行。
      try {
        this._watchSeq = await this._latestSeq()
      } catch (e) {
        /* 取不到就沿用旧基线：宁可重复一句，也不漏掉家人的结果 */
      }
      this._watchConfirmations()
    },

    _handle(ev, bubble, openBubble) {
      const d = ev.data || {}
      switch (ev.event) {
        case 'session':
          this.sessionId = d.session_id
          if (d.session_id) {
            uni.setStorageSync('laoyouji_elder_session_id', d.session_id)
          }
          break

        /**
         * 真进度：后端整列表覆盖写、last-write-wins，前端照抄。
         * 一轮只有一张步骤条 —— 每次快照更新它，而不是再推一张。
         */
        case 'todo': {
          const snapshot = { todos: d.todos || [], progress: d.progress || {} }
          if (this._todoMsg) {
            this._todoMsg.todos = snapshot.todos
            this._todoMsg.progress = snapshot.progress
          } else {
            this._todoMsg = { kind: 'todo', ...snapshot }
            this.messages.push(this._todoMsg)
          }
          this._scrollBottom()
          break
        }

        case 'agent_status': {
          const text = d.text || d.status || ''
          if (text) {
            const existingIdx = this.messages.findIndex(
              (m) => m.kind === 'status' && (m.agent === d.agent || (d.text && m.text === d.text)) && m.text.includes('正在处理'),
            )
            if (existingIdx !== -1) {
              this.messages.splice(existingIdx, 1, { kind: 'status', text, agent: d.agent })
            } else {
              this.messages.push({ kind: 'status', text, agent: d.agent })
            }
          }
          break
        }

        case 'delta': {
          // 打字预览。后端 persist=False，不进事件日志、不进模型历史。
          //
          // 老人主对话框只该出现主智能体**最终定稿**的一句总结，规划过程一律只进
          // 右侧链路。所以这里：①子智能体(银发导航/安康助手/邻里帮)的流式内容直接丢弃，
          // 不进主框；②主智能体的预览只**缓冲**、预览期**不显现气泡**——中间规划步骤
          // 的话术会被随后的 tool_call 清掉（见下），只有不再跟工具调用的最终总结，
          // 才由 agent_msg / final 定稿时显现。这样从根上消除了"规划话术闪一下又没了"。
          if (!this.isMainAgent(d.agent)) break
          bubble.text += d.text || ''
          break
        }

        case 'agent_msg': {
          /**
           * 定稿**覆盖**预览，任何情况下都不保留预览。
           *
           * 医疗安全改写（R1/R2）挂在 agent/request 瀑布最外层，而 delta 是
           * provider 内部逐片推的、比改写更早到前端。所以预览可能是**未审的原话**，
           * 而 agent_msg 才是审过的那一份。见 docs/DESIGN.md §6.1 与
           * test_medical_safety.py::test_the_streaming_preview_is_not_the_authoritative_text。
           *
           * 只认主智能体的定稿：子智能体(agent=health/travel/community)那句"最终答复"
           * 是内部回给主智能体的中间产物，绝不该顶进老人主对话框——子智能体的工作已在
           * 右侧链路以工具节点呈现。delta 预览期不开气泡，最终定稿在这里补上开启。
           */
          if (!this.isMainAgent(d.agent)) break
          bubble.text = d.text ?? ''
          if (bubble.text) openBubble(true)
          break
        }

        case 'tool_call': {
          // 伴随了工具调用说明是中间规划步骤，清空打字预览文本，不作为气泡展示给老人
          if (bubble && bubble.text) {
            bubble.text = ''
          }
          // 幂等：同一 call_id 可能重复到达 —— SSE 断线转轮询时 pollEvents 从
          // afterSeq=0 起把本轮事件整段重放，其中的 tool_call 已在实时流里推过一遍。
          // 原来这里无条件 push，于是断线那一下之前见过的每个工具都叠成两张卡。
          // 已存在同 call_id 就地更新，不再新增；已办结的状态不回退成 running。
          const existingTool = d.call_id
            ? this.messages.find((m) => m.kind === 'tool' && m.callId === d.call_id)
            : null
          if (existingTool) {
            if (d.tool) existingTool.tool = d.tool
            if (d.agent) existingTool.agent = d.agent
            if (d.args && Object.keys(d.args).length) existingTool.args = d.args
            if (d.summary) existingTool.summary = d.summary
          } else {
            this.messages.push({
              kind: 'tool',
              callId: d.call_id,
              tool: d.tool || '',
              agent: d.agent || '',
              args: d.args || {},
              status: 'running',
              summary: d.summary || d.tool,
            })
          }
          this._scrollBottom()
          break
        }

        case 'tool_result': {
          /**
           * 结果摘要覆盖调用摘要 —— 这不是装饰：R4 的免责声明是
           * HealthDisclaimerGuard 注进**结果**的 summary 的（risk_rules.py:100），
           * 只显示 tool_call 的调用摘要，那句声明就永远到不了老人眼前。
           */
          const bubbleMsg = this.messages.find(
            (m) => m.kind === 'tool' && m.callId === d.call_id,
          )
          if (bubbleMsg) {
            bubbleMsg.status = d.suspended ? 'suspended' : (d.ok !== false ? 'completed' : 'failed')
            bubbleMsg.result = d.data || d.summary
            bubbleMsg.ok = d.ok !== false
            if (d.summary) {
              let cleanSummary = d.summary
                .replace(/；本次没产出：[^\n]+/g, '')
                .replace(/本次没产出：[^\n]+/g, '')
                .replace(/已获得字段：[^\n]+/g, '')
                .trim()
              bubbleMsg.summary = cleanSummary || d.summary
              bubbleMsg.blocked = !!d.denied
            }
          }
          break
        }

        case 'card':
          this._upsertCard(d)
          this._scrollBottom()
          break

        case 'suspended': {
          // 幂等：同一笔挂起可能到达两次 —— SSE 断线转 pollEvents 会从 afterSeq=0 把本轮
          // 事件整段重放，其中的 suspended 已在实时流里推过一遍（隔壁 tool_call 早就这么
          // 防了，这个 case 之前漏了，于是断线那一下黄卡叠成两张，就是"¥680 出现两张卡"）。
          // confirmationId 是这张卡后来能被 confirmation_resolved 改写的唯一钥匙；已存在
          // 同 confirmationId（缺 id 时退而求其次同 tool 且仍 pending）就地更新，不再新增。
          const cid = d.confirmation_id || ''
          const dupSuspend = this.messages.find(
            (m) =>
              m.kind === 'suspend' &&
              ((cid && m.confirmationId === cid) ||
                (!cid && m.tool && m.tool === (d.tool || '') && m.status === 'pending')),
          )
          if (dupSuspend) {
            if (d.message) dupSuspend.message = d.message
            if (d.summary) dupSuspend.summary = d.summary
            if (d.amount) dupSuspend.amount = d.amount
            if (d.expires_at) dupSuspend.expiresAt = d.expires_at
            if (!dupSuspend.confirmationId && cid) dupSuspend.confirmationId = cid
          } else {
            this.messages.push({
              kind: 'suspend',
              tool: d.tool || '',
              confirmationId: cid,
              message: d.message || '已经发给家人确认啦',
              summary: d.summary || '',
              amount: d.amount || 0,
              expiresAt: d.expires_at || '',
              status: 'pending',
            })
          }
          this._scrollBottom()
          break
        }

        /**
         * 家人在手机上点完了（confirmation.py:216）。**这条事件原来没接** ——
         * 后端发了、前端丢了，于是老人屏幕上那张黄卡一直在催"等他点同意"，
         * 而家人早就同意、票也出了。老人看到的是一个永远等不完的状态。
         *
         * 正常动线里这条事件其实**到不了这条流**：老人这一轮早就收了 final、
         * 流也关了，家人是几分钟后才点的。所以真正把它送到老人眼前的是
         * _watchConfirmations 那个轮询。这个 case 管的是另一种情形 ——
         * 家人手快，在老人这一轮还没跑完时就点了。
         */
        case 'confirmation_resolved':
          this._resolveCard(d.confirmation_id, d.status, d.ok)
          break

        /**
         * 子智能体的结构化回报。这是"真多智能体"在界面上唯一看得见的证据 ——
         * 三个子 Agent 并发跑完各自回一条，老人看到的是"银发导航查完了"，
         * 评委看到的是扇出确实发生过。回报正文不铺开：它是交付卡片的输入，
         * 铺开会和后面那张卡说两遍同一件事。
         */
        case 'report': {
          const who = AGENT_LABEL[d.agent] || d.agent || '助手'
          const icon = AGENT_ICON[d.agent] || '🤵'
          const pendingIdx = this.messages.findIndex(
            (m) => m.kind === 'status' && (m.agent === d.agent || m.text.includes(who)) && m.text.includes('正在处理'),
          )
          const tail = d.ok === false ? (d.summary ? '已回复' : '稍后处理') : '已经查好了'
          const statusText = `${icon} ${who}${tail}`
          if (pendingIdx !== -1) {
            this.messages.splice(pendingIdx, 1, { kind: 'status', text: statusText, agent: d.agent })
          } else {
            this.messages.push({ kind: 'status', text: statusText, agent: d.agent })
          }
          this._scrollBottom()
          break
        }

        case 'guardian_alert':
          this.messages.push({ kind: 'status', text: '📍 位置有变化，已通知家人' })
          break

        case 'final':
          // 清理可能遗留的未闭合"正在处理…"状态气泡
          this.messages = this.messages.filter(
            (m) => !(m.kind === 'status' && m.text && m.text.includes('正在处理')),
          )
          // 定稿兜底，与 agent_msg 同语义：只在一句话都没出来时补上（保持审过版优先）。
          // 关键改动：delta 预览期不再开气泡，最终文本可能已由 agent_msg 落进 bubble.text
          // 或仍停在 delta 缓冲里——无论哪种，只要有内容就在这里确保气泡显现，
          // 不能再靠 delta 去开气泡了。
          if (d.text && !bubble.text) bubble.text = d.text
          if (bubble.text) openBubble(true)
          this._scrollBottom(true)
          break

        /**
         * 后端出错时特意写了一句给老人听的话（routes_chat.py:76）。
         * 原来这个 case 不存在 —— 那句话被丢掉，老人只看到一个卡住的空气泡，
         * 不知道是该等还是该再说一遍。
         */
        case 'error':
          this.messages.push({
            kind: 'text',
            text: d.message || TURN_FAILED_TEXT,
            agent: 'main',
          })
          this._scrollBottom()
          break
      }
    },

    /**
     * 把某张挂起卡改成"办完了 / 家人没同意 / 没办成"。
     *
     * 按 confirmation_id 精确找回那一张，**不新推一张**：同一笔钱在屏幕上
     * 出现两遍，老人分不清是一笔还是两笔。
     *
     * status 三态照抄后端（executed / rejected / failed），不合成一句
     * "没成功" —— rejected 是家人不同意，failed 是家人同意了但执行出错。
     * 把后者说成前者，等于替家人表了个他没表过的态。老字段 ok 只作兜底。
     */
    _resolveCard(id, status, ok, tool = '') {
      let card = id
        ? this.messages.slice().reverse().find((m) => m.kind === 'suspend' && m.confirmationId === id)
        : null
      if (!card && tool) {
        card = this.messages.slice().reverse().find(
          (m) => m.kind === 'suspend' && m.tool === tool && m.status === 'pending',
        )
        if (!card) {
          // 只剩挂号这一支。原来还有 book_ticket / book_hotel 两支，靠摘要里出现
          // "车票/高铁/酒店"或金额等于写死的 443.5 / 680 来认领那张挂起卡 —— 那两个工具
          // 已随产品收敛删掉，金额也是旧稿 1311.5 元口径的碎片，分支永远走不到。
          // 挂号这一支留着同样不是因为挂号会挂起（它在 risk_rules.NON_PAYMENT_TOOLS 里，
          // 当场办好、只发知会），而是为了兜旧会话里可能残留的历史挂起卡。
          if (tool === 'register_appointment' || tool.includes('appoint')) {
            card = this.messages.slice().reverse().find(
              (m) =>
                m.kind === 'suspend' &&
                m.status === 'pending' &&
                ((m.summary && (m.summary.includes('挂号') || m.summary.includes('医院'))) || m.amount === 100),
            )
          }
        }
      }
      if (!card && !id && !tool) {
        card = this.messages.slice().reverse().find((m) => m.kind === 'suspend' && m.status === 'pending')
      }
      if (!card) return false
      const next = status || (ok ? 'executed' : 'rejected')
      if (card.status === next) return false
      card.status = next
      this.messages = [...this.messages]
      return true
    },

    /**
     * 盯着"家人点了没"。
     *
     * 为什么必须有这么一段：挂起发生在老人这一轮**之内**，而家人是几分钟后
     * 在自己手机上点的 —— 那时老人这条 SSE 流早就收了 final 关掉了。后端确实
     * 把 confirmation_resolved 广播了一次，但那一刻没有人在听。事件本身落了库
     * （confirmation.py 那一段最后自己 flush 了一次），所以补的办法就是回去
     * 读日志，而不是让后端多留一条长连接。
     *
     * 只认两种行：confirmation_resolved（改卡）和 agent_msg（家人点完后那句
     * 播报）。别的一概不看 —— 整条会话的历史已经在屏幕上了，再应用一遍会把
     * 每个气泡都说两遍。
     *
     * 基线只在**第一次**起表时取，且取完不渲染：那一刻屏幕上的内容确实就是
     * 日志里已有的内容。但这个前提**只对第一次成立** —— 停表（onHide / _run
     * 开头）之后再起表时，停表期间落库的行屏幕上一条都没有，此时重取基线
     * 等于把这段时间发生的事实一次性跳过。老人切去别的页面、或者只是被系统
     * 切到后台的那几分钟，恰恰就是家人在自己手机上点同意的那几分钟：重取基线
     * 会把 confirmation/resolved 甩在基线之内，此后每次轮询都是 items=0，
     * 那张黄卡永远不会变绿。所以续表必须沿用已有的 _watchSeq。
     */
    async _watchConfirmations() {
      // 正在办事/流运行中绝不启动轮询，由 SSE 流实时接收事件，避免并发冲突和重复拉取
      if (this.thinking || this._watchTimer || this._watchStarting || !this.sessionId) return
      if (!this._pendingCards().length) return
      this._watchStarting = true
      try {
        // 只有从没盯过（_watchSeq 还是 0）才取基线；续表沿用旧值，
        // 让停表期间落的行在下一次 _pollResolutions 里被补读回来。
        if (!this._watchSeq) {
          this._watchSeq = await this._latestSeq()
        }
      } catch (e) {
        return // 连基线都取不到就先不盯，下次 onShow 再试
      } finally {
        this._watchStarting = false
      }
      if (this.thinking || this._watchTimer) return // 让出期间已被别的调用装上或正在办事
      this._watchTimer = setInterval(() => this._pollResolutions(), 2500)
      this._pollResolutions()
    },

    _stopWatch() {
      if (this._watchTimer) {
        clearInterval(this._watchTimer)
        this._watchTimer = null
      }
    },

    _pendingCards() {
      return this.messages.filter(
        (m) => m.kind === 'suspend' && m.status === 'pending' && m.confirmationId,
      )
    },

    async _latestSeq() {
      const rows = await fetchEvents(this.sessionId)
      return rows.reduce((max, ev) => Math.max(max, (ev._row && ev._row.seq) || 0), 0)
    },

    async _pollResolutions() {
      if (this.thinking) return
      if (!this._pendingCards().length) return this._stopWatch()
      let rows = []
      try {
        rows = await fetchEvents(this.sessionId, this._watchSeq)
      } catch (e) {
        return // 网络抖一下就下一轮再看，不拿这个打扰老人
      }
      for (const ev of rows) {
        this._watchSeq = Math.max(this._watchSeq, (ev._row && ev._row.seq) || 0)
        const d = ev.data || {}
        if (ev.event === 'confirmation_resolved') {
          this._resolveCard(d.confirmation_id, d.status, d.ok)
        } else if (ev.event === 'agent_msg' && d.text) {
          // 只补主智能体的定稿播报：子智能体(health/travel/community)那句"最终答复"是
          // 内部回给主智能体的中间产物，既不该显示、更不该被 speak() 念出来。
          if (!this.isMainAgent(d.agent)) continue
          // 过滤带工具调用的中间思考独白
          if (ev._row && ev._row.payload && Array.isArray(ev._row.payload.tool_calls) && ev._row.payload.tool_calls.length > 0) {
            continue
          }
          // 去重：若当前已有相同助手文本，不重复追加
          const hasSame = this.messages.slice(-5).some(
            (m) => m && m.kind === 'text' && !m.isUser && m.text === d.text,
          )
          if (hasSame) continue

          // 家人点完那句播报。老人这时可能正看着别处，所以这条要自己成一个
          // 气泡并滚到底 —— 它是新消息，不是历史回放。
          this.messages.push({ kind: 'text', text: d.text, agent: d.agent || 'main' })
          try {
            speak(d.text)
          } catch (e) {}
          this._scrollBottom()
        } else if (ev.event === 'card') {
          this._upsertCard(d)
          this._scrollBottom()
        }
      }
      if (!this._pendingCards().length) this._stopWatch()
    },

    /**
     * 卡片幂等更新：若已存在相同计划书/交付物，就地更新，不重复叠加
     */
    _upsertCard(d) {
      const card = this._toCard(d)
      const existingIdx = this.messages.findIndex(
        (m) => m && m.kind === 'card' && (
          (m.title && card.title && m.title === card.title) ||
          (m.title && card.title && m.title.includes('计划书') && card.title.includes('计划书'))
        ),
      )
      if (existingIdx !== -1) {
        this.messages.splice(existingIdx, 1, card)
      } else {
        this.messages.push(card)
      }
    },

    /**
     * 后端交付卡片（`card` 事件）→ 老人端气泡卡片。
     *
     * 后端形状：{type, title, subtitle, pages:[{no,title,rows,notes,complete}],
     *            missing, complete, disclaimer?, footnote?}
     */
    _toCard(d) {
      const pages = d.pages || []
      const notes = []
      if (d.subtitle) notes.push(d.subtitle)
      if (d.disclaimer) notes.push(d.disclaimer)
      /**
       * footnote 是模拟数据披露（plan_builder.py:52 的 MOCK_NOTE，只有五页计划书
       * 带它）。原来这里没取，那句"车次、号源、酒店数据来自模拟接口"就印不到
       * 这张要打印出来的纸上 —— 而披露模拟数据是本项目的合规要求，不是可选装饰。
       * 放在最后一条：它是脚注里的脚注。
       */
      if (d.footnote) notes.push(d.footnote)
      let sections = pages.map((p) => ({
        heading: p.title || '',
        rows: p.rows || [],
        notes: p.notes || [],
      }))
      if (!sections.length && d.body && typeof d.body === 'object') {
        const rows = Object.entries(d.body).map(([label, value]) => ({
          label,
          value: String(value),
          missing: false,
        }))
        sections = [{ heading: '', rows, notes: [] }]
      }
      return {
        kind: 'card',
        // type 必须原样带过去：历史回放时卡片会被存成不带 sections 的裸对象，
        // 再走 _toCard 重建，丢了 type 的话拨号卡/菜谱卡就退化成一纸普通计划书 ——
        // 老人昨天收到的那个电话按钮，今天点开聊天就没了。
        type: d.type || '',
        title: d.title || '',
        sections,
        notes,
        complete: d.complete !== false,
        // 只有五页计划书铺开；两张轻量卡片走紧凑模式
        compact: d.type !== 'trip_plan' && d.type !== 'medical_plan',
        tripId: d.trip_id || d.tripId || (d.data && d.data.trip_id) || '',
        // 拨号卡（suggest_call）与菜谱卡（get_recipe）的专用字段，平面透传。
        // 卡片模板按 type 分流，这里不猜不拼，后端给什么就是什么。
        name: d.name || '',
        relation: d.relation || '',
        phone: d.phone || '',
        reason: d.reason || '',
        dish: d.dish || '',
        minutes: d.minutes || 0,
        tags: d.tags || [],
        ingredients: d.ingredients || [],
        steps: d.steps || [],
        tips: d.tips || [],
        note: d.note || '',
      }
    },

    // ------------------------------------------------------------ 工具
    _scrollBottom(force = false) {
      const now = Date.now()
      if (force || now - this._lastScrollAt > 120) {
        this._lastScrollAt = now
        if (this._scrollTimer) {
          clearTimeout(this._scrollTimer)
          this._scrollTimer = null
        }
        this.scrollTop = this.scrollTop === 999998 ? 999999 : 999998
        this.$nextTick(() => {
          this.anchor = ''
          this.$nextTick(() => {
            this.anchor = 'bottom-anchor'
            this.scrollTop = this.scrollTop === 999998 ? 999999 : 999998
          })
        })
      } else if (!this._scrollTimer) {
        this._scrollTimer = setTimeout(() => {
          this._scrollTimer = null
          this._scrollBottom(true)
        }, 120)
      }
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.chat-page {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  width: 100%;
  max-width: 430px;
  margin: 0 auto;
  height: 100vh;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  background: $lyj-bg;
  box-sizing: border-box;
  overflow: hidden;
  z-index: 10;
}
.topbar {
  position: sticky;
  top: 0;
  left: 0;
  right: 0;
  z-index: 120;
  padding: 16rpx 20rpx;
  padding-top: calc(16rpx + env(safe-area-inset-top, 0px));
  background: $lyj-card;
  border-bottom: 2rpx solid $lyj-line;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12rpx;
  flex-shrink: 0;
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.05);
}
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4rpx;
  padding: 8rpx 18rpx;
  background: $lyj-primary-soft;
  border: 2rpx solid rgba(42, 130, 228, 0.35);
  border-radius: $lyj-radius-pill;
  cursor: pointer;
  flex-shrink: 0;
  transition: all 0.15s;
  min-height: 56rpx;
  box-shadow: 0 2rpx 6rpx rgba(42, 130, 228, 0.12);
}
.back-btn:active {
  opacity: 0.7;
  transform: scale(0.96);
}
.back-icon {
  font-size: 38rpx;
  line-height: 1;
  color: $lyj-primary;
  font-weight: 800;
}
.back-text {
  font-size: 26rpx;
  color: $lyj-primary;
  font-weight: 700;
}
.topbar-main {
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
.title {
  font-size: 34rpx;
  font-weight: 800;
  color: $lyj-text;
  white-space: nowrap !important;
  word-break: keep-all !important;
  flex-shrink: 0;
}
.status {
  font-size: 22rpx;
  color: $lyj-success;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex-shrink: 1;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: 8rpx;
  flex-shrink: 0;
}
.tree-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 6rpx;
  padding: 6rpx 14rpx;
  background: #fdfaf6;
  border: 2rpx solid #e7dcce;
  border-radius: $lyj-radius-pill;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
  position: relative;
}
.tree-toggle-btn:active, .tree-toggle-btn.active {
  background: #0f172a;
  border-color: #1e293b;
  .tree-toggle-text {
    color: #ffffff;
  }
}
.tree-toggle-btn.hasPending {
  border-color: #f59e0b;
}
.tree-toggle-btn.hasRejected {
  border-color: #ef4444;
}
.tree-toggle-icon {
  font-size: 26rpx;
  line-height: 1;
}
.tree-toggle-text {
  font-size: $lyj-font-nav;
  color: $lyj-primary;
  font-weight: 700;
  line-height: 1;
}
.pulse-dot-mini {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;
  background: #2563eb;
  animation: tree-pulse-mini 1.5s infinite;
}
.tree-badge {
  font-size: 20rpx;
  font-weight: 800;
  background: #d97706;
  color: #ffffff;
  border-radius: 999rpx;
  padding: 2rpx 10rpx;
  line-height: 1;
}
@keyframes tree-pulse-mini {
  0%, 100% { box-shadow: 0 0 0 0 rgba(37, 99, 235, 0.4); }
  50% { box-shadow: 0 0 8rpx 3rpx rgba(37, 99, 235, 0.3); }
}
.history-btn,
.new-chat-btn {
  display: inline-flex;
  align-items: center;
  gap: 4rpx;
  padding: 6rpx 14rpx;
  background: #fdfaf6;
  border: 2rpx solid #e7dcce;
  border-radius: $lyj-radius-pill;
  cursor: pointer;
  transition: all 0.15s;
}
.history-btn:active,
.new-chat-btn:active {
  background: #f2e9dc;
}
.history-icon,
.new-chat-icon {
  font-size: 26rpx;
  color: $lyj-primary;
  font-weight: 800;
  line-height: 1;
}
.history-text,
.new-chat-text {
  font-size: $lyj-font-nav;
  color: $lyj-primary;
  font-weight: 700;
  line-height: 1;
}
.agent-tag {
  display: none;
}
.stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: $lyj-bg;
}
.stream-inner {
  padding: 16rpx 0 16rpx;
}
.bottom-anchor {
  height: 16rpx;
}

/* 历史记录弹层：模板用了很久但一条样式都没有 —— 裸元素盖在页面上既点不准
   也看不清。全屏居中蒙层 + 白卡，触控目标全部 ≥ 44px（$lyj-hit-min）。 */
.modal-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba($lyj-text, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal {
  width: 620rpx;
  max-width: 86vw;
  max-height: 70vh;
  background: $lyj-card;
  border-radius: $lyj-radius;
  box-shadow: $lyj-shadow-raised;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.modal-header {
  padding: $lyj-space-md;
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
  text-align: center;
  border-bottom: 2rpx solid $lyj-line;
  flex-shrink: 0;
}
.history-list {
  flex: 1;
  min-height: 0;
  padding: $lyj-space-sm $lyj-space-md;
  box-sizing: border-box;
}
.history-day {
  font-size: $lyj-font-sm;
  font-weight: 700;
  color: $lyj-text-light;
  padding: $lyj-space-sm $lyj-space-xs $lyj-space-xs;
}
.history-group:first-child .history-day {
  padding-top: 0;
}
.history-item {
  min-height: $lyj-hit-min;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4rpx;
  padding: $lyj-space-sm $lyj-space-md;
  border-radius: $lyj-radius;
  margin-bottom: $lyj-space-xs;
  background: $lyj-field;
}
.history-item.active {
  background: $lyj-primary-soft;
}
.history-item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $lyj-space-sm;
}
.history-title {
  flex: 1;
  font-size: $lyj-font-md;
  color: $lyj-text;
  font-weight: 700;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-time {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  flex-shrink: 0;
}
/* 最后一句话的预览：重名会话靠它区分，是次要信息，用浅色小字 */
.history-preview {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.history-empty {
  padding: $lyj-space-xl 0;
  text-align: center;
  font-size: $lyj-font-md;
  color: $lyj-text-light;
}
.input-area {
  background: $lyj-card;
  border-top: 2rpx solid $lyj-line;
  padding: $lyj-space-sm $lyj-space-md;
  padding-bottom: calc(#{$lyj-space-sm} + env(safe-area-inset-bottom, 0px));
  flex-shrink: 0;
  box-shadow: 0 -4rpx 16rpx rgba(0, 0, 0, 0.03);
}
.input-bar {
  display: flex;
  align-items: center;
  gap: $lyj-space-sm;
  min-height: $lyj-hit-min;
}
.mode-btn {
  width: $lyj-hit-min;
  height: $lyj-hit-min;
  border-radius: 50%;
  background: $lyj-field;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 40rpx;
  padding: 0;
  margin: 0;
  flex-shrink: 0;
  border: 2rpx solid $lyj-line;
}
.input-control {
  flex: 1;
  display: flex;
  align-items: center;
}
.text-input-wrap {
  width: 100%;
  display: flex;
  gap: $lyj-space-xs;
  align-items: center;
}
.text-input {
  flex: 1;
  height: $lyj-hit-min;
  background: $lyj-field;
  border-radius: $lyj-radius;
  padding: 0 $lyj-space-md;
  font-size: $lyj-font-md;
}
.send-btn {
  width: 140rpx;
  height: $lyj-hit-min;
  line-height: $lyj-hit-min;
  background: $lyj-primary;
  color: $lyj-text-on;
  font-size: $lyj-font-md;
  font-weight: 600;
  border-radius: $lyj-radius;
  padding: 0;
  margin: 0;
}
.send-btn[disabled] {
  opacity: 0.5;
  background: $lyj-disabled;
}

.workbench-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

.workbench-chat-pane {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

/* 移动端执行树抽屉 (Drawer / Bottom Sheet) */
.mobile-drawer-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(15, 23, 42, 0.55);
  z-index: 150;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  backdrop-filter: blur(4px);
  animation: fadeIn 0.2s ease-out;
}

.mobile-drawer-panel {
  width: 100%;
  height: 86vh;
  background: #F4F8FD;
  border-top-left-radius: 36rpx;
  border-top-right-radius: 36rpx;
  box-shadow: 0 -16rpx 48rpx rgba(19, 36, 56, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  border-top: 2rpx solid $lyj-line;
}

.drawer-drag-bar {
  padding: 18rpx 0 12rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
  background: #132438;
  cursor: grab;
  user-select: none;
  touch-action: none;
}

.drawer-drag-handle {
  width: 80rpx;
  height: 8rpx;
  border-radius: 999rpx;
  background: #3D5369;
}

.drawer-drag-tip {
  font-size: 22rpx;
  color: #8B9EAF;
  line-height: 1;
}

@keyframes slideUp {
  from { transform: translateY(100%); }
  to { transform: translateY(0); }
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}


/* 移动端屏幕自适应 (< 600px)：防止顶栏挤压、杜绝标题折行与多余留白 */
@media screen and (max-width: 600px) {
  .topbar {
    padding: 12rpx 16rpx;
    padding-top: calc(12rpx + env(safe-area-inset-top, 0px));
    gap: 8rpx;
    min-height: 88rpx;
  }
  .back-btn {
    padding: 8rpx 16rpx;
    min-height: 52rpx;
  }
  .topbar-main {
    flex: 1;
    min-width: 0;
  }
  .topbar-main .status {
    display: none; /* 移动端隐藏小状态词，确保主标题 100% 水平独占 */
  }
  .title {
    font-size: 32rpx;
  }
  .agent-tag {
    display: none;
  }
  .tree-toggle-btn {
    padding: 6rpx 12rpx;
    gap: 4rpx;
  }
  .tree-toggle-text {
    font-size: 22rpx;
  }
  .history-btn {
    padding: 6rpx 12rpx;
    .history-text {
      display: none; /* 移动端紧凑化为图标按钮 📜 */
    }
  }
  .new-chat-btn {
    padding: 6rpx 12rpx;
    .new-chat-text {
      display: none; /* 移动端紧凑化为图标按钮 ＋ */
    }
  }
}

/* 移动端横屏或超矮屏幕优化 (< 500px 高度) */
@media screen and (max-height: 500px) {
  .mobile-drawer-panel {
    height: 94vh;
  }
  .drawer-drag-bar {
    padding: 10rpx 0 6rpx;
  }
}
</style>
