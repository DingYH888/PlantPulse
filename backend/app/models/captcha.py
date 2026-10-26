"""图形验证码模型（注册防刷/防机器人）。

验证码在生成接口（GET /auth/captcha）落库，注册时按 captcha_id 取回校验：
- 一次性：校验成功即标记 is_used=True，防止重放
- 时效性：expires_at 控制 5 分钟有效期，过期记录在下次生成时顺带清理
"""

from tortoise import fields

from app.models.base import TimestampMixin


class CaptchaCode(TimestampMixin):
    """图形验证码记录表。"""

    captcha_id = fields.CharField(
        max_length=64, unique=True, description="验证码唯一标识（uuid，注册时回传）"
    )
    code = fields.CharField(max_length=8, description="验证码明文（4位数字）")
    expires_at = fields.DatetimeField(description="过期时间（生成时间 + 5分钟）")
    is_used = fields.BooleanField(default=False, description="是否已使用（一次性校验）")

    class Meta:
        table = "captcha_codes"

    def __str__(self) -> str:
        return f"<CaptchaCode id={self.id} captcha_id={self.captcha_id!r}>"