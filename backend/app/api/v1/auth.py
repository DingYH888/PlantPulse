"""认证模块路由（PRD 5.1 / 9.7 P1 接口清单）。

覆盖：注册、登录、刷新 Token、退出、资料、修改密码。
公开接口：register/login/refresh；其余需 JWT 鉴权。
"""

from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.core.response import BizException, success
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    LoginIn,
    PasswordChangeIn,
    RefreshIn,
    RegisterIn,
    TokenOut,
    UserOut,
    UserUpdateIn,
)

router = APIRouter()


def _build_token_out(user: User) -> TokenOut:
    """签发 access + refresh 双 Token（PRD 7.4）。"""
    return TokenOut(
        access_token=create_access_token(user.id, user.role),
        refresh_token=create_refresh_token(user.id, user.role),
    )


@router.post("/register")
async def register(body: RegisterIn) -> dict:
    """注册：唯一性校验 → 创建用户 → 自动登录（签发 Token）。"""
    # 用户名/邮箱唯一性预检（数据库 unique 约束兜底）
    if await User.exists(username=body.username):
        raise BizException("409", "该用户名已被注册", status_code=409)
    if await User.exists(email=body.email):
        raise BizException("409", "该邮箱已被注册", status_code=409)

    user = await User.create(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        nickname=body.username,
    )
    return success(_build_token_out(user).model_dump(), "注册成功")


@router.post("/login")
async def login(body: LoginIn) -> dict:
    """登录：支持用户名或邮箱，校验密码后签发 Token。"""
    # 通过用户名或邮箱查找账号
    user = await User.get_or_none(username=body.account)
    if user is None:
        user = await User.get_or_none(email=body.account)
    if user is None or not verify_password(body.password, user.password_hash):
        raise BizException("400", "账号或密码错误", status_code=400)
    if not user.is_active:
        raise BizException("403", "账号已被禁用", status_code=403)

    return success(_build_token_out(user).model_dump(), "登录成功")


@router.post("/refresh")
async def refresh(body: RefreshIn) -> dict:
    """刷新 Token：校验 refresh token 后重新签发双 Token（PRD 7.4）。"""
    try:
        payload = decode_token(body.refresh_token)
    except Exception:
        raise BizException("401", "刷新凭证无效或已过期，请重新登录", status_code=401)

    if payload.get("type") != "refresh":
        raise BizException("401", "凭证类型错误", status_code=401)

    user = await User.get_or_none(id=int(payload["sub"]))
    if user is None or not user.is_active:
        raise BizException("401", "账号不存在或已被禁用", status_code=401)

    return success(_build_token_out(user).model_dump(), "刷新成功")


@router.post("/logout")
async def logout(user: CurrentUser) -> dict:
    """退出登录。

    脚手架阶段：前端丢弃本地 Token 即可完成退出；
    服务端 refresh token 黑名单（Redis）在后续安全加固中实现。
    """
    return success({}, "已退出登录")


@router.get("/profile")
async def get_profile(user: CurrentUser) -> dict:
    """获取当前用户资料（PRD 9.7 GET /auth/profile）。"""
    return success(UserOut.model_validate(user).model_dump())


@router.put("/profile")
async def update_profile(body: UserUpdateIn, user: CurrentUser) -> dict:
    """更新用户资料（昵称/头像）。"""
    if body.nickname is not None:
        user.nickname = body.nickname
    if body.avatar_url is not None:
        user.avatar_url = body.avatar_url
    await user.save(update_fields=["nickname", "avatar_url", "updated_at"])
    return success(UserOut.model_validate(user).model_dump(), "更新成功")


@router.put("/password")
async def change_password(body: PasswordChangeIn, user: CurrentUser) -> dict:
    """修改密码：校验原密码后更新哈希。"""
    if not verify_password(body.old_password, user.password_hash):
        raise BizException("400", "原密码错误", status_code=400)
    user.password_hash = hash_password(body.new_password)
    await user.save(update_fields=["password_hash", "updated_at"])
    return success({}, "密码修改成功")