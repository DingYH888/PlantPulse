// 个人中心 API（PRD 5.5 / 9.7 P5 接口清单）
// 统一返回已由 request.js 解包，函数直接返回业务 data
import service from './request'

/**
 * 更新个人资料（昵称 / 头像 URL）
 * @param {Object} data - { nickname?, avatar_url? }
 * @returns {Promise<Object>} 更新后的用户资料
 */
export function updateProfile(data) {
  return service.put('/auth/profile', data)
}

/**
 * 修改密码（校验原密码 + 新密码强度）
 * @param {Object} data - { old_password, new_password }
 * @returns {Promise<Object>}
 */
export function changePassword(data) {
  return service.put('/auth/password', data)
}

/**
 * 个人打卡统计（PRD FR-505）
 * @returns {Promise<{streak_days,month_checkin_count,month_active_days,total_checkin_count,total_active_days,plant_count,type_counts}>}
 */
export function getUserStats() {
  return service.get('/user/stats')
}