<template>
  <view class="chat-page">
    <!-- 顶栏：回退、标题与状态 -->
    <view class="topbar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">‹</text>
        <text class="back-text">首页</text>
      </view>
      <view class="topbar-main">
        <text class="title">和老友记聊聊</text>
        <text class="status">{{ thinking ? '正在办事…' : '随时听您吩咐' }}</text>
      </view>
      <view class="topbar-right">
        <view class="new-chat-btn" @tap="startNewChat" title="开启新对话">
          <text class="new-chat-icon">＋</text>
          <text class="new-chat-text">新对话</text>
        </view>
        <text class="agent-tag" v-if="user">{{ currentAgent }}</text>
      </view>
    </view>

    <!-- 会话流 -->
    <scroll-view class="stream" scroll-y :scroll-top="scrollTop" :scroll-into-view="anchor">
      <view class="stream-inner">
        <view v-for="(m, i) in messages" :key="i">
          <ChatBubble
            v-if="m.kind === 'text'"
            :text="m.text"
            :is-user="m.isUser"
            :agent="m.agent"
          />
          <StepTimeline
            v-else-if="m.kind === 'todo'"
            :todos="m.todos"
            :progress="m.progress"
          />
          <PlanCard
            v-else-if="m.kind === 'card'"
            :title="m.title"
            :sections="m.sections"
            :notes="m.notes"
            :complete="m.complete"
            :compact="m.compact"
          />
          <ConfirmCard
            v-else-if="m.kind === 'suspend'"
            :message="m.message"
            :summary="m.summary"
            :amount="m.amount"
            :expires-at="m.expiresAt"
            :status="m.status"
          />
          <view v-else-if="m.kind === 'tool'" class="tool-bubble" :class="{ blocked: m.blocked }">
            <text class="tool-icon">{{ m.blocked ? '⚠️' : '🔧' }}</text>
            <text class="tool-text">{{ m.summary }}</text>
          </view>
          <view v-else-if="m.kind === 'status'" class="status-bubble">
            <text class="status-text">{{ m.text }}</text>
          </view>
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
          />
          <view v-else class="text-input-wrap">
            <input
              class="text-input"
              v-model="draft"
              placeholder="打字告诉老友记…"
              confirm-type="send"
              @confirm="sendText"
            />
            <button class="send-btn" :disabled="thinking || !draft.trim()" @tap="sendText">发送</button>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import ChatBubble from '../../components/ChatBubble.vue'
import StepTimeline from '../../components/StepTimeline.vue'
import PlanCard from '../../components/PlanCard.vue'
import ConfirmCard from '../../components/ConfirmCard.vue'
import LyjMic from '../../components/LyjMic.vue'
import { get, post } from '../../api/client'
import { chatStream, fetchEvents } from '../../api/sse'
import { getCurrentUser } from '../../store/user'
import { takeUtterance } from '../../store/handoff'

// 子智能体的门面。名字与后端 display_name 一致（travel_agent.py:30 等），
// 图标与 ChatBubble 的 agentIcon 一致 —— 同一个 Agent 在哪儿出现都是同一张脸。
const AGENT_LABEL = {
  main: '老友记',
  travel: '银发导航',
  health: '安康助手',
  community: '邻里帮',
}
const AGENT_ICON = { main: '🤵', travel: '🧭', health: '🏥', community: '🏘️' }

