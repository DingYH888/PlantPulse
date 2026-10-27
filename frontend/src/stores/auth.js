// 认证状态管理（Pinia）：登录、注册、资料、登出
// 对齐后端单 JWT 方案（PRD 5.1.4）：登录/注册返回 access_token，无 refresh_token
import { defineStore } from 'pinia'
import service from '@/api/request'
import { clearTokens, getAccessToken, setTokens } from '@/utils/token'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    // 从本地存储恢复登录态，刷新页面不丢失
    accessToken: getAccessToken(),
    user: null,
  }),
  getters: {
    isLoggedIn: (state) => !!state.accessToken,
  },
  actions: {
    // 登录：昵称 + 密码，成功后持久化 Token 并拉取资料
    async login(nickname, password) {
      const data = await service.post('/auth/login', { nickname, password })
      setTokens(data.access_token)
      this.accessToken = data.access_token
      await this.fetchProfile()
    },
    // 注册：昵称 + 密码 + 图形验证码，注册即自动登录
    async register({ nickname, password, captcha_id, code }) {
      const data = await service.post('/auth/register', {
        nickname,
        password,
        captcha_id,
        code,
      })
      setTokens(data.access_token)
      this.accessToken = data.access_token
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
      this.user = null
    },
  },
})