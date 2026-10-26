# PlantPulse 后端（FastAPI）

植株养护 RAG 智能养护 APP 的服务端，基于 PRD.md 搭建的模块化脚手架。

## 技术栈
- Python 3.13 + FastAPI + Uvicorn
- Tortoise-ORM（SQLite 开发 / MySQL 生产）
- PyJWT（全局 JWT 鉴权）+ bcrypt（密码哈希）
- 统一返回格式：`{"code": "200", "msg": "success", "data": {}}`

## 目录结构
```
backend/
├── app/
│   ├── main.py              # FastAPI 入口：CORS/异常处理器/路由注册/数据库初始化
│   ├── core/                # 全局基础设施
│   │   ├── config.py        # 环境配置（pydantic-settings）
│   │   ├── response.py      # 统一返回格式与全局异常处理器
│   │   ├── security.py      # JWT 签发/校验、密码哈希
│   │   └── deps.py          # 依赖注入：get_current_user（鉴权）
│   ├── api/v1/              # 业务路由（模块化）
│   │   ├── router.py        # v1 路由聚合入口
│   │   ├── health.py        # 健康检查
│   │   ├── auth.py          # 注册/登录/刷新/资料
│   │   └── ...              # plants/metrics/checkins/ai/upload（模块开发时填充）
│   ├── models/              # Tortoise-ORM 模型
│   ├── schemas/             # Pydantic 请求/响应模型
│   └── services/            # 业务逻辑层（模块开发时填充）
├── tests/                   # pytest 单元测试
├── requirements.txt
└── .env.example
```

## 快速开始
```bash
# 1. 创建虚拟环境（Windows）
python -m venv .venv
.venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
copy .env.example .env

# 4. 启动服务（热重载）
uvicorn app.main:app --reload --port 8000

# 5. 运行单元测试
pytest -v
```

## 接口约定
- 统一前缀：`/api/v1`
- 统一返回：`{"code": "200", "msg": "success", "data": {...}}`（错误码见 PRD 9.3）
- 鉴权：`Authorization: Bearer <access_token>`；公开接口：`register/login/refresh`