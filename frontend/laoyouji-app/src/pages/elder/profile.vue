<template>
  <view class="profile-page">
    <view class="topbar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">‹</text>
        <text class="back-text">首页</text>
      </view>
      <text class="title">我的</text>
    </view>

    <view class="user-card">
      <text class="avatar">👵</text>
      <view class="user-info">
        <text class="name">{{ user ? user.name : '' }}</text>
        <text class="city">{{ user ? user.city : '' }} · {{ dialectLabel }}</text>
        <text class="account">账号: {{ user ? user.username || '未设置' : '' }}</text>
      </view>
    </view>

    <!-- 家庭成员与绑定 -->
    <view class="section">
      <text class="section-title">👨‍👩‍👧‍👦 我的家人</text>
      <view class="bind-row">
        <input class="input" v-model="targetUsername" placeholder="输入子女账号关联" />
        <input class="input short" v-model="relation" placeholder="关系（如：儿子）" />
        <button class="mini-btn ok" size="mini" @tap="submitBind">绑定</button>
      </view>
      <view v-if="!members.length" class="empty-note"><text>暂无关联家人</text></view>
      <view v-for="m in members" :key="m.id" class="member-chip">
        <view class="m-left">
          <text class="m-name">{{ m.user ? m.user.name : '家人' }}（{{ m.relation }}）</text>
          <text class="m-status">{{ statusText(m.status) }}</text>
        </view>
        <view class="m-right">
          <button
            v-if="m.status === 'pending' && m.invited_by !== user.id"
            class="mini-btn ok"
            size="mini"
            @tap="acceptBind(m)"
          >
            同意
          </button>
          <button
            v-if="m.status === 'pending' && m.invited_by !== user.id"
            class="mini-btn no"
            size="mini"
            @tap="rejectBind(m)"
          >
            拒绝
          </button>
          <button
            v-if="m.status === 'active'"
            class="mini-btn no"
            size="mini"
            @tap="selectChildForPrivacy(m)"
          >
            设权限
          </button>
        </view>
      </view>
    </view>

    <!-- 方言选择（传给后端 ASR Provider） -->
    <view class="section">
      <text class="section-title">🗣️ 我说话的口音</text>
      <view class="options">
        <view
          v-for="d in dialects"
          :key="d.value"
          class="option"
          :class="{ active: dialect === d.value }"
          @tap="setDialect(d.value)"
        >
          <text>{{ d.label }}</text>
        </view>
      </view>
      <text class="section-note">选准口音，我听得更清楚</text>
    </view>

    <!-- 隐私分级（老人自己掌控授权） -->
    <view class="section" v-if="selectedChild">
      <text class="section-title">🔒 对【{{ selectedChild.name }}】开放权限</text>
      <view class="privacy-row">
        <text class="privacy-label">我的位置</text>
        <view class="options">
          <view
            v-for="o in locationOptions"
            :key="o.value"
            class="option"
            :class="{ active: privacy.location_level === o.value }"
            @tap="setPrivacy('location_level', o.value)"
          >
            <text>{{ o.label }}</text>
          </view>
        </view>
      </view>
      <view class="privacy-row">
        <text class="privacy-label">我的健康</text>
        <view class="options">
          <view
            v-for="o in healthOptions"
            :key="o.value"
            class="option"
            :class="{ active: privacy.health_level === o.value }"
            @tap="setPrivacy('health_level', o.value)"
          >
            <text>{{ o.label }}</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 提醒与保活引导。契约 §3.8：没有桥时不隐藏，换成「请装 App」的说明 -->
    <view class="section">
      <text class="section-title">🔔 提醒与保活</text>

      <view v-if="!native" class="empty-note">
        <text>当前在浏览器中打开，提醒功能需安装康乐 App</text>
      </view>

      <view v-else class="reminder-body">
        <text class="section-note">{{ reminderLine }}</text>
        <view class="perm-list">
          <view v-for="p in permRows" :key="p.key" class="perm-row">
            <text class="perm-name">{{ p.label }}</text>
            <text class="perm-state" :class="p.ok ? 'ok' : 'no'">{{ p.ok ? '已开启' : '未开启' }}</text>
          </view>
        </view>

        <!-- 晨间问候：本机定时，后端没有接口（契约 §10.2）。改了立刻重排闹钟。 -->
        <view class="pref-row">
          <text class="pref-label">每天晨间问候</text>
          <switch :checked="greetingEnabled" color="#FF6B35" @change="toggleGreeting" />
        </view>
        <view class="pref-row">
          <text class="pref-label">问候时间</text>
          <picker mode="time" :value="greetingTime" @change="setGreetingTime">
            <text class="pref-time">{{ greetingTime }}</text>
          </picker>
        </view>

        <button class="btn-ghost" @tap="showGuide">查看保活设置步骤</button>
        <button class="btn-ghost test-btn" @tap="testNotify">试一下提醒</button>
      </view>
    </view>

    <view class="section">
      <button class="btn-ghost" @tap="logout">退出当前登录</button>
    </view>

    <!-- 保活引导弹层：自启动 / 省电白名单 / 通知 / 精确闹钟 四步（契约 §11） -->
    <view v-if="guideVisible" class="guide-mask" @tap="closeGuide">
      <view class="guide-panel" @tap.stop>
        <text class="guide-title">让提醒准时响</text>
        <text class="guide-sub">四步都做完，手机才不会把闹钟顺手清掉</text>

        <view v-for="(s, i) in guideSteps" :key="s.key" class="guide-step">
          <text class="guide-index">{{ i + 1 }}</text>
          <view class="guide-step-body">
            <text class="guide-step-title">{{ s.title }}</text>
            <text class="guide-step-tip">{{ s.tip }}</text>
            <button class="mini-btn ok" size="mini" @tap="runGuideStep(s)">{{ s.actionLabel }}</button>
          </view>
        </view>

        <button class="btn-ghost guide-close" @tap="closeGuide">我知道了</button>
      </view>
    </view>
  </view>
