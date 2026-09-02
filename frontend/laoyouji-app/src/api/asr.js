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
 * 开始录音（H5 用 MediaRecorder；小程序/App 用 uni.getRecorderManager）。
 * 返回 recorder 控制器 {stop(): Promise<{tempFilePath}>}
 */
export function startRecording() {
  // #ifdef H5
  return startH5Recording()
  // #endif
  // #ifndef H5
  return startUniRecording()
  // #endif
}

function startH5Recording() {
  return new Promise(async (resolve, reject) => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mime = MediaRecorder.isTypeSupported('audio/webm')
        ? 'audio/webm'
        : ''
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const chunks = []
      recorder.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data)
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' })
        const url = URL.createObjectURL(blob)
        resolve({
          stop: () => Promise.resolve({ tempFilePath: url, blob }),
          _recorder: recorder,
        })
      }
      recorder.start()
      // 先返回一个可 stop 的控制器
      resolve({
        stop: () =>
          new Promise((res) => {
            recorder.onstop = () => {
              stream.getTracks().forEach((t) => t.stop())
              const blob = new Blob(chunks, {
                type: recorder.mimeType || 'audio/webm',
              })
              res({ tempFilePath: URL.createObjectURL(blob), blob })
            }
            recorder.stop()
          }),
        _recorder: recorder,
      })
    } catch (e) {
      reject(new Error('麦克风不可用：' + (e.message || e.name)))
    }
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
    for (let i = e.resultIndex; i < e.results.length; i++) {
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
