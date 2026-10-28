"""个人中心模块单元测试（PRD 5.5 P5 / 11 对应用例）。

覆盖：
- 权限校验：日历 / 统计 / 资料 / 改密码未登录均返回 401（PRD 11.3）；
- 个人资料：昵称修改成功、昵称重复 409、昵称格式非法 400、头像 URL 更新；
- 修改密码：成功且新密码可登录、原密码错误 400、新密码强度不足 400；
- 打卡日历：默认当月 / 指定月份聚合（同日多类型合并）、跨月隔离、非法月份 400、
  数据隔离（他人记录不出现）；
- 打卡统计：连续天数（今天有记录 / 仅昨天 / 断签）、本月与累计口径、类型分布、数据隔离；
- 撤销打卡：当天成功且统计同步、非当天 400、他人记录 403、不存在 404。

注意：沙箱无法运行 asyncio，请在本地终端执行 pytest。
"""

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.core.timezone import APP_TIMEZONE
from app.models.plant import Plant
from app.models.plant_record import PlantRecord, RecordType
from app.models.user import User

pytestmark = pytest.mark.asyncio

CALENDAR_URL = "/api/v1/checkins/calendar"
CHECKINS_URL = "/api/v1/checkins"
STATS_URL = "/api/v1/user/stats"
PROFILE_URL = "/api/v1/auth/profile"
AVATAR_URL = "/api/v1/auth/avatar"
PASSWORD_URL = "/api/v1/auth/password"
LOGIN_URL = "/api/v1/auth/login"

TODAY = datetime.now(APP_TIMEZONE).date()


# ---- 辅助函数 ----

async def _make_user(nickname: str = "profile01", password: str = "pass1234") -> User:
    """直接落库一个用户（绕过验证码流程），返回用户对象。"""
    return await User.create(nickname=nickname, password_hash=hash_password(password), is_active=True)


def _auth_headers(user: User) -> dict:
    """构造携带 JWT 的请求头。"""
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


async def _make_plant(user: User, name: str = "绿萝") -> Plant:
    """直接落库一株属于该用户的植物。"""
    return await Plant.create(user_id=user.id, name=name)


async def _make_record(user: User, plant: Plant, record_date, care_type: RecordType) -> PlantRecord:
    """直接落库一条打卡记录（用于构造历史/跨月数据）。"""
    return await PlantRecord.create(
        user_id=user.id,
        plant_id=plant.id,
        record_type=care_type,
        record_date=record_date,
    )


# ---- 权限校验（PRD 11.3）----

