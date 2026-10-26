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
│   └── services/            # 业务逻辑层（模块开发时填充）
├── sql/schema.sql           # MySQL 建表脚本（含字段 COMMENT）
├── scripts/smoke_tortoise.py# ORM 冒烟验证脚本（本地运行）
├── tests/                   # pytest 单元测试（异步 TestClient）
├── requirements.txt
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

## 接口约定
- 统一前缀：`/api/v1`
- 统一返回：`{"code": "200", "msg": "success", "data": {...}}`（错误码见 PRD 9.3）
- 鉴权：`Authorization: Bearer <access_token>`；公开接口：`register/login/refresh`
- 路由处理器为 `async def`，数据库访问走 Tortoise-ORM 异步查询（`await User.get_or_none(...)` 等）