</template>

<script>
import { get, put, post } from '../../api/client'
import { getCurrentUser, setCurrentUser, clearCurrentUser } from '../../store/user'
import {
  nativeSupported,
  syncAll,
  getReminders,
  checkPermissions,
  requestPermission,
  openSettings,
  openKeepAliveGuide,
  notifyNow,
  cancelAll,
} from '../../utils/native'

/**
 * 保活引导弹层的事件名 —— 必须与 utils/native.js 里的 KEEPALIVE_GUIDE_EVENT 逐字一致。
 * 契约把该常量留在 native.js 内部（§10 的导出表里没有它），所以两边各写一份。
 */
const KEEPALIVE_GUIDE_EVENT = 'kangle:keepalive-guide'

/**
 * 晨间问候的本机偏好键与默认值 —— 必须与 utils/native.js:22-23、:29 逐字一致（契约 §10.2 冻结）。
 * 同样因为契约把它们留在 native.js 内部（§10 的导出表里没有），这边只能各写一份。
 */
const GREETING_ENABLED_KEY = 'lyj_greeting_enabled'
const GREETING_TIME_KEY = 'lyj_greeting_time'
const GREETING_DEFAULT_TIME = '08:00'

/* times 校验正则：与 utils/native.js:26、pages/elder/medications.vue:172 逐字相同（契约 §0）。 */
const TIME_RE = /^([01]?\d|2[0-3]):[0-5]\d$/

/** 事件解绑时要用同一个函数引用，放模块级存着。 */
let guideListener = null

const DIALECTS = [
  { value: 'southwestern', label: '西南官话' },
  { value: 'cantonese', label: '粤语' },
  { value: 'wu', label: '吴语' },
  { value: 'mandarin', label: '普通话' },
]

