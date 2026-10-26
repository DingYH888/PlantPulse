"""认证相关请求/响应模型（PRD 5.1 / 9.7 P1 接口清单）。

账号体系：nickname（昵称）为唯一登录账号，注册需携带图形验证码凭证。
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterIn(BaseModel):
    """注册请求：昵称 3-20 位字母数字下划线，密码 ≥8 位含字母与数字，须通过图形验证码。"""

    nickname: str = Field(min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(min_length=8, max_length=64)
    captcha_id: str = Field(description="验证码ID（GET /auth/captcha 返回）")
    code: str = Field(min_length=4, max_length=4, pattern=r"^\d{4}$", description="图形验证码（4位数字）")

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        """密码强度校验：必须同时包含字母与数字（PRD 5.1.2 FR-107）。"""
        if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
            raise ValueError("密码必须同时包含字母和数字")
        return value


class LoginIn(BaseModel):
    """登录请求：昵称 + 密码。"""

    nickname: str = Field(min_length=3, max_length=20, description="昵称（登录账号）")
    password: str = Field(min_length=8, max_length=64)


class TokenOut(BaseModel):
    """登录/注册成功返回的 JWT（单 token 方案，7 天有效）。"""

    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """用户资料响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: str
    username: str | None = None
    email: str | None = None
    avatar_url: str | None = None
    role: str


class UserUpdateIn(BaseModel):
    """更新资料请求：昵称/头像。"""

    nickname: str | None = Field(default=None, max_length=32)
    avatar_url: str | None = Field(default=None, max_length=512)


class PasswordChangeIn(BaseModel):
    """修改密码请求。"""

    old_password: str
    new_password: str = Field(min_length=8, max_length=64)

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        """新密码同样要求包含字母与数字。"""
        if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
            raise ValueError("新密码必须同时包含字母和数字")
        return value