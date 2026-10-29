"""图片 URL 处理：把本地静态图片转换为多模态模型可消费的 data URL。

原因：AI 模型在阿里云侧无法访问本机 `http://localhost:8000/static/...`，
直接传本地 URL 会识别失败。统一读取本地文件转 base64 最稳定。
外部公网 URL 原样透传，由模型侧拉取。
"""

import base64
import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.core.config import get_settings

# 与上传接口保持一致：jpg/png/webp，≤5MB（PRD 9.6）
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


class ImageAccessError(ValueError):
    """图片不存在 / 格式不支持 / 超出大小限制。"""


def _resolve_local_path(image_url: str) -> Path | None:
    """把 /static/... 或 http://localhost/static/... 映射到本地文件路径。"""
    settings = get_settings()
    path_value = urlparse(image_url).path if image_url.startswith(("http://", "https://")) else image_url
    if not path_value.startswith("/static/"):
        return None
    relative = unquote(path_value.removeprefix("/static/"))
    candidate = (settings.static_dir / relative).resolve()
    # 防目录穿越：必须位于静态资源目录内
    if settings.static_dir.resolve() not in candidate.parents and candidate != settings.static_dir.resolve():
        raise ImageAccessError("图片路径非法")
    return candidate


def to_model_image_url(image_url: str) -> str:
    """返回可直接传给多模态模型的图片地址（本地图转 data URL）。"""
    if image_url.startswith("data:image/"):
        return image_url

    parsed = urlparse(image_url) if image_url.startswith(("http://", "https://")) else None
    is_remote = parsed is not None and not (
        parsed.hostname in {"localhost", "127.0.0.1", "::1"} or (parsed.hostname or "").startswith("192.168.")
    )
    if is_remote:
        return image_url

    local_path = _resolve_local_path(image_url)
    if local_path is None:
        raise ImageAccessError("仅支持 /static/... 或公网图片地址")

    if not local_path.is_file():
        raise ImageAccessError("图片不存在或已被删除")
    if local_path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ImageAccessError("仅支持 jpg/png/webp 图片")
    if local_path.stat().st_size > MAX_IMAGE_BYTES:
        raise ImageAccessError("图片不能超过 5MB")

    mime = mimetypes.guess_type(local_path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(local_path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"