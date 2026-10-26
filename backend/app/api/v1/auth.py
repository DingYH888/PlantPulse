"""认证模块路由（PRD 5.1 / 9.7 P1 接口清单）。

覆盖：图形验证码、注册、登录、退出、资料、修改密码。
公开接口：captcha / register / login；其余需 JWT 鉴权。
登录成功签发单 JWT，有效期 7 天（单 token 方案）。

数据层：Tortoise-ORM 异步查询（backend/app/models/user.py、captcha.py）。

========================== curl 测试用例 ==========================

1) 获取图形验证码（code 明文只存库，前端需看图）
   curl http://127.0.0.1:8000/api/v1/auth/captcha
   => {"code":"200","msg":"success","data":{"captcha_id":"<id>","image_base64":"<png/base64>"}}

2) 注册（captcha_id 取上一步返回值，code 为图片中 4 位数字）
   curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
     -H "Content-Type: application/json" \
     -d '{"nickname":"plant_fan","password":"pass1234","captcha_id":"<id>","code":"1234"}'
   => {"code":"200","msg":"注册成功","data":{"access_token":"<token>","token_type":"bearer"}}

3) 登录
   curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
     -H "Content-Type: application/json" \
     -d '{"nickname":"plant_fan","password":"pass1234"}'
   => {"code":"200","msg":"登录成功","data":{"access_token":"<token>","token_type":"bearer"}}

4) 获取当前用户资料（携带 token）
   curl http://127.0.0.1:8000/api/v1/auth/profile \
     -H "Authorization: Bearer <token>"

5) 修改密码
   curl -X PUT http://127.0.0.1:8000/api/v1/auth/password \
     -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
     -d '{"old_password":"pass1234","new_password":"newpass1234"}'

6) 退出登录（前端丢弃 token 即可，服务端黑名单后续安全加固实现）
   curl -X POST http://127.0.0.1:8000/api/v1/auth/logout \
     -H "Authorization: Bearer <token>"
===================================================================
"""

from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.core.response import BizException, success
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    LoginIn,
    PasswordChangeIn,
    RegisterIn,
    TokenOut,
    UserOut,
    UserUpdateIn,
)
from app.services.captcha import generate_captcha, verify_captcha

router = APIRouter()


def _build_token_out(user: User) -> TokenOut:
    """签发登录 JWT（单 token 方案，有效期 7 天）。"""
    return TokenOut(access_token=create_access_token(user.id, user.role))


@router.get("/captcha")
async def get_captcha() -> dict:
    """获取图形验证码（公开接口）。

    返回 captcha_id 与 base64 图片；明文验证码仅存数据库，5 分钟有效、一次性使用。
    """
    data = await generate_captcha()
    return success(data, "验证码已生成，5分钟内有效")


@router.post("/register")
async def register(body: RegisterIn) -> dict:
    """注册（公开接口）：校验验证码 → 昵称唯一性 → 创建用户 → 自动登录。

    密码使用 bcrypt 加盐哈希后入库（models.user 约束1：禁止明文）。
    """
    # 1. 图形验证码校验（一次性，成功后自动标记已使用）
    await verify_captcha(body.captcha_id, body.code)

    # 2. 昵称唯一性预检（数据库 unique 约束兜底）
    if await User.exists(nickname=body.nickname):
        raise BizException("409", "该昵称已被注册", status_code=409)

    # 3. 创建用户（bcrypt 加密）
    user = await User.create(
        nickname=body.nickname,
        password_hash=hash_password(body.password),
    )
    return success(_build_token_out(user).model_dump(), "注册成功")


@router.post("/login")
async def login(body: LoginIn) -> dict:
    """登录（公开接口）：nickname + 密码校验，成功签发 7 天有效 JWT。"""
    user = await User.get_or_none(nickname=body.nickname)
    if user is None or not verify_password(body.password, user.password_hash):
        raise BizException("400", "昵称或密码错误", status_code=400)
    if not user.is_active:
        raise BizException("403", "账号已被禁用", status_code=403)

    return success(_build_token_out(user).model_dump(), "登录成功")


@router.post("/logout")
async def logout(user: CurrentUser) -> dict:
    """退出登录。

    脚手架阶段：前端丢弃本地 Token 即可完成退出；
    服务端 token 黑名单（Redis）在后续安全加固中实现。
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