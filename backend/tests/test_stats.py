"""统计与指标模块单元测试（PRD 5.3 / 11 对应用例）。

覆盖：
- 权限：未登录 401、他人植物 403、植物不存在 404；
- 指标录入：成功、越界中文提示、全部为空、未来日期、同日覆盖；
- 指标查询：按天聚合平均；
- 统计：长势健康分/异常告警、浇水/施肥次数、光照平均、时间区间、
  空数据、非法维度与区间。

注意：沙箱无法运行 asyncio，请在本地终端执行 pytest。
"""

from datetime import date, datetime, time, timedelta

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.core.timezone import APP_TIMEZONE
from app.models.plant import Plant
from app.models.plant_metric import PlantMetric
from app.models.user import User

pytestmark = pytest.mark.asyncio


def _metrics_url(plant_id: int) -> str:
    return f"/api/v1/plants/{plant_id}/metrics"


def _stats_url(plant_id: int) -> str:
    return f"/api/v1/plants/{plant_id}/stats"


async def _make_user(nickname: str = "stats_user") -> User:
    """直接落库用户（绕过验证码），返回用户对象。"""
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


async def _create_metric(
    client: AsyncClient,
    user: User,
    plant_id: int,
    record_date: date | None = None,
    **metrics,
) -> dict:
    """录入指标的便捷封装。"""
    payload = {**metrics}
    if record_date is not None:
        payload["record_date"] = record_date.isoformat()
    return await client.post(_metrics_url(plant_id), json=payload, headers=_auth_headers(user))


async def _get_stats(
    client: AsyncClient,
    user: User,
    plant_id: int,
    dimension: str = "growth",
    days: int = 30,
) -> dict:
    """查询统计接口的便捷封装。"""
    return await client.get(
        _stats_url(plant_id),
        params={"dimension": dimension, "days": days},
        headers=_auth_headers(user),
    )


# ---- 权限校验（PRD 11.3）----

async def test_stats_requires_token(client):
    """未登录访问统计接口返回 401。"""
    resp = await client.get(_stats_url(1))
    assert resp.status_code == 401
    assert resp.json()["code"] == "401"


async def test_metrics_requires_token(client):
    """未登录访问指标接口返回 401。"""
    resp = await client.get(_metrics_url(1))
    assert resp.status_code == 401
    assert resp.json()["code"] == "401"


async def test_stats_other_user_plant(client):
    """查询他人植物统计返回 403（数据隔离）。"""
    user_a = await _make_user("stats_own")
    user_b = await _make_user("stats_other")
    plant_b = await _make_plant(user_b, "他人绿萝")

    resp = await _get_stats(client, user_a, plant_b.id)
    assert resp.status_code == 403, resp.json()
    assert resp.json()["code"] == "403"


async def test_stats_plant_not_found(client):
    """不存在的植物返回 404。"""
    user = await _make_user("stats_nf")
    resp = await _get_stats(client, user, 99999)
    assert resp.status_code == 404
    assert resp.json()["code"] == "404"


# ---- 指标录入（FR-301）----

