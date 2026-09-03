<template>
  <!--
    120px 大麦克风 —— 适老硬指标里唯一按直径规定的控件。

    从 chat.vue 抽出来，因为首页也要有它：老人的主入口就是说话，
    麦克风不能只长在二级页。抽成组件而不是复制一遍，是为了让"按住—松开—
    识别—兜底"这条链路只有一份实现（三链路降级见 api/asr.js）。

    组件只负责把话变成文字，然后 emit('text', 文字)。**怎么用这句话是页面的事** ——
    聊天页直接发给老友记，首页则交接过去。
  -->
  <view class="mic-wrap" :class="'mode-' + mode">
    <view
      class="mic"
      :class="{ recording, disabled }"
      @touchstart.prevent="micDown"
      @touchend.prevent="micUp"
      @touchcancel.prevent="micUp"
      @mousedown.prevent="micDown"
      @mouseup.prevent="micUp"
    >
      <text class="mic-icon">{{ recording ? '🎙️' : '🎤' }}</text>
      <text class="mic-label">{{ recording ? '松开说完' : '按住说话' }}</text>
    </view>
    <view v-if="recording && interimText" class="interim">
      <text class="interim-text">{{ interimText }}</text>
    </view>
    <text v-else-if="hint" class="hint">{{ hint }}</text>
  </view>
</template>

<script>
import { startRecording, recognizeAudio, startWebSpeech, webSpeechAvailable } from '../api/asr'

export default {
  name: 'LyjMic',
  props: {
    disabled: { type: Boolean, default: false },
    dialect: { type: String, default: '' },
    hint: { type: String, default: '' }, // 静止时的一行提示，如"按住说话，说完松开"
    mode: { type: String, default: 'circle' }, // circle (首页大圆) | bar (聊天页横向胶囊)
  },
  emits: ['text'],
  data() {
    return { recording: false, interimText: '', _recorder: null, _webSpeech: null }
  },
  beforeUnmount() {
    // 录音中离开页面：必须把麦克风关掉，否则轨道一直开着（H5 上是个亮着的红点）
    this._teardown()
  },
  methods: {
    async micDown() {
      if (this.disabled || this.recording) return
      this.recording = true
      this.interimText = ''
      try {
        // 主链路：录音上传后端方言 ASR
        this._recorder = await startRecording()
        // 附加：Web Speech 只做实时预览，不作为识别结果的唯一来源
        if (webSpeechAvailable()) {
          this._webSpeech = startWebSpeech(
            this.dialect,
            (t) => (this.interimText = t),
            () => {},
          )
        }
      } catch (e) {
        this.recording = false
        uni.showToast({
          title: e.message || '麦克风不可用，请用打字',
          icon: 'none',
          duration: 2500,
        })
      }
    },

    async micUp() {
      if (!this.recording) return
      this.recording = false
      const ws = this._webSpeech
      this._webSpeech = null
      if (ws) ws.stop()
      if (!this._recorder) return

      let text = (this.interimText || '').trim()
      this.interimText = ''
      try {
        const audio = await this._recorder.stop()
        this._recorder = null
        if (!text) {
          text = ((await recognizeAudio(audio.tempFilePath, this.dialect)) || '').trim()
        }
      } catch (e) {
        uni.showToast({ title: '没听清，您再按住说一遍', icon: 'none', duration: 2000 })
        return
      }
      if (!text) {
        uni.showToast({ title: '没听到声音，您再试试', icon: 'none', duration: 2000 })
        return
      }
      this.$emit('text', text)
    },

    _teardown() {
      if (this._webSpeech) {
        try {
          this._webSpeech.stop()
        } catch (e) {
          /* 已经停了 */
        }
        this._webSpeech = null
      }
      if (this._recorder) {
        // stop() 会顺带释放音轨；结果不要了
        Promise.resolve(this._recorder.stop()).catch(() => {})
        this._recorder = null
      }
      this.recording = false
      this.interimText = ''
    },
  },
}
</script>

<style lang="scss" scoped>
@import '../uni.scss';

.mic-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: $lyj-space-sm;
}
.mic {
  /* 120px 直径，硬指标 */
  width: $lyj-mic;
  height: $lyj-mic;
  border-radius: 50%;
  background: linear-gradient(160deg, $lyj-primary-light, $lyj-primary);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: $lyj-space-xs;
  box-shadow: 0 10rpx 30rpx rgba(232, 84, 30, 0.4);
  transition: transform 0.15s;
  user-select: none;
}
.mic.recording {
  transform: scale(1.12);
  background: linear-gradient(160deg, $lyj-danger, $lyj-danger-dark);
}
.mic.disabled {
  filter: grayscale(0.8);
}
.mic-icon {
  font-size: 88rpx;
}
.mic-label {
  font-size: $lyj-font-md;
  color: $lyj-text-on;
  font-weight: 700;
}
.interim {
  padding: 0 $lyj-space-md;
}
.interim-text {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}
.hint {
  font-size: $lyj-font-sm;
  color: $lyj-text-light;
}

/* 紧凑横向录音条模式（用于聊天室底部，释放垂直消息可视区域） */
.mic-wrap.mode-bar {
  width: 100%;
  position: relative;
  .mic {
    width: 100%;
    height: 96rpx;
    border-radius: $lyj-radius-pill;
    flex-direction: row;
    justify-content: center;
    gap: $lyj-space-sm;
    box-shadow: 0 4rpx 16rpx rgba(232, 84, 30, 0.25);
    .mic-icon {
      font-size: 48rpx;
    }
    .mic-label {
      font-size: $lyj-font-md;
      font-weight: 700;
    }
  }
  .mic.recording {
    transform: scale(1.02);
  }
  .interim {
    position: absolute;
    bottom: 110rpx;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(40, 40, 40, 0.85);
    padding: 12rpx 28rpx;
    border-radius: $lyj-radius-pill;
    white-space: nowrap;
    pointer-events: none;
    box-shadow: 0 8rpx 24rpx rgba(0, 0, 0, 0.2);
    z-index: 10;
    .interim-text {
      color: #ffffff;
      font-size: $lyj-font-sm;
    }
  }
}
</style>
