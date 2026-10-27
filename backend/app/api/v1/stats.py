"""统计聚合路由（PRD 5.3 P3 数据图表）。

接口：GET /plants/{plant_id}/stats?dimension=growth&days=30
- dimension=growth：长势健康分折线（按 PRD 5.3.3 阈值折算）
- dimension=watering / fertilizing：按自然日打卡次数柱状
- dimension=light：按自然日平均光照柱状

数据权限：仅能查询本人植物（404/403，PRD 7.3）。
"""

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser
from app.core.response import BizException, success
from app.core.timezone import APP_TIMEZONE, local_day_end, local_day_start
from app.models.plant_metric import PlantMetric
from app.models.plant_record import PlantRecord, RecordType
from app.schemas.stats import (
    DIMENSION_LABELS,
    StatsDimension,
    StatsOut,
    StatsPlant,
    StatsPoint,
    StatsSummary,
)
from app.services.plant_access import get_owned_plant
from app.services.plant_stats import (
    METRIC_KEYS,
    aggregate_metric_days,
    build_date_series,
    build_growth_point,
    summarize_values,
)

router = APIRouter()

# 支持的时间区间（天）；query 用 int 接收后手动校验，
# 避免 Literal[int] 在 FastAPI query 中把 "30" 当字符串导致误判。
VALID_DAYS: tuple[int, ...] = (7, 30, 90)

# 维度 → 单位 / 图表类型（长势折线、其余柱状）
DIMENSION_META: dict[StatsDimension, dict[str, str]] = {
    StatsDimension.GROWTH: {"unit": "分", "chart_type": "line"},
    StatsDimension.WATERING: {"unit": "次", "chart_type": "bar"},
    StatsDimension.FERTILIZING: {"unit": "次", "chart_type": "bar"},
    StatsDimension.LIGHT: {"unit": "lux", "chart_type": "bar"},
}

# 打卡维度 → 记录枚举（PRD care_type 口径）
CHECKIN_DIMENSIONS: dict[StatsDimension, RecordType] = {
    StatsDimension.WATERING: RecordType.WATERING,
    StatsDimension.FERTILIZING: RecordType.FERTILIZING,
}



async def _build_metric_points(
    user_id: int,
    plant_id: int,
    dimension: StatsDimension,
    start_date: date,
    end_date: date,
) -> list[StatsPoint]:
    """长势/光照维度：按天聚合指标并生成统计点。"""
    records = await PlantMetric.filter(
        user_id=user_id,
        plant_id=plant_id,
        record_time__gte=local_day_start(start_date),
        record_time__lt=local_day_end(end_date),
    ).order_by("record_time")
    aggregated = aggregate_metric_days(records)

    points: list[StatsPoint] = []
    for day in build_date_series(start_date, end_date):
        day_values = aggregated.get(day, {})

        if dimension == StatsDimension.GROWTH:
            growth = build_growth_point(day_values)
            metrics = {key: day_values[key] for key in METRIC_KEYS if key in day_values}
            points.append(
                StatsPoint(
                    date=day.isoformat(),
                    value=growth["value"],
                    status=growth["status"],
                    alerts=growth["alerts"],
                    metrics=metrics or None,
                )
            )
            continue

        # 光照统计：只取当日平均光照
        light_value = day_values.get("light")
        points.append(StatsPoint(date=day.isoformat(), value=light_value))

    return points


async def _build_checkin_points(
    user_id: int,
    plant_id: int,
    record_type: RecordType,
    start_date: date,
    end_date: date,
) -> list[StatsPoint]:
    """浇水/施肥维度：按自然日统计打卡次数，并携带当日备注（plant_record.content）。"""
    rows = await PlantRecord.filter(
        user_id=user_id,
        plant_id=plant_id,
        record_type=record_type,
        record_date__gte=start_date,
        record_date__lte=end_date,
    ).values("record_date", "content")

    counts = Counter(row["record_date"] for row in rows)
    # 无备注/纯空白统一转 None，前端 tooltip 据此不渲染备注行
    content_by_day = {
        row["record_date"]: (row["content"] or "").strip() or None for row in rows
    }
    points: list[StatsPoint] = []
    for day in build_date_series(start_date, end_date):
        count = int(counts.get(day, 0))
        points.append(
            StatsPoint(
                date=day.isoformat(),
                value=count,
                count=count,
                content=content_by_day.get(day),
            )
        )
    return points


@router.get("/{plant_id}/stats")
async def get_plant_stats(
    plant_id: int,
    user: CurrentUser,
    dimension: Annotated[
        StatsDimension, Query(description="统计维度：growth/watering/fertilizing/light")
    ] = StatsDimension.GROWTH,
    days: Annotated[int, Query(description="统计区间：近 7/30/90 天")] = 30,
) -> dict:
    """植物统计接口（PRD 5.3 数据图表）。

    返回连续自然日序列，确保折线/柱状图 X 轴完整；
    无数据的日期在长势/光照维度返回 null（折线断点），打卡维度返回 0。
    """
    if days not in VALID_DAYS:
        raise BizException("400", "时间区间仅支持近7天、近30天或近90天", status_code=400)

    plant = await get_owned_plant(plant_id, user.id)

    end_date = datetime.now(APP_TIMEZONE).date()
    start_date = end_date - timedelta(days=days - 1)

    if dimension in CHECKIN_DIMENSIONS:
        points = await _build_checkin_points(
            user.id, plant_id, CHECKIN_DIMENSIONS[dimension], start_date, end_date
        )
        # 打卡维度：全区间每个自然日都参与日均计算（无打卡日为 0）
        summary_values = [point.value or 0 for point in points]
        summary = summarize_values(summary_values, fixed_days=days, total_mode="sum")
        # "最近一次"取最近有打卡的日期，而不是今天（今天可能尚未打卡）
        summary["latest"] = next((value for value in reversed(summary_values) if value), None)
    else:
        points = await _build_metric_points(user.id, plant_id, dimension, start_date, end_date)
        # 指标维度：只统计有数据的日期，避免空白天拉低平均值
        summary_values = [point.value for point in points if point.value is not None]
        summary = summarize_values(summary_values, total_mode="count")

    meta = DIMENSION_META[dimension]
    has_data = summary["total"] > 0

    result = StatsOut(
        plant=StatsPlant(id=plant.id, name=plant.name),
        dimension=dimension,
        dimension_label=DIMENSION_LABELS[dimension],
        days=days,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        unit=meta["unit"],
        chart_type=meta["chart_type"],
        has_data=has_data,
        points=points,
        summary=StatsSummary(**summary),
    )
    return success(result.model_dump(mode="json"), "查询成功")