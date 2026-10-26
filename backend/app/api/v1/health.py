"""健康检查模块（PRD 12 可用性）。

用于部署探活与启动验证，无需鉴权。
"""

from fastapi import APIRouter

from app import __version__
from app.core.response import success

router = APIRouter()


@router.get("")
async def health_check() -> dict:
    """健康检查：返回服务状态与版本号。"""
    return success({"status": "ok", "app": "PlantPulse", "version": __version__})