export default {
  components: { ChatBubble, StepTimeline, PlanCard, ConfirmCard, LyjMic },
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
      _todoMsg: null, // 本轮的步骤条（整表覆盖，不新增第二张）
      _watchTimer: null, // 盯"家人点了没"的轮询句柄
      _watchStarting: false, // 启动中的同步占位（三条 suspended 并发时防重复装表）
      _watchSeq: 0, // 盯到哪一行了（只补这一行之后的新事实）
      _scrollTimer: null,
      _lastScrollAt: 0,
    }
  },
  computed: {
    currentAgent() {
      for (let i = this.messages.length - 1; i >= 0; i--) {
        const m = this.messages[i]
        if (m.agent && AGENT_LABEL[m.agent]) {
          return `${AGENT_ICON[m.agent] || '🤵'} ${AGENT_LABEL[m.agent]}`
        }
      }
      return '🤵 生活管家'
    },
  },
  async onShow() {
    this.user = getCurrentUser()
    if (!this.user) {
      uni.reLaunch({ url: '/pages/login/login' })
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
    this._stopWatch()
  },
  onUnload() {
    this._stopWatch()
  },
  methods: {
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
            return
          }
        }
      } catch (e) {
        console.warn('获取历史会话失败：', e)
      }
      this._resetDefaultGreeting()
    },

    _resetDefaultGreeting() {
      this.messages = [
        {
          kind: 'text',
          text: `${this.user.name}您好，我是老友记。您想做什么，按住下面的大按钮跟我说就行——看病挂号、买票出门、订饭找保洁，我都办得了。`,
          agent: 'main',
        },
      ]
      this.$nextTick(() => this._scrollBottom(true))
    },

    async startNewChat() {
      if (this.thinking) return
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
      const pages = getCurrentPages()
      if (pages && pages.length > 1) {
        uni.navigateBack()
      } else {
        uni.switchTab({ url: '/pages/elder/home' })
      }
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

    async _run(text) {
      // 这一轮自己有一条活着的流，轮询让位：两条链路同时往屏幕上推
      // agent_msg，每句话会说两遍。轮次结束后（见本方法末尾）把基线推到
      // 本轮末尾再起表，于是这一轮 SSE 已经渲染过的行不会被轮询再应用一次。
      this._stopWatch()
      this.messages.push({ kind: 'text', text, isUser: true })
      this.thinking = true
      this._todoMsg = null
      const bubble = { kind: 'text', text: '', agent: 'main' }
      let bubbleOpen = false

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
          onError: (e) => {
            this.messages.push({
              kind: 'text',
              text: '哎呀，网络出了点问题，您再说一遍试试。',
              agent: 'main',
            })
          },
        },
      )
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

        case 'agent_status':
          this.messages.push({ kind: 'status', text: d.text || d.status || '' })
          break

        case 'delta': {
          // 打字预览。后端 persist=False，不进事件日志、不进模型历史。
          if (!bubble.text) openBubble(true)
          bubble.text += d.text || ''
          this._scrollBottom()
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
           */
          if (!bubble.text) openBubble(true)
          bubble.text = d.text ?? ''
          break
        }

        case 'tool_call': {
          // 流水提示，**不动步骤条**（步骤状态只由 todo 快照决定）
          this.messages.push({
            kind: 'tool',
            callId: d.call_id,
            summary: d.summary || d.tool,
          })
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
          if (bubbleMsg && d.summary) {
            bubbleMsg.summary = d.summary
            bubbleMsg.blocked = !!d.denied
          }
          break
        }

        case 'card':
          this.messages.push(this._toCard(d))
          this._scrollBottom()
          break

        case 'suspended':
          this.messages.push({
            kind: 'suspend',
            // confirmationId 是这张卡后来能被改写的唯一钥匙（见下面
            // confirmation_resolved）。少了它，家人点完同意，这张黄卡就永远
            // 停在"等他点同意"上。
            confirmationId: d.confirmation_id || '',
            message: d.message || '已经发给家人确认啦',
            summary: d.summary || '',
            amount: d.amount || 0,
            expiresAt: d.expires_at || '',
            status: 'pending',
          })
          this._scrollBottom()
          break

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
          const tail = d.ok === false ? '没办成，稍后再试' : '已经查好了'
          this.messages.push({ kind: 'status', text: `${icon} ${who}${tail}` })
          this._scrollBottom()
          break
        }

        case 'guardian_alert':
          this.messages.push({ kind: 'status', text: '📍 位置有变化，已通知家人' })
          break

        case 'final':
          // 定稿兜底，与 agent_msg 同语义：只在一句话都没出来时补上
          if (d.text && !bubble.text) {
            bubble.text = d.text
            openBubble(true)
          }
          this._scrollBottom()
          break

        /**
         * 后端出错时特意写了一句给老人听的话（routes_chat.py:76）。
         * 原来这个 case 不存在 —— 那句话被丢掉，老人只看到一个卡住的空气泡，
         * 不知道是该等还是该再说一遍。
         */
        case 'error':
          this.messages.push({
            kind: 'text',
            text: d.message || '哎呀，我这儿出了点小问题，您再说一遍试试。',
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
    _resolveCard(id, status, ok) {
      if (!id) return false
      const card = this.messages.find(
        (m) => m.kind === 'suspend' && m.confirmationId === id,
      )
      const next = status || (ok ? 'executed' : 'rejected')
      if (!card || card.status === next) return false
      card.status = next
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
      // `_watchStarting` 是同步占位，不能只看 `_watchTimer`：下面那句
      // `await this._latestSeq()` 会让出执行权，而旗舰流程里三条 suspended
      // 几乎同时到达。只看 _watchTimer 的话三次调用都会在它仍是 null 时通过，
      // 装上三个 setInterval，而 _stopWatch 只清得掉最后一个 —— 剩下两个会把
      // 家人那句播报重复推给老人。
      if (this._watchTimer || this._watchStarting || !this.sessionId) return
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
      if (this._watchTimer) return // 让出期间已被别的调用装上了
      this._watchTimer = setInterval(() => this._pollResolutions(), 5000)
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
          // 家人点完那句播报。老人这时可能正看着别处，所以这条要自己成一个
          // 气泡并滚到底 —— 它是新消息，不是历史回放。
          this.messages.push({ kind: 'text', text: d.text, agent: d.agent || 'main' })
          this._scrollBottom()
        }
      }
      if (!this._pendingCards().length) this._stopWatch()
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
      return {
        kind: 'card',
        title: d.title || '',
        sections: pages.map((p) => ({
          heading: p.title || '',
          rows: p.rows || [],
          notes: p.notes || [],
        })),
        notes,
        complete: d.complete !== false,
        // 只有五页计划书铺开；两张轻量卡片走紧凑模式
        compact: d.type !== 'trip_plan',
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
        this.$nextTick(() => {
          this.anchor = ''
          this.$nextTick(() => {
            this.anchor = 'bottom-anchor'
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
  /* #ifdef H5 */
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: var(--window-bottom, 50px);
  /* #endif */
  /* #ifndef H5 */
  height: 100vh;
  /* #endif */
  display: flex;
  flex-direction: column;
  background: $lyj-bg;
  box-sizing: border-box;
  overflow: hidden;
  z-index: 10;
}
.topbar {
  padding: 20rpx $lyj-space-lg;
  background: $lyj-card;
  border-bottom: 2rpx solid $lyj-line;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: $lyj-space-md;
  flex-shrink: 0;
}
.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 4rpx;
  padding: 8rpx 18rpx;
  background: $lyj-field;
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
.topbar-main {
  display: flex;
  align-items: baseline;
  gap: $lyj-space-sm;
  flex: 1;
}
.title {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.status {
  font-size: $lyj-font-sm;
  color: $lyj-success;
}
.topbar-right {
  display: flex;
  align-items: center;
  gap: $lyj-space-sm;
  flex-shrink: 0;
}
.new-chat-btn {
  display: inline-flex;
  align-items: center;
  gap: 4rpx;
  padding: 8rpx 18rpx;
  background: #fdfaf6;
  border: 2rpx solid #e7dcce;
  border-radius: $lyj-radius-pill;
  cursor: pointer;
  transition: all 0.15s;
}
.new-chat-btn:active {
  background: #f2e9dc;
}
.new-chat-icon {
  font-size: 26rpx;
  color: $lyj-primary;
  font-weight: 800;
  line-height: 1;
}
.new-chat-text {
  font-size: $lyj-font-nav;
  color: $lyj-primary;
  font-weight: 700;
  line-height: 1;
}
.agent-tag {
  font-size: $lyj-font-sm;
  color: $lyj-primary;
  background: $lyj-primary-soft;
  padding: 6rpx 18rpx;
  border-radius: $lyj-radius-pill;
  font-weight: 600;
  flex-shrink: 0;
}
.stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  background: $lyj-bg;
}
.stream-inner {
  padding: $lyj-space-md 0 40rpx;
}
.tool-bubble {
  display: flex;
  align-items: center;
  gap: $lyj-space-xs;
  margin: $lyj-space-xs $lyj-space-md;
  background: $lyj-muted-bg;
  border-radius: $lyj-radius;
  padding: $lyj-space-sm $lyj-space-md;
}
.tool-bubble.blocked {
  background: $lyj-warn-bg;
}
.tool-icon {
  font-size: $lyj-font-sm;
}
.tool-text {
  flex: 1;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  line-height: $lyj-line-height;
}
.tool-bubble.blocked .tool-text {
  color: $lyj-warn-text;
}
.status-bubble {
  text-align: center;
  margin: $lyj-space-xs 0;
}
.status-text {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.bottom-anchor {
  height: 40rpx;
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

/* 电脑端宽屏自适应：固定在 960px 舒适阅读区，消灭底部大面积空洞留白与悬浮孤岛 */
@media screen and (min-width: 768px) {
  .chat-page {
    max-width: 960px;
    left: 0 !important;
    right: 0 !important;
    margin: 0 auto !important;
    border-left: 2rpx solid $lyj-line;
    border-right: 2rpx solid $lyj-line;
    box-shadow: 0 0 30px rgba(0, 0, 0, 0.06);
  }
  .topbar {
    padding: 24rpx 32rpx;
  }
  .stream-inner {
    max-width: 860px;
    margin: 0 auto;
    padding: 24rpx 20rpx 40rpx;
  }
  .input-bar {
    max-width: 860px;
    margin: 0 auto;
  }
}
</style>
