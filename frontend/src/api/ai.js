// AI 智能养护 API（PRD 9.7 P4 接口清单）
// 统一返回已由 request.js 解包，函数直接返回业务 data
import service, { API_BASE_URL, redirectToLogin } from './request'
import { getAccessToken } from '@/utils/token'

/**
 * 图像识别：返回候选品种与置信度
 * @param {{image_url: string}} payload
 * @returns {Promise<{species:string,confidence:number,is_known:boolean,source:string,candidates:Array}>}
 */
export function identifyPlant(payload) {
  return service.post('/ai/identify', payload, { timeout: 130000 })
}

/**
 * 生成个性化养护建议（完整 AI-RAG 链路，实测 40~60s）
 * @param {Object} payload - { image_url, question, session_id }
 * 品种不再由前端指定：纯文本由后端从问题中解析，上传图片时以图像识别为准
 * @param {AbortSignal} [signal] - 前端取消诊断
 * @returns {Promise<Object>} 建议详情（含 sections / doc_refs / is_fallback）
 */
export function createCareAdvice(payload, signal) {
  return service.post('/ai/care-advice', payload, { timeout: 130000, signal })
}

/**
 * 解析一帧 SSE（event: xxx / data: {...}）
 * 只处理本项目用到的事件与数据字段，注释帧（以冒号开头）直接忽略。
 */
function parseSseFrame(frame) {
  let type = 'message'
  const dataLines = []
  for (const line of frame.split('\n')) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    if (colon < 0) continue
    const field = line.slice(0, colon)
    const value = line.slice(colon + 1).replace(/^ /, '')
    if (field === 'event') type = value
    else if (field === 'data') dataLines.push(value)
  }
  if (!dataLines.length) return null
  try {
    return { type, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    return null
  }
}

/**
 * 流式生成养护建议（SSE over POST）
 *
 * 为什么不用 EventSource：它只支持 GET，无法携带请求体与 Authorization 头；
 * 本接口需要 POST 提交问题/图片/会话并带 JWT，因此用 fetch + ReadableStream 手工解析 SSE。
 *
 * @param {Object} payload - { image_url, question, session_id }
 * @param {Object} [handlers]
 * @param {AbortSignal} [handlers.signal] - 停止生成
 * @param {(stage: {node:number,label:string}) => void} [handlers.onStage] - 前置节点进度
 * @param {(text: string) => void} [handlers.onDelta] - 正文增量
 * @returns {Promise<Object>} 落库后的完整建议（含 id / sections / doc_refs）
 */
export async function createCareAdviceStream(payload, { signal, onStage, onDelta } = {}) {
  const token = getAccessToken()
  let response
  try {
    response = await fetch(`${API_BASE_URL}/ai/care-advice/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
      signal,
    })
  } catch (error) {
    // 用户主动停止：保留原始 AbortError，交由页面判断
    if (error.name === 'AbortError') throw error
    throw new Error('网络异常，请确认后端服务已启动')
  }

  if (response.status === 401) {
    redirectToLogin()
    throw new Error('登录已过期，请重新登录')
  }
  if (!response.ok) {
    // 建立流之前的业务错误仍是标准 {code,msg,data}，优先用后端中文提示
    let msg = `请求失败（HTTP ${response.status}）`
    try {
      const body = await response.json()
      if (body?.msg) msg = body.msg
    } catch {
      // 响应体不是 JSON 时保留兜底文案
    }
    throw new Error(msg)
  }
  if (!response.body) throw new Error('当前浏览器不支持流式响应，请升级浏览器')

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let advice = null

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      // 兼容代理把行尾改成 \r\n 的情况，否则找 \n\n 会一直找不到帧边界
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let splitIndex
      while ((splitIndex = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0, splitIndex)
        buffer = buffer.slice(splitIndex + 2)
        const event = parseSseFrame(frame)
        if (!event) continue
        if (event.type === 'stage') {
          onStage?.(event.data)
        } else if (event.type === 'delta') {
          onDelta?.(event.data?.text || '')
        } else if (event.type === 'error') {
          throw new Error(event.data?.msg || 'AI 生成失败')
        } else if (event.type === 'done') {
          advice = event.data?.data || null
        }
      }
    }
  } finally {
    reader.releaseLock?.()
  }

  if (!advice) throw new Error('AI 响应中断，请重试')
  return advice
}

/**
 * AI 建议历史（分页）
 * @param {{page?:number,page_size?:number,plant_id?:number}} params
 */
export function getAdvices(params) {
  return service.get('/ai/advices', { params })
}

/** 建议详情（含参考来源与 trace） */
export function getAdviceDetail(id) {
  return service.get(`/ai/advices/${id}`)
}

/**
 * 建议反馈：1 有用 / -1 无用 / 0 中性
 * @param {number} id
 * @param {number} feedback
 */
export function sendAdviceFeedback(id, feedback) {
  return service.post(`/ai/advices/${id}/feedback`, { feedback })
}

/** 清除内存对话记忆（“新对话”） */
export function clearAiSession(sessionId) {
  return service.delete(`/ai/sessions/${encodeURIComponent(sessionId)}`)
}

/**
 * 删除历史会话：同时删除数据库记录与内存记忆
 * @param {string} sessionId
 * @returns {Promise<{session_id:string,deleted:number}>}
 */
export function deleteAiSessionHistory(sessionId) {
  return service.delete(`/ai/sessions/${encodeURIComponent(sessionId)}/history`)
}

/**
 * 聊天式历史会话列表（按 session_id 分组）
 * @param {{page?:number,page_size?:number}} params
 */
export function getAiSessions(params) {
  return service.get('/ai/sessions', { params })
}

/**
 * 某次会话的完整消息流（用户提问 + AI 建议交替）
 * @param {string} sessionId
 */
export function getAiSessionMessages(sessionId) {
  return service.get(`/ai/sessions/${encodeURIComponent(sessionId)}`)
}