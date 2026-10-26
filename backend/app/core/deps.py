"""依赖注入模块（PRD 7.3/7.4）。

提供鉴权依赖：从 Authorization 头解析 JWT → 加载当前用户。
所有需要"当前登录用户"的业务接口都应声明依赖此函数，保证数据隔离。
异步实现（Tortoise-ORM 基于 asyncio，路由处理器同为 async）。
"""

from typing import Annotated

from fastapi import Depends, Header
from jwt import PyJWTError

from app.core.response import BizException
from app.core.security import decode_token
from app.models.user import User


async def get_current_user(authorization: Annotated[str | None, Header()] = None) -> User:
    """鉴权依赖：校验 Bearer token 并返回当前用户。

    失败时统一抛出 BizException(code=401)，由全局异常处理器转换为标准返回格式。
    注意：Header 参数必须有默认值 None，否则未携带请求头时 FastAPI 会在进入
    函数前抛参数校验错误（400），导致无法统一返回 401。
    """
    # 1. 校验 Authorization 头格式
    if not authorization or not authorization.startswith("Bearer "):
        raise BizException("401", "未登录或凭证缺失，请先登录", status_code=401)

    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = decode_token(token)
    except PyJWTError:
        # Token 过期 / 签名非法 / 格式错误统一视为未认证
        raise BizException("401", "登录已过期，请重新登录", status_code=401)

    # 2. 仅接受 access token 访问业务接口
    if payload.get("type") != "access":
        raise BizException("401", "凭证类型错误，请使用登录令牌", status_code=401)

    # 3. 加载用户并校验有效性（Tortoise 主键查询）
    user = await User.get_or_none(id=int(payload["sub"]))
    if user is None or not user.is_active:
        raise BizException("401", "账号不存在或已被禁用", status_code=401)
    return user


# 便捷别名：声明依赖时直接使用 CurrentUser
CurrentUser = Annotated[User, Depends(get_current_user)]