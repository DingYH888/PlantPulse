// 认证状态管理（Pinia）：登录、注册、资料、登出
import { defineStore } from 'pinia'
import service from '@/api/request'
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from '@/utils/token'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    // 从本地存储恢复登录态，刷新页面不丢失
    accessToken: getAccessToken(),
    refreshToken: getRefreshToken(),
    user: null,
  }),
  getters: {
    isLoggedIn: (state) => !!state.accessToken,
  },
  actions: {
    // 登录：成功后持久化 Token 并拉取资料
    async login(account, password) {
      const data = await service.post('/auth/login', { account, password })
      setTokens(data.access_token, data.refresh_token)
      this.accessToken = data.access_token
      this.refreshToken = data.refresh_token
      await this.fetchProfile()
    },
    // 注册：注册即自动登录
    async register({ username, email, password }) {
      const data = await service.post('/auth/register', { username, email, password })
      setTokens(data.access_token, data.refresh_token)
      this.accessToken = data.access_token
      this.refreshToken = data.refresh_token
      await this.fetchProfile()
    },
    // 拉取当前用户资料
    async fetchProfile() {
      this.user = await service.get('/auth/profile')
      return this.user
    },
    // 登出：清理本地状态（服务端黑名单由后端后续实现）
    logout() {
      clearTokens()
      this.accessToken = ''
      this.refreshToken = ''
      this.user = null
    },
  },
})