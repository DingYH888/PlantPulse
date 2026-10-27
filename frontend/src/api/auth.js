// 认证模块 API（PRD 9.7 P1 接口清单）
// 统一返回已由 request.js 解包，函数直接返回业务 data
import service from './request'

/**
 * 获取图形验证码（注册用）
 * @returns {Promise<{captcha_id:string, image_base64:string}>}
 */
export function getCaptcha() {
  return service.get('/auth/captcha')
}