// 打卡模块 API（PRD 9.7 P5 接口清单，记录页面入口为 P2）
// 统一返回已由 request.js 解包，函数直接返回业务 data
import service from './request'

/**
 * 新增打卡
 * @param {Object} data - { plant_id, care_type, content, record_date, image_urls }
 * @returns {Promise<Object>} 新建的打卡记录
 */
export function createCheckin(data) {
  return service.post('/checkins', data)
}

/**
 * 打卡历史（时间倒序分页）
 * @param {Object} params - { plant_id?, record_date?, page, page_size }
 *   plant_id 可选：不传返回当前用户全部植物记录；
 *   record_date 可选：按日期筛选（历史卡片默认传当天）。
 * @returns {Promise<{items:Array,total:number,page:number,page_size:number}>}
 */
export function getCheckins(params) {
  return service.get('/checkins', { params })
}