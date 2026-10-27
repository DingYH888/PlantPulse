// Token 本地存储工具：统一管理 access token 的读写
// 独立模块避免 api/request.js 与 stores/auth.js 循环依赖
// 方案：单 JWT（PRD 5.1.4），后端无 refresh_token，本地只存 access token

const ACCESS_KEY = 'plantpulse_access_token'

export function getAccessToken() {
  return localStorage.getItem(ACCESS_KEY) || ''
}

export function setTokens(accessToken) {
  localStorage.setItem(ACCESS_KEY, accessToken)
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY)
}