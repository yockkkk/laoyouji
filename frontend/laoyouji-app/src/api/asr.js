/**
 * 语音识别三链路（风险对冲：讯飞 key 缺失也能演示）：
 *   1. 录音上传后端 → ASR Provider（讯飞方言 / mock）
 *   2. Web Speech API 浏览器直连（降级）
 *   3. 文字输入永远可用（最终兜底）
 */
import { uploadAudio } from './client'

/** 是否支持 Web Speech API（仅 H5 / Chrome 系） */
export function webSpeechAvailable() {
  // #ifdef H5
  return !!(window.SpeechRecognition || window.webkitSpeechRecognition)
  // #endif
  // #ifndef H5
  return false
  // #endif
}

/**
 * 开始录音（H5 用 AudioContext 采 PCM 封装 WAV；小程序/App 用 uni.getRecorderManager）。
 * 返回 recorder 控制器 {stop(): Promise<{tempFilePath}>}
 *
 * 为什么 H5 不直接录 webm/opus：MediaRecorder 在 Chrome/Edge 只给 audio/webm，
 * 而腾讯一句话识别的容器白名单里没有 webm（也没服务端转码），录音一上传就被
 * 502 拒 —— LyjMic 就报"没听清，再按住说一遍"。所以 H5 绕开 MediaRecorder，
 * 走 WebAudio 拿原始 PCM，降采样成 16k 单声道 16bit WAV，正好喂腾讯的 16k 引擎。
 */
export function startRecording() {
  // #ifdef H5
  return startH5Recording()
  // #endif
  // #ifndef H5
  return startUniRecording()
  // #endif
}

/** 线性重采样：fromRate → toRate（录音在非 16k 设备上时用到） */
function resampleLinear(input, fromRate, toRate) {
  const ratio = fromRate / toRate
  const out = new Float32Array(Math.max(1, Math.round(input.length / ratio)))
  for (let i = 0; i < out.length; i++) {
    const pos = i * ratio
    const i0 = Math.floor(pos)
    const i1 = Math.min(i0 + 1, input.length - 1)
    const frac = pos - i0
    out[i] = input[i0] * (1 - frac) + input[i1] * frac
  }
  return out
}

