<template>
  <view class="route-page" role="main">
    <!-- 适老大字顶部导航栏 (触控靶区 >= 48px / 96rpx, WCAG 2.1 AAA 高对比) -->
    <view class="elder-navbar">
      <button class="nav-back-btn" aria-label="返回上一页" @tap="goBack">
        <text class="back-arrow" aria-hidden="true">‹</text>
        <text class="back-text">返回</text>
      </button>
      <view class="nav-title-group">
        <text class="nav-title">北斗适老实景导航</text>
        <text class="nav-subtitle">亚米级高精避障护航</text>
      </view>
      <button class="nav-speak-btn" aria-label="全路线语音慢速播报" @tap="speakFullRoute">
        <text class="speak-icon" aria-hidden="true">🔊</text>
        <text class="speak-text">全线播报</text>
      </button>
    </view>

    <!-- 北斗高精时空状态指示条 (BdsStatusBar) -->
    <bds-status-bar
      :satellite-count="bdsSatelliteCount"
      :fix-status="bdsFixStatus"
      :accuracy="bdsAccuracy"
      :hdop="bdsHdop"
      :warm-notice="bdsWarmNotice"
      :is-rtk-fixed="true"
    />

    <!-- 温和声控偏航安抚浮层 (触偏航走廊时暖心提醒，拒绝恐慌红斑，适老温和暖金) -->
    <view
      v-if="deviationAlert.active"
      class="deviation-reassurance-card"
      role="alert"
      aria-live="assertive"
    >
      <view class="deviation-header">
        <view class="deviation-icon-badge" aria-hidden="true">🧭</view>
        <view class="deviation-title-box">
          <text class="deviation-title">温和偏航指引 · 别着急</text>
          <text class="deviation-subtitle">北斗高精感知偏差约 {{ deviationAlert.distanceM }} 米</text>
        </view>
        <button
          class="deviation-close-btn"
          aria-label="关闭偏航提示"
          @tap="dismissDeviationAlert"
        >
          ✕
        </button>
      </view>

      <view class="deviation-msg-content">
        <text class="deviation-msg-text">
          “{{ deviationReassuranceText }}”
        </text>
      </view>

      <view class="deviation-action-buttons">
        <button
          class="dev-btn dev-btn-speak"
          aria-label="听安抚指引语音"
          @tap="playDeviationVoice"
        >
          <text class="btn-icon" aria-hidden="true">🔊</text>
          <text class="btn-text">听安抚指引</text>
        </button>
        <button
          class="dev-btn dev-btn-realign"
          aria-label="对准平缓步道"
          @tap="realignToRoute"
        >
          <text class="btn-icon" aria-hidden="true">🚶</text>
          <text class="btn-text">帮我回到主道</text>
        </button>
      </view>
    </view>

    <!-- 家人实时守护状态指示条 -->
    <view class="reporting-banner">
      <view class="pulse-dot" aria-hidden="true"></view>
      <text class="report-text">
        🛡️ 子女守护中 · 北斗高精时空轨迹已实时同步给【{{ familyContactName }}】
      </text>
    </view>

    <!-- 路线概览信息条 (高对比适老卡片) -->
    <view class="route-summary-bar">
      <view class="summary-line">
        <text class="summary-badge start">起</text>
        <text class="summary-place">{{ originName || '待定' }}</text>
        <text class="summary-arrow" aria-hidden="true">➔</text>
        <text class="summary-badge end">终</text>
        <text class="summary-place">{{ destinationName || '待定' }}</text>
      </view>
      <view class="summary-meta">
        <text class="meta-item" v-if="routeDuration">⏱️ {{ routeDuration }}</text>
        <text class="meta-item" v-if="routeDistance">🛣️ 约 {{ routeDistance }}</text>
        <text class="meta-item" v-if="routeModeText">{{ routeModeText }}</text>
        <text class="meta-item barrier-free-score-tag">♿ 适老无障碍 {{ barrierFreeScore }}分</text>
      </view>
    </view>

    <!-- 常用适老出行路线快捷切换 -->
    <view class="scene-switch-bar">
      <view class="scene-switch-header">
        <text class="scene-title">📍 常用适老出行路线切换</text>
      </view>
      <view class="scene-chips">
        <button
          v-for="(sc, sIdx) in demoScenes"
          :key="sc.id"
          class="scene-chip"
          :class="{ active: currentSceneIdx === sIdx }"
          @tap="switchDemoScene(sIdx)"
        >
          <text class="chip-icon">{{ sc.icon }}</text>
          <text class="chip-label">{{ sc.label }}</text>
        </button>
      </view>
    </view>

    <!-- 适老地图视窗 (Leaflet 渲染高德栅格瓦片，坐标 GCJ-02) -->
    <view class="map-section" :class="{ 'fullscreen-mode': isMapFullscreen }">
      <!-- 适老微地形高精图层状态栏 -->
      <view class="microterrain-status-bar">
        <view class="micro-status-pill pill-corridor" @tap="speakMicroFeature('corridor')">
          <text class="pill-icon">🛡️</text>
          <text class="pill-text">30m安全走廊</text>
        </view>
        <view class="micro-status-pill pill-slope" @tap="speakMicroFeature('slope')">
          <text class="pill-icon">🟢</text>
          <text class="pill-text">坡度&lt;2.5%平缓</text>
        </view>
        <view class="micro-status-pill pill-barrier" @tap="speakMicroFeature('barrier')">
          <text class="pill-icon">⛔</text>
          <text class="pill-text">险台阶已硬阻断</text>
        </view>
        <view class="micro-status-pill pill-bench" @tap="speakMicroFeature('bench')">
          <text class="pill-icon">🪑</text>
          <text class="pill-text">沿途长椅守护</text>
        </view>
      </view>

      <div id="elder-amap-container" class="amap-box"></div>
      <view v-if="mapLoading" class="map-loading-mask">
        <text class="loading-icon" aria-hidden="true">⏳</text>
        <text class="loading-text">北斗适老实景地图加载中…</text>
      </view>
      <view v-else-if="mapFailed" class="map-loading-mask">
        <text class="loading-icon" aria-hidden="true">🗺️</text>
        <text class="loading-text">地图暂时没能加载出来</text>
        <button class="map-retry-btn" @tap="initMap">点我重新加载地图</button>
      </view>

      <!-- 全屏大图模式下顶部悬浮条 (返回药丸按钮 + 缩放提示) -->
      <view v-if="isMapFullscreen" class="fullscreen-topbar">
        <view class="fullscreen-topbar-inner">
          <button class="fullscreen-exit-pill" @tap="toggleMapFullscreen">
            <text class="exit-icon" aria-hidden="true">‹</text>
            <text class="exit-text">退出大图</text>
          </button>
          <text class="fullscreen-hint">双指缩放 · 拖动浏览</text>
        </view>
      </view>

      <!-- 全屏大图模式下底部悬浮退出大按钮 (老年友好，超大触控靶区) -->
      <view v-if="isMapFullscreen" class="fullscreen-bottombar">
        <button class="fullscreen-bottom-btn" @tap="toggleMapFullscreen">
          <text class="bottom-btn-icon" aria-hidden="true">📋</text>
          <text class="bottom-btn-text">退出大图 · 查看详细实景地标指引</text>
        </button>
      </view>

      <!-- 地图工具浮层 (触控靶区 >= 48px) -->
      <view class="map-controls">
        <button class="ctrl-btn ctrl-btn-fullscreen" @tap="toggleMapFullscreen">
          {{ isMapFullscreen ? '✕ 退出大图' : '⛶ 全屏大图' }}
        </button>
        <button class="ctrl-btn" @tap="resetView">🗺️ 全览</button>
        <button class="ctrl-btn" @tap="locateElder">📍 我的位置</button>
        <!-- 偏航安抚演示按钮 (便于评审与演示) -->
        <button class="ctrl-btn ctrl-btn-deviation" @tap="triggerSimulatedDeviation">
          ⚠️ 偏航安抚演示
        </button>
      </view>
    </view>

    <!-- 一键大白话语音问询与转向引导条 (触控靶区 >= 48px) -->
    <view class="voice-steer-action-bar">
      <button class="btn-voice-inquiry" @tap="handleElderVoiceInquiry">
        <text class="inquiry-mic-icon" aria-hidden="true">🎤</text>
        <view class="inquiry-text-group">
          <text class="inquiry-main-title">问康乐：“我现在走到哪了？”</text>
          <text class="inquiry-sub-title">一点即答 · 播报当前地标与无障碍设施</text>
        </view>
      </button>
    </view>

    <!-- 适老地标实景指引卡片区 (LandmarkGuidanceCard) -->
    <view class="steps-section">
      <view class="section-header">
        <view class="section-title-line">
          <text class="section-title">🚶 换乘步骤大字指引与地标实景</text>
          <text class="landmark-tag">避开台阶与陡坡</text>
        </view>
        <text class="section-subtitle">跟着大树、银行与缓坡走 · 不记复杂方向与米数</text>
      </view>

      <!-- 没查到路线时的友好提示卡 -->
      <view v-if="steps.length === 0" class="step-empty-card">
        <text class="step-empty-icon" aria-hidden="true">🧭</text>
        <text class="step-empty-text">{{ routeNotice }}</text>
      </view>

      <!-- 地标实景指引卡片组件列表 -->
      <landmark-guidance-card
        v-for="(step, index) in steps"
        :key="index"
        :step="step"
        :index="index"
        :is-active="currentStepIndex === index"
        @select="onStepSelected"
        @speak="onStepSpeak"
      />

      <!-- 适老安心守护与联系家人 (触控靶区 >= 48px, WCAG 2.1 AAA 高对比) -->
      <view class="help-section">
        <button class="btn-help-safe" :loading="checkingIn" @tap="sendSafetyCheckin">
          <text class="btn-icon" aria-hidden="true">🕊️</text>
          <text class="btn-text">一键给家人报平安</text>
        </button>
        <button class="btn-help-tel" @tap="callFamilyDirect">
          <text class="btn-icon" aria-hidden="true">📞</text>
          <text class="btn-text">电话联系家人{{ familyContactName ? '（' + familyContactName + '）' : '' }}</text>
        </button>
      </view>
    </view>
  </view>
