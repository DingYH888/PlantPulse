# PlantPulse 后端（FastAPI + Tortoise-ORM）

植株养护 RAG 智能养护 APP 的服务端：REST 业务接口 + AI-RAG 链式编排 + 本地知识库向量检索。

## 技术栈

| 层次 | 选型 |
|---|---|
| 运行时 | Python 3.13 + FastAPI + Uvicorn |
| ORM / DB | Tortoise-ORM（异步）+ MySQL 8；测试使用 SQLite |
| 鉴权 | PyJWT（单 Token，7 天）+ bcrypt（cost 12） |
| 验证码 | captcha + Pillow（4 位数字，落库 5 分钟一次性） |
| AI 编排 | LangChain 0.3.27（LCEL） |
| 向量检索 | ChromaDB 1.x（本地持久化，cosine） |
| 模型服务 | 阿里云百炼 OpenAI 兼容接口（MaaS 主地址 / dashscope 备用） |
| 响应格式 | `{"code": "200", "msg": "success", "data": {}}` |

## 目录结构

```text
backend/
├── app/
│   ├── main.py                  # 入口：Tortoise 初始化 / CORS / 异常处理 / 静态资源挂载
│   ├── core/
│   │   ├── config.py            # pydantic-settings 配置（数据库/JWT/AI/RAG）
│   │   ├── response.py          # 统一返回与全局异常处理器
│   │   ├── security.py          # JWT 签发/校验、bcrypt 哈希（异步包装）
│   │   ├── deps.py              # get_current_user 依赖注入
│   │   ├── timezone.py          # Asia/Shanghai 自然日工具
│   │   └── db_migrate.py        # 开发环境幂等补列（ai_advice.session_id）
│   ├── models/                  # base + user/captcha/plant/plant_record/plant_metric/ai_advice
│   ├── schemas/                 # auth/plant/checkin/metric/stats/ai/common
│   ├── services/                # captcha/image_storage/plant_stats/checkin_calendar/plant_access
│   ├── api/v1/
│   │   ├── router.py            # v1 路由聚合
│   │   └── health/auth/plants/metrics/stats/checkins/ai/upload/user.py
│   └── ai/
│       ├── chain.py             # LCEL 七步编排（同步 + 流式）
│       ├── prompts.py           # 视觉 / 同步生成 / 流式生成提示词
│       ├── schemas.py           # 分节结构与来源校验
│       ├── question_parser.py   # 节点0 问题解析、节点2.5 植物定位
│       ├── species_aliases.py   # 品种别名归一化
│       ├── retriever.py         # 阈值过滤 + 通用知识回退
│       ├── vector_store.py      # ChromaDB 集合管理
│       ├── ingestion.py         # 加载→切分→入库（按 source 幂等）
│       ├── loaders.py / splitter.py / image_utils.py / json_utils.py
│       ├── context.py           # 节点4 打卡与指标摘要
│       ├── memory.py            # 进程内多轮记忆
│       ├── rate_limit.py        # AI 接口进程内限流
│       ├── fallback.py          # 通用知识兜底
│       └── advice_service.py    # 建议落库/历史/会话/反馈
├── sql/
│   ├── schema.sql               # MySQL 建表脚本
│   └── migrate_ai_session.sql   # 老库补 session_id
├── scripts/                     # 入库、冒烟、调参、静态校验
├── tests/                       # 9 个文件 / 124 个用例
├── requirements.txt             # 基础依赖
├── requirements-ai.txt          # AI 依赖（LangChain 0.3 锁定）
├── pytest.ini                   # asyncio_mode=auto
└── .env.example
```

## 数据模型

| 表 | 说明 | 隔离键 |
|---|---|---|
| `users` | 账号（nickname 唯一登录，password_hash 存 bcrypt） | — |
| `captcha_codes` | 注册图形验证码（一次性、5 分钟有效） | — |
| `plants` | 植物档案 | `user_id` |
| `plant_record` | 打卡/养护记录（`record_type` 六值枚举） | `user_id` + `plant_id` |
| `plant_metric` | 五维指标 | `user_id` + `plant_id` |
| `ai_advice` | AI 建议（`content`/`doc_refs`/`trace` JSON） | `user_id` + `plant_id` |

关键约定：

- 所有业务表含 `id / created_at / updated_at`，外键 `on_delete=CASCADE`。
- `plant_record.image_url` 存**多图 JSON 数组字符串**；接口入参 `image_urls[]`、出参 `images[]`。
- 同植物同类型同日**允许重复打卡**，无唯一约束；`(user_id, plant_id, record_type, record_date)` 仅为普通复合索引。
- 指标同日唯一由接口层「查当天最后一条→整条覆盖」实现，表上无唯一约束。
- 自然日统计统一按 `Asia/Shanghai` 计算。