/** Float32 PCM → 16bit 单声道 WAV 字节（腾讯 16k_zh 引擎直接收） */
function encodeWav(samples, sampleRate) {
  const buf = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buf)
  const ascii = (off, s) => {
    for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i))
  }
  ascii(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  ascii(8, 'WAVE')
  ascii(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // byteRate
  view.setUint16(32, 2, true) // blockAlign
  view.setUint16(34, 16, true) // bitsPerSample
  ascii(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  let off = 44
  for (let i = 0; i < samples.length; i++, off += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return new Uint8Array(buf)
}

function startH5Recording() {
  return new Promise((resolve, reject) => {
    let stream
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((s) => {
        stream = s
        return beginCapture(stream)
      })
      .then((ctrl) => resolve(ctrl))
      .catch((e) => reject(new Error('麦克风不可用：' + (e.message || e.name))))
  })
}

/** 用 WebAudio 抓 16k 单声道 PCM，松手时封装 WAV。 */
function beginCapture(stream) {
  return new Promise((resolve, reject) => {
    const AC = window.AudioContext || window.webkitAudioContext
    let ctx, src, sp
    let chunks = []
    try {
      ctx = new AC({ sampleRate: 16000 }) // 直接要 16k，省去重采样
      if (!ctx.sampleRate) ctx = new AC() // 老内核不认 {sampleRate}
    } catch (e) {
      try {
        ctx = new AC()
      } catch (e2) {
        stream.getTracks().forEach((t) => t.stop())
        reject(new Error('该浏览器不支持录音'))
        return
      }
    }
    const recordedRate = ctx.sampleRate || 16000
    try {
      if (ctx.state === 'suspended') ctx.resume && ctx.resume()
      src = ctx.createMediaStreamSource(stream)
      sp = ctx.createScriptProcessor(4096, 1, 1) // 引擎自动 down-mix 到单声道
      sp.onaudioprocess = (ev) => {
        const d = ev.inputBuffer.getChannelData(0)
        if (d && d.length) chunks.push(new Float32Array(d))
      }
      const mute = ctx.createGain()
      mute.gain.value = 0 // 只是为了让节点"在处理中"，别真把麦克风声放出来（防回声啸叫）
      src.connect(sp)
      sp.connect(mute)
      mute.connect(ctx.destination)
    } catch (e) {
      try {
        stream.getTracks().forEach((t) => t.stop())
        ctx.close && ctx.close()
      } catch (e2) {}
      reject(new Error('录音初始化失败：' + (e.message || e.name)))
      return
    }

    const stop = () =>
      new Promise((res) => {
        try {
          sp.disconnect()
          src.disconnect()
          stream.getTracks().forEach((t) => t.stop())
          ctx.close && ctx.close()
        } catch (e) {}
        // 拼 PCM → 必要时降采样 → 封装 WAV
        const len = chunks.reduce((n, c) => n + c.length, 0)
        const raw = new Float32Array(len)
        let off = 0
        for (const c of chunks) {
          raw.set(c, off)
          off += c.length
        }
        const pcm =
          recordedRate === 16000 ? raw : resampleLinear(raw, recordedRate, 16000)
        const wav = encodeWav(pcm, 16000)
        const blob = new Blob([wav], { type: 'audio/wav' })
        res({ tempFilePath: URL.createObjectURL(blob), blob, fmt: 'wav' })
      })

    resolve({
      stop,
      _recorder: { stop }, // LyjMic 兜底释放音轨用；WAV 无需真正"停止"外部 recorder
    })
  })
}

function startUniRecording() {
  const rec = uni.getRecorderManager()
  return new Promise((resolve, reject) => {
    rec.onStart(() => {
      resolve({
        stop: () =>
          new Promise((res) => {
            rec.onStop((r) => res(r))
            rec.stop()
          }),
        _recorder: rec,
      })
    })
    rec.onError((e) => reject(new Error('录音失败：' + (e.errMsg || ''))))
    rec.start({ format: 'mp3', duration: 60000 })
  })
}

/**
 * 把录音送后端识别。
 * @returns {Promise<string>} 识别文本
 */
export async function recognizeAudio(tempFilePath, dialect) {
  const r = await uploadAudio(tempFilePath, dialect)
  return r.text || ''
}

/**
 * Web Speech 直连（浏览器本地识别，无需后端 key）。
 * 返回 controller {stop()}；识别结果经 onResult 回调。
 */
export function startWebSpeech(dialect, onResult, onEnd) {
  // #ifdef H5
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition
  if (!SR) return null
  const rec = new SR()
  rec.lang = dialect === 'southwestern' ? 'zh-CN' : 'zh-CN'
  rec.interimResults = true
  rec.continuous = true
  rec.onresult = (e) => {
    let text = ''
    for (let i = 0; i < e.results.length; i++) {
      text += e.results[i][0].transcript
    }
    onResult && onResult(text)
  }
  rec.onend = () => onEnd && onEnd()
  rec.start()
  return {
    stop: () => rec.stop(),
    _rec: rec,
  }
  // #endif
  // #ifndef H5
  return null
  // #endif
}

/** TTS 播报（浏览器 speechSynthesis，"再念一遍"按钮用）。 */
export function speak(text) {
  // #ifdef H5
  if (typeof speechSynthesis === 'undefined') return false
  speechSynthesis.cancel()
  const u = new SpeechSynthesisUtterance(text)
  u.lang = 'zh-CN'
  u.rate = 0.85 // 放慢语速，适老
  speechSynthesis.speak(u)
  return true
  // #endif
  // #ifndef H5
  return false
  // #endif
}