@pytest.mark.parametrize(
    ("method", "url", "payload"),
    [
        ("get", CALENDAR_URL, None),
        ("get", STATS_URL, None),
        ("put", PROFILE_URL, {"nickname": "no_login"}),
        ("put", PASSWORD_URL, {"old_password": "pass1234", "new_password": "newpass1234"}),
    ],
)
async def test_profile_endpoints_require_token(client, method, url, payload):
    """未携带 Token 访问个人中心相关接口统一返回 401。"""
    resp = await (
        client.request(method, url, json=payload) if payload else client.request(method, url)
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "401"


# ---- 个人资料（FR-506）----

async def test_update_nickname_success(client):
    """修改昵称成功：返回新昵称并落库。"""
    user = await _make_user("nick_old")
    resp = await client.put(
        PROFILE_URL, json={"nickname": "nick_new"}, headers=_auth_headers(user)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "200"
    assert body["data"]["nickname"] == "nick_new"

    await user.refresh_from_db()
    assert user.nickname == "nick_new"


async def test_update_nickname_duplicate(client):
    """修改为他人已占用昵称返回 409 与中文提示。"""
    user_a = await _make_user("nick_a")
    await _make_user("nick_b")

    resp = await client.put(PROFILE_URL, json={"nickname": "nick_b"}, headers=_auth_headers(user_a))
    assert resp.status_code == 409
    body = resp.json()
    assert body["code"] == "409"
    assert "昵称" in body["msg"]


async def test_update_nickname_invalid_format(client):
    """昵称格式非法（过短 / 含中文）返回 400。"""
    user = await _make_user("nick_fmt")

    resp = await client.put(PROFILE_URL, json={"nickname": "ab"}, headers=_auth_headers(user))
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"

    resp = await client.put(PROFILE_URL, json={"nickname": "中文昵称"}, headers=_auth_headers(user))
    assert resp.status_code == 400


async def test_update_avatar_url(client):
    """头像上传后回写 avatar_url 成功。"""
    user = await _make_user("avatar01")
    avatar = "/static/uploads/avatar_abc.png"

    resp = await client.put(PROFILE_URL, json={"avatar_url": avatar}, headers=_auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"]["avatar_url"] == avatar

    await user.refresh_from_db()
    assert user.avatar_url == avatar


async def test_update_avatar_removes_old_file(client, monkeypatch, tmp_path):
    """头像更新成功后自动删除旧头像文件，新头像文件保留（释放磁盘空间）。"""
    from types import SimpleNamespace

    from app.services import image_storage

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(image_storage, "get_settings", lambda: SimpleNamespace(upload_dir=upload_dir))

    user = await _make_user("avatar_cleanup")
    old_name, new_name = "old_avatar.png", "new_avatar.png"
    (upload_dir / old_name).write_bytes(b"old")
    (upload_dir / new_name).write_bytes(b"new")
    user.avatar_url = f"/static/uploads/{old_name}"
    await user.save(update_fields=["avatar_url"])

    resp = await client.put(
        PROFILE_URL,
        json={"avatar_url": f"/static/uploads/{new_name}"},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    assert not (upload_dir / old_name).exists()
    assert (upload_dir / new_name).exists()


async def test_update_avatar_keeps_referenced_file(client, monkeypatch, tmp_path):
    """旧头像 URL 仍被打卡图片引用时不删除，避免误删业务图片。"""
    import json
    from types import SimpleNamespace

    from app.services import image_storage

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(image_storage, "get_settings", lambda: SimpleNamespace(upload_dir=upload_dir))

    user = await _make_user("avatar_shared")
    old_name, new_name = "shared.png", "new_avatar.png"
    old_url = f"/static/uploads/{old_name}"
    (upload_dir / old_name).write_bytes(b"shared")
    (upload_dir / new_name).write_bytes(b"new")
    user.avatar_url = old_url
    await user.save(update_fields=["avatar_url"])

    plant = await _make_plant(user)
    await PlantRecord.create(
        user_id=user.id,
        plant_id=plant.id,
        record_type=RecordType.WATERING,
        record_date=TODAY,
        image_url=json.dumps([old_url]),
    )

    resp = await client.put(
        PROFILE_URL,
        json={"avatar_url": f"/static/uploads/{new_name}"},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    assert (upload_dir / old_name).exists()


async def test_upload_avatar_atomic_replaces_old(client, monkeypatch, tmp_path):
    """原子头像接口：上传成功即落库并删除旧头像文件。"""
    from types import SimpleNamespace

    from app.services import image_storage

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(image_storage, "get_settings", lambda: SimpleNamespace(upload_dir=upload_dir))

    user = await _make_user("avatar_atomic")
    old = upload_dir / "old_avatar.png"
    old.write_bytes(b"old")
    user.avatar_url = "/static/uploads/old_avatar.png"
    await user.save(update_fields=["avatar_url"])

    resp = await client.put(
        AVATAR_URL,
        files={"file": ("new.png", b"\x89PNG\r\n\x1a\nfake-image", "image/png")},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    new_url = resp.json()["data"]["avatar_url"]
    assert new_url.startswith("/static/uploads/")
    assert (upload_dir / new_url.rsplit("/", 1)[-1]).exists()
    assert not old.exists()

    await user.refresh_from_db()
    assert user.avatar_url == new_url


async def test_upload_avatar_rollback_when_save_fails(client, monkeypatch, tmp_path):
    """落库失败时回滚新上传文件：旧头像保留，上传目录不残留孤儿文件。"""
    from types import SimpleNamespace

    from tortoise.exceptions import IntegrityError

    from app.services import image_storage

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(image_storage, "get_settings", lambda: SimpleNamespace(upload_dir=upload_dir))

    user = await _make_user("avatar_rollback")
    old = upload_dir / "old_avatar.png"
    old.write_bytes(b"old")
    user.avatar_url = "/static/uploads/old_avatar.png"
    await user.save(update_fields=["avatar_url"])

    async def _fail_save(self, *args, **kwargs):
        raise IntegrityError("save failed")

    monkeypatch.setattr(User, "save", _fail_save)

    resp = await client.put(
        AVATAR_URL,
        files={"file": ("new.png", b"\x89PNG\r\n\x1a\nfake-image", "image/png")},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 500
    assert resp.json()["code"] == "500"
    assert old.exists()
    assert sorted(p.name for p in upload_dir.iterdir()) == ["old_avatar.png"]

    await user.refresh_from_db()
    assert user.avatar_url == "/static/uploads/old_avatar.png"



async def test_delete_upload_image_safety(monkeypatch, tmp_path):
    """删除服务安全边界：外部 URL 忽略、路径穿越拒绝、本地上传文件正常删除。"""
    from types import SimpleNamespace

    from app.services import image_storage

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(image_storage, "get_settings", lambda: SimpleNamespace(upload_dir=upload_dir))

    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"secret")
    local = upload_dir / "old.png"
    local.write_bytes(b"old")

    assert image_storage.delete_upload_image(None) is False
    assert image_storage.delete_upload_image("https://example.com/a.png") is False
    assert image_storage.delete_upload_image("/static/uploads/../secret.txt") is False
    assert secret.exists()
    assert image_storage.delete_upload_image("/static/uploads/old.png") is True
    assert not local.exists()
    assert image_storage.delete_upload_image("/static/uploads/old.png") is False


# ---- 修改密码（PRD 5.1 / BR-02）----

async def test_change_password_success_and_login(client):
    """修改密码成功：新密码可登录，旧密码失效。"""
    user = await _make_user("pwd_user", password="pass1234")

    resp = await client.put(
        PASSWORD_URL,
        json={"old_password": "pass1234", "new_password": "newpass1234"},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    assert resp.json()["code"] == "200"

    resp = await client.post(LOGIN_URL, json={"nickname": "pwd_user", "password": "newpass1234"})
    assert resp.status_code == 200
    assert resp.json()["data"]["access_token"]

    resp = await client.post(LOGIN_URL, json={"nickname": "pwd_user", "password": "pass1234"})
    assert resp.status_code == 400


async def test_change_password_wrong_old(client):
    """原密码错误返回 400 与中文提示。"""
    user = await _make_user("pwd_wrong")

    resp = await client.put(
        PASSWORD_URL,
        json={"old_password": "wrong1234", "new_password": "newpass1234"},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 400
    assert "原密码错误" in resp.json()["msg"]


async def test_change_password_weak(client):
    """新密码不含字母（强度不足）返回 400（PRD FR-107 口径）。"""
    user = await _make_user("pwd_weak")

    resp = await client.put(
        PASSWORD_URL,
        json={"old_password": "pass1234", "new_password": "12345678"},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"


async def test_change_password_missing_fields(client):
    """修改密码缺少必填字段返回 400（参数缺失场景）。"""
    user = await _make_user("pwd_missing")

    resp = await client.put(PASSWORD_URL, json={"old_password": "pass1234"}, headers=_auth_headers(user))
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"


async def test_update_nickname_race_conflict(client, monkeypatch):
    """并发改名竞态：唯一约束兜底异常转为 409，不暴露 500。"""
    from tortoise.exceptions import IntegrityError

    user = await _make_user("nick_race")

    async def _conflict_save(self, *args, **kwargs):
        raise IntegrityError("duplicate nickname")

    monkeypatch.setattr(User, "save", _conflict_save)
    resp = await client.put(PROFILE_URL, json={"nickname": "race_new"}, headers=_auth_headers(user))
    assert resp.status_code == 409
    assert resp.json()["code"] == "409"


# ---- 打卡日历（FR-501）----

async def test_calendar_default_current_month(client):
    """不传 month 默认当月，仅返回本月打卡日期并按天聚合。"""
    user = await _make_user("cal_default")
    plant = await _make_plant(user)
    await _make_record(user, plant, TODAY, RecordType.WATERING)
    await _make_record(user, plant, TODAY, RecordType.FERTILIZING)
    # 上月记录不应出现在当月日历中（若今天是月初，仍能验证区间隔离）
    await _make_record(user, plant, TODAY - timedelta(days=30), RecordType.PRUNING)

    resp = await client.get(CALENDAR_URL, headers=_auth_headers(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["month"] == TODAY.strftime("%Y-%m")
    today_cell = next((day for day in data["days"] if day["date"] == TODAY.isoformat()), None)
    assert today_cell is not None
    assert today_cell["count"] == 2
    assert today_cell["types"] == ["fertilizing", "watering"]
    assert data["checkin_count"] >= 2


async def test_calendar_specific_month_and_isolation(client):
    """指定月份：返回该月记录，且不包含他人数据（数据隔离）。"""
    user_a = await _make_user("cal_a")
    user_b = await _make_user("cal_b")
    plant_a = await _make_plant(user_a, "A的绿萝")
    plant_b = await _make_plant(user_b, "B的绿萝")

    month_key = TODAY.strftime("%Y-%m")
    await _make_record(user_a, plant_a, TODAY, RecordType.WATERING)
    await _make_record(user_b, plant_b, TODAY, RecordType.PEST_CONTROL)

    resp = await client.get(
        CALENDAR_URL, params={"month": month_key}, headers=_auth_headers(user_a)
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    dates = {day["date"]: day for day in data["days"]}
    assert TODAY.isoformat() in dates
    assert dates[TODAY.isoformat()]["types"] == ["watering"]
    assert data["checkin_count"] == 1
    assert data["active_days"] == 1


async def test_calendar_invalid_month(client):
    """非法月份格式返回 400 与中文提示。"""
    user = await _make_user("cal_bad")

    for bad in ("2026-13", "2026-1", "abc"):
        resp = await client.get(CALENDAR_URL, params={"month": bad}, headers=_auth_headers(user))
        assert resp.status_code == 400, bad
        assert resp.json()["code"] == "400"
        assert "月份格式" in resp.json()["msg"]


# ---- 打卡统计（FR-505）----

async def test_stats_streak_and_summary(client):
    """连续打卡 3 天：streak=3，总量与类型分布正确。"""
    user = await _make_user("stats_ok")
    plant = await _make_plant(user)
    dates = [TODAY, TODAY - timedelta(days=1), TODAY - timedelta(days=2)]
    await _make_record(user, plant, dates[0], RecordType.WATERING)
    await _make_record(user, plant, dates[1], RecordType.WATERING)
    await _make_record(user, plant, dates[2], RecordType.FERTILIZING)

    resp = await client.get(STATS_URL, headers=_auth_headers(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["streak_days"] == 3
    assert data["total_checkin_count"] == 3
    assert data["total_active_days"] == 3
    assert data["plant_count"] == 1

    same_month = [day for day in dates if (day.year, day.month) == (TODAY.year, TODAY.month)]
    assert data["month_checkin_count"] == len(same_month)
    assert data["month_active_days"] == len(set(same_month))

    type_map = {item["type"]: item for item in data["type_counts"]}
    assert type_map["watering"]["count"] == 2
    assert type_map["watering"]["label"] == "浇水"
    assert type_map["fertilizing"]["count"] == 1


async def test_stats_streak_counts_from_yesterday(client):
    """今天未打卡时从昨天向前回溯（给当天补打卡留余地）。"""
    user = await _make_user("stats_yesterday")
    plant = await _make_plant(user)
    await _make_record(user, plant, TODAY - timedelta(days=1), RecordType.WATERING)
    await _make_record(user, plant, TODAY - timedelta(days=2), RecordType.WATERING)

    data = (await client.get(STATS_URL, headers=_auth_headers(user))).json()["data"]
    assert data["streak_days"] == 2


async def test_stats_streak_broken(client):
    """最近两天无打卡 → 连续天数为 0。"""
    user = await _make_user("stats_break")
    plant = await _make_plant(user)
    await _make_record(user, plant, TODAY - timedelta(days=3), RecordType.WATERING)

    data = (await client.get(STATS_URL, headers=_auth_headers(user))).json()["data"]
    assert data["streak_days"] == 0


async def test_stats_isolated_between_users(client):
    """统计仅计算本人数据，他人打卡不计入。"""
    user_a = await _make_user("stats_a")
    user_b = await _make_user("stats_b")
    plant_a = await _make_plant(user_a)
    plant_b = await _make_plant(user_b)
    await _make_record(user_a, plant_a, TODAY, RecordType.WATERING)
    await _make_record(user_b, plant_b, TODAY, RecordType.WATERING)

    data = (await client.get(STATS_URL, headers=_auth_headers(user_a))).json()["data"]
    assert data["total_checkin_count"] == 1
    assert data["plant_count"] == 1


# ---- 撤销打卡（FR-503）----

async def test_delete_today_checkin(client: AsyncClient):
    """撤销当天打卡成功，记录删除且统计同步减少。"""
    user = await _make_user("del_today")
    plant = await _make_plant(user)
    record = await _make_record(user, plant, TODAY, RecordType.WATERING)

    resp = await client.delete(f"{CHECKINS_URL}/{record.id}", headers=_auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["code"] == "200"
    assert await PlantRecord.get_or_none(id=record.id) is None

    data = (await client.get(STATS_URL, headers=_auth_headers(user))).json()["data"]
    assert data["total_checkin_count"] == 0
    assert data["streak_days"] == 0

    calendar = (await client.get(CALENDAR_URL, headers=_auth_headers(user))).json()["data"]
    assert calendar["days"] == []


async def test_delete_history_checkin_rejected(client):
    """撤销非当天记录返回 400（PRD 5.5.3-5）。"""
    user = await _make_user("del_history")
    plant = await _make_plant(user)
    record = await _make_record(user, plant, TODAY - timedelta(days=1), RecordType.WATERING)

    resp = await client.delete(f"{CHECKINS_URL}/{record.id}", headers=_auth_headers(user))
    assert resp.status_code == 400
    assert "仅允许撤销当天" in resp.json()["msg"]
    assert await PlantRecord.get_or_none(id=record.id) is not None


async def test_delete_others_checkin_forbidden(client):
    """撤销他人记录返回 403（数据隔离 BR-02）。"""
    user_a = await _make_user("del_a")
    user_b = await _make_user("del_b")
    plant_b = await _make_plant(user_b)
    record = await _make_record(user_b, plant_b, TODAY, RecordType.WATERING)

    resp = await client.delete(f"{CHECKINS_URL}/{record.id}", headers=_auth_headers(user_a))
    assert resp.status_code == 403
    assert "无权" in resp.json()["msg"]
    assert await PlantRecord.get_or_none(id=record.id) is not None


async def test_delete_missing_checkin(client):
    """撤销不存在的记录返回 404。"""
    user = await _make_user("del_missing")

    resp = await client.delete(f"{CHECKINS_URL}/999999", headers=_auth_headers(user))
    assert resp.status_code == 404
    assert "不存在" in resp.json()["msg"]