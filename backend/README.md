# PlantPulse 后端（FastAPI + Tortoise-ORM）

植株养护 RAG 智能养护 APP 的服务端，基于 PRD.md 搭建的模块化脚手架。

## 技术栈
- Python 3.13 + FastAPI + Uvicorn
- **Tortoise-ORM（异步）** + MySQL 8（测试/开发调试可切 SQLite）
- PyJWT（全局 JWT 鉴权）+ bcrypt（密码哈希，只存哈希不存明文）
- 统一返回格式：`{"code": "200", "msg": "success", "data": {}}`

## 目录结构
```
backend/
├── app/
│   ├── main.py              # FastAPI 入口：Tortoise 初始化/CORS/异常处理/开发建表
│   ├── core/                # 全局基础设施
│   │   ├── config.py        # 环境配置（pydantic-settings，含数据库连接串）
│   │   ├── response.py      # 统一返回格式与全局异常处理器
│   │   ├── security.py      # JWT 签发/校验、密码哈希
│   │   └── deps.py          # 依赖注入：get_current_user（鉴权，异步）
│   ├── models/              # Tortoise-ORM 模型（user/plant/plant_record/metric/advice）
│   ├── api/v1/              # 业务路由（模块化，异步 handler）
│   │   ├── router.py        # v1 路由聚合入口
│   │   ├── health.py        # 健康检查
│   │   ├── auth.py          # 注册/登录/刷新/资料
│   │   └── ...              # plants/metrics/checkins/ai/upload（模块开发时填充）
│   ├── schemas/             # Pydantic 请求/响应模型
│   ├── services/            # 业务逻辑层（模块开发时填充）
│   └── ai/                  # AI-RAG 模块（LangChain 五节点编排）
│       ├── llm.py           # LLM / Embedding 工厂（百炼 OpenAI 兼容）
│       ├── prompts.py       # 防幻觉提示词
│       ├── schemas.py       # 结构化输出与来源校验
│       ├── loaders.py       # md/txt/pdf/docx 加载 + frontmatter
│       ├── splitter.py      # 中文友好切分
│       ├── vector_store.py  # ChromaDB 持久化
│       ├── ingestion.py     # 加载→切分→入库（幂等）
│       ├── retriever.py     # 阈值过滤 + 通用知识降级
│       ├── context.py       # 打卡/指标摘要（节点4）
│       ├── memory.py        # ConversationBufferMemory 多轮记忆
│       ├── chain.py         # LCEL 五节点编排
│       └── advice_service.py# 建议落库/历史/反馈
├── chroma_db/               # 向量库持久化（git 忽略）
├── sql/schema.sql           # MySQL 建表脚本（含字段 COMMENT）
├── scripts/
│   ├── smoke_tortoise.py    # ORM 冒烟验证脚本（本地运行）
│   ├── ingest_knowledge.py  # 知识库入库
│   ├── smoke_ai.py          # AI 链路冒烟自测
│   └── tune_rag.py          # RAG 检索调参
├── tests/                   # pytest 单元测试（异步 TestClient）
├── requirements.txt
├── requirements-ai.txt      # AI 依赖（LangChain 0.3 稳定线，锁定版本）
└── .env.example
```

## 数据模型（PRD 13）
| 表 | 说明 | 隔离键 |
|---|---|---|
| users | 用户账号（password_hash 存 bcrypt 哈希） | — |
| plants | 植物档案 | user_id |
| plant_record | 养护/打卡记录（record_type 枚举：watering/fertilizing/pruning/repotting/pest_control/other） | user_id |
| plant_metric | 养护指标 | user_id |
| ai_advice | AI 建议（is_fallback/doc_refs/trace 防幻觉） | user_id |

所有表均含 created_at/updated_at；`plant_record` 唯一约束 `(user_id, plant_id, record_type, record_date)` 防重复打卡。

