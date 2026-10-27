// 路由配置与全局守卫：未登录访问业务页跳转登录页（PRD 5.1）
import { createRouter, createWebHistory } from 'vue-router'
import { getAccessToken } from '@/utils/token'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true }, // 公开页面：无需登录
  },
  {
    path: '/',
    name: 'plants',
    component: () => import('@/views/Plants.vue'),
    meta: { title: '植物记录' },
  },
  {
    path: '/plants/:id',
    name: 'plant-detail',
    component: () => import('@/views/PlantDetail.vue'),
    meta: { title: '植物详情' },
  },
  {
    path: '/stats',
    name: 'stats',
    component: () => import('@/views/Stats.vue'),
    meta: { title: '数据统计' },
  },
  {
    path: '/ai',
    name: 'ai-care',
    component: () => import('@/views/AICare.vue'),
    meta: { title: 'AI 智能养护' },
  },
  {
    path: '/profile',
    name: 'profile',
    component: () => import('@/views/Profile.vue'),
    meta: { title: '个人中心' },
  },
  // 兜底：未匹配路由回到首页
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 全局前置守卫：基于本地 Token 判断登录态（PRD 7.4）
router.beforeEach((to) => {
  const hasToken = !!getAccessToken()
  if (!to.meta.public && !hasToken) {
    return { name: 'login' }
  }
  // 已登录访问登录页 → 跳回首页
  if (to.name === 'login' && hasToken) {
    return { name: 'plants' }
  }
})

export default router