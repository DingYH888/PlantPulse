"""节点4：当前用户 + 当前植物的养护摘要（PRD 8.1 节点4 / 7.3 AI 上下文隔离）。

严格约束：
- 只查询当前 user_id 名下的指定植物，禁止跨用户拼接（PRD 7.3-3）；
- 植物不存在 404、非本人 403（复用 plant_access，口径与业务模块一致）；
- 无植物/无记录时显式标注"新用户"，禁止模型臆测历史操作。
"""

from datetime import datetime, timedelta

from app.ai.fallback import GENERAL_KNOWLEDGE
from app.core.timezone import APP_TIMEZONE
from app.models.plant import Plant
from app.models.plant_metric import PlantMetric
from app.models.plant_record import PlantRecord
from app.services.checkin_calendar import CARE_TYPE_LABELS, care_type_value
from app.services.plant_access import get_owned_plant

# PRD 5.3.3 通用正常区间（品种级阈值由 AI 建议另行覆盖，这里只做摘要提示）
METRIC_NORMAL_RANGES = {
    "temperature": (15.0, 30.0, "℃", "温度"),
    "humidity": (40.0, 70.0, "%", "空气湿度"),
    "soil_moisture": (30.0, 60.0, "%", "土壤湿度"),
    "light": (5000.0, 50000.0, "lux", "光照"),
    "ph": (5.5, 7.0, "", "pH"),
}


def _to_float(value) -> float | None:
    """Tortoise Decimal → float（None 原样返回）。"""
    return None if value is None else float(value)


def _metric_average(metrics: list[PlantMetric], field_name: str) -> float | None:
    """计算近 7 天某指标均值（忽略空值）。"""
    values = [_to_float(getattr(metric, field_name, None)) for metric in metrics]
    valid = [value for value in values if value is not None]
    return round(sum(valid) / len(valid), 2) if valid else None


def _metric_summary(metrics: list[PlantMetric]) -> tuple[list[str], list[str]]:
    """生成指标描述与异常提示。"""
    lines: list[str] = []
    warnings: list[str] = []
    for field_name, (low, high, unit, label) in METRIC_NORMAL_RANGES.items():
        average = _metric_average(metrics, field_name)
        if average is None:
            continue
        status = "正常" if low <= average <= high else "超出通用正常区间"
        lines.append(f"{label}均值 {average}{unit}（{status}）")
        if not low <= average <= high and field_name in {"soil_moisture", "humidity", "temperature"}:
            warnings.append(f"近7天{label}均值 {average}{unit}，超出通用正常区间 {low}~{high}{unit}")
    return lines, warnings


async def build_care_context(user_id: int, plant_id: int | None) -> dict:
    """构建节点4上下文，返回结构化摘要 + 可直接注入提示词的文本。"""
    context: dict = {
        "has_plant": False,
        "plant_id": plant_id,
        "plant_name": "",
        "species": "",
        "record_counts": {},
        "last_records": [],
        "metric_lines": [],
        "warnings": [],
        "summary": "",
    }

    if plant_id is None:
        context["summary"] = "用户本次未关联植物档案，没有打卡与指标数据（按新用户处理）。"
        return context

    plant: Plant = await get_owned_plant(plant_id, user_id)
    context.update(
        has_plant=True,
        plant_name=plant.name,
        species=plant.species or "",
    )

    today = datetime.now(APP_TIMEZONE).date()
    start_date = today - timedelta(days=30)
    records = await PlantRecord.filter(
        user_id=user_id,
        plant_id=plant_id,
        record_date__gte=start_date,
        record_date__lte=today,
    ).order_by("-record_date", "id")

    counts: dict[str, int] = {}
    last_records: list[dict] = []
    for record in records:
        care_type = care_type_value(record.record_type)
        counts[care_type] = counts.get(care_type, 0) + 1
        if len(last_records) < 5:
            last_records.append(
                {
                    "care_type": care_type,
                    "label": CARE_TYPE_LABELS.get(care_type, care_type),
                    "date": record.record_date.isoformat(),
                    "content": record.content or "",
                }
            )
    context["record_counts"] = counts
    context["last_records"] = last_records

    start_time = datetime.now(APP_TIMEZONE) - timedelta(days=7)
    metrics = await PlantMetric.filter(
        user_id=user_id,
        plant_id=plant_id,
        record_time__gte=start_time,
    ).order_by("-record_time")
    metric_lines, metric_warnings = _metric_summary(metrics)
    context["metric_lines"] = metric_lines
    context["warnings"] = metric_warnings

    # 组装中文摘要
    parts = [f"植物：{plant.name}" + (f"（品种：{plant.species}）" if plant.species else "")]
    if counts:
        count_text = "、".join(
            f"{CARE_TYPE_LABELS.get(care_type, care_type)} {count} 次" for care_type, count in counts.items()
        )
        parts.append(f"近30天打卡：{count_text}")
    if last_records:
        last = last_records[0]
        parts.append(f"最近一次养护：{last['date']} {last['label']}" + (f"（{last['content']}）" if last["content"] else ""))
    else:
        parts.append("近30天无打卡记录，按新用户处理，请勿臆测历史操作")
    if metric_lines:
        parts.append("近7天指标：" + "；".join(metric_lines))
    else:
        parts.append("近7天无指标记录")
    if metric_warnings:
        parts.append("异常提示：" + "；".join(metric_warnings))
    context["summary"] = "\n".join(parts)
    return context


def general_knowledge_text() -> str:
    """内置通用知识文本（节点3b 兜底注入提示词）。"""
    return "\n".join(f"- {key}：{content}" for key, content in GENERAL_KNOWLEDGE.items())