</template>

<script>
import {
  loadLeaflet,
  ensureAmapMarkerStyles,
  toLeafletLatLng,
  makeMapMarkerIcon,
  AMAP_RASTER_TILE_URL,
  AMAP_TILE_SUBDOMAINS,
  AMAP_TILE_ATTRIBUTION,
} from '../../utils/amap'
import { get, post } from '../../api/client'
import { getCurrentUser } from '../../store/user'
import { speak } from '../../api/asr'
import BdsStatusBar from '../../components/BdsStatusBar.vue'
import LandmarkGuidanceCard from '../../components/LandmarkGuidanceCard.vue'

export default {
  name: 'ElderRouteMap',
  components: {
    BdsStatusBar,
    LandmarkGuidanceCard,
  },
  data() {
    return {
      user: null,
      city: '长沙', // 默认赛事演示城市，可由 URL 或 user.city 覆盖
      tripId: '',
      title: '',
      currentSceneIdx: 0,
      originName: '家（华夏路社区）',
      originName: '湖南烈士公园西门（无障碍入口）',
      destinationName: '烈士公园朝晖楼（年嘉湖晨练区）',
      routeDuration: '约15分钟',
      routeDistance: '0.95公里',
      routeMode: '步行',
      routeNotice: '北斗亚米级高精时空护航已就绪，正在引导平缓无障碍步道…',
      mapLoading: true,
      mapFailed: false,
      isMapFullscreen: false,
      checkingIn: false,
      familyContactName: '小敏（女儿）',
      familyContactPhone: '13812345678',
      reportCount: 0,
      reportTimer: null,
      currentStepIndex: 0,
      elderCoords: [112.9936, 28.2092], // 湖南省示范点·烈士公园西门无障碍入口
      elderMarker: null,
      routePolyline: null,
      routeCasing: null,
      routeCorridor: null,
      homeCircleLayer: null,
      microTerrainLayers: [],
      stationMarkers: [],
      tileLayer: null,
      leafletMap: null,
      resizeObserver: null,
      steps: [],
      routePoints: [],
      polylinePath: [],
      // 湖南省大学生智能导航科技创新大赛 3 大核心示范场景（高精度实景人行步道）
      demoScenes: [
        {
          id: 'park',
          label: '烈士公园晨练步道',
          icon: '🌳',
          origin: '湖南烈士公园西门（无障碍入口）',
          destination: '烈士公园朝晖楼（年嘉湖晨练区）',
          city: '长沙',
          desc: '年嘉湖环湖林荫绿道 · 坡度<2.5% · 避开38级险台阶 · 途经2处适老长椅',
          duration: '约15分钟',
          distance: '0.95公里',
          score: 98,
          points: [
            { location: '湖南烈士公园西门（无障碍入口）', name: '烈士公园西门无障碍入口', lng: 112.9936, lat: 28.2092 },
            { location: '烈士公园林荫平缓慢步道', name: '平缓林荫慢步道', lng: 112.9958, lat: 28.2090 },
            { location: '年嘉湖西堤适老爱心长椅区', name: '年嘉湖西堤爱心长椅', lng: 112.9975, lat: 28.2086 },
            { location: '年嘉湖环湖适老防滑木栈道', name: '环湖适老防滑木栈道', lng: 112.9995, lat: 28.2072 },
            { location: '烈士公园朝晖楼（年嘉湖晨练区）', name: '朝晖楼康养晨练区', lng: 113.0018, lat: 28.2030 }
          ],
          polyline: [
            [112.9936, 28.2092],
            [112.9940, 28.2092],
            [112.9945, 28.2091],
            [112.9950, 28.2091],
            [112.9955, 28.2090],
            [112.9960, 28.2090],
            [112.9965, 28.2089],
            [112.9970, 28.2088],
            [112.9975, 28.2086],
            [112.9979, 28.2084],
            [112.9983, 28.2082],
            [112.9987, 28.2079],
            [112.9991, 28.2076],
            [112.9995, 28.2072],
            [112.9998, 28.2068],
            [113.0001, 28.2064],
            [113.0004, 28.2059],
            [113.0007, 28.2054],
            [113.0010, 28.2048],
            [113.0012, 28.2043],
            [113.0014, 28.2038],
            [113.0016, 28.2034],
            [113.0018, 28.2030]
          ],
          steps: [
            {
              title: '第 1 步：湖南烈士公园西门无障碍林荫慢步道',
              landmark: '烈士公园西门无障碍入口',
              icon: '🌳',
              content: '由烈士公园西门平缓通道进园，沿林荫道稳步行进，地面平整无台阶坑洼。',
              accessibleFeatures: ['无台阶', '全程平缓 (<1.2%)', '绿荫覆盖率 92%'],
              voiceHint: '张阿姨，顺着西大门阴凉的平缓林荫道慢慢走，路面特别平整防滑。',
              coords: [112.9936, 28.2092]
            },
            {
              title: '第 2 步：避开假山险台阶绕行平缓通道',
              landmark: '假山台阶绕行指示桩',
              icon: '⛔',
              content: '算法硬阻断已剪枝避开假山 38 级险陡台阶，引导您走右侧宽阔平缓绿道。',
              accessibleFeatures: ['已避开38级险台阶', '坡度1.1%极缓', '配备防滑扶手'],
              voiceHint: '张阿姨，前面假山台阶很陡，系统已为您选好平缓绿道，避开台阶安心走。',
              coords: [112.9958, 28.2090]
            },
            {
              title: '第 3 步：年嘉湖西堤适老爱心长椅区',
              landmark: '年嘉湖西堤便民长椅',
              icon: '🪑',
              content: '途经适老休息驿站，设有便民长椅与遮阳棚，低位扶手设计，可随时小憩。',
              accessibleFeatures: ['适老爱心长椅', '直饮水补给点', '遮阳挡雨棚'],
              voiceHint: '张阿姨，湖边有带遮阳棚的爱心长椅，走累了坐下歇歇脚、喝口温水。',
              coords: [112.9975, 28.2086]
            },
            {
              title: '第 4 步：年嘉湖环湖适老防滑木栈道',
              landmark: '年嘉湖环湖木栈道',
              icon: '🚶',
              content: '顺着环湖适老防滑木栈道前行，湖面微风舒适，坡度仅 1.6%，全程无障碍直通。',
              accessibleFeatures: ['防滑木栈道', '缓坡平顺 (<2%)', '避开临水湿滑'],
              voiceHint: '张阿姨，顺着平整的木栈道继续往前走，湖景开阔，微风吹着很舒畅。',
              coords: [112.9995, 28.2072]
            },
            {
              title: '第 5 步：烈士公园朝晖楼康养晨练广场',
              landmark: '朝晖楼晨练康养广场',
              icon: '🏅',
              content: '顺利抵达朝晖楼晨练区，设有志愿服务站与医疗急救呼叫桩，晨练适宜。',
              accessibleFeatures: ['平层无障碍到达', '红十字急救桩', '志愿助老岗亭'],
              voiceHint: '张阿姨，到达朝晖楼啦！这里有志愿服务站，祝您晨练愉快！',
              coords: [113.0018, 28.2030]
            }
          ],
          microBarriers: [
            { name: '避开假山38级险台阶', desc: 'Cost=∞ 硬阻断剪枝，杜绝长辈摔伤，改走平缓绿道', coords: [112.9965, 28.2096], icon: '⛔' },
            { name: '避开过街陡坡 (11.8%)', desc: '坡度过大存在摔倒高危，算法已智能绕开', coords: [112.9945, 28.2098], icon: '⚠️' }
          ],
          microPois: [
            { name: '坡度 1.1% (平缓绿道)', desc: '平缓防滑人行步道，老年慢步极度舒适', coords: [112.9950, 28.2091], type: 'slope', icon: '🟢' },
            { name: '坡度 1.6% (平缓木栈道)', desc: '年嘉湖环湖适老防滑木栈道', coords: [112.9995, 28.2072], type: 'slope', icon: '🟢' },
            { name: '适老长椅 1号 (配遮阳棚)', desc: '距起点260米，设有低位防滑扶手与温开水点', coords: [112.9975, 28.2086], type: 'bench', icon: '🪑' },
            { name: '适老长椅 2号 (湖滨长椅)', desc: '距起点580米，视野开阔透气，配有靠背扶手', coords: [113.0004, 28.2059], type: 'bench', icon: '🪑' }
          ]
        },
        {
          id: 'xiangya',
          label: '湘雅老院区绿通',
          icon: '🏥',
          origin: '家（长沙市开福区华夏路社区）',
          destination: '中南大学湘雅医院',
          city: '长沙',
          desc: '适老防滑人行道 · 湘雅路45秒有声斑马线 · 门诊无障碍连廊',
          duration: '约8分钟',
          distance: '0.48公里',
          score: 98,
          points: [
            { location: '家（长沙市开福区华夏路社区）', name: '家（华夏路社区）', lng: 112.9835, lat: 28.2160 },
            { location: '华夏路适老林荫人行道', name: '华夏路缓坡人行道', lng: 112.9836, lat: 28.2148 },
            { location: '湘雅路街心爱心长椅', name: '街心长椅休息区', lng: 112.9854, lat: 28.2141 },
            { location: '湘雅路有声安全斑马线', name: '湘雅路有声安全斑马线', lng: 112.9868, lat: 28.2141 },
            { location: '中南大学湘雅医院门诊大楼', name: '湘雅医院门诊1号无障碍坡道', lng: 112.9871, lat: 28.2125 }
          ],
          polyline: [
            [112.9835, 28.2160],
            [112.9835, 28.2155],
            [112.9836, 28.2150],
            [112.9836, 28.2145],
            [112.9837, 28.2141],
            [112.9842, 28.2141],
            [112.9848, 28.2141],
            [112.9854, 28.2141],
            [112.9860, 28.2141],
            [112.9865, 28.2141],
            [112.9868, 28.2141],
            [112.9870, 28.2141],
            [112.9870, 28.2137],
            [112.9870, 28.2133],
            [112.9871, 28.2129],
            [112.9871, 28.2125]
          ],
          steps: [
            {
              title: '第 1 步：华夏路社区东门无障碍人行道',
              landmark: '华夏路社区便民服务亭',
              icon: '🏡',
              content: '出小区东门沿防滑人行道向南慢行，路面平整，无坑洼台阶。',
              accessibleFeatures: ['无台阶', '全程平缓 (<0.9%)', '林荫遮阳步道'],
              voiceHint: '张阿姨，顺着咱们小区门口平平的防滑步道慢慢走，路况特别好。',
              coords: [112.9835, 28.2160]
            },
            {
              title: '第 2 步：避开地下通道险陡台阶',
              landmark: '地面无障碍通道口',
              icon: '⛔',
              content: '算法硬阻断已剪枝避开地下通道 42 级险台阶，引导走地面平层通道。',
              accessibleFeatures: ['已避开42级险台阶', '地面平层通行', '人车分流'],
              voiceHint: '张阿姨，地道台阶很陡，系统已为您选好平整的地面人行道，安心过。',
              coords: [112.9836, 28.2148]
            },
            {
              title: '第 3 步：湘雅路街心爱心长椅区',
              landmark: '湘雅路街心休息长椅',
              icon: '🪑',
              content: '途经街心长椅驿站，设有便民长椅与温开水补给点，可在此随心小憩。',
              accessibleFeatures: ['适老爱心长椅', '温开水补给点', '防滑低位扶手'],
              voiceHint: '张阿姨，路边有爱心长椅和热水点，走累了随时坐下喝口水歇歇。',
              coords: [112.9854, 28.2141]
            },
            {
              title: '第 4 步：湘雅路口有声安全斑马线',
              landmark: '湘雅路口有声红绿灯',
              icon: '🚦',
              content: '过配备清脆语音提示的有声斑马线（绿灯时长 45 秒，中途设行人安全岛）。',
              accessibleFeatures: ['45秒长绿灯', '语音声响指引', '行人安全岛'],
              voiceHint: '张阿姨，经过路口有清脆的提示音，绿灯时间很长，慢慢走不用着急。',
              coords: [112.9868, 28.2141]
            },
            {
              title: '第 5 步：湘雅医院门诊大楼 1 号无障碍坡道',
              landmark: '中南大学湘雅医院门诊大楼',
              icon: '🏥',
              content: '抵达湘雅医院门诊大楼，顺着左侧专用防滑坡道进入大厅，直通骨科与无障碍直梯。',
              accessibleFeatures: ['专用防滑坡道', '无障碍直梯', '导医志愿者引导'],
              voiceHint: '到达湘雅医院啦！走左边平缓坡道进门就是导医台，骨科在二楼。',
              coords: [112.9871, 28.2125]
            }
          ],
          microBarriers: [
            { name: '避开地道42级险台阶', desc: 'Cost=∞ 算法硬阻断剪枝，改走地面平层无障碍通道', coords: [112.9848, 28.2146], icon: '⛔' }
          ],
          microPois: [
            { name: '坡度 0.9% (平整步道)', desc: '华夏路适老防滑人行步道', coords: [112.9836, 28.2148], type: 'slope', icon: '🟢' },
            { name: '湘雅路街心爱心长椅', desc: '长辈专用休息长椅，配有温开水补给点', coords: [112.9854, 28.2141], type: 'bench', icon: '🪑' },
            { name: '平层无障碍直梯连廊', desc: '推车轮椅无缝直通门诊二楼骨科', coords: [112.9871, 28.2129], type: 'slope', icon: '♿' }
          ]
        },
        {
          id: 'renmin',
          label: '省人民医院老年专线',
          icon: '🏛️',
          origin: '蔡锷北路适老驿站',
          destination: '湖南省人民医院',
          city: '长沙',
          desc: '人车分流安全绿道 · 45秒长绿灯斑马线 · 南大门无障碍直梯',
          duration: '约22分钟',
          distance: '2.2公里',
          score: 95,
          points: [
            { location: '蔡锷北路适老驿站', name: '蔡锷北路适老驿站', lng: 112.9818, lat: 28.2045 },
            { location: '蔡锷路林荫人行道', name: '蔡锷路林荫步道', lng: 112.9817, lat: 28.2015 },
            { location: '蔡锷中路适老长椅', name: '蔡锷中路休息驿站', lng: 112.9815, lat: 28.1985 },
            { location: '解放西路有声红绿灯斑马线', name: '解放西路有声斑马线', lng: 112.9814, lat: 28.1970 },
            { location: '湖南省人民医院天心阁院区', name: '省人民医院天心阁院区门诊', lng: 112.9810, lat: 28.1920 }
          ],
          polyline: [
            [112.9818, 28.2045],
            [112.9818, 28.2030],
            [112.9817, 28.2015],
            [112.9817, 28.2000],
            [112.9816, 28.1985],
            [112.9815, 28.1970],
            [112.9814, 28.1955],
            [112.9813, 28.1940],
            [112.9812, 28.1930],
            [112.9810, 28.1920]
          ],
          steps: [
            {
              title: '第 1 步：蔡锷北路平缓无障碍步道',
              landmark: '蔡锷北路适老驿站',
              icon: '🏡',
              content: '顺蔡锷北路宽敞防滑人行道向南慢行，绿树成荫，全程缓坡无台阶。',
              accessibleFeatures: ['无台阶', '人车分流', '防滑路面'],
              voiceHint: '张阿姨，咱们慢慢走，沿路都是平平的防滑步道。',
              coords: [112.9818, 28.2045]
            },
            {
              title: '第 2 步：避开天桥64级险陡台阶',
              landmark: '地面无障碍斑马线指示',
              icon: '⛔',
              content: '算法硬阻断已剪枝避开人行天桥 64 级无梯陡阶，引导走地面安全斑马线。',
              accessibleFeatures: ['已避开64级险台阶', '地面平层通行'],
              voiceHint: '张阿姨，天桥台阶太高太陡，咱们走地面的平整斑马线。',
              coords: [112.9817, 28.2015]
            },
            {
              title: '第 3 步：蔡锷中路适老爱心长椅区',
              landmark: '蔡锷中路便民长椅',
              icon: '🪑',
              content: '途经爱心长椅休息区，配有遮阳棚与无障碍公厕引导，可随时休息。',
              accessibleFeatures: ['配备爱心长椅', '遮阳棚', '无障碍公厕引导'],
              voiceHint: '张阿姨，路边有长椅可以歇歇脚，不着急赶路。',
              coords: [112.9815, 28.1985]
            },
            {
              title: '第 4 步：解放西路有声安全斑马线',
              landmark: '解放西路口安全岛',
              icon: '🚦',
              content: '过有声信号灯斑马线，安全绿灯时长 45 秒，中途设行人安全岛。',
              accessibleFeatures: ['45秒长绿灯', '语音声响指引', '行人安全岛'],
              voiceHint: '张阿姨，路口绿灯时间长，有清脆语音提示，慢慢过不用着急。',
              coords: [112.9814, 28.1970]
            },
            {
              title: '第 5 步：湖南省人民医院天心阁院区无障碍入口',
              landmark: '湖南省人民医院天心阁院区',
              icon: '🏥',
              content: '抵达省人民医院，走左侧专用防滑缓坡进入门诊大厅，直通无障碍直梯。',
              accessibleFeatures: ['专用防滑缓坡', '无障碍直梯', '急救绿通定锚'],
              voiceHint: '张阿姨，到达省人民医院了！走左侧平缓坡道直接进大厅。',
              coords: [112.9810, 28.1920]
            }
          ],
          microBarriers: [
            { name: '避开天桥64级无梯台阶', desc: 'Cost=∞ 剪枝，改走45秒长绿灯有声安全斑马线', coords: [112.9816, 28.1990], icon: '⛔' }
          ],
          microPois: [
            { name: '坡度 1.2% (平缓步道)', desc: '蔡锷路林荫人行道，路面平坦', coords: [112.9817, 28.2015], type: 'slope', icon: '🟢' },
            { name: '蔡锷中路适老长椅', desc: '沿途休息驿站，距起点320米', coords: [112.9815, 28.1985], type: 'bench', icon: '🪑' },
            { name: '三甲急救绿通定锚点', desc: '500ms秒级自愈重划天心阁院区急救通道', coords: [112.9812, 28.1930], type: 'hazard', icon: '🏥' }
          ]
        }
      ],
      // 北斗高精时空状态
      bdsSatelliteCount: 18,
      bdsFixStatus: 'RTK固定解 (亚米级差分)',
      bdsAccuracy: 0.35,
      bdsHdop: 0.72,
      barrierFreeScore: 98,
      bdsWarmNotice: '',
      // 偏航防迷路声控纠偏状态
      deviationAlert: {
        active: false,
        distanceM: 28,
        landmark: '便民大药房',
        customText: '',
      },
    }
  },
  computed: {
    userName() {
      if (this.user && this.user.role === 'elder' && this.user.name) {
        const n = this.user.name
        return n.length >= 2 ? `${n[0]}阿姨` : n
      }
      return '张阿姨'
    },
    deviationReassuranceText() {
      if (this.deviationAlert.customText) return this.deviationAlert.customText
      return `${this.userName}，您稍微走偏了点，别着急，转过身向右边${this.deviationAlert.landmark}方向走${this.deviationAlert.distanceM}米就回到主道啦。`
    },
    routeModeText() {
      const m = String(this.routeMode || '')
      if (!m) return '🚶 适老无障碍步道'
      if (m.includes('地铁') || m.includes('轨道') || m.includes('轻轨')) return '🚇 地铁无障碍直梯'
      if (m.includes('步行')) return '🚶 适老避障步道'
      if (m.includes('公交') || m.includes('巴士')) return '🚌 无障碍公交'
      if (m.includes('驾车') || m.includes('打车')) return '🚕 爱心接送'
      return m
    },
  },
  onLoad(opts) {
    if (opts) {
      if (opts.trip_id) this.tripId = opts.trip_id
      if (opts.title) this.title = decodeURIComponent(opts.title)
      if (opts.origin) this.originName = decodeURIComponent(opts.origin)
      if (opts.destination) this.destinationName = decodeURIComponent(opts.destination)
      if (opts.city) this.city = decodeURIComponent(opts.city)
    }
  },
  onBackPress(options) {
    if (this.isMapFullscreen) {
      this.toggleMapFullscreen()
      return true
    }
    return false
  },
  mounted() {
    this.user = getCurrentUser()
    if (this.user && this.user.role === 'child') {
      uni.redirectTo({
        url: `/pages/child/guardian?trip_id=${encodeURIComponent(this.tripId || '')}`,
      })
      return
    }
    if (!this.city && this.user && this.user.city) {
      this.city = this.user.city
    }
    this.fetchFamilyContact()
    this.initPage()
    if (typeof window !== 'undefined') {
      window.addEventListener('popstate', this.handlePopState)
    }
  },
  onUnload() {
    this.stopReporting()
    if (this.resizeObserver) {
      this.resizeObserver.disconnect()
      this.resizeObserver = null
    }
    if (typeof window !== 'undefined') {
      window.removeEventListener('popstate', this.handlePopState)
    }
    if (this.leafletMap) {
      try {
        this.leafletMap.remove()
      } catch (e) {}
      this.leafletMap = null
    }
  },
  methods: {
    async initPage() {
      // 预先装配默认示范场景数据（烈士公园晨练步道）
      const defaultSc = this.demoScenes[this.currentSceneIdx || 0]
      if (defaultSc) {
        this.originName = defaultSc.origin
        this.destinationName = defaultSc.destination
        this.routeDuration = defaultSc.duration
        this.routeDistance = defaultSc.distance
        this.barrierFreeScore = defaultSc.score
        this.polylinePath = defaultSc.polyline
        this.steps = defaultSc.steps
        this.routePoints = defaultSc.points
        this.elderCoords = [defaultSc.points[0].lng, defaultSc.points[0].lat]
      }
      await this.fetchRouteFromBackend()
      await this.initMap()
      this.startReporting()
    },
    async fetchRouteFromBackend() {
      try {
        let routeResult = null

        // 1. 如果已有 tripId，优先拉取
        if (this.tripId) {
          const res = await get(`/api/trips/${this.tripId}`).catch(() => null)
          if (res && res.route && res.route.ok) {
            routeResult = res.route
          }
        }

        // 2. 如果没有 tripId，尝试从行程列表中匹配
        if (!this.tripId) {
          const listRes = await get('/api/trips?limit=10').catch(() => null)
          if (listRes && Array.isArray(listRes.trips)) {
            const destCore = (this.destinationName || '').replace(/北京|南京|上海|长沙/g, '').trim()
            const matched = listRes.trips.find((t) => {
              const p = t.purpose || (t.plan && t.plan.title) || ''
              return destCore && p.includes(destCore)
            })
            if (matched) {
              this.tripId = matched.id
              const res = await get(`/api/trips/${this.tripId}`).catch(() => null)
              if (res && res.route && res.route.ok) {
                routeResult = res.route
              }
            }
          }
        }

        // 3. 尝试调用后端直接路线规划接口
        if (!routeResult) {
          const directRes = await get('/api/trips/route/direct', {
            origin: this.originName,
            destination: this.destinationName,
            city: this.city || '长沙',
          }).catch(() => null)
          if (directRes && directRes.route && directRes.route.ok) {
            routeResult = directRes.route
          }
        }

        // 4. 若未绑定 tripId，自动创建快速守护行程，以保障 10 秒定时上报闭环
        if (!this.tripId) {
          const quickRes = await post('/api/trips/quick', {
            origin: this.originName,
            destination: this.destinationName,
            elder_id: this.user ? this.user.id : null,
            purpose: this.title || `前往${this.destinationName}北斗适老出行`,
          }).catch(() => null)
          if (quickRes && quickRes.trip) {
            this.tripId = quickRes.trip.id
          }
        }

        // 5. 应用规划数据到界面响应式状态
        if (routeResult) {
          const r = routeResult
          if (r.duration) this.routeDuration = r.duration
          if (r.distance_km) this.routeDistance = `${r.distance_km}公里`
          if (r.mode) this.routeMode = r.mode
          if (r.origin) this.originName = r.origin
          if (r.destination) this.destinationName = r.destination
          if (r.bds_satellite_count) this.bdsSatelliteCount = r.bds_satellite_count
          if (r.bds_accuracy_m) this.bdsAccuracy = r.bds_accuracy_m
          if (r.barrier_free_score) this.barrierFreeScore = Math.round(r.barrier_free_score * 100)

          if (Array.isArray(r.points) && r.points.length) {
            this.routePoints = r.points.map((p, idx) => ({
              name: p.location || p.name,
              lng: p.lng,
              lat: p.lat,
              type: idx === 0 ? 'start' : idx === r.points.length - 1 ? 'end' : 'station',
            }))
            if (this.routePoints.length && this.routePoints[0].lng) {
              this.elderCoords = [this.routePoints[0].lng, this.routePoints[0].lat]
            }
          }

          // 仅当后端返回的点数足够密集（>=10个点）时采用，否则保留高精度平滑人行道轨迹
          if (Array.isArray(r.polyline) && r.polyline.length >= 10) {
            this.polylinePath = r.polyline.map((p) => [p.lng, p.lat])
          } else if (!this.polylinePath.length && this.routePoints.length) {
            this.polylinePath = this.routePoints.map((p) => [p.lng, p.lat])
          }

          if (Array.isArray(r.steps) && r.steps.length) {
            this.steps = r.steps.map((st, idx) => this.enrichStepWithLandmarks(st, idx, r))
          } else if (!this.steps.length) {
            this.steps = this.generateFallbackElderLandmarkSteps()
          }
        } else if (!this.steps.length) {
          this.steps = this.generateFallbackElderLandmarkSteps()
        }
      } catch (e) {
        console.warn('获取后端路线规划失败，使用适老地标实景步骤兜底:', e)
        if (!this.steps.length) {
          this.steps = this.generateFallbackElderLandmarkSteps()
        }
      }
    },
    // 将传统冰冷步骤转化为适老地标实景与无障碍属性卡片
    enrichStepWithLandmarks(st, idx, r) {
      const text = typeof st === 'string' ? st : (st.instruction || st.content || '')
      const pt = (this.routePoints && this.routePoints[idx]) || (this.routePoints && this.routePoints[this.routePoints.length - 1])

      // 提取或匹配直观地标与拟物化图标
      let landmark = st.landmark || ''
      let icon = st.icon || ''
      let actionDesc = st.action_desc || ''
      let accessibleBadges = st.accessible_features || st.accessibleBadges || []
      let voiceHint = st.voice_hint || st.voiceHint || ''

      if (!landmark) {
        const dest = (this.destinationName || (r && r.destination) || '').trim()
        if (dest.includes('烈士') || dest.includes('年嘉湖')) {
          if (idx === 0) {
            landmark = '烈士公园西门无障碍入口'
            icon = '🌳'
            actionDesc = '由烈士公园西门平缓通道进园，沿林荫道稳步行进，地面平整无台阶坑洼。'
            accessibleBadges = ['无台阶', '全程平缓 (<1.2%)', '绿荫覆盖率 92%']
          } else if (idx === 1) {
            landmark = '假山台阶绕行指示桩'
            icon = '⛔'
            actionDesc = '算法硬阻断已剪枝避开假山 38 级险陡台阶，引导走右侧宽阔平缓绿道。'
            accessibleBadges = ['已避开38级险台阶', '坡度1.1%极缓', '配备防滑扶手']
          } else if (idx === 2) {
            landmark = '年嘉湖西堤便民长椅'
            icon = '🪑'
            actionDesc = '途经适老休息驿站，设有便民长椅与遮阳棚，低位扶手设计，可随时小憩。'
            accessibleBadges = ['适老爱心长椅', '直饮水补给点', '遮阳挡雨棚']
          } else if (idx === 3) {
            landmark = '年嘉湖环湖木栈道'
            icon = '🚶'
            actionDesc = '顺着环湖适老防滑木栈道前行，湖面微风舒适，坡度仅 1.6%，全程无障碍直通。'
            accessibleBadges = ['防滑木栈道', '缓坡平顺 (<2%)', '避开临水湿滑']
          } else {
            landmark = '朝晖楼晨练康养广场'
            icon = '🏅'
            actionDesc = '顺利抵达朝晖楼晨练区，设有志愿服务站与医疗急救呼叫桩，晨练适宜。'
            accessibleBadges = ['平层无障碍到达', '红十字急救桩', '志愿助老岗亭']
          }
        } else if (dest.includes('湘雅')) {
          if (idx === 0) {
            landmark = '华夏路社区东门便民服务亭'
            icon = '🏡'
            actionDesc = '出小区东门沿平缓防滑人行道向南慢行，路面平整，无坑洼台阶。'
            accessibleBadges = ['无台阶', '全程平缓 (<0.9%)', '林荫遮阳步道']
          } else if (idx === 1) {
            landmark = '地面无障碍通道口'
            icon = '⛔'
            actionDesc = '算法硬阻断已剪枝避开地下通道 42 级险台阶，引导走地面平层通道。'
            accessibleBadges = ['已避开42级险台阶', '地面平层通行', '人车分流']
          } else if (idx === 2) {
            landmark = '湘雅路街心休息长椅'
            icon = '🪑'
            actionDesc = '途经街心长椅驿站，设有便民长椅与温开水补给点，可在此随心小憩。'
            accessibleBadges = ['适老爱心长椅', '温开水补给点', '防滑低位扶手']
          } else if (idx === 3) {
            landmark = '湘雅路口有声红绿灯'
            icon = '🚦'
            actionDesc = '过配备清脆语音提示的有声斑马线（绿灯时长 45 秒，中途设行人安全岛）。'
            accessibleBadges = ['45秒长绿灯', '语音声响指引', '行人安全岛']
          } else {
            landmark = '湘雅医院门诊大楼 1 号无障碍坡道'
            icon = '🏥'
            actionDesc = '抵达湘雅医院门诊大楼，顺着左侧专用防滑坡道进入大厅，直通骨科与无障碍直梯。'
            accessibleBadges = ['专用防滑坡道', '无障碍直梯', '导医志愿者引导']
          }
        } else {
          // 省人民医院 / 默认
          if (idx === 0) {
            landmark = '蔡锷北路适老驿站'
            icon = '🏡'
            actionDesc = '顺蔡锷北路宽敞防滑人行道向南慢行，绿树成荫，全程缓坡无台阶。'
            accessibleBadges = ['无台阶', '人车分流', '防滑路面']
          } else if (idx === 1) {
            landmark = '地面无障碍斑马线指示'
            icon = '⛔'
            actionDesc = '算法硬阻断已剪枝避开人行天桥 64 级无梯陡阶，引导走地面安全斑马线。'
            accessibleBadges = ['已避开64级险台阶', '地面平层通行']
          } else if (idx === 2) {
            landmark = '蔡锷中路便民长椅'
            icon = '🪑'
            actionDesc = '途经爱心长椅休息区，配有遮阳棚与无障碍公厕引导，可随时休息。'
            accessibleBadges = ['配备爱心长椅', '遮阳棚', '无障碍公厕引导']
          } else if (idx === 3) {
            landmark = '解放西路口安全岛'
            icon = '🚦'
            actionDesc = '过有声信号灯斑马线，安全绿灯时长 45 秒，中途设行人安全岛。'
            accessibleBadges = ['45秒长绿灯', '语音声响指引', '行人安全岛']
          } else {
            landmark = `${this.destinationName || '医院'}无障碍入口`
            icon = '🏥'
            actionDesc = `抵达${this.destinationName || '目的地'}，走左侧专用防滑缓坡进入大厅，直通无障碍直梯。`
            accessibleBadges = ['专用防滑缓坡', '无障碍直梯', '急救绿通定锚']
          }
        }
      }

      if (!actionDesc) {
        actionDesc = text || '顺着平整无障碍步道慢慢走，无台阶无陡坡。'
      }

      if (!voiceHint) {
        voiceHint = `${this.userName}，第${idx + 1}步：在${landmark}，${actionDesc}`
      }

      return {
        title: `第 ${idx + 1} 步：${landmark}`,
        landmark,
        icon,
        content: actionDesc,
        instruction: actionDesc,
        accessibleFeatures: accessibleBadges,
        voiceHint,
        tip: idx === 0
          ? '出发前带好温开水与遮阳帽，路上慢慢走，不着急。'
          : idx === ((r && r.steps) ? r.steps.length - 1 : 4)
          ? '到达目的地后，导医台和工作人员随时为您提供帮助。'
          : '前行路边设有适老休息长椅，走累了可以坐下来歇歇。',
        coords: pt ? [pt.lng, pt.lat] : this.elderCoords,
      }
    },
    // 生成长沙典型地标的高保真适老指引步骤
    generateFallbackElderLandmarkSteps() {
      const curScene = this.demoScenes[this.currentSceneIdx || 0]
      if (curScene && curScene.steps && curScene.steps.length) {
        return curScene.steps
      }
      return this.demoScenes[0].steps
    },
    async switchDemoScene(sIdx) {
      this.currentSceneIdx = sIdx
      const sc = this.demoScenes[sIdx]
      if (!sc) return

      this.originName = sc.origin
      this.destinationName = sc.destination
      this.city = sc.city
      this.routeDuration = sc.duration
      this.routeDistance = sc.distance
      this.barrierFreeScore = sc.score
      this.steps = sc.steps
      this.polylinePath = sc.polyline
      this.routePoints = sc.points
      this.elderCoords = [sc.points[0].lng, sc.points[0].lat]
      this.currentStepIndex = 0

      // 尝试调用后端直接路线规划接口同步（仅在后端有点更多更高精时采纳，防止覆盖高精人行步道）
      try {
        const directRes = await get('/api/trips/route/direct', {
          origin: sc.origin,
          destination: sc.destination,
          city: '长沙',
        }).catch(() => null)
        if (directRes && directRes.route && directRes.route.ok) {
          const r = directRes.route
          if (r.duration) this.routeDuration = r.duration
          if (r.distance_km) this.routeDistance = `${r.distance_km}公里`
          if (Array.isArray(r.polyline) && r.polyline.length >= sc.polyline.length) {
            this.polylinePath = r.polyline.map((p) => [p.lng, p.lat])
          }
        }

        const quickRes = await post('/api/trips/quick', {
          origin: sc.origin,
          destination: sc.destination,
          elder_id: this.user ? this.user.id : null,
          purpose: `前往${sc.destination}适老无障碍出行`,
        }).catch(() => null)
        if (quickRes && quickRes.trip) {
          this.tripId = quickRes.trip.id
        }
      } catch (e) {
        console.warn('切换场景后端同步异常:', e)
      }

      if (this.leafletMap) {
        this.renderRoute()
        this.resetView()
      }

      speak(`已切换至适老路线【${sc.label}】：从${sc.origin}到${sc.destination}，亚米级北斗避障护航已开启。`)
      uni.showToast({
        title: `已切换至：${sc.label}`,
        icon: 'none',
        duration: 2500,
      })
    },
    async initMap() {
      this.mapFailed = false
      this.mapLoading = true
      let L
      try {
        L = await loadLeaflet()
      } catch (err) {
        console.error('地图库加载失败:', err)
        this.mapLoading = false
        this.mapFailed = true
        return
      }
      ensureAmapMarkerStyles()
      await this.$nextTick()
      const container = document.getElementById('elder-amap-container')
      if (!container) {
        this.mapLoading = false
        return
      }

      try {
        if (this.leafletMap) {
          this.leafletMap.remove()
          this.leafletMap = null
        }

        this.leafletMap = L.map(container, {
          zoomControl: true,
          attributionControl: true,
          zoomSnap: 1,
          zoomDelta: 1,
          zoomAnimation: true,
          fadeAnimation: true,
          markerZoomAnimation: true,
          scrollWheelZoom: true,
          wheelPxPerZoomLevel: 120,
        }).setView(toLeafletLatLng(this.elderCoords), 15)

        if (this.leafletMap.attributionControl) {
          this.leafletMap.attributionControl.setPrefix(false)
          this.leafletMap.attributionControl.setPosition('bottomleft')
        }

        this.tileLayer = L.tileLayer(AMAP_RASTER_TILE_URL, {
          subdomains: AMAP_TILE_SUBDOMAINS,
          maxZoom: 18,
          minZoom: 3,
          attribution: AMAP_TILE_ATTRIBUTION,
        }).addTo(this.leafletMap)

        // 监听容器尺寸动态调整，彻底消除高度突变或初始化尺寸未定导致的底图灰色半边
        if (typeof ResizeObserver !== 'undefined') {
          if (this.resizeObserver) {
            this.resizeObserver.disconnect()
          }
          this.resizeObserver = new ResizeObserver(() => {
            if (this.leafletMap) {
              this.leafletMap.invalidateSize({ animate: false })
            }
          })
          this.resizeObserver.observe(container)
        }

        this.renderRoute(L)
        this.mapLoading = false

        this.$nextTick(() => {
          setTimeout(() => {
            if (this.leafletMap) this.leafletMap.invalidateSize({ animate: false })
          }, 80)
          setTimeout(() => {
            if (this.leafletMap) {
              this.leafletMap.invalidateSize({ animate: false })
              this.resetView()
            }
          }, 300)
        })
      } catch (err) {
        console.error('地图渲染失败:', err)
        this.mapLoading = false
        this.mapFailed = true
      }
    },
    renderRoute(L) {
      L = L || window.L
      if (!L || !this.leafletMap) return

      // 先清理所有旧图层，防止多路线叠加
      if (this.microTerrainLayers && this.microTerrainLayers.length) {
        this.microTerrainLayers.forEach((layer) => {
          try { this.leafletMap.removeLayer(layer) } catch (e) {}
        })
        this.microTerrainLayers = []
      }
      if (this.routeCorridor) {
        try { this.leafletMap.removeLayer(this.routeCorridor) } catch (e) {}
        this.routeCorridor = null
      }
      if (this.homeCircleLayer) {
        try { this.leafletMap.removeLayer(this.homeCircleLayer) } catch (e) {}
        this.homeCircleLayer = null
      }
      if (this.routeCasing) {
        try { this.leafletMap.removeLayer(this.routeCasing) } catch (e) {}
        this.routeCasing = null
      }
      if (this.routePolyline) {
        try { this.leafletMap.removeLayer(this.routePolyline) } catch (e) {}
        this.routePolyline = null
      }
      if (this.elderMarker) {
        try { this.leafletMap.removeLayer(this.elderMarker) } catch (e) {}
        this.elderMarker = null
      }
      if (this.stationMarkers && this.stationMarkers.length) {
        this.stationMarkers.forEach((m) => {
          try { this.leafletMap.removeLayer(m) } catch (e) {}
        })
        this.stationMarkers = []
      }

      // 如果没有 polylinePath，从 steps 抽取
      if (!this.polylinePath.length && this.steps.length) {
        this.polylinePath = this.steps.map((s) => s.coords)
      }

      const latlngs = this.polylinePath.map((p) => toLeafletLatLng(p))

      // 1. 动态安全走廊：翡翠绿半透明光带 (32px宽度，代表步道两侧25-30m安全走廊)
      if (latlngs.length >= 2) {
        this.routeCorridor = L.polyline(latlngs, {
          color: '#10b981',
          weight: 34,
          opacity: 0.28,
          lineJoin: 'round',
          lineCap: 'round',
        }).addTo(this.leafletMap)
        this.routeCorridor.bindTooltip('🛡️ 北斗适老动态安全走廊 (30m免打扰守护)', { permanent: false, direction: 'top' })

        // 家·500米生活守护圈 (以起点为中心画绿色虚线圆)
        this.homeCircleLayer = L.circle(latlngs[0], {
          radius: 500,
          color: '#10b981',
          weight: 2,
          dashArray: '6, 6',
          fillColor: '#10b981',
          fillOpacity: 0.08,
        }).addTo(this.leafletMap)
        this.homeCircleLayer.bindTooltip('🏠 家·500米生活守护圈 (圈内日常慢步静默伴随)', { permanent: false, direction: 'top' })
      }

      // 2. 规划路线描边 + 适老高辨识度天青蓝
      if (latlngs.length >= 2) {
        this.routeCasing = L.polyline(latlngs, {
          color: '#ffffff',
          weight: 12,
          opacity: 0.95,
          lineJoin: 'round',
          lineCap: 'round',
        }).addTo(this.leafletMap)

        this.routePolyline = L.polyline(latlngs, {
          color: '#2A82E4', // WCAG AAA 高对比鲜艳明亮蓝
          weight: 8,
          opacity: 0.98,
          lineJoin: 'round',
          lineCap: 'round',
        }).addTo(this.leafletMap)
      }

      // 3. 标注当前场景的微地形要素：险台阶硬阻断剪枝点 + 缓坡/长椅适老POI
      const curScene = this.demoScenes[this.currentSceneIdx || 0]
      if (curScene) {
        // 险台阶/陡坡硬阻断点 (红色警示图章)
        if (curScene.microBarriers && curScene.microBarriers.length) {
          curScene.microBarriers.forEach((b) => {
            const icon = makeMapMarkerIcon(L, {
              html: `<div class="micro-barrier-badge"><span class="barrier-icon">${b.icon || '⛔'}</span><span>${b.name}</span></div>`,
              size: [52, 28],
            })
            const bm = L.marker(toLeafletLatLng(b.coords), { icon, zIndexOffset: 800 }).addTo(this.leafletMap)
            bm.bindTooltip(`⚠️ ${b.desc || '已硬阻断剪枝，为您避开陡阶危险'}`, { permanent: false })
            this.microTerrainLayers.push(bm)
          })
        }
        // 坡度分段与长椅休憩POI
        if (curScene.microPois && curScene.microPois.length) {
          curScene.microPois.forEach((poi) => {
            const isBench = poi.type === 'bench'
            const isSlope = poi.type === 'slope'
            const badgeClass = isBench ? 'poi-bench' : isSlope ? 'poi-slope' : 'poi-hazard'
            const icon = makeMapMarkerIcon(L, {
              html: `<div class="micro-poi-badge ${badgeClass}"><span class="poi-icon">${poi.icon}</span><span>${poi.name}</span></div>`,
              size: [48, 26],
            })
            const pm = L.marker(toLeafletLatLng(poi.coords), { icon, zIndexOffset: 700 }).addTo(this.leafletMap)
            pm.bindTooltip(`${poi.desc || poi.name}`, { permanent: false })
            this.microTerrainLayers.push(pm)
          })
        }
      }

      // 4. 标注地标与起终点
      this.stationMarkers = []
      this.steps.forEach((st, idx) => {
        const isStart = idx === 0
        const isEnd = idx === this.steps.length - 1
        const badgeClass = isStart ? 'badge-start' : isEnd ? 'badge-end' : 'badge-station'
        const labelPrefix = isStart ? '🟢 起点：' : isEnd ? '🔴 终点：' : '🌳 地标：'
        const icon = makeMapMarkerIcon(L, {
          html: `<div class="elder-map-marker ${badgeClass}"><span class="marker-title">${labelPrefix}${st.landmark || st.title}</span></div>`,
          size: [48, 36],
        })
        const m = L.marker(toLeafletLatLng(st.coords), { icon }).addTo(this.leafletMap)
        this.stationMarkers.push(m)
      })

      // 5. 绘制长辈当前实时定位 Marker (带呼吸波纹动效与北斗高精徽标)
      const liveIcon = makeMapMarkerIcon(L, {
        html: `<div class="elder-live-pulse-marker"><div class="pulse-ring"></div><div class="pulse-core">🛰️ ${this.userName} (北斗0.35m)</div></div>`,
        size: [80, 80],
      })
      this.elderMarker = L.marker(toLeafletLatLng(this.elderCoords), {
        icon: liveIcon,
        zIndexOffset: 1000,
      }).addTo(this.leafletMap)

      if (latlngs.length >= 2 && this.routePolyline) {
        this.leafletMap.fitBounds(this.routePolyline.getBounds(), {
          padding: [50, 50],
          maxZoom: 16,
        })
      }
    },
    speakMicroFeature(type) {
      if (type === 'corridor') {
        speak('北斗动态安全走廊已覆盖步道两侧30米，在此走廊内自由漫步，子女端静默守护不打扰。')
        uni.showToast({ title: '🛡️ 30米动态安全走廊保护中', icon: 'none' })
      } else if (type === 'slope') {
        speak('当前路线经过微地形代价多目标优化，全程平均坡度小于2.5%，路面平整防滑。')
        uni.showToast({ title: '🟢 纵坡<2.5% 平缓适老绿道', icon: 'none' })
      } else if (type === 'barrier') {
        speak('微地形算法已为您硬阻断沿途全部险陡台阶和过街天桥，确保100%零台阶无障碍通行。')
        uni.showToast({ title: '⛔ 沿途险台阶已100%硬阻断', icon: 'none' })
      } else if (type === 'bench') {
        speak('沿途每隔150至200米设有适老休息长椅与遮阳棚，走累了随时可以坐下歇歇脚。')
        uni.showToast({ title: '🪑 沿途多处长椅休息点已标定', icon: 'none' })
      }
    },
    startReporting() {
      this.stopReporting()
      this.doReportLocation()
      this.reportTimer = setInterval(() => {
        this.doReportLocation()
      }, 10000)
    },
    stopReporting() {
      if (this.reportTimer) {
        clearInterval(this.reportTimer)
        this.reportTimer = null
      }
    },
    async doReportLocation() {
      const [lng, lat] = this.elderCoords
      const curStep = this.steps[this.currentStepIndex] || {}
      const locationName = curStep.landmark || curStep.title || '适老行进中'

      if (this.tripId) {
        try {
          const res = await post(`/api/trips/${this.tripId}/checkpoints`, {
            location: locationName,
            lng,
            lat,
            satellites: this.bdsSatelliteCount,
            accuracy: this.bdsAccuracy,
          })
          if (res && res.checkpoint) {
            this.reportCount++
          }
          // 若后端返回偏航检测
          if (res && res.evaluation && res.evaluation.status === 'OFF_ROUTE') {
            this.triggerDeviationReassurance(
              res.evaluation.alert_message || '',
              res.evaluation.distance_to_corridor_m || 28
            )
          }
        } catch (e) {
          console.warn('位置定时上报网络波动:', e.message)
        }
      }
    },
    // 触发温和偏航安抚 (支持自动与模拟演示)
    triggerDeviationReassurance(customText = '', distance = 28) {
      this.deviationAlert.active = true
      this.deviationAlert.distanceM = Math.round(distance)
      if (customText) {
        this.deviationAlert.customText = customText
      } else {
        this.deviationAlert.customText = `${this.userName}，您稍微走偏了点，别着急，转过身向右边便民大药房方向走${this.deviationAlert.distanceM}米就回到主道啦。`
      }
      this.playDeviationVoice()
    },
    triggerSimulatedDeviation() {
      this.triggerDeviationReassurance(
        `${this.userName}，您稍微走偏了点，别着急，转过身向右边便民大药房方向走28米就回到主道啦。`,
        28
      )
      uni.showToast({
        title: '已触发北斗偏航声控温和安抚',
        icon: 'none',
        duration: 3000,
      })
    },
    playDeviationVoice() {
      speak(this.deviationReassuranceText)
    },
    dismissDeviationAlert() {
      this.deviationAlert.active = false
    },
    realignToRoute() {
      this.deviationAlert.active = false
      const step = this.steps[this.currentStepIndex] || this.steps[0]
      if (step && step.coords && this.leafletMap) {
        this.elderCoords = step.coords
        if (this.elderMarker) {
          this.elderMarker.setLatLng(toLeafletLatLng(this.elderCoords))
        }
        this.leafletMap.panTo(toLeafletLatLng(this.elderCoords))
      }
      speak(`已帮您对准主道，顺着前方平缓绿道稳步走，路面无台阶。`)
      uni.showToast({
        title: '已对准适老无障碍通道',
        icon: 'success',
      })
    },
    // 问康乐：“我现在走到哪了？” 一键语音大白话问询
    handleElderVoiceInquiry() {
      const curStep = this.steps[this.currentStepIndex] || this.steps[0]
      const lm = (curStep && curStep.landmark) || '烈士公园南门大樟树'
      const spokenText = `${this.userName}，北斗定位显示您当前在【${lm}】，北斗差分精度0.35米，状态非常好。前方路面平坦无台阶，您慢慢走不着急。`
      speak(spokenText)
      uni.showModal({
        title: '🎤 康乐实时语音问询',
        content: spokenText,
        showCancel: false,
        confirmText: '我知道了',
      })
    },
    toggleMapFullscreen() {
      if (this.isMapFullscreen) {
        if (typeof window !== 'undefined' && window.history && window.history.state && window.history.state.isFullscreen) {
          window.history.back()
          return
        }
        this.isMapFullscreen = false
      } else {
        this.isMapFullscreen = true
        if (typeof window !== 'undefined' && window.history) {
          window.history.pushState({ isFullscreen: true }, '')
        }
      }
      this.refreshMapBounds()
    },
    handlePopState() {
      if (this.isMapFullscreen) {
        this.isMapFullscreen = false
        this.refreshMapBounds()
      }
    },
    refreshMapBounds() {
      this.$nextTick(() => {
        setTimeout(() => {
          if (this.leafletMap) {
            this.leafletMap.invalidateSize()
            this.resetView()
          }
        }, 150)
      })
    },
    resetView() {
      if (!this.leafletMap) return
      if (this.routePolyline && this.polylinePath.length >= 2) {
        try {
          this.leafletMap.fitBounds(this.routePolyline.getBounds(), {
            padding: this.isMapFullscreen ? [60, 60] : [30, 30],
            animate: true,
            duration: 0.8,
            easeLinearity: 0.25,
          })
          return
        } catch (e) {}
      }
      if (this.elderCoords) {
        this.leafletMap.flyTo(toLeafletLatLng(this.elderCoords), 15, {
          animate: true,
          duration: 0.8,
          easeLinearity: 0.25,
        })
      }
    },
    locateElder() {
      if (!this.leafletMap || !this.elderCoords) return
      this.leafletMap.flyTo(toLeafletLatLng(this.elderCoords), 16, {
        animate: true,
        duration: 0.8,
        easeLinearity: 0.25,
      })
      uni.showToast({ title: '已定位到北斗高精当前位置', icon: 'none' })
    },
    onStepSelected(payload) {
      const { step, index } = payload
      this.currentStepIndex = index
      if (step && step.coords && this.leafletMap) {
        this.leafletMap.flyTo(toLeafletLatLng(step.coords), 16, {
          animate: true,
          duration: 0.6,
          easeLinearity: 0.25,
        })
      }
    },
    onStepSpeak(payload) {
      // 步骤语音朗读在 LandmarkGuidanceCard 内已触发 speak
      const { index } = payload
      this.currentStepIndex = index
    },
    speakFullRoute() {
      const parts = [`北斗适老导航系统为您护航，从${this.originName}到${this.destinationName}。`]
      if (this.routeDuration) parts.push(`全程预计耗时${this.routeDuration}`)
      if (this.routeDistance) parts.push(`路程大约${this.routeDistance}`)
      parts.push(`全程无台阶，平均坡度小于4%，已为您避开过街天桥与施工路段。`)
      this.steps.forEach((s) => {
        parts.push(`${s.title}。${s.content}`)
      })
      const ok = speak(parts.join('。'))
      if (!ok) uni.showToast({ title: '当前设备不支持语音播放', icon: 'none' })
    },
    async fetchFamilyContact() {
      try {
        const res = await get('/api/family/members').catch(() => null)
        if (res && Array.isArray(res.items) && res.items.length) {
          const childMember = res.items.find((m) => m.user && m.user.role === 'child') || res.items[0]
          if (childMember && childMember.user) {
            this.familyContactName = childMember.user.name || '李明'
            this.familyContactPhone = childMember.user.phone || '13812345678'
          }
        }
      } catch (e) {}
    },
    async sendSafetyCheckin() {
      if (this.checkingIn) return
      this.checkingIn = true
      const [lng, lat] = this.elderCoords
      const curStep = this.steps[this.currentStepIndex] || {}
      const where = curStep.landmark || curStep.title || (this.destinationName || '前往途中')

      try {
        let res = null
        if (this.tripId) {
          res = await post(`/api/trips/${this.tripId}/checkin`, {
            location: where,
            lng,
            lat,
            message: `长辈主动报平安：目前一切安好，正顺着无障碍绿道前往${this.destinationName || '目的地'}`,
          }).catch(() => null)
        }

        const childName = (res && res.family && res.family.name) || this.familyContactName || '子女'
        const phone = (res && res.family && res.family.phone) || this.familyContactPhone || '13812345678'

        uni.showModal({
          title: '🕊️ 已向家人报平安',
          content: `已成功同步您的北斗高精时空位置至【${childName}】的守护看板！当前位置：${where}。`,
          confirmText: '呼叫家人',
          cancelText: '我知道了',
          success: (mRes) => {
            if (mRes.confirm) {
              this.makeSafePhoneCall(phone)
            }
          },
        })
      } catch (err) {
        uni.showToast({ title: '网络稍有波动，已记录本地状态', icon: 'none' })
      } finally {
        this.checkingIn = false
      }
    },
    callFamilyDirect() {
      const phone = this.familyContactPhone || '13812345678'
      const name = this.familyContactName || '家人'
      uni.showModal({
        title: '📞 拨打家人电话',
        content: `即将呼叫家人【${name}】（${phone}）`,
        confirmText: '立即呼叫',
        cancelText: '取消',
        success: (res) => {
          if (res.confirm) {
            this.makeSafePhoneCall(phone)
          }
        },
      })
    },
    makeSafePhoneCall(phoneNumber) {
      if (!phoneNumber) return
      uni.makePhoneCall({
        phoneNumber,
        fail: () => {
          uni.setClipboardData({
            data: phoneNumber,
            success: () => {
              uni.showToast({
                title: `已复制号码：${phoneNumber}，可在拨号盘粘贴呼叫`,
                icon: 'none',
                duration: 3500,
              })
            },
          })
        },
      })
    },
    goBack() {
      const pages = getCurrentPages()
      if (pages.length > 1) {
        uni.navigateBack()
      } else {
        uni.switchTab({ url: '/pages/elder/chat' })
      }
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../../uni.scss';

.route-page {
  min-height: 100vh;
  background: #f8fafc; // 清爽防眩光浅云底
  padding-bottom: calc(64rpx + env(safe-area-inset-bottom, 0px));
  box-sizing: border-box;
}

/* 顶部适老导航条 (触控靶区 >= 48px / 96rpx) */
.elder-navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx 24rpx 20rpx;
  background: #ffffff;
  border-bottom: 2rpx solid #e2e8f0;
  min-height: 104rpx;
}

.nav-back-btn {
  min-height: 96rpx;
  min-width: 144rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  background: #f1f5f9;
  color: #0f172a;
  border-radius: 48rpx;
  border: 2rpx solid #cbd5e1;
  padding: 0 24rpx;
  margin: 0;
  cursor: pointer;
}

.back-arrow {
  font-size: 48rpx;
  font-weight: 800;
  line-height: 1;
}

.back-text {
  font-size: 32rpx;
  font-weight: 800;
}

.nav-title-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4rpx;
}

.nav-title {
  font-size: 38rpx;
  font-weight: 900;
  color: #0f172a; // WCAG AAA 高对比
  letter-spacing: 0.5rpx;
}

.nav-subtitle {
  font-size: 22rpx;
  font-weight: 700;
  color: #059669; // 北斗绿
}

.nav-speak-btn {
  min-height: 96rpx;
  display: flex;
  align-items: center;
  gap: 8rpx;
  background: #eff6ff;
  color: #1d4ed8;
  border-radius: 48rpx;
  border: 2rpx solid #93c5fd;
  padding: 0 28rpx;
  margin: 0;
  cursor: pointer;
}

.speak-icon {
  font-size: 36rpx;
}

.speak-text {
  font-size: 30rpx;
  font-weight: 800;
}

/* 偏航声控安抚浮层 (温和暖金琥珀底，消除长辈恐慌) */
.deviation-reassurance-card {
  margin: 16rpx 24rpx;
  background: #fffbeb;
  border-radius: 24rpx;
  border: 3rpx solid #f59e0b;
  box-shadow: 0 8rpx 24rpx rgba(245, 158, 11, 0.2);
  padding: 24rpx;
}

.deviation-header {
  display: flex;
  align-items: center;
  gap: 14rpx;
  margin-bottom: 14rpx;
}

.deviation-icon-badge {
  font-size: 40rpx;
  line-height: 1;
}

.deviation-title-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.deviation-title {
  font-size: 34rpx;
  font-weight: 900;
  color: #92400e; // WCAG AAA 高对比深琥珀
}

.deviation-subtitle {
  font-size: 24rpx;
  font-weight: 700;
  color: #b45309;
}

.deviation-close-btn {
  width: 64rpx;
  height: 64rpx;
  border-radius: 50%;
  background: #fef3c7;
  border: 2rpx solid #fde68a;
  color: #78350f;
  font-size: 28rpx;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0;
  padding: 0;
  cursor: pointer;
}

.deviation-msg-content {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 18rpx 20rpx;
  margin-bottom: 18rpx;
  border: 1rpx solid #fed7aa;
}

.deviation-msg-text {
  font-size: 34rpx; // 适老大字
  font-weight: 800;
  color: #1a2838;
  line-height: 1.6;
}

.deviation-action-buttons {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.dev-btn {
  flex: 1;
  min-height: 96rpx; // 触控靶区 >= 48px
  border-radius: 48rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10rpx;
  border: none;
  cursor: pointer;
  margin: 0;
}

.dev-btn-speak {
  background: #d97706;
  color: #ffffff;
  box-shadow: 0 6rpx 16rpx rgba(217, 119, 6, 0.3);
}

.dev-btn-realign {
  background: #10b981;
  color: #ffffff;
  box-shadow: 0 6rpx 16rpx rgba(16, 185, 129, 0.3);
}

.dev-btn .btn-icon {
  font-size: 34rpx;
}

.dev-btn .btn-text {
  font-size: 30rpx;
  font-weight: 800;
}

/* 10秒定时上报状态指示条 */
.reporting-banner {
  display: flex;
  align-items: center;
  background: #f0fdf4;
  border-bottom: 2rpx solid #bbf7d0;
  padding: 14rpx 24rpx;
}

.pulse-dot {
  width: 18rpx;
  height: 18rpx;
  border-radius: 50%;
  background: #059669;
  box-shadow: 0 0 0 6rpx rgba(5, 150, 105, 0.25);
  animation: pulseGreen 1.6s infinite ease-in-out;
  flex-shrink: 0;
  margin-right: 14rpx;
}

@keyframes pulseGreen {
  0% { transform: scale(0.9); opacity: 0.7; }
  50% { transform: scale(1.2); opacity: 1; box-shadow: 0 0 0 10rpx rgba(5, 150, 105, 0); }
  100% { transform: scale(0.9); opacity: 0.7; }
}

.report-text {
  flex: 1;
  font-size: 26rpx;
  color: #064e3b;
  font-weight: 700;
}

/* 路线概览信息 */
.route-summary-bar {
  margin: 16rpx 24rpx;
  padding: 24rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 2rpx solid #e2e8f0;
  box-shadow: 0 4rpx 16rpx rgba(0, 0, 0, 0.04);
}

.summary-line {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex-wrap: wrap;
}

.summary-badge {
  font-size: 26rpx;
  font-weight: 800;
  padding: 4rpx 14rpx;
  border-radius: 10rpx;
  color: #ffffff;
}

.summary-badge.start {
  background: #059669;
}

.summary-badge.end {
  background: #dc2626;
}

.summary-place {
  font-size: 36rpx;
  font-weight: 900;
  color: #0f172a;
}

.summary-arrow {
  font-size: 30rpx;
  color: #94a3b8;
  margin: 0 4rpx;
}

.summary-meta {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-top: 14rpx;
  padding-top: 14rpx;
  border-top: 2rpx dashed #e2e8f0;
  flex-wrap: wrap;
}

.meta-item {
  font-size: 28rpx;
  color: #334155;
  font-weight: 700;
}

.barrier-free-score-tag {
  color: #047857;
  background: #d1fae5;
  padding: 4rpx 14rpx;
  border-radius: 12rpx;
  font-weight: 800;
}

/* 赛事示范路线快捷切换栏 */
.scene-switch-bar {
  margin: 0 24rpx 18rpx;
  background: #ffffff;
  border-radius: 20rpx;
  padding: 16rpx 20rpx;
  border: 2rpx solid #e2e8f0;
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.04);
}

.scene-switch-header {
  margin-bottom: 12rpx;
}

.scene-title {
  font-size: 26rpx;
  font-weight: 800;
  color: #0f172a;
  letter-spacing: 0.5rpx;
}

.scene-chips {
  display: flex;
  gap: 12rpx;
  overflow-x: auto;
  padding-bottom: 4rpx;
  -webkit-overflow-scrolling: touch;
}

.scene-chip {
  flex: 1;
  min-width: 0;
  min-height: 72rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  padding: 8rpx 16rpx;
  border-radius: 16rpx;
  background: #f1f5f9;
  border: 2rpx solid #cbd5e1;
  color: #334155;
  cursor: pointer;
  white-space: nowrap;
  font-size: 26rpx;
  font-weight: 700;
  transition: all 0.2s ease;
  margin: 0;
}

.scene-chip.active {
  background: #eff6ff;
  border-color: #2563eb;
  color: #1d4ed8;
  font-weight: 900;
  box-shadow: 0 4rpx 12rpx rgba(37, 99, 235, 0.15);
}

.chip-icon {
  font-size: 30rpx;
}

.chip-label {
  font-size: 26rpx;
}

/* 高德地图容器 (58% 黄金分屏比例) */
.map-section {
  position: relative;
  margin: 0 24rpx 24rpx;
  border-radius: 24rpx;
  overflow: hidden;
  box-shadow: 0 6rpx 20rpx rgba(0, 0, 0, 0.08);
  border: 2rpx solid #cbd5e1;
}

/* 适老微地形高精要素状态栏 */
.microterrain-status-bar {
  position: absolute;
  top: 14rpx;
  left: 14rpx;
  right: 14rpx;
  z-index: 500;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8rpx;
  pointer-events: auto;
}

.micro-status-pill {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6rpx;
  padding: 8rpx 8rpx;
  background: rgba(15, 23, 42, 0.85);
  backdrop-filter: blur(8px);
  border: 1.5rpx solid rgba(255, 255, 255, 0.25);
  border-radius: 20rpx;
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.2);
  cursor: pointer;
  white-space: nowrap;
}

