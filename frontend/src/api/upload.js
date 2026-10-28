// 图片上传 API（PRD 9.6）
// 统一返回已由 request.js 解包，函数直接返回业务 data
import service from './request'

/**
 * 上传单张图片（jpg/png/webp，≤5MB），返回可访问 URL
 * @param {File} file - 原始图片文件
 * @returns {Promise<string>} 图片 URL（如 /static/uploads/xxx.png）
 */
export async function uploadImage(file) {
  const formData = new FormData()
  formData.append('file', file)
  // 不手动设置 Content-Type：交由浏览器自动附带 multipart boundary
  const data = await service.post('/upload/image', formData)
  return data.url
}
/**
 * 上传并更新头像（原子接口）
 * 服务端一次请求内完成「落盘 → 落库 → 删除旧头像」；
 * 落库失败会自动回滚新文件，不会留下孤儿文件。
 * @param {File} file - 原始图片文件
 * @returns {Promise<Object>} 更新后的用户资料（含 avatar_url）
 */
export async function uploadAvatar(file) {
  const formData = new FormData()
  formData.append('file', file)
  return service.put('/auth/avatar', formData)
}