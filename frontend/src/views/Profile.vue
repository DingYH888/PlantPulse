<script setup>
// 个人中心页（PRD 5.5 P5）——骨架：展示用户信息 + 登出
// 待开发：日历打卡、连续天数统计、设置
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

onMounted(async () => {
  if (!auth.user) {
    try {
      await auth.fetchProfile()
    } catch (error) {
      // 资料拉取失败时静默，后续操作会触发 401 处理
    }
  }
})

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="page">
    <h2>个人中心</h2>

    <div v-if="auth.user" class="user-card">
      <p class="name">{{ auth.user.nickname || auth.user.username }}</p>
      <p class="meta">@{{ auth.user.username }} · {{ auth.user.email }}</p>
    </div>

    <p class="placeholder">日历打卡与连续天数统计开发中（PRD 5.5）</p>

    <button class="logout" @click="handleLogout">退出登录</button>
  </div>
</template>

<style scoped>
.user-card {
  padding: 18px;
  background: #fff;
  border-radius: 12px;
  margin-bottom: 16px;
}

.name {
  font-size: 18px;
  font-weight: 600;
}

.meta {
  margin-top: 6px;
  color: #889488;
  font-size: 13px;
}

.placeholder {
  color: #889488;
  text-align: center;
  padding: 60px 0;
  border: 1px dashed #c5cfc2;
  border-radius: 12px;
  margin-bottom: 20px;
}

.logout {
  padding: 10px 28px;
  border: 1px solid #d32f2f;
  background: none;
  color: #d32f2f;
  border-radius: 8px;
  cursor: pointer;
}
</style>