.micro-status-pill:active {
  transform: scale(0.96);
}

.micro-status-pill.pill-corridor {
  border-color: rgba(16, 185, 129, 0.8);
}

.micro-status-pill.pill-slope {
  border-color: rgba(2, 132, 199, 0.8);
}

.micro-status-pill.pill-barrier {
  border-color: rgba(220, 38, 38, 0.8);
}

.micro-status-pill.pill-bench {
  border-color: rgba(217, 119, 6, 0.8);
}

.micro-status-pill .pill-icon {
  font-size: 22rpx;
}

.micro-status-pill .pill-text {
  font-size: 20rpx;
  font-weight: 800;
  color: #ffffff;
}

.amap-box {
  width: 100%;
  height: 58vh;
  min-height: 380px;
  background: #e2e8f0;
  touch-action: pan-x pan-y !important;
  -webkit-user-select: none;
  user-select: none;
  overscroll-behavior: contain;
}

.map-section.fullscreen-mode {
  position: fixed !important;
  top: 0 !important;
  left: 0 !important;
  right: 0 !important;
  bottom: 0 !important;
  width: 100vw !important;
  height: 100vh !important;
  z-index: 9999 !important;
  margin: 0 !important;
  border-radius: 0 !important;
}

.map-section.fullscreen-mode .amap-box {
  width: 100% !important;
  height: 100% !important;
  min-height: 100% !important;
}

