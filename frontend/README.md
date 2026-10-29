# PlantPulse 前端（Vue 3 + Vite + NaiveUI）

植株养护 RAG 智能养护 APP 的 Web 端：登录注册、植物打卡、数据统计、AI 流式问答、个人中心。

## 技术栈

| 层次 | 选型 |
|---|---|
| 框架 | Vue 3.5（组合式 API）+ Vite 5 |
| UI 组件库 | NaiveUI 2.45（全量引入 `app.use(naive)`） |
| 状态 / 路由 | Pinia 2 + Vue Router 4（HTML5 history） |
| 图表 | ECharts 5.5（按需注册 Line / Bar） |
| 请求 | Axios（REST）+ 原生 `fetch` + `ReadableStream`（SSE） |
| 样式 | 各组件 scoped CSS，无预处理器 |

## 目录结构

```text
frontend/
├── src/
│   ├── main.js                  # 应用入口（挂载 Pinia / Router / NaiveUI）
│   ├── App.vue                  # 顶栏导航 + RouterView
│   ├── api/
│   │   ├── request.js           # Axios 封装：统一返回解包、JWT 附加、401 跳转
│   │   ├── ai.js                # AI 接口 + SSE 帧解析
│   │   ├── auth.js / user.js / plants.js / checkins.js / metrics.js / stats.js / upload.js
│   ├── components/ai/
│   │   ├── AdviceCard.vue       # 建议卡片：分节 / 来源 / 降级标注 / 反馈
│   │   └── SessionList.vue      # 会话列表 / 删除确认
│   ├── router/index.js          # 路由表 + 登录守卫
│   ├── stores/auth.js           # 认证状态（单 Token）
│   ├── utils/token.js           # localStorage 读写
│   └── views/
│       ├── Login.vue            # 登录 / 注册（图形验证码）
│       ├── Plants.vue           # 植物记录 + 快捷打卡
│       ├── PlantDetail.vue      # 占位页
│       ├── Stats.vue            # 数据统计 + 指标录入
│       ├── AICare.vue           # AI 会话 + SSE 流式
│       └── Profile.vue          # 个人中心 + 日历打卡
├── vite.config.js               # /api 与 /static 代理
├── index.html
├── package.json
└── .env.example
```

## 页面与路由

| 路由 | 页面 | 说明 |
|---|---|---|
| `/login` | 登录 / 注册 | 公开页；昵称 + 密码，注册需 4 位图形验证码 |
| `/` | 植物记录 | 植物选择、新增植物、打卡表单、历史打卡 |
| `/plants/:id` | 植物详情 | 占位页（`Plants.vue` 点击卡片为弹窗，暂未跳转） |
| `/stats` | 数据统计 | 四维度（长势/浇水/施肥/光照）+ 7/30/90 天 + 指标录入 |
| `/ai` | AI 智能养护 | 聊天式会话、图片上传、SSE 流式、停止生成、历史会话 |
| `/profile` | 个人中心 | 资料/头像/改密、月历打卡、编辑打卡、个人统计 |

导航固定为「植物记录 / 数据统计 / AI 养护 / 个人中心」；未登录访问业务页重定向 `/login`，已登录访问 `/login` 回首页，未匹配路由回首页。

## 快速开始

```bat
cd frontend
copy .env.example .env.development
npm install
npm run dev
```

访问 <http://localhost:5173>，需后端已启动在 `8000` 端口。

```bat
:: 生产构建
npm run build

:: 预览构建产物
npm run preview
```

> 若 `npm install` 因 esbuild 平台二进制失败，先 `npm install --ignore-scripts`，再 `npm rebuild esbuild`。`package.json` 已通过 `overrides` 锁定 `esbuild ^0.25.0`。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `VITE_API_BASE_URL` | `/api/v1` | 后端接口前缀；缺 `/v1` 会 404 |

开发环境由 Vite 代理：

- `/api` → `http://localhost:8000`（超时 130s，避免 AI 生成被代理截断）
- `/static` → `http://localhost:8000`（打卡/植物/头像图片）

## 接口约定

- 所有 REST 请求经 `VITE_API_BASE_URL`，响应统一 `{code, msg, data}`，`code === '200'` 时自动解包 `data`。
- 401 处理：清理本地 Token 并硬跳转 `/login`，**无 refresh token 链路**。
- 其他业务码：优先展示后端中文 `msg`；网络异常提示「网络异常，请确认后端服务已启动」。
- AI 生成使用 **SSE over POST**（`fetch` + `ReadableStream`），因为 `EventSource` 不支持 POST body 与 `Authorization` 头。
- 建流前错误为 HTTP 状态 + 统一结构；建流后错误为 `event: error`。

## AI 页面交互

- **图片**：选择后立即 `POST /upload/image`，拿到 URL 随消息发送；仅 jpg/png/webp，≤5MB。
- **流式渲染**：`stage` 更新进度文案；`delta` 按「【标题】」实时分块；`done` 用完整建议替换为 `AdviceCard`。
- **停止**：`AbortController.abort()`，保留已收正文并标注「已停止生成」，不落库。
- **重试**：失败后展示错误 + 已收正文 + 「重新发送」，不重复插入用户气泡。
- **会话**：「新对话」只清内存记忆；「删除会话」同时删数据库历史（`DELETE /ai/sessions/{id}/history`）。
- **来源**：分节标签显示「知识库 / 通用知识」；参考来源展示标题与相似度百分比。

## 构建与质量

```bat
npm run build
```

- 当前未接入 ESLint / Prettier / Vitest / Playwright / TypeScript，构建通过是唯一质量门禁。
- NaiveUI 全量引入，主包体积约 1.5MB，构建时会有 chunk 体积警告（可接受）。

## 已知限制

- `PlantDetail.vue` 为占位页，无实际入口。
- 前端无自动化测试与静态检查。
- 无全局 404 页面（通配路由回首页）。
- 路由守卫只判断本地是否存在 Token，不预检过期；过期 Token 依赖首个接口 401 触发跳转。
- 移动端断点不统一（640 / 768 / 900），按页面各自适配。

更多业务规则见 `docs/PRD.md`。