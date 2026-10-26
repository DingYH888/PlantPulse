"""认证模块单元测试：注册/登录/刷新/鉴权（PRD 11.1 TC-101~TC-103）。

覆盖：正常流程、重复注册、错误密码、Token 刷新、未登录访问受保护接口。
"""

import pytest

pytestmark = pytest.mark.asyncio

REGISTER_URL = "/api/v1/auth/register"
LOGIN_URL = "/api/v1/auth/login"
REFRESH_URL = "/api/v1/auth/refresh"
PROFILE_URL = "/api/v1/auth/profile"


async def _register(client, username: str = "tester01", email: str = "tester01@plantpulse.com") -> dict:
    """注册辅助函数，返回响应体。"""
    resp = await client.post(
        REGISTER_URL,
        json={"username": username, "email": email, "password": "pass1234"},
    )
    assert resp.status_code == 200
    return resp.json()


async def test_register_success(client):
    """TC-101 注册成功：返回统一格式与 Token 对，用户可登录。"""
    body = await _register(client)

    assert body["code"] == "200"
    data = body["data"]
    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["refresh_token"]


async def test_register_duplicate_username(client):
    """TC-102 用户名重复：返回 code=409。"""
    await _register(client, username="dup001", email="dup001@plantpulse.com")
    resp = await client.post(
        REGISTER_URL,
        json={"username": "dup001", "email": "other@plantpulse.com", "password": "pass1234"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "409"


async def test_register_weak_password(client):
    """FR-107 弱密码（纯字母）被校验拦截：返回 code=400。"""
    resp = await client.post(
        REGISTER_URL,
        json={"username": "weak001", "email": "weak@plantpulse.com", "password": "onlyletters"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"


async def test_login_success(client):
    """登录成功：用户名或邮箱均可登录。"""
    await _register(client)
    # 用户名登录
    resp = await client.post(LOGIN_URL, json={"account": "tester01", "password": "pass1234"})
    assert resp.status_code == 200
    assert resp.json()["data"]["access_token"]
    # 邮箱登录
    resp = await client.post(
        LOGIN_URL, json={"account": "tester01@plantpulse.com", "password": "pass1234"}
    )
    assert resp.status_code == 200


async def test_login_wrong_password(client):
    """密码错误：返回 code=400 与提示。"""
    await _register(client)
    resp = await client.post(LOGIN_URL, json={"account": "tester01", "password": "wrong1234"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"


async def test_refresh_token(client):
    """刷新 Token：refresh token 可换取新的 access token。"""
    body = await _register(client)
    resp = await client.post(REFRESH_URL, json={"refresh_token": body["data"]["refresh_token"]})
    assert resp.status_code == 200
    assert resp.json()["data"]["access_token"]


async def test_profile_requires_token(client):
    """权限校验：未携带 Token 访问受保护接口返回 code=401（PRD 11.3）。"""
    resp = await client.get(PROFILE_URL)
    assert resp.status_code == 401
    assert resp.json()["code"] == "401"


async def test_profile_with_token(client):
    """携带有效 Token 获取资料：返回当前用户信息。"""
    body = await _register(client)
    resp = await client.get(
        PROFILE_URL, headers={"Authorization": f"Bearer {body['data']['access_token']}"}
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == "tester01"