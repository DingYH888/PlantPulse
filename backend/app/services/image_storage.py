"""图片存储服务（PRD 9.6 / 5.2.3）。

职责：统一"校验 → 落地 → 返回可访问 URL → 清理旧文件"的图片存储逻辑，
供打卡图片与头像上传（POST /upload/image）复用，
避免各处各写一套规则导致口径不一致。

安全约定：
- Content-Type 白名单（jpg/png/webp），≤5MB；
- 文件名使用 uuid 随机生成，杜绝路径穿越、覆盖与中文名乱码；
- URL 与 main.py 的 /static 挂载点同源：/static/<上传目录名>/<文件名>；
- 删除仅允许上传目录内的文件，外部 URL / 路径穿越一律忽略。
"""

import logging
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.response import BizException

logger = logging.getLogger(__name__)

# 允许的图片类型映射：Content-Type → 落地扩展名（PRD 5.2.3）
ALLOWED_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_SIZE = 5 * 1024 * 1024  # ≤5MB


async def save_upload_image(file: UploadFile) -> str:
    """校验并保存上传图片，返回前端可直接引用的 URL。

    校验失败抛 BizException（400 + 中文提示），由全局异常处理器转统一格式。
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
    upload_dir: Path = get_settings().upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    (upload_dir / filename).write_bytes(content)

    # 4. 返回与 /static 挂载点一致的 URL，前端 <img> 可直接加载
    return f"/static/{upload_dir.name}/{filename}"

def delete_upload_image(url: str | None) -> bool:
    """删除上传目录内的图片文件（头像替换后清理旧文件，释放磁盘空间）。

    安全边界：
    - 仅处理 /static/<上传目录名>/ 前缀的本地上传 URL，外部 URL 直接忽略；
    - 只接受纯文件名（拒绝 / \\ .. 等路径片段），并二次校验解析后仍在上传目录内；
    - 文件不存在或删除失败返回 False，不影响主业务流程。
    """
    if not url:
        return False

    upload_dir = get_settings().upload_dir
    prefix = f"/static/{upload_dir.name}/"
    # 兼容前端给图片加的时间戳查询串（?t=xxx），只取纯路径部分
    clean_url = url.split("?", 1)[0].split("#", 1)[0]
    if not clean_url.startswith(prefix):
        return False

    filename = clean_url[len(prefix) :]
    if not filename or filename != Path(filename).name:
        return False

    target = (upload_dir / filename).resolve()
    try:
        target.relative_to(upload_dir.resolve())
    except ValueError:
        return False

    try:
        target.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        logger.warning("删除旧图片失败：%s", target, exc_info=True)
        return False
    return True