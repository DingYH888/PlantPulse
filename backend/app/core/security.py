"""安全模块：JWT 签发/校验与密码哈希（PRD 7.4）。

- Token：单 token 方案，载荷 {sub: user_id, role, iat, exp, jti}，有效期 7 天
- 密码：bcrypt 加盐哈希，禁止明文存储
"""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    """生成密码哈希（bcrypt，成本因子取默认 12）。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """校验密码与哈希是否匹配。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # 哈希格式非法时视为校验失败，避免抛出异常
        return False


def _create_token(user_id: int, role: str, expires_delta: timedelta, token_type: str) -> str:
    """签发 JWT：token_type 用于标识令牌用途（单 token 方案固定为 access）。"""
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),          # 用户主键
        "role": role,                 # 角色（PRD 7.1）
        "type": token_type,           # access
        "jti": uuid.uuid4().hex,      # Token 唯一标识（供黑名单使用）
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: int, role: str) -> str:
    """签发登录 JWT（单 token 方案，有效期 7 天）。"""
    settings = get_settings()
    return _create_token(user_id, role, timedelta(days=settings.ACCESS_TOKEN_EXPIRE_DAYS), "access")


def decode_token(token: str) -> dict:
    """解析并校验 JWT，非法/过期抛 jwt 异常。"""
    settings = get_settings()
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])