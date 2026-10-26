"""图片上传模块路由（PRD 9.6）——占位。

约定：POST /upload/image，multipart 字段 file，jpg/png/webp ≤5MB。
"""

from fastapi import APIRouter

router = APIRouter()