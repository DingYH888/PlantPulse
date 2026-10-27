"""图片上传模块路由（PRD 9.6）。

约定：POST /upload/image，multipart 字段 file，仅支持 jpg/png/webp 且 ≤5MB
（PRD 5.2.3 / 10.2.2）。落地到配置目录后返回可访问 URL：/static/uploads/<uuid>.<ext>。

安全：登录鉴权（CurrentUser）；Content-Type 白名单；大小读入内存校验；文件名
使用 uuid 随机生成，杜绝路径穿越与覆盖攻击。
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile

from app.core.config import get_settings
from app.core.deps import CurrentUser
from app.core.response import BizException, success

router = APIRouter()

# 允许的图片类型映射：Content-Type → 落地扩展名（PRD 5.2.3）
ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_SIZE = 5 * 1024 * 1024  # ≤5MB

settings = get_settings()


@router.post("/image")
async def upload_image(file: UploadFile, user: CurrentUser) -> dict:
    """图片上传（登录）：类型/大小校验通过后落地，返回可访问 URL。

    前端调用方式：FormData 携带 file 字段，拿到 url 后随打卡请求一起提交。
    """
    # 1. 类型校验：Content-Type 白名单（与前端 <input accept> 保持一致）
    ext = ALLOWED_TYPES.get(file.content_type)
    if ext is None:
        raise BizException("400", "仅支持 jpg/png/webp 格式图片", status_code=400)

    # 2. 大小校验：读入内存判断字节数，超限直接拒绝（避免占满磁盘）
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise BizException("400", "图片大小不能超过 5MB", status_code=400)

    # 3. 落地：uuid 文件名防冲突，目录不存在则自动创建
    upload_dir: Path = settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    (upload_dir / filename).write_bytes(content)

    return success({"url": f"/static/uploads/{filename}"}, "上传成功")