"""认证相关请求/响应模型（PRD 5.1 / 9.7 P1 接口清单）。"""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterIn(BaseModel):
    """注册请求：用户名 3-20 位字母数字下划线，密码 ≥8 位含字母与数字。"""

    username: str = Field(min_length=3, max_length=20, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        """密码强度校验：必须同时包含字母与数字（PRD 5.1.2 FR-107）。"""
        if not any(ch.isalpha() for ch in value) or not any(ch.isdigit() for ch in value):
            raise ValueError("密码必须同时包含字母和数字")
        return value


class LoginIn(BaseModel):
    """登录请求：支持用户名或邮箱。"""

    account: str = Field(min_length=3, max_length=128, description="用户名或邮箱")
    password: str = Field(min_length=8, max_length=64)


class RefreshIn(BaseModel):
    """刷新 Token 请求。"""

    refresh_token: str


class TokenOut(BaseModel):
    """登录/注册成功返回的 Token 对。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    """用户资料响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    nickname: str | None = None
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