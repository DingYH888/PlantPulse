import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// Vite 配置：开发代理将 /api 转发到 FastAPI 后端，避免跨域
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // @ 指向 src，简化导入路径
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // 上传的打卡/植物图片也由后端托管（PRD 9.6 静态资源）
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})