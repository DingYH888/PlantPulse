// 统计模块 API（PRD 9.7 P3 数据图表）
// 统一返回已由 request.js 解包，函数直接返回业务 data
import service from './request'

/**
 * 获取植物统计（长势/浇水/施肥/光照）
 * @param {number} plantId - 植物 ID（必须属于当前用户）
 * @param {Object} params - { dimension: 'growth'|'watering'|'fertilizing'|'light', days: 7|30|90 }
 * @returns {Promise<Object>} { plant, dimension, chart_type, unit, points, summary, has_data, ... }
 */
export function getPlantStats(plantId, params) {
  return service.get(`/plants/${plantId}/stats`, { params })
}