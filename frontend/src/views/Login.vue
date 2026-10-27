<script setup>
// 登录/注册页（PRD 5.1）：昵称+密码登录；注册需图形验证码，注册成功自动登录
// 对齐后端：nickname 为唯一登录账号（3-20 位字母数字下划线），单 JWT（PRD 5.1.4）
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { getCaptcha } from '@/api/auth'

const router = useRouter()
const auth = useAuthStore()

// 页面模式：login | register
const mode = ref('login')
const form = ref({
  nickname: '',
  password: '',
  confirmPassword: '',
  code: '', // 图形验证码（4 位数字）
})
const errorMsg = ref('')
const loading = ref(false)

// ---- 密码可见性切换 ----
// 登录/注册共用同一个密码输入框，共用一个开关；确认密码独立一个开关
const showPassword = ref(false)
const showConfirmPassword = ref(false)

// ---- 图形验证码状态 ----
const captchaId = ref('')
const captchaImg = ref('') // data:image/png;base64,...
const captchaLoading = ref(false)

// 拉取图形验证码（后端 5 分钟有效、一次性，失败后需重新获取）
async function loadCaptcha() {
  captchaLoading.value = true
  try {
    const data = await getCaptcha()
    captchaId.value = data.captcha_id
    captchaImg.value = `data:image/png;base64,${data.image_base64}`
    form.value.code = ''
  } catch (err) {
    errorMsg.value = err.message || '验证码获取失败'
  } finally {
    captchaLoading.value = false
  }
}

// 重置表单：清空全部输入与密码可见性，保证切换模式后是全新页面
function resetForm() {
  form.value = { nickname: '', password: '', confirmPassword: '', code: '' }
  showPassword.value = false
  showConfirmPassword.value = false
  errorMsg.value = ''
}

function switchMode(next) {
  if (next === mode.value) return
  mode.value = next
  resetForm()
  // 进入注册模式：重置后重新拉取验证码（旧验证码可能已使用/过期）
  if (next === 'register') {
    loadCaptcha()
  }
}

// 前端预校验：与后端 RegisterIn/LoginIn 规则一致，提示全部使用中文
function validate() {
  const nickname = form.value.nickname.trim()
  const password = form.value.password

  if (!nickname) {
    errorMsg.value = '请输入昵称'
    return false
  }
  if (!/^[a-zA-Z0-9_]{3,20}$/.test(nickname)) {
    errorMsg.value = '昵称需为 3-20 位字母、数字或下划线'
    return false
  }
  if (!password) {
    errorMsg.value = '请输入密码'
    return false
  }
  if (password.length < 8 || !/[a-zA-Z]/.test(password) || !/\d/.test(password)) {
    errorMsg.value = '密码至少 8 位，且必须同时包含字母和数字'
    return false
  }

  if (mode.value === 'register') {
    if (!form.value.confirmPassword) {
      errorMsg.value = '请再次输入密码'
      return false
    }
    if (password !== form.value.confirmPassword) {
      errorMsg.value = '两次输入的密码不一致'
      return false
    }
    if (!/^\d{4}$/.test(form.value.code)) {
      errorMsg.value = '请输入 4 位数字验证码'
      return false
    }
  }
  return true
}

