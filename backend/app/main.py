"""PlantPulse 后端应用入口（PRD 3.1/3.4）。

职责：应用装配——数据库初始化、CORS、全局异常处理、路由注册。
数据层：Tortoise-ORM（backend/app/models，默认连接 MySQL 8）。
启动命令：uvicorn app.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from tortoise import Tortoise

from app import __version__
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.response import register_exception_handlers

settings = get_settings()

# Tortoise 模型模块列表：新增数据模型时在此追加（models 包中导出）
TORTOISE_MODULES = {
    "models": [
        "app.models.user",
        "app.models.captcha",
        "app.models.plant",
        "app.models.plant_record",
        "app.models.plant_metric",
        "app.models.ai_advice",
    ]
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库，关闭时释放连接。

    generate_schemas 仅用于开发环境自动建表；生产环境应使用 Aerich 迁移。

    _enable_global_fallback=True：Tortoise 1.1.x 用 ContextVar 管理连接状态，
    uvicorn 的 lifespan 在后台任务运行，而 HTTP 请求在另一个任务执行，
    若不启用全局回退，请求侧读不到 lifespan 里建立的连接上下文，
    会抛 "No TortoiseContext is currently active"。
    """
    await Tortoise.init(
        db_url=settings.DATABASE_URL,
        modules=TORTOISE_MODULES,
        _enable_global_fallback=True,
    )
    if settings.ENV == "development":
        await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


# 应用实例
app = FastAPI(
    title=settings.APP_NAME,
    description="植株养护 RAG 智能养护 APP 后端服务",
    version=__version__,
    lifespan=lifespan,
)

# CORS：允许前端开发服务器访问（PRD 12 安全）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局异常处理器：保证所有响应统一为 {"code","msg","data"} 格式
register_exception_handlers(app)

# 业务路由统一挂载于 /api/v1 前缀
app.include_router(api_router, prefix="/api/v1")

# 静态资源（打卡/植物/头像图片）：/static 指向上传目录的父级，
# 保证 URL /static/uploads/<file> 能映射到 upload_dir/<file>（少一层会 404）
# StaticFiles 要求目录已存在，挂载前先创建（幂等）
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

r'''
启动后端命令
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000 --reload
前端启动
npm run dev
'''