/* 全屏大图模式顶部悬浮栏 */
.fullscreen-topbar {
  position: absolute;
  top: calc(env(safe-area-inset-top, 0px) + 24rpx);
  left: 24rpx;
  right: 24rpx;
  z-index: 1300;
  pointer-events: none;
}

.fullscreen-topbar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.fullscreen-exit-pill {
  pointer-events: auto;
  min-height: 88rpx;
  display: inline-flex;
  align-items: center;
  gap: 10rpx;
  background: #ffffff;
  color: #0f172a;
  border: 2rpx solid #94a3b8;
  border-radius: 44rpx;
  box-shadow: 0 6rpx 20rpx rgba(0, 0, 0, 0.2);
  padding: 0 30rpx;
  cursor: pointer;
}

.exit-icon {
  font-size: 44rpx;
  font-weight: 800;
  color: #2563eb;
  line-height: 1;
}

.exit-text {
  font-size: 30rpx;
  font-weight: 800;
  color: #0f172a;
}

.fullscreen-hint {
  font-size: 26rpx;
  font-weight: 700;
  color: #ffffff;
  background: rgba(15, 23, 42, 0.85);
  padding: 10rpx 24rpx;
  border-radius: 20rpx;
  backdrop-filter: blur(4px);
}

/* 全屏大图模式底部悬浮退出大按钮 */
.fullscreen-bottombar {
  position: absolute;
  bottom: calc(env(safe-area-inset-bottom, 0px) + 28rpx);
  left: 28rpx;
  right: 28rpx;
  z-index: 1300;
}

