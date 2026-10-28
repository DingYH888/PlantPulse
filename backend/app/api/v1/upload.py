"""图片上传模块路由（PRD 9.6）。

约定：POST /upload/image，multipart 字段 file，仅支持 jpg/png/webp 且 ≤5MB
（PRD 5.2.3 / 10.2.2）。校验与落盘统一由 app.services.image_storage 负责，
返回可访问 URL：/static/uploads/<uuid>.<ext>。

安全：登录鉴权（CurrentUser）；类型/大小校验与 uuid 文件名由共享服务保证。
"""

from fastapi import APIRouter, UploadFile

from app.core.deps import CurrentUser
from app.core.response import success
from app.services.image_storage import save_upload_image

router = APIRouter()


@router.post("/image")
async def upload_image(file: UploadFile, user: CurrentUser) -> dict:
    """图片上传（登录）：类型/大小校验通过后落地，返回可访问 URL。

    前端调用方式：FormData 携带 file 字段，拿到 url 后随打卡请求一起提交。
    """
    url = await save_upload_image(file)
    return success({"url": url}, "上传成功")