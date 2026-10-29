"""打卡链路模块单元测试：植物列表 / 新增打卡 / 打卡历史 / 图片上传。

覆盖（PRD 11 对应用例）：
- 权限校验：未携带 Token 访问 plants/checkins/upload 返回 401（PRD 11.3）；
- 植物列表：登录后仅返回本人名下植物（数据隔离 TC-203）；
- 新增打卡：成功（默认当天 + 多图）、未来日期 400（TC-505）、重复打卡 409（TC-502）、
  非本人植物 403（PRD 10.2.1）、植物不存在 404；
- 打卡历史：按植物筛选、时间倒序、分页结构；
- 图片上传：png 成功返回 URL、类型非法 400、超 5MB 400（PRD 10.2.2）。

注意：沙箱无法运行 asyncio，请在本地终端执行 pytest。
"""

from datetime import date

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.models.plant import Plant
from app.models.user import User

pytestmark = pytest.mark.asyncio

PLANTS_URL = "/api/v1/plants"
CHECKINS_URL = "/api/v1/checkins"
UPLOAD_URL = "/api/v1/upload/image"


# ---- 辅助函数 ----

async def _make_user(nickname: str = "checker01") -> User:
    """直接落库一个用户（绕过验证码流程），返回可用的 JWT。"""
    return await User.create(
        nickname=nickname,
        password_hash=hash_password("pass1234"),
        is_active=True,
    )


def _auth_headers(user: User) -> dict:
    """构造携带 JWT 的请求头。"""
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


async def _make_plant(user: User, name: str = "绿萝") -> Plant:
    """直接落库一株属于该用户的植物。"""
    return await Plant.create(user_id=user.id, name=name)


async def _create_checkin(client: AsyncClient, user: User, plant_id: int, **kwargs) -> dict:
    """POST 打卡的便捷封装。"""
    payload = {"plant_id": plant_id, "care_type": "watering", **kwargs}
    return await client.post(CHECKINS_URL, json=payload, headers=_auth_headers(user))


# ---- 权限校验（PRD 11.3）----

async def test_plants_requires_token(client):
    """未携带 Token 访问植物列表返回 401。"""
    resp = await client.get(PLANTS_URL)
    assert resp.status_code == 401
    assert resp.json()["code"] == "401"


async def test_checkins_requires_token(client):
    """未携带 Token 访问打卡历史返回 401。"""
    resp = await client.get(CHECKINS_URL, params={"plant_id": 1})
    assert resp.status_code == 401
    assert resp.json()["code"] == "401"


async def test_upload_requires_token(client):
    """未携带 Token 上传图片返回 401。"""
    resp = await client.post(UPLOAD_URL, files={"file": ("a.png", b"x", "image/png")})
    assert resp.status_code == 401
    assert resp.json()["code"] == "401"


# ---- 植物列表（FR-201 / 数据隔离）----

async def test_plants_list_only_own(client):
    """植物列表：登录后仅返回本人名下植物（数据隔离，他人不可见）。"""
    user_a = await _make_user("plants_a")
    user_b = await _make_user("plants_b")
    plant_own = await _make_plant(user_a, "我的绿萝")
    await _make_plant(user_b, "他人绿萝")

    resp = await client.get(PLANTS_URL, headers=_auth_headers(user_a))
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "200"
    data = body["data"]
    assert data["total"] == 1
    assert data["items"][0]["id"] == plant_own.id
    assert data["items"][0]["name"] == "我的绿萝"


async def test_plants_list_keyword_filter(client):
    """植物列表：keyword 按名称模糊筛选。"""
    user = await _make_user("plants_c")
    await _make_plant(user, "发财树")
    await _make_plant(user, "绿萝")

    resp = await client.get(PLANTS_URL, params={"keyword": "绿萝"}, headers=_auth_headers(user))
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["name"] == "绿萝"


# ---- 新增打卡（FR-502）----

