"""API v1 路由聚合入口。

新增业务模块时：创建模块路由文件 → 在此 include_router（PRD 9.7 接口清单）。
"""

from fastapi import APIRouter

from app.api.v1 import ai, auth, checkins, health, metrics, plants, stats, upload, user

api_router = APIRouter()

# 基础设施
api_router.include_router(health.router, prefix="/health", tags=["health"])

# 认证模块（P1）
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])

# 业务模块（脚手架阶段仅注册空路由容器，接口随模块开发填充）
api_router.include_router(plants.router, prefix="/plants", tags=["plants"])
api_router.include_router(metrics.router, prefix="/plants", tags=["metrics"])
api_router.include_router(stats.router, prefix="/plants", tags=["stats"])
api_router.include_router(checkins.router, prefix="/checkins", tags=["checkins"])
api_router.include_router(ai.router, prefix="/ai", tags=["ai"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])
api_router.include_router(user.router, prefix="/user", tags=["user"])