## 快速开始

```bat
:: 1. 在项目根创建虚拟环境（整个仓库共用一个 .venv）
python -m venv .venv
.venv\Scripts\activate

:: 2. 安装依赖
pip install -r backend\requirements.txt
pip install -r backend\requirements-ai.txt

:: 3. 配置环境变量（.env 必须位于 backend 目录）
copy backend\.env.example backend\.env
```

首次初始化数据库：

```bat
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS plantpulse DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql -u root -p < backend\sql\schema.sql
```

> 开发环境（`ENV=development`）启动时会执行 `Tortoise.generate_schemas()` 自动建表，只需先创建数据库即可。
> `schema.sql` 末尾的索引调整语句在全新库上可能报「索引不存在」，可先注释末尾两行，或直接依赖自动建表。

启动服务：

```bat
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/v1/health>
- 静态图片：<http://localhost:8000/static/uploads/{filename}>

## 环境变量

完整模板见 `.env.example`，关键项：

| 变量 | 说明 |
|---|---|
| `ENV` | `development` 时自动建表 + 补列 |
| `DATABASE_URL` | MySQL 连接串；可切 `sqlite://./db.sqlite3` |
| `JWT_SECRET` / `ACCESS_TOKEN_EXPIRE_DAYS` | 签名密钥 / 有效期（默认 7 天） |
| `CAPTCHA_EXPIRE_MINUTES` | 验证码有效期（默认 5） |
| `LLM_API_KEY` / `EMBEDDING_API_KEY` | 两份独立密钥 |
| `LLM_BASE_URL` / `EMBEDDING_BASE_URL` | MaaS 专属地址；`AI_USE_FALLBACK_BASE_URL=true` 切 dashscope |
| `KNOWLEDGE_DIR` / `CHROMA_DIR` / `CHROMA_COLLECTION` | 知识库目录 / 向量库目录 / 集合名 |
| `RAG_TOP_K` / `RAG_SCORE_THRESHOLD` | 检索条数与阈值（`.env.example` 预置 3 / 0.55） |
| `AI_TIMEOUT_SECONDS` | 链路超时（预置 120，MaaS 生成约 40~60s） |
| `AI_MEMORY_MAX_TURNS` / `AI_RATE_LIMIT_PER_MINUTE` | 会话记忆轮数 / 每用户每分钟限流 |

## AI 模块

### 依赖与版本

AI 依赖单独放在 `requirements-ai.txt`，锁定 LangChain **0.3 稳定线**（不使用 1.x / beta）：

- `langchain==0.3.27` / `langchain-openai==0.3.28` / `langchain-chroma==0.2.4`
- `chromadb` 锁 1.x 主版本（保留补丁浮动，兼容 Windows + Python 3.13 wheel）
- LLM 与 Embedding 使用**独立 API Key、独立 Base URL**

### 知识库入库

文档放在项目根 `docs/knowledge_base/`（规范见该目录 `README.md`）：

```bat
cd backend

:: 全量重建（首次或结构大改）
..\.venv\Scripts\python.exe -m scripts.ingest_knowledge --rebuild

:: 增量入库（按 source 幂等覆盖）
..\.venv\Scripts\python.exe -m scripts.ingest_knowledge
```

向量库持久化在 `backend/chroma_db/`，重启不丢失。

### 自测与调参

```bat
cd backend
..\.venv\Scripts\python.exe -m scripts.smoke_ai --query "绿萝叶子发黄怎么办" --species 绿萝
..\.venv\Scripts\python.exe -m scripts.tune_rag --query "绿萝叶子发黄" --species 绿萝
..\.venv\Scripts\python.exe -m pytest tests/test_ai.py tests/test_ai_stream.py -v
```

### AI 接口（10 个）

| 方法/路径 | 说明 | 鉴权 |
|---|---|---|
| POST `/api/v1/ai/identify` | 图像识别（品种 + 置信度） | 登录 + 限流 |
| POST `/api/v1/ai/care-advice` | 同步生成建议（兼容脚本与测试） | 登录 + 限流 |
| POST `/api/v1/ai/care-advice/stream` | SSE 流式生成建议 | 登录 + 限流 |
| GET `/api/v1/ai/advices` | 建议历史（分页 / 植物 / 会话） | 登录·本人 |
| GET `/api/v1/ai/advices/{id}` | 建议详情（含 `trace`） | 登录·本人 |
| POST `/api/v1/ai/advices/{id}/feedback` | 反馈 1 / -1 / 0 | 登录·本人 |
| GET `/api/v1/ai/sessions` | 会话列表（按 `session_id` 分组） | 登录·本人 |
| GET `/api/v1/ai/sessions/{id}` | 会话消息流 | 登录·本人 |
| DELETE `/api/v1/ai/sessions/{id}` | 清除内存记忆（不删库） | 登录·本人 |
| DELETE `/api/v1/ai/sessions/{id}/history` | 删除数据库历史 + 记忆 | 登录·本人 |

