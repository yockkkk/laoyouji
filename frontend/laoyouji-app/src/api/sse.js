/**
 * SSE 流式对话客户端（带 Bearer Token 与事件日志轮询降级）。
 */
import { BASE_URL } from './client'
import { getAccessToken } from '../store/user'
import { NET_FAILED_TEXT, NOT_SENT_TEXT } from './messages'

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

function rowToEvent(row) {
  let name = _DURABLE_TO_SSE[row.type]
  if (!name) return null
  // 若 assistant/message 包含 tool_calls，说明是中间思考规划，转为 agent_thought 不作为老人消息展示
  if (name === 'agent_msg' && row.payload && Array.isArray(row.payload.tool_calls) && row.payload.tool_calls.length > 0) {
    name = 'agent_thought'
  }
  return { event: name, data: row.payload || {}, _row: row }
}

function parseChunk(buffer) {
  const events = []
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
        events.push({ event, data })
      }
    }
  }
  return [events, rest]
}

export async function chatStream(body, handlers) {
  let sessionId = body.session_id || null
  const token = getAccessToken()
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  try {
    const resp = await fetch(BASE_URL + '/api/chat/stream', {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    })
    // 404 = 这段会话在服务端没了（清过库/换过环境）。接着去轮询同一个死会话是
    // 白等两分钟，所以单独标出来，让调用方换一段新会话重发。
    if (resp.status === 404) {
      const gone = new Error('会话不存在')
      gone.sessionGone = true
      throw gone
    }
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
        if (ev.event === 'final' || ev.event === 'error') {
          ended = true
          break
        }
      }
    }
    if (!gotAny) throw new Error('SSE 无输出')
    handlers.onDone && handlers.onDone()
  } catch (err) {
    if (err.sessionGone) {
      // 交给调用方自愈（另开会话重发）。轮询一个已经不存在的会话没有意义。
      if (handlers.onSessionGone) return handlers.onSessionGone(err)
      handlers.onError && handlers.onError(err)
      return
    }
    console.warn('SSE 主链路失败，降级轮询：', err.message)
    try {
      const reachedFinal = await pollEvents(sessionId, handlers)
      // 轮完 60 轮也没等到 final：以前这里就这么 return 了 —— onDone 在
      // chat.vue 里是个空函数，于是老人盯着"处理中"转两分钟，然后一句话都没有。
      // 没等到结果就得说没等到，不许静悄悄收场。
      if (!reachedFinal) {
        handlers.onError && handlers.onError(new Error(NET_FAILED_TEXT))
      }
    } catch (e2) {
      handlers.onError && handlers.onError(e2)
    }
  }
}

async function pollEvents(sessionId, handlers) {
  if (!sessionId) {
    throw new Error(NOT_SENT_TEXT)
  }
  let afterSeq = 0
  let done = false
  const token = getAccessToken()
  const headers = token ? { Authorization: `Bearer ${token}` } : {}

  for (let i = 0; i < 60 && !done; i++) {
    const resp = await fetch(
      `${BASE_URL}/api/sessions/${sessionId}/events?after_seq=${afterSeq}`,
      { headers }
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

export async function fetchEvents(sessionId, afterSeq = 0) {
  const token = getAccessToken()
  const headers = token ? { Authorization: `Bearer ${token}` } : {}
  const resp = await fetch(
    `${BASE_URL}/api/sessions/${sessionId}/events?after_seq=${afterSeq}`,
    { headers }
  )
  if (!resp.ok) throw new Error('事件拉取失败')
  const payload = await resp.json()
  return (payload.items || []).map(rowToEvent).filter(Boolean)
}
