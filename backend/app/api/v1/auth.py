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

import logging

from fastapi import APIRouter, UploadFile
from tortoise.exceptions import IntegrityError

from app.core.deps import CurrentUser
from app.core.response import BizException, success
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.plant import Plant
from app.models.plant_record import PlantRecord
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
from app.services.image_storage import delete_upload_image, save_upload_image

router = APIRouter()
logger = logging.getLogger(__name__)


def _build_token_out(user: User) -> TokenOut:
    """签发登录 JWT（单 token 方案，有效期 7 天）。"""
    return TokenOut(access_token=create_access_token(user.id, user.role))


async def _is_image_referenced(url: str, exclude_user_id: int) -> bool:
    """旧头像文件是否仍被其他业务引用（其他用户头像 / 植物图片 / 打卡图片）。

    存在共享引用时禁止删除，避免把打卡照片等业务图片一并清掉。
    """
    if await User.filter(avatar_url=url).exclude(id=exclude_user_id).exists():
        return True
    if await Plant.filter(image_url=url).exists():
        return True
    # 打卡图片以 JSON 数组字符串落库，用包含匹配判断是否引用该 URL
    return await PlantRecord.filter(image_url__contains=url).exists()


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
    """更新用户资料（昵称/头像，PRD FR-506）。

    昵称即登录账号：变更前先做唯一性预检，避免触发数据库唯一约束导致 500；
    头像推荐走 PUT /auth/avatar（原子上传 + 落库 + 清理旧图）；
    此处保留 avatar_url 回写能力以兼容旧调用。
    """
    old_avatar_url = user.avatar_url
    if body.nickname is not None and body.nickname != user.nickname:
        if await User.exists(nickname=body.nickname):
            raise BizException("409", "该昵称已被占用，请换一个", status_code=409)
        user.nickname = body.nickname
    if body.avatar_url is not None:
        user.avatar_url = body.avatar_url
    try:
        await user.save(update_fields=["nickname", "avatar_url", "updated_at"])
    except IntegrityError:
        # 并发改名竞态：预检通过后仍可能撞唯一约束，兜底转 409 而非 500
        raise BizException("409", "该昵称已被占用，请换一个", status_code=409)

    # 头像确实变更后才清理旧文件；仍被其他业务引用时保留，删除失败不影响本次更新
    if body.avatar_url is not None and old_avatar_url and old_avatar_url != body.avatar_url:
        if not await _is_image_referenced(old_avatar_url, user.id):
            delete_upload_image(old_avatar_url)

    return success(UserOut.model_validate(user).model_dump(), "更新成功")


@router.put("/avatar")
async def update_avatar(file: UploadFile, user: CurrentUser) -> dict:
    """上传并更新头像（原子操作，PRD FR-506）。

    「上传 → 落库 → 清理旧头像」在同一次请求内完成：
    - 落库失败时删除刚上传的新文件，避免产生孤儿文件；
    - 落库成功后清理旧头像，仍被其他业务引用时保留；
    - 旧头像删除失败不影响本次更新结果。
    """
    old_avatar_url = user.avatar_url
    new_avatar_url = await save_upload_image(file)
    try:
        user.avatar_url = new_avatar_url
        await user.save(update_fields=["avatar_url", "updated_at"])
    except Exception:
        # 落库失败：回滚刚写入的新文件，旧头像保持不变
        delete_upload_image(new_avatar_url)
        logger.exception("头像落库失败，已回滚新上传文件：%s", new_avatar_url)
        raise BizException("500", "头像更新失败，请稍后重试", status_code=500)

    if old_avatar_url and old_avatar_url != new_avatar_url:
        if not await _is_image_referenced(old_avatar_url, user.id):
            delete_upload_image(old_avatar_url)

    return success(UserOut.model_validate(user).model_dump(), "头像更新成功")


@router.put("/password")
async def change_password(body: PasswordChangeIn, user: CurrentUser) -> dict:
    """修改密码：校验原密码后更新哈希。"""
    if not verify_password(body.old_password, user.password_hash):
        raise BizException("400", "原密码错误", status_code=400)
    user.password_hash = hash_password(body.new_password)
    await user.save(update_fields=["password_hash", "updated_at"])
    return success({}, "密码修改成功")