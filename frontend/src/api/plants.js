// 植物模块 API（PRD 9.7 P2 接口清单）
// 统一返回已由 request.js 解包，函数直接返回业务 data
import service from './request'

/**
 * 获取当前用户名下的植物列表（分页/关键词筛选）
 * @param {Object} params - { page, page_size, keyword }
 * @returns {Promise<{items:Array,total:number,page:number,page_size:number}>}
 */
export function getPlants(params) {
  return service.get('/plants', { params })
}
/**
 * 新增植物档案（手动建档）
 * @param {Object} payload - { name, species, location, planted_at, notes }
 * @returns {Promise<Object>} 新建植物信息
 */
export function createPlant(payload) {
  return service.post('/plants', payload)
}