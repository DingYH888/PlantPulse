"""图形验证码服务：生成（画图 + 落库）与校验（一次性 + 5 分钟过期）。

职责分离：图片渲染（captcha 库）与验证码状态管理（CaptchaCode 表）都收敛于此，
路由层只负责参数校验与统一返回格式，不感知验证码实现细节。
"""

import base64
import io
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from captcha.image import ImageCaptcha

from app.core.config import get_settings
from app.core.response import BizException
from app.models.captcha import CaptchaCode


def _now() -> datetime:
    """当前 UTC 时间（naive，不带时区）。

    Tortoise 序列化 aware datetime 时会调用 zoneinfo 重建时区，而 Windows
    无 IANA 时区数据库（未装 tzdata 时）会抛 ZoneInfoNotFoundError，
    因此统一使用 naive UTC 落库与比较。
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _normalize(dt: datetime) -> datetime:
    """把读回的时间归一为 naive UTC 再比较（防御 Tortoise 返回 aware 的情况）。"""
    if dt.tzinfo is not None:
        return dt.astimezone(UTC).replace(tzinfo=None)
    return dt


async def generate_captcha() -> dict:
    """生成图形验证码。

    返回 {"captcha_id": uuid, "image_base64": png 的 base64 字符串}；
    明文 code 与过期时间只落库，不回传前端（防止接口泄漏验证码）。
    """
    # 1. 顺带清理已过期 / 已使用的旧记录，防止表无限膨胀
    await CaptchaCode.filter(expires_at__lt=_now()).delete()
    await CaptchaCode.filter(is_used=True).delete()

    # 2. 生成 4 位数字验证码（用 secrets 保证随机性，杜绝 predictable 攻击）
    code = f"{secrets.randbelow(10000):04d}"
    captcha_id = uuid.uuid4().hex

    # 3. 渲染图形并转 base64（前端直接 <img src="data:image/png;base64,..."> 展示）
    image = ImageCaptcha(width=160, height=60)
    buffer = io.BytesIO()
    image.write(code, buffer)
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode("utf-8")

    # 4. 落库：5 分钟有效期
    settings = get_settings()
    await CaptchaCode.create(
        captcha_id=captcha_id,
        code=code,
        expires_at=_now() + timedelta(minutes=settings.CAPTCHA_EXPIRE_MINUTES),
    )
    return {"captcha_id": captcha_id, "image_base64": image_base64}


async def verify_captcha(captcha_id: str, code: str) -> None:
    """校验验证码：不存在 / 已使用 / 已过期 / 不匹配均抛 BizException。

    校验成功会标记 is_used=True，保证验证码一次性（防重放攻击）。
    """
    record = await CaptchaCode.get_or_none(captcha_id=captcha_id)
    if record is None:
        raise BizException("400", "验证码不存在，请重新获取", status_code=400)
    if record.is_used:
        raise BizException("400", "验证码已被使用，请重新获取", status_code=400)
    if _normalize(record.expires_at) < _now():
        raise BizException("400", "验证码已过期，请重新获取", status_code=400)
    if record.code != code:
        raise BizException("400", "验证码错误", status_code=400)

    # 一次性：标记已使用
    record.is_used = True
    await record.save(update_fields=["is_used", "updated_at"])