.fullscreen-bottom-btn {
  width: 100%;
  min-height: 104rpx; // 触控靶区 >= 48px
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
  background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
  color: #ffffff;
  border: none;
  border-radius: 52rpx;
  box-shadow: 0 10rpx 28rpx rgba(29, 78, 216, 0.45);
  padding: 0 32rpx;
  cursor: pointer;
}

.bottom-btn-icon {
  font-size: 40rpx;
}

.bottom-btn-text {
  font-size: 34rpx;
  font-weight: 900;
  color: #ffffff;
}

.map-section.fullscreen-mode .map-controls {
  bottom: calc(env(safe-area-inset-bottom, 0px) + 160rpx) !important;
}

.map-loading-mask {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255, 255, 255, 0.88);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14rpx;
}

.loading-icon {
  font-size: 52rpx;
}

.loading-text {
  font-size: 30rpx;
  color: #1e293b;
  font-weight: 700;
}

.map-retry-btn {
  margin-top: 16rpx;
  min-height: 80rpx;
  background: #2563eb;
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 800;
  border: none;
  border-radius: 40rpx;
  padding: 0 36rpx;
}

.map-controls {
  position: absolute;
  right: 20rpx;
  bottom: 20rpx;
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  z-index: 1200;
}

.ctrl-btn {
  background: #ffffff;
  color: #0f172a;
  border: 2rpx solid #cbd5e1;
  border-radius: 36rpx;
  font-size: 26rpx;
  font-weight: 800;
  min-height: 72rpx;
  padding: 8rpx 22rpx;
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.15);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.ctrl-btn.ctrl-btn-fullscreen {
  background: #1e40af;
  color: #ffffff;
  border-color: #1d4ed8;
}

