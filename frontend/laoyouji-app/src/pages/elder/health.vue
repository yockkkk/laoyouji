<template>
  <view class="health-page">
    <view class="topbar">
      <view class="back-btn" @tap="goBack">
        <text class="back-icon">‹</text>
        <text class="back-text">首页</text>
      </view>
      <view class="topbar-info">
        <text class="title">我的健康</text>
        <text class="sub">量一量，记下来，心里有数</text>
      </view>
    </view>

    <!-- 分诊档位横幅：这一页的主结论。四档配色不同，因为"要不要去医院"是
         老人从这一屏上唯一必须读懂的一件事。 -->
    <view class="level-banner" :class="levelClass">
      <view class="level-row">
        <text class="level-word">{{ overview.level }}</text>
        <text class="level-label">康乐建议</text>
      </view>
      <text class="level-headline">{{ overview.headline }}</text>
      <text class="level-advice">{{ overview.advice }}</text>
    </view>

    <!-- 一键记录 -->
    <view class="card">
      <text class="card-title">记一次</text>
      <view class="chips">
        <view
          v-for="m in metrics"
          :key="m.metric_type"
          class="chip"
          :class="{ on: form.metric_type === m.metric_type }"
          @tap="pickMetric(m.metric_type)"
        >
          <text class="chip-text">{{ m.label }}</text>
        </view>
      </view>

      <view v-if="form.metric_type === 'bp'" class="inputs">
        <view class="field">
          <text class="field-label">高压</text>
          <input
            class="field-input"
            type="number"
            v-model="form.systolic"
            placeholder="178"
          />
        </view>
        <view class="field">
          <text class="field-label">低压</text>
          <input
            class="field-input"
            type="number"
            v-model="form.diastolic"
            placeholder="105"
          />
        </view>
      </view>

      <view v-else class="inputs">
        <view class="field">
          <text class="field-label">{{ currentMeta.label }}</text>
          <input
            class="field-input"
            type="number"
            v-model="form.value"
            :placeholder="currentMeta.unit"
          />
        </view>
        <view v-if="form.metric_type === 'glucose'" class="field">
          <text class="field-label">什么时候测的</text>
          <view class="ctx-row">
            <view
              v-for="c in ['空腹', '餐后']"
              :key="c"
              class="ctx-btn"
              :class="{ on: form.context === c }"
              @tap="form.context = c"
            >
              <text class="ctx-text">{{ c }}</text>
            </view>
          </view>
        </view>
      </view>

      <view class="submit-btn" :class="{ busy: saving }" @tap="submit">
        <text class="submit-text">{{ saving ? '记着呢…' : '记下来' }}</text>
      </view>
      <text class="hint">{{ currentMeta.normal }}</text>
    </view>

    <!-- 指标列表：每条一行大字读数 + 近 7 次走向 -->
    <view v-if="readings.length" class="section">
      <text class="section-title">最近的指标</text>
      <VitalTrend
        v-for="r in readings"
        :key="r.metric_type"
        :label="r.label"
        :unit="r.unit"
        :normal="r.normal"
        :trend="r.trend"
        :points="r.points"
      />
    </view>

    <!-- 慢病列表 -->
    <view class="section">
      <text class="section-title">我的慢病</text>
      <view v-if="conditions.length" class="card">
        <view v-for="c in conditions" :key="c.id" class="cond-row">
          <text class="cond-name">{{ c.name }}</text>
          <text v-if="c.severity" class="cond-sev">{{ c.severity }}</text>
        </view>
      </view>
      <view v-else class="empty">
        <text class="empty-text">还没登记慢病，医生说过的话可以记在这儿</text>
      </view>

      <view class="cond-add">
        <input
          class="cond-input"
          v-model="newCondition"
          placeholder="医生确诊的慢病名称"
        />
        <view class="cond-btn" :class="{ busy: addingCondition }" @tap="addCondition">
          <text class="cond-btn-text">登记</text>
        </view>
      </view>
    </view>

    <!-- R4：这一页会给出档位判断，声明必须跟着结论一起出现 -->
    <text v-if="disclaimer" class="disclaimer">{{ disclaimer }}</text>
  </view>
</template>

<script>
import { get, post } from '../../api/client'
import { getCurrentUser } from '../../store/user'
import VitalTrend from '../../components/VitalTrend.vue'

