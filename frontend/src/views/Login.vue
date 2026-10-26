<script setup>
// 登录/注册页（PRD 5.1）：支持账号密码登录与注册，注册成功自动登录
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

// 页面模式：login | register
const mode = ref('login')
const form = ref({
  username: '',
  email: '',
  account: '',
  password: '',
  confirmPassword: '',
})
const errorMsg = ref('')
const loading = ref(false)

function switchMode(next) {
  mode.value = next
  errorMsg.value = ''
}

function validate() {
  if (mode.value === 'register') {
    if (!form.value.username || !form.value.email || !form.value.password) {
      errorMsg.value = '请填写完整注册信息'
      return false
    }
    if (form.value.password !== form.value.confirmPassword) {
      errorMsg.value = '两次输入的密码不一致'
      return false
    }
  } else if (!form.value.account || !form.value.password) {
    errorMsg.value = '请输入账号和密码'
    return false
  }
  return true
}

async function handleSubmit() {
  if (!validate()) return
  loading.value = true
  errorMsg.value = ''
  try {
    if (mode.value === 'login') {
      await auth.login(form.value.account, form.value.password)
    } else {
      await auth.register({
        username: form.value.username,
        email: form.value.email,
        password: form.value.password,
      })
    }
    router.push('/')
  } catch (error) {
    errorMsg.value = error.message || '操作失败，请重试'
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
        <!-- 注册：用户名 / 邮箱 -->
        <template v-if="mode === 'register'">
          <input v-model="form.username" type="text" placeholder="用户名（3-20位字母数字下划线）" />
          <input v-model="form.email" type="email" placeholder="邮箱" />
        </template>
        <!-- 登录：账号（用户名或邮箱） -->
        <template v-else>
          <input v-model="form.account" type="text" placeholder="用户名或邮箱" />
        </template>

        <input v-model="form.password" type="password" placeholder="密码（≥8位，含字母和数字）" />
        <input
          v-if="mode === 'register'"
          v-model="form.confirmPassword"
          type="password"
          placeholder="确认密码"
        />

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