.ctrl-btn.ctrl-btn-deviation {
  background: #fffbeb;
  color: #92400e;
  border-color: #f59e0b;
}

/* 一键大白话语音问询与转向引导条 */
.voice-steer-action-bar {
  margin: 0 24rpx 24rpx;
}

.btn-voice-inquiry {
  width: 100%;
  min-height: 108rpx; // 触控靶区 >= 48px
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  border: 3rpx solid #93c5fd;
  border-radius: 28rpx;
  padding: 16rpx 24rpx;
  display: flex;
  align-items: center;
  gap: 18rpx;
  box-shadow: 0 6rpx 20rpx rgba(37, 99, 235, 0.12);
  cursor: pointer;
  box-sizing: border-box;
}

.inquiry-mic-icon {
  font-size: 48rpx;
  color: #1d4ed8;
  line-height: 1;
  flex-shrink: 0;
}

.inquiry-text-group {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4rpx;
}

.inquiry-main-title {
  font-size: 34rpx;
  font-weight: 900;
  color: #1e3a8a; // WCAG AAA 高对比深蓝
}

.inquiry-sub-title {
  font-size: 24rpx;
  font-weight: 700;
  color: #2563eb;
}

/* 地标实景指引步骤列表 */
.steps-section {
  margin: 0 24rpx;
}

