"""数据图表模块路由（PRD 5.3 / 9.7 P3 接口清单）。

覆盖：
- POST /plants/{plant_id}/metrics：指标录入（同一植物同一天再次录入视为覆盖更新）
- GET  /plants/{plant_id}/metrics：指标按天聚合趋势（近 7/30/90 天）

数据层：Tortoise-ORM 异步查询，强制 user_id 过滤（PRD 7.3 数据隔离）。
区间校验在路由层完成，保证越界返回统一中文提示（PRD 5.3.3 / 10.2.3）。
"""

from datetime import datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser
from app.core.response import BizException, success
from app.core.timezone import APP_TIMEZONE, local_day_end, local_day_start
from app.models.plant_metric import PlantMetric
from app.schemas.metric import MetricCreate, MetricDailyPoint, MetricOut
from app.services.plant_access import get_owned_plant
from app.services.plant_stats import (
    METRIC_KEYS,
    aggregate_metric_days,
    build_date_series,
)

router = APIRouter()

# PRD 5.3.3 指标合法区间：字段名 → (最小值, 最大值, 中文提示)
METRIC_RANGES: dict[str, tuple[float, float, str]] = {
    "temperature": (-20, 60, "温度需在 -20~60℃ 之间"),
    "humidity": (0, 100, "空气湿度需在 0~100% 之间"),
    "light": (0, 200000, "光照需在 0~200000 lux 之间"),
    "soil_moisture": (0, 100, "土壤湿度需在 0~100% 之间"),
    "ph": (0, 14, "pH 需在 0~14 之间"),
}


# 支持的时间区间（天）；用 int 接收后手动校验，避免 Literal[int] 对 query 字符串误判
VALID_DAYS: tuple[int, ...] = (7, 30, 90)



def _validate_metric_ranges(body: MetricCreate) -> None:
    """校验指标合法区间与「至少填写一项」（PRD 5.3.3/5.3.5）。"""
    provided = [key for key in METRIC_KEYS if getattr(body, key) is not None]
    if not provided:
        raise BizException("400", "请至少填写一项养护指标", status_code=400)

    for key in provided:
        value = getattr(body, key)
        low, high, message = METRIC_RANGES[key]
        if value < low or value > high:
            raise BizException("400", message, status_code=400)


@router.post("/{plant_id}/metrics")
async def create_metric(plant_id: int, body: MetricCreate, user: CurrentUser) -> dict:
    """录入养护指标（PRD FR-301）。

    - 植物必须属于当前用户：不存在 404 / 非本人 403；
    - 日期规则：默认当天，禁止未来日期；
    - 覆盖规则：同植物同一天再次录入视为更新（PRD 5.3.3）。
    """
    await get_owned_plant(plant_id, user.id)

    today = datetime.now(APP_TIMEZONE).date()
    record_date = body.record_date or today
    if record_date > today:
        raise BizException("400", "不能录入未来日期的指标", status_code=400)

    _validate_metric_ranges(body)

    # 整条覆盖：未填写的指标置空，避免新旧数据混合产生错误均值
    values = {key: getattr(body, key) for key in METRIC_KEYS}

    existing = await (
        PlantMetric.filter(
            user_id=user.id,
            plant_id=plant_id,
            record_time__gte=local_day_start(record_date),
            record_time__lt=local_day_end(record_date),
        )
        .order_by("-record_time")
        .first()
    )

    if existing is not None:
        for key, value in values.items():
            setattr(existing, key, value)
        await existing.save()
        return success(MetricOut.model_validate(existing).model_dump(), "指标已更新（同日录入自动覆盖）")

    # 历史日期录入：先创建再回写 record_time，避免 auto_now_add 覆盖传入时间
    metric = await PlantMetric.create(
        user_id=user.id,
        plant_id=plant_id,
        **values,
    )
    if record_date != today:
        await PlantMetric.filter(id=metric.id).update(
            record_time=datetime.combine(record_date, time(12, 0), tzinfo=APP_TIMEZONE)
        )
        metric = await PlantMetric.get(id=metric.id)

    return success(MetricOut.model_validate(metric).model_dump(), "指标录入成功")


@router.get("/{plant_id}/metrics")
async def list_metrics(
    plant_id: int,
    user: CurrentUser,
    days: Annotated[int, Query(description="统计区间：近 7/30/90 天")] = 30,
) -> dict:
    """指标按天聚合趋势（PRD FR-302）。

    聚合口径：同一自然日多条记录按指标求平均（PRD 5.3.3）。
    返回连续日期序列，未录入的日期各项指标为 null，前端据此绘制断点趋势。
    """
    if days not in VALID_DAYS:
        raise BizException("400", "时间区间仅支持近7天、近30天或近90天", status_code=400)

    await get_owned_plant(plant_id, user.id)

    end_date = datetime.now(APP_TIMEZONE).date()
    start_date = end_date - timedelta(days=days - 1)
    records = await PlantMetric.filter(
        user_id=user.id,
        plant_id=plant_id,
        record_time__gte=local_day_start(start_date),
        record_time__lt=local_day_end(end_date),
    ).order_by("record_time")

    aggregated = aggregate_metric_days(records)
    points: list[dict] = []
    for day in build_date_series(start_date, end_date):
        values = aggregated.get(day, {})
        points.append(
            MetricDailyPoint(
                date=day.isoformat(),
                **{key: values.get(key) for key in METRIC_KEYS},
            ).model_dump()
        )

    return success(
        {
            "days": days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "total_records": len(records),
            "points": points,
        },
        "查询成功",
    )