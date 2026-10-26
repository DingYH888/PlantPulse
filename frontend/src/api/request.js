// Axios 统一封装：自动附加 Token、统一返回格式解包、401 自动刷新重放
// 约定：后端统一返回 {code, msg, data}，业务成功以 code==='200' 为准（PRD 9.3）
import axios from 'axios'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from '@/utils/token'

const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
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

// ---- 响应拦截器：统一返回处理 + 401 自动刷新 ----
let refreshing = null // 单飞：并发 401 时共享同一次刷新请求，避免重复刷新

async function refreshAccessToken() {
  const refreshToken = getRefreshToken()
  if (!refreshToken) {
    throw new Error('缺少刷新凭证')
  }
  if (!refreshing) {
    // service.post 的响应已被本拦截器解包为 data
    refreshing = service
      .post('/auth/refresh', { refresh_token: refreshToken })
      .catch((error) => {
        clearTokens()
        throw error
      })
      .finally(() => {
        refreshing = null
      })
  }
  const data = await refreshing
  setTokens(data.access_token, data.refresh_token)
}

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
    // 未认证：尝试自动刷新并重放原请求（仅一次）
    if (body.code === '401' && !response.config._retried) {
      response.config._retried = true
      try {
        await refreshAccessToken()
        return service(response.config)
      } catch (error) {
        redirectToLogin()
        return Promise.reject(new Error('登录已过期，请重新登录'))
      }
    }
    // 其他业务错误（400/403/409/429 等）：统一抛出提示
    return Promise.reject(new Error(body.msg || '请求失败'))
  },
  (error) => {
    // HTTP 层错误：401 同样走刷新链路
    if (error.response?.status === 401 && !error.config?._retried) {
      error.config._retried = true
      refreshAccessToken()
        .then(() => service(error.config))
        .catch(() => redirectToLogin())
    }
    return Promise.reject(error)
  }
)

export default service