async def test_create_metric_success(client):
    """录入全部指标成功，返回指标值。"""
    user = await _make_user("metric_ok")
    plant = await _make_plant(user)

    resp = await _create_metric(
        client,
        user,
        plant.id,
        temperature=25,
        humidity=50,
        light=20000,
        soil_moisture=45,
        ph=6.2,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "200"
    assert body["data"]["temperature"] == 25
    assert body["data"]["plant_id"] == plant.id


async def test_create_metric_out_of_range(client):
    """指标越界返回 400 且为中文提示（PRD 5.3.3/10.2.3）。"""
    user = await _make_user("metric_range")
    plant = await _make_plant(user)

    resp = await _create_metric(client, user, plant.id, temperature=100)
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"
    assert "温度" in resp.json()["msg"]


async def test_create_metric_requires_one_value(client):
    """五项全空返回 400。"""
    user = await _make_user("metric_empty")
    plant = await _make_plant(user)

    resp = await _create_metric(client, user, plant.id)
    assert resp.status_code == 400
    assert "至少" in resp.json()["msg"]


async def test_create_metric_future_date(client):
    """未来日期录入指标返回 400。"""
    user = await _make_user("metric_future")
    plant = await _make_plant(user)

    resp = await _create_metric(
        client, user, plant.id,
        record_date=datetime.now(APP_TIMEZONE).date() + timedelta(days=1),
        temperature=20,
    )
    assert resp.status_code == 400
    assert "未来" in resp.json()["msg"]


async def test_create_metric_same_day_overwrite(client):
    """同植物同日再次录入视为覆盖更新（PRD 5.3.3），不产生重复记录。"""
    user = await _make_user("metric_overwrite")
    plant = await _make_plant(user)

    first = await _create_metric(client, user, plant.id, temperature=20, humidity=50)
    assert first.status_code == 200

    second = await _create_metric(client, user, plant.id, temperature=26)
    assert second.status_code == 200
    body = second.json()
    assert "覆盖" in body["msg"]
    # 整条覆盖：第二次未填写的湿度应被清空
    assert body["data"]["temperature"] == 26
    assert body["data"]["humidity"] is None

    # 统计接口只有一天数据，健康分按新值重新计算
    stats = await _get_stats(client, user, plant.id, "growth", 7)
    data = stats.json()["data"]
    valid_points = [p for p in data["points"] if p["value"] is not None]
    assert len(valid_points) == 1
    assert valid_points[0]["value"] == 100


# ---- 指标聚合查询（FR-302）----

async def test_list_metrics_daily_average(client):
    """指标查询：同一自然日多条记录按项求平均（PRD 5.3.3），返回连续日期序列。"""
    user = await _make_user("metric_avg")
    plant = await _make_plant(user)
    today = datetime.now(APP_TIMEZONE).date()

    # 直接落库两条同日记录（模拟历史多条数据，绕过录入接口的覆盖逻辑）
    first = await PlantMetric.create(user_id=user.id, plant_id=plant.id, temperature=20)
    await PlantMetric.filter(id=first.id).update(
        record_time=datetime.combine(today, time(9, 0), tzinfo=APP_TIMEZONE)
    )
    second = await PlantMetric.create(user_id=user.id, plant_id=plant.id, temperature=30)
    await PlantMetric.filter(id=second.id).update(
        record_time=datetime.combine(today, time(15, 0), tzinfo=APP_TIMEZONE)
    )

    resp = await client.get(
        _metrics_url(plant.id), params={"days": 7}, headers=_auth_headers(user)
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["days"] == 7
    assert len(data["points"]) == 7
    by_date = {p["date"]: p for p in data["points"]}
    # 同一天两条记录 (20 + 30) / 2 = 25
    assert by_date[today.isoformat()]["temperature"] == 25


# ---- 长势统计（FR-302 / FR-304）----

async def test_stats_growth_score_and_alerts(client):
    """长势：正常指标折算 100 分；光照异常后分数下降并返回中文告警。"""
    user = await _make_user("stats_growth")
    plant = await _make_plant(user)

    await _create_metric(
        client,
        user,
        plant.id,
        temperature=25,
        humidity=50,
        light=20000,
        soil_moisture=45,
        ph=6.2,
    )
    resp = await _get_stats(client, user, plant.id, "growth", 7)
    data = resp.json()["data"]
    today_point = data["points"][-1]
    assert data["chart_type"] == "line"
    assert data["unit"] == "分"
    assert data["has_data"] is True
    assert today_point["value"] == 100
    assert today_point["status"] == "normal"
    assert today_point["alerts"] == []

    # 覆盖为光照异常：正常 100×4 + 异常 20 = 84.0
    await _create_metric(
        client,
        user,
        plant.id,
        temperature=25,
        humidity=50,
        light=1000,
        soil_moisture=45,
        ph=6.2,
    )
    resp = await _get_stats(client, user, plant.id, "growth", 7)
    today_point = resp.json()["data"]["points"][-1]
    assert today_point["value"] == 84.0
    assert today_point["status"] == "abnormal"
    assert any("光照" in alert for alert in today_point["alerts"])


async def test_stats_growth_empty(client):
    """无指标数据：has_data=false，所有长势点 value 为 null。"""
    user = await _make_user("stats_empty")
    plant = await _make_plant(user)

    resp = await _get_stats(client, user, plant.id, "growth", 7)
    data = resp.json()["data"]
    assert data["has_data"] is False
    assert len(data["points"]) == 7
    assert all(point["value"] is None for point in data["points"])


# ---- 浇水/施肥统计（FR-303）----

async def test_stats_watering_counts(client):
    """浇水统计：按自然日返回打卡次数与备注；无备注/空白备注返回 null。"""
    user = await _make_user("stats_water")
    plant = await _make_plant(user)
    today = datetime.now(APP_TIMEZONE).date()
    yesterday = today - timedelta(days=1)
    contents = {today: "浇透水 200ml", yesterday: "   "}

    for record_date in (today, yesterday):
        resp = await client.post(
            "/api/v1/checkins",
            json={
                "plant_id": plant.id,
                "care_type": "watering",
                "content": contents[record_date],
                "record_date": record_date.isoformat(),
            },
            headers=_auth_headers(user),
        )
        assert resp.status_code == 200

    resp = await _get_stats(client, user, plant.id, "watering", 7)
    data = resp.json()["data"]
    assert data["chart_type"] == "bar"
    assert data["unit"] == "次"
    assert data["summary"]["total"] == 2
    assert data["summary"]["average"] == round(2 / 7, 2)
    assert data["summary"]["max"] == 1
    assert data["summary"]["latest"] == 1
    # X 轴连续 7 天，今天与昨天各 1 次；备注随统计点返回
    by_date = {p["date"]: p for p in data["points"]}
    assert by_date[today.isoformat()]["count"] == 1
    assert by_date[today.isoformat()]["content"] == "浇透水 200ml"
    assert by_date[yesterday.isoformat()]["count"] == 1
    assert by_date[yesterday.isoformat()]["content"] is None


async def test_stats_fertilizing_isolated_by_plant(client):
    """施肥统计只统计指定植物，其他植物打卡不计入。"""
    user = await _make_user("stats_fert")
    plant_a = await _make_plant(user, "绿萝")
    plant_b = await _make_plant(user, "发财树")

    for plant_id in (plant_a.id, plant_b.id):
        resp = await client.post(
            "/api/v1/checkins",
            json={"plant_id": plant_id, "care_type": "fertilizing"},
            headers=_auth_headers(user),
        )
        assert resp.status_code == 200

    resp = await _get_stats(client, user, plant_a.id, "fertilizing", 7)
    data = resp.json()["data"]
    assert data["summary"]["total"] == 1
    assert data["points"][-1]["count"] == 1


# ---- 光照统计 ----

async def test_stats_light_average(client):
    """光照统计：按天返回平均光照，汇总平均为有数据天的均值。"""
    user = await _make_user("stats_light")
    plant = await _make_plant(user)
    today = datetime.now(APP_TIMEZONE).date()

    await _create_metric(client, user, plant.id, record_date=today, light=20000)
    await _create_metric(
        client, user, plant.id, record_date=today - timedelta(days=1), light=30000
    )

    resp = await _get_stats(client, user, plant.id, "light", 7)
    data = resp.json()["data"]
    assert data["chart_type"] == "bar"
    assert data["unit"] == "lux"
    assert data["summary"]["total"] == 2
    assert data["summary"]["average"] == 25000
    assert data["summary"]["max"] == 30000
    by_date = {p["date"]: p for p in data["points"]}
    assert by_date[today.isoformat()]["value"] == 20000


# ---- 参数校验 ----

@pytest.mark.parametrize(
    "params",
    [
        {"dimension": "unknown"},
        {"dimension": "growth", "days": 10},
    ],
)
async def test_stats_invalid_params(client, params):
    """非法维度或非法时间区间返回 400（PRD 10.2.3）。"""
    user = await _make_user("stats_params")
    plant = await _make_plant(user)

    resp = await client.get(_stats_url(plant.id), params=params, headers=_auth_headers(user))
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"