## 快速开始
```bash
# 1. 创建虚拟环境（Windows）
python -m venv .venv
.venv\Scripts\activate

# 2. 安装依赖（含 Tortoise-ORM + aiomysql）
pip install -r requirements.txt

# 3. 配置环境变量（MySQL 连接串，本地账号 root/123456 已在 .env.example 预填）
copy .env.example .env

# 4. 初始化数据库（建库 + 建表，需本机已装 MySQL）
mysql -u root -p < sql/schema.sql

# 5. 启动服务（开发环境自动建表，热重载）
uvicorn app.main:app --reload --port 8000

# 6. 运行单元测试（独立 SQLite 测试库，不影响开发库）
pytest -v

# 7.（可选）ORM 冒烟验证
python -m scripts.smoke_tortoise
```

## AI 模块（PRD 5.4 / 第 8 章）

### 依赖与版本
AI 依赖单独放在 `requirements-ai.txt`，锁定 LangChain **0.3 稳定线**（不使用 1.x / beta）：

```bash
.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

- `langchain==0.3.27` / `langchain-openai==0.3.28` / `langchain-chroma==0.2.4`
- `chromadb` 锁 1.x 主版本（保留补丁浮动，兼容 Windows + Python 3.13 的 wheel）
- LLM 与 Embedding 使用**独立 API Key、独立 OpenAI 兼容地址**，见 `.env.example`

### 知识库入库
文档放在项目根 `docs/knowledge_base/`（规范见该目录 README.md）：

```bash
# 增量入库（新增/修改文件自动覆盖旧向量）
.venv\Scripts\python.exe -m scripts.ingest_knowledge
# 全量重建（知识库结构大改时）
.venv\Scripts\python.exe -m scripts.ingest_knowledge --rebuild
```

向量库持久化在 `backend/chroma_db/`，重启不丢失。

### 自测与调参（需本地网络）
```bash
.venv\Scripts\python.exe -m scripts.smoke_ai --query "绿萝叶子发黄怎么办" --species 绿萝
.venv\Scripts\python.exe -m scripts.tune_rag --query "绿萝叶子发黄" --species 绿萝
.venv\Scripts\python.exe -m pytest tests/test_ai.py -v
```

### AI 接口
| 方法/路径 | 说明 |
|---|---|
| POST /api/v1/ai/identify | 图像识别（品种 + 置信度） |
| POST /api/v1/ai/care-advice | 完整 AI-RAG 生成建议（同步，超时 120s → 504） |
| GET /api/v1/ai/sessions | 聊天式会话列表（按 session_id 分组） |
| GET /api/v1/ai/sessions/{id} | 会话完整消息流（用户提问 + AI 建议交替） |
| GET /api/v1/ai/advices | 建议历史（分页，可按 session_id 过滤） |
| GET /api/v1/ai/advices/{id} | 建议详情（含来源 + trace） |
| POST /api/v1/ai/advices/{id}/feedback | 有用/无用反馈 |
| DELETE /api/v1/ai/sessions/{id} | 清除内存对话记忆（不删除数据库历史） |

> 会话改造需要 `ai_advice.session_id` 列：开发环境启动时自动迁移；生产/权限不足时手工执行
> `backend/sql/migrate_ai_session.sql`。

### 关键约束
- 五节点固定链路：识别 → 归一化 → 检索（阈值 0.45，无命中回退通用知识）→ 打卡摘要 → LLM 生成；
- 防幻觉：每条分节必须带 `doc_ids`（knowledge）或 `source_type=general`，来源非法即服务端改写/重试；
- 降级：检索无命中或 LLM 异常时 `is_fallback=true`，前端显示“通用知识”；
- 多轮记忆：`ConversationBufferMemory` 按 `user_id + session_id` 隔离，只存进程内存，不写向量库/数据库。

## 接口约定
- 统一前缀：`/api/v1`
- 统一返回：`{"code": "200", "msg": "success", "data": {...}}`（错误码见 PRD 9.3）
- 鉴权：`Authorization: Bearer <access_token>`；公开接口：`register/login/refresh`
- 路由处理器为 `async def`，数据库访问走 Tortoise-ORM 异步查询（`await User.get_or_none(...)` 等）