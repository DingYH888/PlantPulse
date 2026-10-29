<script setup>
// 应用根组件：全局导航栏 + 页面出口
// 未登录时（路由守卫已拦截），仅登录页可见，故导航仅在登录态下渲染
// NMessageProvider：为页面 useMessage() 提供上下文（PRD 交互提示）
// 四个业务页统一使用浅色绿主题，不再为 AI 页单独切换深色顶栏/全宽布局
import { NMessageProvider } from 'naive-ui'
</script>

<template>
  <NMessageProvider>
    <div class="app-shell">
      <header class="app-header">
        <h1 class="logo">🌿 PlantPulse</h1>
        <nav class="nav">
          <RouterLink to="/">植物记录</RouterLink>
          <RouterLink to="/stats">数据统计</RouterLink>
          <RouterLink to="/ai">AI 养护</RouterLink>
          <RouterLink to="/profile">个人中心</RouterLink>
        </nav>
      </header>
      <main class="app-main">
        <RouterView />
      </main>
    </div>
  </NMessageProvider>
</template>

<style>
/* 全局基础样式：简洁、移动端自适应 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background: #f5f7f2;
  color: #2d3a2d;
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 16px;
  padding: 14px 24px;
  background: #ffffff;
  border-bottom: 1px solid #e3e8e0;
}

.logo {
  font-size: 18px;
}

.nav {
  display: flex;
  flex-wrap: wrap;
}

.nav a {
  margin-left: 16px;
  color: #4a5a4a;
  text-decoration: none;
  font-size: 14px;
}

.nav a.router-link-active {
  color: #3f8f47;
  font-weight: 600;
}

.app-main {
  max-width: 960px;
  margin: 0 auto;
  padding: 20px 16px;
}

/* 移动端：导航独占一行并均分，避免 4 个入口与 Logo 挤在同一行溢出 */
@media (max-width: 640px) {
  .app-header {
    padding: 12px 16px;
  }

  .nav {
    width: 100%;
    justify-content: space-between;
  }

  .nav a {
    margin-left: 0;
    font-size: 13px;
  }
}
</style>