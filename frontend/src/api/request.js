// Axios 统一封装：自动附加 Token、统一返回格式解包、401 跳登录
// 约定：后端统一返回 {code, msg, data}，业务成功以 code==='200' 为准（PRD 9.3）
// 方案：单 JWT（7 天有效），过期即 401 → 清理本地 Token 并跳转登录页
import axios from 'axios'
import { clearTokens, getAccessToken } from '@/utils/token'

const service = axios.create({
  // 后端接口统一挂在 /api/v1 前缀下（PRD 9.7），缺 /v1 会 404
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000, // AI 生成类接口耗时较长，放宽至 30s
})

// ---- 请求拦截器：附加 Bearer Token ----
service.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// ---- 响应拦截器：统一返回处理 + 401 清理登录态 ----
function redirectToLogin() {
  clearTokens()
  if (!window.location.pathname.startsWith('/login')) {
    window.location.href = '/login'
  }
}

service.interceptors.response.use(
  async (response) => {
    const body = response.data
    // 业务成功：解包返回 data，调用方直接拿到业务数据
    if (body.code === '200') {
      return body.data
    }
    // 未认证/过期：清理本地凭证并跳转登录页
    if (body.code === '401') {
      redirectToLogin()
      return Promise.reject(new Error(body.msg || '登录已过期，请重新登录'))
    }
    // 其他业务错误（400/403/409/429 等）：统一抛出提示
    return Promise.reject(new Error(body.msg || '请求失败'))
  },
  (error) => {
    const status = error.response?.status
    // HTTP 层 401：清理本地凭证并跳转登录页
    if (status === 401) {
      redirectToLogin()
    }
    // 后端业务错误体为 {code, msg, data}：优先展示中文提示（如「昵称或密码错误」）
    const body = error.response?.data
    if (body && typeof body.msg === 'string' && body.msg) {
      return Promise.reject(new Error(body.msg))
    }
    // 无响应体：通常是后端未启动 / 网络中断
    if (!error.response) {
      return Promise.reject(new Error('网络异常，请确认后端服务已启动'))
    }
    // 兜底：避免直接暴露 "Request failed with status code xxx"
    return Promise.reject(new Error(`请求失败（HTTP ${status}）`))
  }
)

export default service