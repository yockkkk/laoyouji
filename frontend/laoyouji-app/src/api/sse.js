/**
 * SSE 流式对话客户端（ADR-3）：
 *   主链路  fetch + ReadableStream 手工解析（uni-app H5 环境浏览器原生支持）
 *   兜底    GET /api/sessions/{id}/events?after_seq=N 轮询（2s）
 * 两条链路共用同一套事件回调，前端无感切换。
 *
 * "无感切换"这句话原来是假的，返工时才发现：后端有**两套事件名**，而兜底链路
 * 用错了那一套。见下面 _DURABLE_TO_SSE 的注释。
 */
import { BASE_URL } from './client'

/**
 * 持久事件类型 → SSE 线格式名。
 *
 * 后端刻意分了两套词表（core/events.py:20）：落库的是可回放的事实
 * `assistant/message`，推给前端的是活信号 `agent_msg`。`_SSE_TO_DURABLE` 是
 * 后端那一侧的翻译点，但它**只翻一个方向**。
 *
 * 而兜底链路读的是事件日志的行，`row.type` 是斜杠那一套。原来的代码直接
 * `event: ev.type` 往上抛，于是 chat.vue 的 switch 拿到 'assistant/message'
 * —— 一个 case 都不匹配，**整条降级链路一个字都渲染不出来**。
 * 所以这里必须有反向表，它是前端这一侧的翻译点。
 */
const _DURABLE_TO_SSE = {
  'user/message': 'user_msg',
  'assistant/message': 'agent_msg',
  'assistant/final': 'final',
  'tool/call': 'tool_call',
  'tool/result': 'tool_result',
  'todo/write': 'todo',
  'agent/report': 'report',
  'artifact/card': 'card',
  'confirmation/suspended': 'suspended',
  'confirmation/resolved': 'confirmation_resolved',
  'guardian/alert': 'guardian_alert',
}

/**
 * 一条日志行 → 一个 UI 事件；界面用不上的（turn/start、step/end 之类）返回 null。
 * 返回 null 就跳过，而不是抛一个界面不认识的名字上去 —— 后者是原来的做法。
 */
function rowToEvent(row) {
  const name = _DURABLE_TO_SSE[row.type]
  if (!name) return null
  return { event: name, data: row.payload || {}, _row: row }
}

/** 解析一段 SSE 文本缓冲，返回 [事件数组, 剩余缓冲]。 */
function parseChunk(buffer) {
  const events = []
  // 事件块以空行分隔：event: xxx\ndata: {...}
  const blocks = buffer.split(/\r?\n\r?\n/)
  const rest = blocks.pop() || ''
  for (const block of blocks) {
    let event = 'message'
    let data = ''
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data += line.slice(5).trim()
    }
    if (data) {
      try {
        events.push({ event, data: JSON.parse(data) })
      } catch (e) {
        // 非 JSON 数据，原样透传
        events.push({ event, data })
      }
    }
  }
  return [events, rest]
}

/**
 * 流式对话。
 * @param {object} body {user_id, session_id?, text}
 * @param {object} handlers {onEvent(ev), onDone(), onError(err)}
 *   ev = {event: 'delta'|'agent_msg'|'card'|'suspended'|'final'|..., data: {...}}
 */
export async function chatStream(body, handlers) {
  // 首条消息 body.session_id 是 null，但 session 事件会在流的第一帧就把 ID 带回来。
  // 记下它：流中途断掉时，兜底轮询才知道该去查哪个会话（原来只看 body，
  // 于是首条消息一断线就直接判死，而那正是演示时最可能断的一次）。
  let sessionId = body.session_id || null
  try {
    const resp = await fetch(BASE_URL + '/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!resp.ok || !resp.body) throw new Error('SSE 连接失败（' + resp.status + '）')

    const reader = resp.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let gotAny = false
    let ended = false

    while (!ended) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const [events, rest] = parseChunk(buffer)
      buffer = rest
      for (const ev of events) {
        gotAny = true
        if (ev.event === 'session' && ev.data && ev.data.session_id) {
          sessionId = ev.data.session_id
        }
        handlers.onEvent && handlers.onEvent(ev)
        // 收到定稿或错误就收流。原来这里写的是 `onDone && onEvent(ev)`——
        // 判断 onDone 存在、却又调一次 onEvent，等于把 final 派发了两遍，
        // 而 onDone 一次也没调。
        if (ev.event === 'final' || ev.event === 'error') {
          ended = true
          break
        }
      }
    }
    if (!gotAny) throw new Error('SSE 无输出')
    handlers.onDone && handlers.onDone()
  } catch (err) {
    console.warn('SSE 主链路失败，降级轮询：', err.message)
    // 兜底：轮询事件日志。轮询读的是已落库的事实，所以只要后端那一轮跑完了，
    // 结论仍然能补给老人 —— 断的是运输，不是办事。
    try {
      await pollEvents(sessionId, handlers)
    } catch (e2) {
      handlers.onError && handlers.onError(e2)
    }
  }
}

/**
 * 轮询兜底。
 * 两处修正：① 拿到 assistant/final 就收工（原来不管结论有没有来，都要把
 * 60 轮 × 2s 走满 —— 老人已经拿到答复，界面上那个"正在想"还要再转两分钟）；
 * ② 结束时调 onDone（原来一次都不调，调用方的 loading 只能靠超时解除）。
 */
async function pollEvents(sessionId, handlers) {
  if (!sessionId) {
    // 连会话 ID 都没拿到，说明请求根本没落地，日志里也不会有东西可捞
    throw new Error('这一句没有发出去，您再说一遍试试')
  }
  let afterSeq = 0
  let done = false
  // 最多轮询 60 次 × 2s = 2 分钟
  for (let i = 0; i < 60 && !done; i++) {
    const resp = await fetch(
      `${BASE_URL}/api/sessions/${sessionId}/events?after_seq=${afterSeq}`
    )
    if (!resp.ok) throw new Error('轮询失败（' + resp.status + '）')
    const payload = await resp.json()
    for (const row of payload.items || []) {
      afterSeq = Math.max(afterSeq, row.seq || 0)
      const ev = rowToEvent(row)
      if (!ev) continue
      handlers.onEvent && handlers.onEvent(ev)
      if (ev.event === 'final') done = true
    }
    if (!done) await new Promise((r) => setTimeout(r, 2000))
  }
  handlers.onDone && handlers.onDone()
  return done
}

/**
 * 拉取历史事件（重进会话时回放会话流）。
 * 返回的事件名已经是 UI 那一套；界面用不上的行直接滤掉。
 */
export async function fetchEvents(sessionId, afterSeq = 0) {
  const resp = await fetch(
    `${BASE_URL}/api/sessions/${sessionId}/events?after_seq=${afterSeq}`
  )
  if (!resp.ok) throw new Error('事件拉取失败')
  const payload = await resp.json()
  return (payload.items || []).map(rowToEvent).filter(Boolean)
}