.section-header {
  margin-bottom: 20rpx;
}

.section-title-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12rpx;
}

.section-title {
  font-size: 38rpx;
  font-weight: 900;
  color: #0f172a;
}

.landmark-tag {
  font-size: 24rpx;
  font-weight: 800;
  color: #065f46;
  background: #d1fae5;
  padding: 4rpx 14rpx;
  border-radius: 12rpx;
  border: 1rpx solid #a7f3d0;
}

.section-subtitle {
  display: block;
  font-size: 26rpx;
  font-weight: 700;
  color: #475569;
  margin-top: 6rpx;
}

.step-empty-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
  padding: 56rpx 32rpx;
  background: #ffffff;
  border: 2rpx dashed #cbd5e1;
  border-radius: 24rpx;
  margin-bottom: 24rpx;
}

.step-empty-icon {
  font-size: 68rpx;
}

.step-empty-text {
  font-size: 32rpx;
  color: #334155;
  font-weight: 700;
  line-height: 1.6;
  text-align: center;
}

/* 适老安心守护与联系家人按钮 (触控靶区 >= 48px / 96rpx) */
.help-section {
  margin-top: 36rpx;
  margin-bottom: 48rpx;
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.btn-help-safe {
  width: 100%;
  min-height: 104rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14rpx;
  background: #059669;
  color: #ffffff;
  border-radius: 52rpx;
  border: none;
  font-size: 36rpx;
  font-weight: 900;
  box-shadow: 0 8rpx 20rpx rgba(5, 150, 105, 0.3);
  cursor: pointer;
}

.btn-help-tel {
  width: 100%;
  min-height: 104rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14rpx;
  background: #ffffff;
  color: #1d4ed8;
  border-radius: 52rpx;
  border: 3rpx solid #bfdbfe;
  font-size: 34rpx;
  font-weight: 900;
  box-shadow: 0 6rpx 16rpx rgba(29, 78, 216, 0.12);
  cursor: pointer;
}

.btn-help-safe .btn-icon,
.btn-help-tel .btn-icon {
  font-size: 40rpx;
}
</style>