async function handleSubmit() {
  if (!validate()) return
  loading.value = true
  errorMsg.value = ''
  try {
    if (mode.value === 'login') {
      await auth.login(form.value.nickname.trim(), form.value.password)
    } else {
      await auth.register({
        nickname: form.value.nickname.trim(),
        password: form.value.password,
        captcha_id: captchaId.value,
        code: form.value.code,
      })
    }
    router.push('/')
  } catch (error) {
    // request.js 已把后端中文 msg 透出（如「昵称或密码错误」「该昵称已被注册」）
    errorMsg.value = error.message || '操作失败，请重试'
    // 注册失败（验证码错误/过期/昵称重复）时刷新验证码，便于重试
    if (mode.value === 'register') {
      loadCaptcha()
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <h2 class="title">🌿 PlantPulse</h2>
      <p class="subtitle">植株养护智能助手</p>

      <div class="tabs">
        <button :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</button>
        <button :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</button>
      </div>

      <form class="form" @submit.prevent="handleSubmit">
        <input v-model="form.nickname" type="text" placeholder="昵称（3-20位字母数字下划线）" maxlength="20" />

        <!-- 密码：右侧按钮切换明文/密文显示 -->
        <div class="password-row">
          <input
            v-model="form.password"
            :type="showPassword ? 'text' : 'password'"
            placeholder="密码（≥8位，含字母和数字）"
            maxlength="64"
          />
          <button
            type="button"
            class="toggle-eye"
            :aria-label="showPassword ? '隐藏密码' : '显示密码'"
            :title="showPassword ? '隐藏密码' : '显示密码'"
            @click="showPassword = !showPassword"
          >
            <!-- 隐藏态：眼睛带斜线；显示态：睁眼 -->
            <svg v-if="showPassword" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
              <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
              <path d="M1 1l22 22" />
            </svg>
          </button>
        </div>

        <!-- 注册：确认密码 + 图形验证码 -->
        <template v-if="mode === 'register'">
          <div class="password-row">
            <input
              v-model="form.confirmPassword"
              :type="showConfirmPassword ? 'text' : 'password'"
              placeholder="确认密码"
              maxlength="64"
            />
            <button
              type="button"
              class="toggle-eye"
              :aria-label="showConfirmPassword ? '隐藏密码' : '显示密码'"
              :title="showConfirmPassword ? '隐藏密码' : '显示密码'"
              @click="showConfirmPassword = !showConfirmPassword"
            >
              <svg v-if="showConfirmPassword" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
              <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                <path d="M1 1l22 22" />
              </svg>
            </button>
          </div>
          <div class="captcha-row">
            <input v-model="form.code" type="text" placeholder="验证码（4位数字）" maxlength="4" />
            <button type="button" class="captcha-img" :disabled="captchaLoading" @click="loadCaptcha">
              <img v-if="captchaImg" :src="captchaImg" alt="验证码，点击刷新" />
              <span v-else>{{ captchaLoading ? '加载中...' : '获取验证码' }}</span>
            </button>
          </div>
        </template>

        <p v-if="errorMsg" class="error">{{ errorMsg }}</p>

        <button class="submit" type="submit" :disabled="loading">
          {{ loading ? '处理中...' : mode === 'login' ? '登录' : '注册' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(160deg, #e8f5e9, #f1f8e9);
}

.login-card {
  width: 360px;
  padding: 32px 28px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.08);
}

.title {
  text-align: center;
  font-size: 24px;
}

.subtitle {
  text-align: center;
  color: #889488;
  font-size: 13px;
  margin-bottom: 20px;
}

.tabs {
  display: flex;
  margin-bottom: 18px;
  border-bottom: 1px solid #e3e8e0;
}

.tabs button {
  flex: 1;
  padding: 10px 0;
  border: none;
  background: none;
  font-size: 14px;
  color: #7a867a;
  cursor: pointer;
  border-bottom: 2px solid transparent;
}

.tabs button.active {
  color: #3f8f47;
  font-weight: 600;
  border-bottom-color: #3f8f47;
}

.form input {
  width: 100%;
  padding: 10px 12px;
  margin-bottom: 12px;
  border: 1px solid #dde4da;
  border-radius: 8px;
  font-size: 14px;
}

.captcha-row {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.captcha-row input {
  flex: 1;
  margin-bottom: 0;
}

/* 密码输入框：右侧预留图标空间，切换按钮绝对定位在输入框内 */
.password-row {
  position: relative;
  margin-bottom: 12px;
}

.password-row input {
  margin-bottom: 0;
  padding-right: 42px;
}

.toggle-eye {
  position: absolute;
  top: 50%;
  right: 8px;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px;
  border: none;
  background: none;
  color: #879487;
  cursor: pointer;
}

.toggle-eye:hover {
  color: #3f8f47;
}

.captcha-img {
  flex-shrink: 0;
  width: 110px;
  height: 40px;
  border: 1px solid #dde4da;
  border-radius: 8px;
  background: #f2f6f0;
  cursor: pointer;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #7a867a;
}

.captcha-img img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.error {
  color: #d32f2f;
  font-size: 13px;
  margin-bottom: 10px;
}

.submit {
  width: 100%;
  padding: 11px 0;
  border: none;
  border-radius: 8px;
  background: #3f8f47;
  color: #fff;
  font-size: 15px;
  cursor: pointer;
}

.submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>