async def test_create_checkin_success_with_images(client):
    """新增打卡成功：默认当天日期，多图 URL 落库为 JSON 数组并在响应中还原。"""
    user = await _make_user("check_success")
    plant = await _make_plant(user)

    resp = await _create_checkin(
        client, user, plant.id,
        care_type="fertilizing",
        content="施肥 10g",
        image_urls=["/static/uploads/a.jpg", "/static/uploads/b.jpg"],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "200"
    data = body["data"]
    assert data["care_type"] == "fertilizing"
    assert data["plant_name"] == "绿萝"
    assert data["record_date"] == date.today().isoformat()
    assert data["images"] == ["/static/uploads/a.jpg", "/static/uploads/b.jpg"]


async def test_create_checkin_default_today(client):
    """不传 record_date 时默认当天打卡。"""
    user = await _make_user("check_today")
    plant = await _make_plant(user)

    resp = await _create_checkin(client, user, plant.id)
    assert resp.status_code == 200
    assert resp.json()["data"]["record_date"] == date.today().isoformat()


async def test_create_checkin_future_date(client):
    """未来日期打卡返回 400（PRD BR-04 / TC-505）。"""
    user = await _make_user("check_future")
    plant = await _make_plant(user)

    resp = await _create_checkin(client, user, plant.id, record_date="2099-01-01")
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"
    assert "未来" in resp.json()["msg"]


async def test_create_checkin_duplicate(client):
    """同植物同类型同日重复打卡返回 409（PRD BR-03 / TC-502）。"""
    user = await _make_user("check_dup")
    plant = await _make_plant(user)

    resp = await _create_checkin(client, user, plant.id)
    assert resp.status_code == 200

    resp = await _create_checkin(client, user, plant.id)
    assert resp.status_code == 409
    assert resp.json()["code"] == "409"
    assert "重复" in resp.json()["msg"]


async def test_create_checkin_allow_different_type_same_day(client):
    """同一天不同类型允许多次打卡（PRD 5.5.3 规则 2）。"""
    user = await _make_user("check_multi")
    plant = await _make_plant(user)

    resp = await _create_checkin(client, user, plant.id, care_type="watering")
    assert resp.status_code == 200
    resp = await _create_checkin(client, user, plant.id, care_type="pest_control")
    assert resp.status_code == 200


async def test_create_checkin_other_user_plant(client):
    """对他人植物打卡返回 403（数据隔离 PRD BR-02 / 10.2.1）。"""
    user_a = await _make_user("check_own")
    user_b = await _make_user("check_other")
    plant_b = await _make_plant(user_b, "他人绿萝")

    resp = await _create_checkin(client, user_a, plant_b.id)
    assert resp.status_code == 403
    assert resp.json()["code"] == "403"


async def test_create_checkin_plant_not_found(client):
    """不存在的植物返回 404。"""
    user = await _make_user("check_nf")
    resp = await _create_checkin(client, user, 99999)
    assert resp.status_code == 404
    assert resp.json()["code"] == "404"


# ---- 打卡历史（FR-504）----

async def test_list_checkins_by_plant_desc(client):
    """打卡历史：按植物筛选，日期倒序，返回分页结构。"""
    user = await _make_user("history_a")
    plant = await _make_plant(user)

    # 昨天浇水、今天施肥，应倒序返回
    await _create_checkin(client, user, plant.id, care_type="watering", record_date="2026-10-25")
    await _create_checkin(client, user, plant.id, care_type="fertilizing", record_date="2026-10-26")

    resp = await client.get(CHECKINS_URL, params={"plant_id": plant.id}, headers=_auth_headers(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    assert [item["care_type"] for item in data["items"]] == ["fertilizing", "watering"]


async def test_list_checkins_pagination(client):
    """打卡历史：分页参数生效，page_size 超上限返回 400。"""
    user = await _make_user("history_b")
    plant = await _make_plant(user)
    for day in ("2026-10-20", "2026-10-21"):
        await _create_checkin(client, user, plant.id, care_type="watering", record_date=day)

    resp = await client.get(
        CHECKINS_URL,
        params={"plant_id": plant.id, "page": 1, "page_size": 1},
        headers=_auth_headers(user),
    )
    data = resp.json()["data"]
    assert data["total"] == 2
    assert len(data["items"]) == 1

    resp = await client.get(
        CHECKINS_URL,
        params={"plant_id": plant.id, "page_size": 51},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 400


async def test_list_checkins_other_user_plant(client):
    """查询他人植物的打卡历史返回 403。"""
    user_a = await _make_user("history_own")
    user_b = await _make_user("history_other")
    plant_b = await _make_plant(user_b, "他人绿萝")

    resp = await client.get(CHECKINS_URL, params={"plant_id": plant_b.id}, headers=_auth_headers(user_a))
    assert resp.status_code == 403
    assert resp.json()["code"] == "403"


async def test_list_checkins_all_plants_for_user(client):
    """不传 plant_id：返回当前用户全部植物的打卡记录，并带植物名称（历史卡片展示）。"""
    user = await _make_user("history_all")
    plant_a = await _make_plant(user, "绿萝")
    plant_b = await _make_plant(user, "水仙花")
    other = await _make_user("history_all_other")
    other_plant = await _make_plant(other, "他人植物")

    await _create_checkin(client, user, plant_a.id)
    await _create_checkin(client, user, plant_b.id, care_type="fertilizing")
    await _create_checkin(client, other, other_plant.id)

    resp = await client.get(CHECKINS_URL, headers=_auth_headers(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 2
    assert {item["plant_name"] for item in data["items"]} == {"绿萝", "水仙花"}


async def test_list_checkins_filter_by_date(client):
    """record_date 精确筛选指定日期，且返回植物名称。"""
    user = await _make_user("history_date")
    plant = await _make_plant(user, "发财树")
    await _create_checkin(client, user, plant.id, care_type="watering", record_date="2026-10-25")
    await _create_checkin(client, user, plant.id, care_type="pruning", record_date="2026-10-26")

    resp = await client.get(
        CHECKINS_URL, params={"record_date": "2026-10-26"}, headers=_auth_headers(user)
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["care_type"] == "pruning"
    assert data["items"][0]["plant_name"] == "发财树"


# ---- 图片上传（PRD 9.6 / 10.2.2）----

def _patch_upload_dir(monkeypatch, tmp_path):
    """将上传目录重定向到临时目录。

    落盘逻辑已下沉到 app.services.image_storage，upload 路由不再持有 settings，
    因此需要替换 image_storage.get_settings（与 test_profile.py 保持一致）。
    """
    from types import SimpleNamespace

    from app.services import image_storage

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(
        image_storage, "get_settings", lambda: SimpleNamespace(upload_dir=upload_dir)
    )
    return upload_dir


async def test_upload_image_success(client, monkeypatch, tmp_path):
    """上传 png 成功：返回 /static/uploads/ 前缀的 URL，且文件真实落地。"""
    upload_dir = _patch_upload_dir(monkeypatch, tmp_path)

    user = await _make_user("upload_ok")
    resp = await client.post(
        UPLOAD_URL,
        files={"file": ("plant.png", b"\x89PNG\r\n\x1a\nfake-image", "image/png")},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    url = resp.json()["data"]["url"]
    assert url.startswith("/static/uploads/")
    assert (upload_dir / url.rsplit("/", 1)[-1]).exists()


async def test_upload_image_wrong_type(client, monkeypatch, tmp_path):
    """非白名单类型（text/plain）返回 400。"""
    _patch_upload_dir(monkeypatch, tmp_path)

    user = await _make_user("upload_badtype")
    resp = await client.post(
        UPLOAD_URL,
        files={"file": ("a.txt", b"hello", "text/plain")},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 400
    assert "格式" in resp.json()["msg"]


async def test_upload_image_too_large(client, monkeypatch, tmp_path):
    """超过 5MB 返回 400（PRD 10.2.2 图片超限）。"""
    _patch_upload_dir(monkeypatch, tmp_path)

    user = await _make_user("upload_big")
    big = b"0" * (5 * 1024 * 1024 + 1)
    resp = await client.post(
        UPLOAD_URL,
        files={"file": ("big.png", big, "image/png")},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 400
    assert "5MB" in resp.json()["msg"]