export default {
  components: { VitalTrend },
  data() {
    return {
      user: null,
      metrics: [],
      readings: [],
      conditions: [],
      overview: {
        // 兜底给"保健"：拉取失败时横幅上宁可先显示最轻的一档，也不能空白
        // —— 空白会被读成"没什么事"。真数据一到就被覆盖。
        level: '保健',
        headline: '',
        advice: '',
      },
      disclaimer: '',
      // 表单默认血压：这是老人最常量的那一项，不该每次进来都要先点一下。
      form: { metric_type: 'bp', systolic: '', diastolic: '', value: '', context: '空腹' },
      saving: false,
      addingCondition: false,
      newCondition: '',
    }
  },
  computed: {
    currentMeta() {
      const m = this.metrics.find((x) => x.metric_type === this.form.metric_type)
      return m || { label: '', unit: '', normal: '' }
    },
    // 四档各自的配色。前两档是"在家照顾好"的暖调，后两档才逐渐发红：
    // "建议就医"用挂起态的暖黄而不是红色 —— 它是**一次进展**，不是错误。
    levelClass() {
      const lv = this.overview.level
      if (lv === '紧急') return 'lv-emergency'
      if (lv === '建议就医') return 'lv-see-doctor'
      if (lv === '观察') return 'lv-watch'
      return 'lv-care'
    },
  },
  onShow() {
    this.user = getCurrentUser()
    if (!this.user) {
      // 换身份 —— 清栈是这里要的语义
      uni.reLaunch({ url: '/pages/login/login' })
      return
    }
    this.load()
  },
  methods: {
    goBack() {
      const pages = getCurrentPages()
      if (pages && pages.length > 1) {
        uni.navigateBack()
      } else {
        uni.switchTab({ url: '/pages/elder/home' })
      }
    },
    async load() {
      const elder_id = this.user.id
      try {
        // 三个请求互不依赖，并行发 —— 老人端等的是"这一屏什么时候出来"。
        const [metrics, readings, overview, conditions] = await Promise.all([
          get('/api/health/metrics'),
          get('/api/health/readings', { elder_id }),
          get('/api/health/overview', { elder_id }),
          get('/api/health/conditions', { elder_id }),
        ])
        this.metrics = metrics.items || []
        this.readings = readings.items || []
        this.conditions = conditions.items || []
        this.overview = overview
        this.disclaimer = overview.disclaimer || ''
      } catch (e) {
        uni.showToast({ title: '加载失败：' + e.message, icon: 'none' })
      }
    },
    pickMetric(metric_type) {
      if (this.form.metric_type === metric_type) return
      // 换指标要把上一项的输入清掉，否则高压 178 会被带成心率的 178
      this.form = { metric_type, systolic: '', diastolic: '', value: '', context: '空腹' }
    },
    async submit() {
      if (this.saving) return
      const payload = { elder_id: this.user.id, metric_type: this.form.metric_type }
      if (this.form.metric_type === 'bp') {
        payload.systolic = this.form.systolic
        payload.diastolic = this.form.diastolic
      } else {
        payload.value = this.form.value
        if (this.form.metric_type === 'glucose') payload.context = this.form.context
      }

      // 前端只做"空不空"这一层提示，数值本身合不合法交给后端判 ——
      // 那条判定必须和聊天那条路是同一条（record_reading），在这里再写一份就会漂。
      if (this.form.metric_type === 'bp') {
        if (payload.systolic === '' || payload.diastolic === '') {
          return uni.showToast({ title: '高压和低压都要填', icon: 'none' })
        }
      } else if (payload.value === '') {
        return uni.showToast({ title: '请填一个数值', icon: 'none' })
      }

      this.saving = true
      try {
        const r = await post('/api/health/readings', payload)
        // 记完当场把档位回给老人 —— 记录不该是"存进去就没下文"。
        uni.showToast({ title: `已记录：${r.label} ${r.display}（${r.level}）`, icon: 'none' })
        this.form = {
          metric_type: this.form.metric_type,
          systolic: '', diastolic: '', value: '', context: '空腹',
        }
        await this.load()
      } catch (e) {
        // 后端对"没记上"回 4xx，这里的 message 就是它给的那句人话
        uni.showToast({ title: e.message, icon: 'none' })
      } finally {
        this.saving = false
      }
    },
    async addCondition() {
      if (this.addingCondition) return
      const name = (this.newCondition || '').trim()
      if (!name) {
        return uni.showToast({ title: '请填上慢性病名称', icon: 'none' })
      }
      this.addingCondition = true
      try {
        await post('/api/health/conditions', { elder_id: this.user.id, name })
        uni.showToast({ title: '记下了', icon: 'success' })
        this.newCondition = ''
        await this.load()
      } catch (e) {
        uni.showToast({ title: e.message || '登记失败', icon: 'none' })
      } finally {
        this.addingCondition = false
      }
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.health-page {
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
  flex-shrink: 0;
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
.topbar-info {
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.title {
  font-size: $lyj-font-xl;
  font-weight: 800;
  color: $lyj-text;
}
.sub {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}

/* ---------------------------------------------------- 分诊档位横幅 */
.level-banner {
  margin: $lyj-space-sm $lyj-space-md $lyj-space-md;
  padding: $lyj-space-lg;
  border-radius: $lyj-radius;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-sm;
  box-shadow: $lyj-shadow-card;
}
.level-row {
  display: flex;
  align-items: baseline;
  gap: $lyj-space-sm;
}
.level-word {
  font-size: $lyj-font-xl;
  font-weight: 800;
}
.level-label {
  font-size: $lyj-font-sm;
  opacity: 0.75;
}
.level-headline {
  font-size: $lyj-font-md;
  font-weight: 700;
  line-height: $lyj-line-height;
}
.level-advice {
  font-size: $lyj-font-md;
  line-height: $lyj-line-height;
}
.lv-care {
  background: $lyj-success-bg;
  color: $lyj-success;
}
.lv-watch {
  background: $lyj-info-bg;
  color: $lyj-info;
}
.lv-see-doctor {
  background: $lyj-warn-bg;
  color: $lyj-warn-text;
}
/* 紧急要一眼可辨：整块实色，字反白。这一档不该跟"观察"看起来差不多。 */
.lv-emergency {
  background: $lyj-danger;
  color: $lyj-text-on;
}

/* ---------------------------------------------------- 卡片 */
.card {
  background: $lyj-card;
  border-radius: $lyj-radius;
  margin: $lyj-space-md;
  padding: $lyj-space-md;
  box-shadow: $lyj-shadow-card;
}
.card-title {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
}
.section {
  margin: $lyj-space-lg $lyj-space-md 0;
}
.section-title {
  display: block;
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text;
  margin-bottom: $lyj-space-md;
}

/* ---------------------------------------------------- 记录表单 */
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: $lyj-space-sm;
  margin-top: $lyj-space-md;
}
.chip {
  padding: $lyj-space-sm $lyj-space-md;
  border-radius: $lyj-radius-pill;
  background: $lyj-field;
  /* 命中区下限：老人手指点不准，标签再小也不能小于 44px 高 */
  min-height: $lyj-hit-min;
  display: flex;
  align-items: center;
}
.chip.on {
  background: $lyj-primary-soft;
}
.chip-text {
  font-size: $lyj-font-md;
  color: $lyj-text;
}
.chip.on .chip-text {
  color: $lyj-primary-dark;
  font-weight: 800;
}

.inputs {
  display: flex;
  gap: $lyj-space-md;
  margin-top: $lyj-space-md;
}
.field {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: $lyj-space-xs;
}
.field-label {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.field-input {
  background: $lyj-field;
  border-radius: $lyj-radius;
  padding: 0 $lyj-space-md;
  height: $lyj-btn-main;
  font-size: $lyj-font-lg;
  font-weight: 700;
  color: $lyj-text;
}
.ctx-row {
  display: flex;
  gap: $lyj-space-sm;
}
.ctx-btn {
  flex: 1;
  height: $lyj-btn-main;
  border-radius: $lyj-radius;
  background: $lyj-field;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ctx-btn.on {
  background: $lyj-primary-soft;
}
.ctx-text {
  font-size: $lyj-font-md;
  color: $lyj-text;
}
.ctx-btn.on .ctx-text {
  color: $lyj-primary-dark;
  font-weight: 800;
}

.submit-btn {
  margin-top: $lyj-space-md;
  height: $lyj-btn-main;
  border-radius: $lyj-radius-pill;
  background: $lyj-primary;
  display: flex;
  align-items: center;
  justify-content: center;
}
.submit-btn.busy {
  opacity: 0.6;
}
.submit-text {
  font-size: $lyj-font-lg;
  font-weight: 800;
  color: $lyj-text-on;
}
.hint {
  display: block;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  margin-top: $lyj-space-sm;
  line-height: $lyj-line-height;
}

/* ---------------------------------------------------- 慢病 */
.cond-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: $lyj-space-sm 0;
}
.cond-name {
  font-size: $lyj-font-md;
  font-weight: 700;
  color: $lyj-text;
}
.cond-sev {
  font-size: $lyj-font-sm;
  color: $lyj-warn-text;
}
.empty {
  background: $lyj-card;
  border-radius: $lyj-radius;
  padding: $lyj-space-lg;
  box-shadow: $lyj-shadow-card;
}
.empty-text {
  font-size: $lyj-font-md;
  color: $lyj-text-light;
  line-height: $lyj-line-height;
}
.cond-add {
  display: flex;
  gap: $lyj-space-sm;
  margin-top: $lyj-space-md;
}
.cond-input {
  flex: 1;
  background: $lyj-field;
  border-radius: $lyj-radius;
  padding: 0 $lyj-space-md;
  height: $lyj-btn-main;
  font-size: $lyj-font-md;
  color: $lyj-text;
}
.cond-btn {
  min-width: 200rpx;
  height: $lyj-btn-main;
  border-radius: $lyj-radius-pill;
  background: $lyj-primary;
  display: flex;
  align-items: center;
  justify-content: center;
}
.cond-btn.busy {
  opacity: 0.6;
}
.cond-btn-text {
  font-size: $lyj-font-md;
  font-weight: 800;
  color: $lyj-text-on;
}

.disclaimer {
  display: block;
  margin: $lyj-space-lg $lyj-space-md 0;
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
  line-height: $lyj-line-height;
}
</style>
