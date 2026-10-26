# PlantPulse 前端（Vue 3 + Vite）

植株养护 RAG 智能养护 APP 的 Web 端，基于 PRD.md 搭建的模块化脚手架。

## 技术栈
- Vue 3 + Vite + Pinia + Vue Router
- Axios（统一返回格式处理 + JWT 自动附加 + 401 自动刷新）
- ECharts（数据图表，P3 模块开发时使用）

## 目录结构
```
frontend/
├── src/
│   ├── main.js            # 应用入口
│   ├── App.vue            # 根组件（导航 + 页面出口）
│   ├── api/request.js     # Axios 统一封装（拦截器/刷新/重放）
│   ├── router/index.js    # 路由 + 登录守卫
│   ├── stores/auth.js     # 认证状态（Pinia）
│   ├── utils/token.js     # Token 本地存储工具
│   └── views/             # 五大页面（Login 已实现，其余占位）
├── vite.config.js         # 开发代理 /api → 后端
├── index.html
└── package.json
```

## 快速开始
```bash
# 1. 安装依赖
npm install

# 2. 配置环境变量（可选，默认 /api）
copy .env.example .env.development

# 3. 启动开发服务器（需后端已启动在 8000 端口）
npm run dev
# 访问 http://localhost:5173

# 4. 构建生产包
npm run build
```

## 接口约定
- 所有请求经 `/api` 前缀，开发环境由 Vite 代理到 `http://localhost:8000`（见 vite.config.js）。
- 响应统一为 `{code, msg, data}`；`code==='200'` 视为成功并自动解包 `data`（PRD 9.3）。
- 401 自动携带 refresh token 刷新并重放原请求，失败跳转登录页。