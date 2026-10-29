// AI 智能养护 API（PRD 9.7 P4 接口清单）
// 统一返回已由 request.js 解包，函数直接返回业务 data
import service from './request'

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