> `session_id` 列在开发环境启动时自动补齐；生产或权限不足时手工执行 `backend/sql/migrate_ai_session.sql`。

### 流式协议

响应 `text/event-stream`，事件类型：

| 事件 | data | 说明 |
|---|---|---|
| `stage` | `{"node": 3, "label": "正在检索养护知识库"}` | 前置节点完成即推送 |
| `delta` | `{"text": "【浇水】表土干燥后浇透。"}` | 节点 5 逐 token 正文 |
| `done` | `{"code":"200","msg":"success","data": 建议详情}` | 落库后的完整结果 |
| `error` | `{"code":"400/500/503/504","msg":"..."}` | 建流后的错误 |
| `: ping` | — | 每 10s 心跳注释帧 |

建流前完成鉴权、限流、参数校验与植物归属校验，错误仍为标准 HTTP 状态 + 统一结构。

### 关键约束

- **七步链路**：问题解析 → 图像识别 → 品种归一化 → 植物定位 → 知识检索（阈值 + 通用回退）→ 打卡摘要 → LLM 生成。
- **防幻觉**：同步链路分节 `doc_ids` 必须是本轮真实检索文档；流式链路模型不接触 `doc_id`，由服务端按主题关键词绑定，最多 2 个来源。
- **降级**：检索无命中或 LLM 异常时 `is_fallback=true`，前端显示「通用知识」；仅图像识别服务不可用返回 503。
- **多轮记忆**：`ConversationBufferMemory` 按 `user_id + session_id` 隔离，10 轮 / 1 小时 TTL / 500 会话上限，仅存进程内存，重启失效。
- **限流**：识别与生成接口按用户 5 次/分钟（进程内滑动窗口），历史查询不限流。
- **落库**：仅成功完成的建议写入 `ai_advice`；用户停止生成不落库、不写记忆。

## 接口约定

- 统一前缀：`/api/v1`
- 统一返回：`{"code": "200", "msg": "success", "data": {...}}`（错误码见 `docs/PRD.md` 9.3）
- 鉴权：`Authorization: Bearer <access_token>`
- 公开接口：`GET /health`、`GET /auth/captcha`、`POST /auth/register`、`POST /auth/login`
- 单 Token 方案：无 refresh 接口；401 后前端清理 Token 并跳转登录
- 路由处理器为 `async def`，数据库访问走 Tortoise-ORM 异步查询；bcrypt、图片读写、验证码渲染等同步操作通过 `asyncio.to_thread` 卸载

## 测试

```bat
cd backend
..\.venv\Scripts\python.exe -m pytest -v
```

9 个文件 124 个用例，覆盖认证、植物、打卡与上传、指标与统计、个人中心、AI 同步链路、SSE 流式、问题解析。测试使用独立临时 SQLite，不触碰开发库；AI 链路在单测中 mock，不真实外呼。

## 脚本

| 脚本 | 用途 |
|---|---|
| `scripts/ingest_knowledge.py` | 知识库增量/全量入库 |
| `scripts/smoke_ai.py` | AI 链路冒烟（Embedding、检索、生成、记忆） |
| `scripts/tune_rag.py` | 扫描 top_k 与阈值调参 |
| `scripts/verify_api_paths.py` | 前后端接口路径一致性校验 |
| `scripts/verify_*_static.py` | 沙箱静态校验（路由/Schema/纯函数） |
| `scripts/smoke_tortoise.py` | ORM 冒烟（**已知过期**：仍按 5 表与打卡唯一约束断言） |

## 已知限制

- 植物仅支持新增与列表，编辑/删除/图片更换未实现。
- `plants.status` 无派生逻辑，固定 `healthy`。
- AI 限流与会话记忆为进程内状态，多 worker 下不共享。
- 统一返回格式未覆盖未匹配路由（404/405）。
- `scripts/smoke_tortoise.py` 与 `schema.sql` 存在过期断言/不可重复执行问题。

详见 `docs/PRD.md` 第 15 章。