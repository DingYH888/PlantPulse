"""植物建档模块单元测试：新增植物 POST /plants。

覆盖（PRD FR-201 / 7.3 数据隔离）：
- 权限校验：未携带 Token 新增植物返回 401；
- 成功建档：名称去首尾空白、status 默认 healthy、选填字段落库；
- 名称校验：纯空白 400、缺失 400、超长 400；
- 数据隔离：新建植物仅出现在本人列表中。

注意：沙箱无法运行 asyncio，请在本地终端执行 pytest。
"""

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.models.plant import Plant
from app.models.user import User

pytestmark = pytest.mark.asyncio

PLANTS_URL = "/api/v1/plants"


# ---- 辅助函数 ----

async def _make_user(nickname: str = "planter01") -> User:
    """直接落库一个用户（绕过验证码流程）。"""
    return await User.create(
        nickname=nickname,
        password_hash=hash_password("pass1234"),
        is_active=True,
    )


def _auth_headers(user: User) -> dict:
    """构造携带 JWT 的请求头。"""
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


# ---- 权限校验（PRD 11.3）----

async def test_create_plant_requires_token(client: AsyncClient):
    """未携带 Token 新增植物返回 401。"""
    resp = await client.post(PLANTS_URL, json={"name": "绿萝"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "401"


# ---- 成功建档（FR-201）----

async def test_create_plant_success(client: AsyncClient):
    """新增植物成功：名称 trim、status 默认 healthy、归属当前用户。"""
    user = await _make_user("plant_ok")

    resp = await client.post(
        PLANTS_URL,
        json={"name": "  绿萝  ", "species": "   ", "location": "阳台"},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "200"
    data = body["data"]
    assert data["name"] == "绿萝"
    assert data["species"] is None  # 纯空白选填字段按未填写处理
    assert data["location"] == "阳台"
    assert data["status"] == "healthy"

    plant = await Plant.get(id=data["id"])
    assert plant.user_id == user.id


async def test_create_plant_optional_fields(client: AsyncClient):
    """选填字段（品种/种植日期/备注）正确落库并回显。"""
    user = await _make_user("plant_fields")
    resp = await client.post(
        PLANTS_URL,
        json={
            "name": "发财树",
            "species": "马拉巴栗",
            "planted_at": "2026-03-01",
            "notes": "喜散射光",
        },
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["species"] == "马拉巴栗"
    assert data["planted_at"] == "2026-03-01"
    assert data["notes"] == "喜散射光"


async def test_create_plant_visible_in_own_list(client: AsyncClient):
    """新建植物只出现在本人列表（数据隔离）。"""
    user_a = await _make_user("plant_a")
    user_b = await _make_user("plant_b")

    resp = await client.post(PLANTS_URL, json={"name": "我的绿萝"}, headers=_auth_headers(user_a))
    assert resp.status_code == 200

    resp_a = await client.get(PLANTS_URL, headers=_auth_headers(user_a))
    assert resp_a.json()["data"]["total"] == 1

    resp_b = await client.get(PLANTS_URL, headers=_auth_headers(user_b))
    assert resp_b.json()["data"]["total"] == 0


# ---- 名称校验 ----

async def test_create_plant_blank_name(client: AsyncClient):
    """纯空白名称返回 400（中文提示）。"""
    user = await _make_user("plant_blank")
    resp = await client.post(PLANTS_URL, json={"name": "   "}, headers=_auth_headers(user))
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"
    assert resp.json()["msg"] == "植物名称不能为空"


async def test_create_plant_missing_name(client: AsyncClient):
    """缺少 name 字段返回 400（参数校验失败）。"""
    user = await _make_user("plant_missing")
    resp = await client.post(PLANTS_URL, json={}, headers=_auth_headers(user))
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"


async def test_create_plant_name_too_long(client: AsyncClient):
    """名称超过 64 字符返回 400（参数校验失败）。"""
    user = await _make_user("plant_long")
    resp = await client.post(PLANTS_URL, json={"name": "绿" * 65}, headers=_auth_headers(user))
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"