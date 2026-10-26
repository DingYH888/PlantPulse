"""认证模块单元测试：图形验证码/注册/登录/鉴权（PRD 11.1 TC-101~TC-103）。

覆盖：验证码生成落库、注册成功、验证码错误/过期/重复使用、昵称重复、弱密码、
登录成功/密码错误、未登录访问受保护接口、携带 token 获取资料。
数据层：Tortoise-ORM 独立 SQLite 测试库 + 异步 TestClient。
注意：沙箱无法运行 asyncio，请在本地终端执行 pytest。
"""

from datetime import UTC, datetime, timedelta

import pytest
from app.models.captcha import CaptchaCode

pytestmark = pytest.mark.asyncio

CAPTCHA_URL = "/api/v1/auth/captcha"
REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
PROFILE_URL = "/api/v1/auth/profile"


async def _get_captcha(client) -> dict:
    """请求验证码接口，并直读数据库取回明文 code（模拟前端看图输码）。"""
    resp = await client.get(CAPTCHA_URL)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["captcha_id"]
    assert data["image_base64"]
    record = await CaptchaCode.get_or_none(captcha_id=data["captcha_id"])
    assert record is not None, "验证码必须落库"
    return {"captcha_id": data["captcha_id"], "code": record.code}


async def _register(client, nickname: str = "tester01", captcha: dict | None = None):
    """注册辅助：默认先生成真实验证码，再携带注册。"""
    if captcha is None:
        captcha = await _get_captcha(client)
    return await client.post(
        REGISTER_URL,
        json={"nickname": nickname, "password": "pass1234", **captcha},
    )


async def test_captcha_generate(client):
    """验证码接口：返回 captcha_id 与 base64 图片，且明文 code 落库。"""
    captcha = await _get_captcha(client)
    record = await CaptchaCode.get(captcha_id=captcha["captcha_id"])
    assert len(record.code) == 4
    assert record.code.isdigit()
    assert not record.is_used


async def test_register_success(client):
    """注册成功：返回统一格式与 7 天有效 JWT，且可用该昵称登录。"""
    resp = await _register(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "200"
    data = body["data"]
    assert data["token_type"] == "bearer"
    assert data["access_token"]

    # 注册成功后可直接登录
    login = await client.post(
        LOGIN_URL, json={"nickname": "tester01", "password": "pass1234"}
    )
    assert login.status_code == 200
    assert login.json()["data"]["access_token"]


async def test_register_wrong_captcha(client):
    """验证码错误：返回 code=400。"""
    captcha = await _get_captcha(client)
    wrong_code = "9999" if captcha["code"] != "9999" else "8888"
    resp = await client.post(
        REGISTER_URL,
        json={"nickname": "bad_cap", "password": "pass1234", "captcha_id": captcha["captcha_id"], "code": wrong_code},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"
    assert "验证码" in resp.json()["msg"]


async def test_register_captcha_reused(client):
    """验证码重复使用（重放）：首次成功，二次返回 code=400。"""
    captcha = await _get_captcha(client)
    resp = await _register(client, nickname="reuse01", captcha=captcha)
    assert resp.status_code == 200
    # 同一验证码换昵称再注册 → 应被拒绝
    resp = await _register(client, nickname="reuse02", captcha=captcha)
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"


async def test_register_captcha_expired(client):
    """验证码过期：把库中记录过期时间拨到过去后注册，返回 code=400。"""
    captcha = await _get_captcha(client)
    record = await CaptchaCode.get(captcha_id=captcha["captcha_id"])
    record.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
    await record.save(update_fields=["expires_at"])
    resp = await _register(client, nickname="expired01", captcha=captcha)
    assert resp.status_code == 400
    assert "过期" in resp.json()["msg"]


async def test_register_duplicate_nickname(client):
    """昵称重复：返回 code=409。"""
    await _register(client, nickname="dup001")
    captcha = await _get_captcha(client)
    resp = await _register(client, nickname="dup001", captcha=captcha)
    assert resp.status_code == 409
    assert resp.json()["code"] == "409"


async def test_register_weak_password(client):
    """FR-107 弱密码（纯字母）被校验拦截：返回 code=400。"""
    captcha = await _get_captcha(client)
    resp = await client.post(
        REGISTER_URL,
        json={"nickname": "weak001", "password": "onlyletters", **captcha},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"


async def test_login_success(client):
    """登录成功：nickname + 密码返回 7 天 JWT。"""
    await _register(client)
    resp = await client.post(LOGIN_URL, json={"nickname": "tester01", "password": "pass1234"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "200"
    assert body["data"]["access_token"]
    assert body["data"]["token_type"] == "bearer"


async def test_login_wrong_password(client):
    """密码错误：返回 code=400 与提示。"""
    await _register(client)
    resp = await client.post(LOGIN_URL, json={"nickname": "tester01", "password": "wrong1234"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"


async def test_profile_requires_token(client):
    """权限校验：未携带 Token 访问受保护接口返回 code=401（PRD 11.3）。"""
    resp = await client.get(PROFILE_URL)
    assert resp.status_code == 401
    assert resp.json()["code"] == "401"


async def test_profile_with_token(client):
    """携带有效 Token 获取资料：返回当前用户昵称。"""
    resp = await _register(client)
    token = resp.json()["data"]["access_token"]
    resp = await client.get(PROFILE_URL, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["data"]["nickname"] == "tester01"