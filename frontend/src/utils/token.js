// Token 本地存储工具：统一管理 access/refresh token 的读写
// 独立模块避免 api/request.js 与 stores/auth.js 循环依赖

const ACCESS_KEY = 'plantpulse_access_token'
const REFRESH_KEY = 'plantpulse_refresh_token'

export function getAccessToken() {
  return localStorage.getItem(ACCESS_KEY) || ''
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY) || ''
}

export function setTokens(accessToken, refreshToken) {
  localStorage.setItem(ACCESS_KEY, accessToken)
  localStorage.setItem(REFRESH_KEY, refreshToken)
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}