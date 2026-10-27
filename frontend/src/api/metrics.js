// 养护指标 API（PRD 5.3 FR-301/FR-302）
// 统一返回已由 request.js 解包，函数直接返回业务 data
import service from './request'

/**
 * 录入指标（同一植物同一天再次录入会覆盖当日记录）
 * @param {number} plantId - 植物 ID
 * @param {Object} data - { temperature, humidity, light, soil_moisture, ph, record_date }
 * @returns {Promise<Object>} 指标记录
 */
export function createMetric(plantId, data) {
  return service.post(`/plants/${plantId}/metrics`, data)
}

/**
 * 指标按天聚合趋势
 * @param {number} plantId - 植物 ID
 * @param {Object} params - { days: 7|30|90 }
 * @returns {Promise<Object>} { days, start_date, end_date, total_records, points }
 */
export function getMetrics(plantId, params) {
  return service.get(`/plants/${plantId}/metrics`, { params })
}