export default {
  data() {
    return {
      user: null,
      dialect: 'mandarin',
      members: [],
      selectedChild: null,
      targetUsername: '',
      relation: '',
      privacy: { location_level: 'realtime', health_level: 'summary' },
      dialects: DIALECTS,
      locationOptions: [
        { value: 'realtime', label: '实时位置' },
        { value: 'city', label: '只看城市' },
        { value: 'off', label: '不给看' },
      ],
      healthOptions: [
        { value: 'full', label: '全部' },
        { value: 'summary', label: '只看摘要' },
        { value: 'off', label: '不给看' },
      ],
      // —— 提醒与保活（原生桥缺失时 native 恒为 false，这一整块退化成一行说明）——
      native: false,
      reminderCount: 0,
      syncMode: '',
      perms: null,
      guideVisible: false,
      // —— 晨间问候偏好：写进 uni 存储的两个本机键，native.js 合成 Reminder 时读同一对键 ——
      greetingEnabled: true,
      greetingTime: GREETING_DEFAULT_TIME,
    }
  },
  computed: {
    dialectLabel() {
      const d = DIALECTS.find((x) => x.value === this.dialect)
      return d ? d.label : '普通话'
    },
    /** 如实描述排期情况：拿不到精确闹钟权限就说"可能延迟几分钟"，不粉饰。 */
    reminderLine() {
      if (!this.reminderCount) {
        return '还没有排上提醒：添加一味药、或打开晨间问候后再回来看看'
      }
      const tail = this.syncMode === 'exact' ? '已开启精确提醒' : '可能延迟几分钟'
      return `已排上 ${this.reminderCount} 条提醒 · ${tail}`
    },
    permRows() {
      const p = this.perms || {}
      return [
        { key: 'notifications', label: '通知', ok: !!(p.notifications && p.notifications.granted) },
        { key: 'exactAlarm', label: '精确闹钟', ok: !!(p.exactAlarm && p.exactAlarm.granted) },
        {
          key: 'batteryOptimized',
          label: '省电白名单',
          ok: !!(p.batteryOptimized && p.batteryOptimized.granted),
        },
      ]
    },
    guideSteps() {
      return [
        {
          key: 'auto_start',
          title: '允许自启动',
          tip: '小米手机：设置 → 应用设置 → 应用管理 → 康乐 → 自启动，把它打开',
          actionLabel: '去设置',
        },
        {
          key: 'battery',
          title: '加入省电白名单',
          tip: '系统清理后台时会顺手清掉闹钟，不白名单就会出现「前几天还响，突然不响了」',
          actionLabel: '去设置',
        },
        {
          key: 'notifications',
          title: '允许通知',
          tip: '通知被关掉的话，到点也不会弹出来',
          actionLabel: '去开启',
        },
        {
          key: 'exact_alarm',
          title: '允许精确闹钟',
          tip: '拿不到就只会晚几分钟响；在设置页里手动打开可以准点到',
          actionLabel: '去开启',
        },
      ]
    },
  },
  onLoad() {
    guideListener = () => this.openGuide()
    try {
      uni.$on(KEEPALIVE_GUIDE_EVENT, guideListener)
    } catch (e) {
      /* 事件总线不可用就不接这一条，页面其余部分照常 */
    }
  },
  onUnload() {
    try {
      uni.$off(KEEPALIVE_GUIDE_EVENT, guideListener)
    } catch (e) {}
  },
  onShow() {
    try {
      uni.showTabBar({ animation: false })
    } catch (e) {}
    this.user = getCurrentUser()
    if (!this.user) {
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.dialect = this.user.dialect || 'mandarin'
    this.loadMembers()
    // 回到「我的」再同步一次：用药计划可能刚被改过，顺带刷新引导页的权限状态。
    this.loadGreetingPrefs()
    this.refreshReminders()
  },
  methods: {
    statusText(s) {
      return { active: '已绑定', pending: '待确认', rejected: '已拒绝', revoked: '已解除' }[s] || s
    },

    /**
     * 同步闹钟 + 刷新引导状态。原生桥缺失时 syncAll/checkPermissions 都会立刻返回空值，
     * 这里只把 native 置为 false，让模板换成"请装 App"那一句。
     * force=true 用于用户显式改动提醒之后 —— 绕开 native.js 的 30 秒防抖，否则改完不重排。
     */
    async refreshReminders(force) {
      this.native = nativeSupported()
      if (!this.native) return
      const out = await syncAll(force ? { force: true } : undefined)
      this.syncMode = (out && out.mode) || ''
      this.reminderCount = getReminders().length
      this.perms = checkPermissions()
    },
    openGuide() {
      this.guideVisible = true
    },
    /**
     * 「查看保活设置步骤」按钮走 native.js 的 openKeepAliveGuide()（契约 §10 的导出），
     * 由它 uni.$emit(KEEPALIVE_GUIDE_EVENT)，本页 onLoad 注册的监听器再打开弹层 ——
     * 不直接 this.guideVisible = true，是为了让那个导出有真实调用点，而不是一个没人调的空接口。
     * 桥不在时它按 §3.8 返回 no_bridge（这一步本来也不会渲染，v-else 之外），就直连兜一层。
     */
    showGuide() {
      const out = openKeepAliveGuide()
      if (!out || !out.ok) this.openGuide()
    },
    /** 读本机的问候偏好；读不到就用默认值 —— 与 native.js 的 readLocalPrefs() 同一套语义。 */
    loadGreetingPrefs() {
      let enabled = true
      let time = GREETING_DEFAULT_TIME
      try {
        const rawEnabled = uni.getStorageSync(GREETING_ENABLED_KEY)
        if (rawEnabled !== '' && rawEnabled !== undefined && rawEnabled !== null) {
          enabled = String(rawEnabled) !== '0'
        }
      } catch (e) {
        /* 读不到就是默认开 */
      }
      try {
        const rawTime = uni.getStorageSync(GREETING_TIME_KEY)
        if (typeof rawTime === 'string' && TIME_RE.test(rawTime)) time = rawTime
      } catch (e) {
        /* 读不到就是默认 08:00 */
      }
      this.greetingEnabled = enabled
      this.greetingTime = time
    },
    /**
     * 写问候偏好并立刻重排闹钟。
     * 契约 §10.2 把这两个键写成活路径，但此前全仓没有任何地方写它们 —— 晨间问候于是永远
     * 锁死在「开 / 08:00」，native.js 里读预取的那两段降级分支成了死代码。这里补上写入端。
     */
    async saveGreetingPrefs() {
      try {
        uni.setStorageSync(GREETING_ENABLED_KEY, this.greetingEnabled ? '1' : '0')
        uni.setStorageSync(GREETING_TIME_KEY, this.greetingTime)
      } catch (e) {
        uni.showToast({ title: '保存失败', icon: 'none' })
        return
      }
      await this.refreshReminders(true)
      uni.showToast({ title: '提醒已更新', icon: 'success' })
    },
    toggleGreeting(e) {
      this.greetingEnabled = !!(e && e.detail && e.detail.value)
      this.saveGreetingPrefs()
    },
    setGreetingTime(e) {
      const v = (e && e.detail && e.detail.value) || ''
      if (!TIME_RE.test(v)) return
      this.greetingTime = v
      this.saveGreetingPrefs()
    },
    closeGuide() {
      this.guideVisible = false
    },
    /**
     * 四步里的"去设置"。弹框/跳页都是异步的，契约 §3.4 明确说 H5 不在回调里等结果 ——
     * 用户从设置页回来时 onShow 会重新探测一次 checkPermissions()。
     */
    runGuideStep(step) {
      if (!step) return
      if (step.key === 'notifications') requestPermission('notifications')
      else openSettings(step.key)
    },
    /** 「试一下提醒」：让长辈当场听到/看到一条，比任何文字说明都管用。 */
    testNotify() {
      notifyNow({
        id: 'test:now',
        kind: 'greeting',
        title: '康乐提醒',
        body: '能看到这条，就说明提醒能弹出来',
        hour: 8,
        minute: 0,
        enabled: true,
        planId: null,
        elderId: this.user ? this.user.id : null,
        repeat: 'daily',
      })
      uni.showToast({ title: '稍等一下，通知马上到', icon: 'none' })
    },

    async loadMembers() {
      try {
        const res = await get('/api/family/members')
        this.members = res.items || []
        const firstActive = this.members.find((m) => m.status === 'active')
        if (firstActive && firstActive.user) {
          this.selectedChild = firstActive.user
          this.loadPrivacy(firstActive.user.id)
        }
      } catch (err) {
        /* ignore */
      }
    },
    selectChildForPrivacy(m) {
      if (!m.user) return
      this.selectedChild = m.user
      this.loadPrivacy(m.user.id)
    },
    async submitBind() {
      if (!this.targetUsername.trim() || !this.relation.trim()) {
        uni.showToast({ title: '请填写子女账号与关系', icon: 'none' })
        return
      }
      try {
        await post('/api/family/requests', {
          target_username: this.targetUsername.trim(),
          relation: this.relation.trim(),
        })
        uni.showToast({ title: '已发送关联申请', icon: 'success' })
        this.targetUsername = ''
        this.relation = ''
        this.loadMembers()
      } catch (e) {
        uni.showToast({ title: e.message || '申请失败', icon: 'none' })
      }
    },
    async acceptBind(m) {
      try {
        await post(`/api/family/requests/${m.binding_id}/accept`, {})
        uni.showToast({ title: '已确认绑定', icon: 'success' })
        this.loadMembers()
      } catch (e) {
        uni.showToast({ title: e.message || '操作失败', icon: 'none' })
      }
    },
    async rejectBind(m) {
      try {
        await post(`/api/family/requests/${m.binding_id}/reject`, {})
        uni.showToast({ title: '已拒绝', icon: 'none' })
        this.loadMembers()
      } catch (e) {
        uni.showToast({ title: e.message || '操作失败', icon: 'none' })
      }
    },
    setDialect(value) {
      this.dialect = value
      this.user.dialect = value
      setCurrentUser(this.user)
      uni.showToast({ title: '好嘞，我记住了', icon: 'success' })
    },
    async loadPrivacy(childId) {
      if (!childId) return
      try {
        const d = await get(`/api/privacy/${this.user.id}`, { child_id: childId })
        if (d) this.privacy = d
      } catch (e) {
        /* ignore */
      }
    },
    async setPrivacy(field, value) {
      if (!this.selectedChild) {
        uni.showToast({ title: '请先绑定家人', icon: 'none' })
        return
      }
      const before = this.privacy[field]
      this.privacy[field] = value
      try {
        await put(`/api/privacy/${this.user.id}`, {
          child_id: this.selectedChild.id,
          location_level: this.privacy.location_level,
          health_level: this.privacy.health_level,
        })
        uni.showToast({ title: '已更新', icon: 'success' })
      } catch (e) {
        this.privacy[field] = before
        uni.showToast({ title: e.message || '修改失败', icon: 'none' })
      }
    },
    goBack() {
      const pages = getCurrentPages()
      if (pages && pages.length > 1) {
        uni.navigateBack()
      } else {
        uni.switchTab({ url: '/pages/elder/home' })
      }
    },
    /**
     * 退出登录。契约 §10.3 的时机表最后一行：`clearCurrentUser()` 之后调 `cancelAll()`。
     * 不这么做的话，原生副本与 AlarmManager 里已排的闹钟会原样留在设备上 ——
     * 一个已经登出的长辈端仍会按点弹通知，点开还会拉起壳并落到登录页；
     * 共用演示机换账号时，旧账号的用药提醒会弹给下一个人看。
     * cancelAll 是 fire-and-forget 的（浏览器里按 §3.8 返回 no_bridge，无副作用），
     * 但也不 await 它阻塞跳转 —— 桥调用偶尔要等 JavaBridge 线程。
     */
    logout() {
      try {
        cancelAll()
      } catch (e) {
        /* 清不掉闹钟不该把退出登录本身挡住 */
      }
      clearCurrentUser()
      uni.reLaunch({ url: '/pages/login/login' })
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.profile-page {
  min-height: 100vh;
  background: $lyj-bg;
  padding-bottom: $lyj-space-xl;
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
.title {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.user-card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-xs $lyj-space-md $lyj-space-md;
  padding: $lyj-space-lg;
  display: flex;
  align-items: center;
  gap: $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
}
.avatar {
  font-size: 100rpx;
}
.user-info {
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.name {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.city, .account {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.section {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-md;
  padding: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
}
.section-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-text;
}
.bind-row {
  display: flex;
  gap: $lyj-space-xs;
  margin-top: $lyj-space-sm;
}
.input {
  flex: 1;
  height: $lyj-hit-min;
  background: $lyj-field;
  border-radius: $lyj-radius;
  padding: 0 $lyj-space-sm;
  font-size: $lyj-font-sm;
}
.input.short {
  flex: 0.8;
}
.member-chip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-line;
}
.m-name {
  font-size: $lyj-font-md;
  font-weight: 600;
}
.m-status {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.m-right {
  display: flex;
  gap: $lyj-space-xs;
}
.mini-btn {
  font-size: $lyj-font-sm;
  margin: 0;
}
.mini-btn.ok {
  background: $lyj-success;
  color: #fff;
}
.mini-btn.no {
  background: $lyj-muted-bg;
  color: $lyj-text;
}
.empty-note {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  padding: $lyj-space-sm 0;
}
.options {
  display: flex;
  flex-wrap: wrap;
  gap: $lyj-space-sm;
  margin-top: $lyj-space-md;
}
.option {
  min-height: $lyj-hit-min;
  display: flex;
  align-items: center;
  padding: 0 $lyj-space-lg;
  border-radius: $lyj-radius;
  background: $lyj-field;
  font-size: $lyj-font-md;
  color: $lyj-text;
}
.option.active {
  background: $lyj-primary-soft;
  color: $lyj-primary;
  font-weight: 700;
  border: 3rpx solid $lyj-primary;
}
.section-note {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  margin-top: $lyj-space-sm;
}
.privacy-row {
  margin-top: $lyj-space-md;
}
.privacy-label {
  font-size: $lyj-font-md;
  font-weight: 600;
  color: $lyj-text;
}

/* ---------------- 提醒与保活 ---------------- */
.reminder-body {
  margin-top: $lyj-space-sm;
}
.perm-list {
  margin: $lyj-space-sm 0 $lyj-space-md;
}
.perm-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-line;
}
.perm-name {
  font-size: $lyj-font-md;
  color: $lyj-text;
}
.perm-state {
  font-size: $lyj-font-sm;
  font-weight: 700;
}
.perm-state.ok {
  color: $lyj-success;
}
.perm-state.no {
  color: $lyj-warn-text;
}
/* ---------------- 晨间问候偏好 ---------------- */
.pref-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: $lyj-space-sm 0;
  border-bottom: 2rpx solid $lyj-line;
}
.pref-label {
  font-size: $lyj-font-md;
  color: $lyj-text;
}
.pref-time {
  /* 可点的时刻：触控区不低于 44px，颜色取主色，让长辈看得出这里能改 */
  display: inline-block;
  min-height: $lyj-hit-min;
  line-height: $lyj-hit-min;
  padding: 0 $lyj-space-lg;
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-primary;
  background: $lyj-field;
  border-radius: $lyj-radius;
}
.test-btn {
  margin-top: $lyj-space-sm;
}

/* ---------------- 保活引导弹层 ---------------- */
.guide-mask {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: $lyj-space-md;
  box-sizing: border-box;
  z-index: 999;
}
.guide-panel {
  width: 100%;
  max-width: 640rpx;
  max-height: 80vh;
  overflow-y: auto;
  box-sizing: border-box;
  background: $lyj-card;
  border-radius: $lyj-radius;
  padding: $lyj-space-lg;
}
.guide-title {
  display: block;
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.guide-sub {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  margin-top: $lyj-space-xs;
}
.guide-step {
  display: flex;
  gap: $lyj-space-sm;
  margin-top: $lyj-space-md;
}
.guide-index {
  flex-shrink: 0;
  width: 48rpx;
  height: 48rpx;
  border-radius: 50%;
  background: $lyj-primary;
  color: $lyj-text-on;
  font-size: $lyj-font-sm;
  font-weight: 800;
  text-align: center;
  line-height: 48rpx;
}
.guide-step-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.guide-step-title {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-text;
}
.guide-step-tip {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  line-height: $lyj-line-height;
}
.guide-close {
  margin-top: $lyj-space-lg;
}

@media screen and (min-width: 768px) {
  .profile-page {
    max-width: 900px;
    margin: 0 auto;
    padding: 20rpx 40rpx 120rpx;
  }
}
</style>
