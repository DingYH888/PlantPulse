"""养护统计纯计算服务（PRD 5.3 数据图表）。

职责边界：
- 本模块只做"指标阈值判定 / 长势评分 / 按天聚合 / 汇总"等纯计算，不访问数据库；
- 路由层负责数据查询与权限校验，便于单元测试与复用。

长势口径（用户确认）：
- 按 PRD 5.3.3 阈值，将当日各项指标折算为状态分：正常 100 / 待关注 60 / 异常 20；
- 当日长势健康分 = 当日已录入各项指标状态分的平均值（0~100，保留 1 位小数）；
- 当日状态取最差指标状态，异常项通过 alerts 返回给前端 tooltip 高亮。
"""

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean
from typing import Any

from app.core.timezone import to_local_date

# ---- 指标元数据：key → 中文名 / 单位 / 正常区间说明 ----
METRIC_META: dict[str, dict[str, str]] = {
    "temperature": {"label": "温度", "unit": "℃"},
    "humidity": {"label": "空气湿度", "unit": "%"},
    "soil_moisture": {"label": "土壤湿度", "unit": "%"},
    "ph": {"label": "pH", "unit": ""},
    "light": {"label": "光照", "unit": "lux"},
}

# 指标计算顺序固定，保证 alerts/tooltip 展示顺序稳定
METRIC_KEYS: tuple[str, ...] = (
    "temperature",
    "humidity",
    "soil_moisture",
    "ph",
    "light",
)

# 状态分与严重程度排序（数值越大越严重）
STATUS_SCORE: dict[str, int] = {"normal": 100, "attention": 60, "abnormal": 20}
STATUS_RANK: dict[str, int] = {"normal": 0, "attention": 1, "abnormal": 2}
STATUS_LABEL: dict[str, str] = {
    "normal": "正常",
    "attention": "待关注",
    "abnormal": "异常",
}


def evaluate_metric_status(metric_key: str, value: float) -> str:
    """按 PRD 5.3.3 阈值表判定单项指标状态。

    返回 normal / attention / abnormal。
    light 的 >50000 lux 在 PRD 表中未定义异常档，这里按"超出正常上限"归为待关注。
    """
    if metric_key == "temperature":
        if value < 8 or value > 35:
            return "abnormal"
        if value < 15 or value > 30:
            return "attention"
        return "normal"

    if metric_key == "humidity":
        if value < 30 or value > 80:
            return "abnormal"
        if value < 40 or value > 70:
            return "attention"
        return "normal"

    if metric_key == "soil_moisture":
        if value < 20 or value > 75:
            return "abnormal"
        if value < 30 or value > 60:
            return "attention"
        return "normal"

    if metric_key == "light":
        if value < 2000:
            return "abnormal"
        if value < 5000 or value > 50000:
            return "attention"
        return "normal"

    if metric_key == "ph":
        if value < 5.0 or value > 7.5:
            return "abnormal"
        if value < 5.5 or value > 7.0:
            return "attention"
        return "normal"

    # 未知指标不参与评分，避免脏数据影响长势结果
    return "normal"


def _is_low(metric_key: str, value: float) -> bool:
    """判断指标偏低/偏高，用于生成中文告警文案。"""
    if metric_key == "temperature":
        return value < 15
    if metric_key == "humidity":
        return value < 40
    if metric_key == "soil_moisture":
        return value < 30
    if metric_key == "light":
        return value < 5000
    if metric_key == "ph":
        return value < 5.5
    return False


def describe_metric_alert(metric_key: str, value: float) -> str | None:
    """生成异常/待关注指标的中文提示，例如「光照偏低（1200lux）」。"""
    status = evaluate_metric_status(metric_key, value)
    if status == "normal":
        return None

    meta = METRIC_META.get(metric_key)
    if meta is None:
        return None

    direction = "偏低" if _is_low(metric_key, value) else "偏高"
    # 去掉无意义的小数零，同时保留必要的精度
    display = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{meta['label']}{direction}（{display}{meta['unit']}）"


def build_growth_point(metric_values: dict[str, float]) -> dict[str, Any]:
    """根据当日各项指标均值计算长势健康分、状态与告警。

    无任何指标时返回 value=None，前端折线断开（不把"未记录"误画成 0 分）。
    """
    scores: list[int] = []
    statuses: list[str] = []
    alerts: list[str] = []

    for key in METRIC_KEYS:
        value = metric_values.get(key)
        if value is None:
            continue
        status = evaluate_metric_status(key, value)
        scores.append(STATUS_SCORE[status])
        statuses.append(status)
        alert = describe_metric_alert(key, value)
        if alert:
            alerts.append(alert)

    if not scores:
        return {"value": None, "status": None, "alerts": []}

    worst_status = max(statuses, key=lambda item: STATUS_RANK[item])
    return {
        "value": round(mean(scores), 1),
        "status": worst_status,
        "alerts": alerts,
    }


def aggregate_metric_days(records: list[Any]) -> dict[date, dict[str, float]]:
    """把指标记录按自然日分组并对每项指标求平均。

    入参为 PlantMetric 模型列表；返回 {date: {metric_key: 平均值}}，
    当日未录入的指标不会出现在该日字典中。
    """
    buckets: dict[date, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for record in records:
        record_time = getattr(record, "record_time", None)
        if record_time is None:
            continue
        # 按应用本地时区切自然日（UTC+8 凌晨记录不会被归到前一天）
        day = to_local_date(record_time)
        for key in METRIC_KEYS:
            value = getattr(record, key, None)
            if value is None:
                continue
            buckets[day][key].append(float(value))

    result: dict[date, dict[str, float]] = {}
    for day, values_by_key in buckets.items():
        result[day] = {
            key: round(mean(values), 2) for key, values in values_by_key.items() if values
        }
    return result


def build_date_series(start_date: date, end_date: date) -> list[date]:
    """生成 [start_date, end_date] 的连续自然日序列（含首尾）。"""
    total_days = (end_date - start_date).days + 1
    return [start_date + timedelta(days=offset) for offset in range(total_days)]


def summarize_values(
    values: list[float | int],
    *,
    fixed_days: int | None = None,
    total_mode: str = "sum",
) -> dict[str, Any]:
    """计算统计汇总：总数 / 平均 / 最大 / 最小 / 最近值。

    fixed_days 非空时平均值按"全区间日均"计算（打卡次数维度）；
    否则按"有数据天"计算（长势/光照等指标维度）。
    total_mode="count" 时 total 表示有数据的天数，否则表示数值累加。
    """
    if not values:
        return {"total": 0, "average": None, "max": None, "min": None, "latest": None}

    total = len(values) if total_mode == "count" else round(sum(values), 2)
    if fixed_days and fixed_days > 0:
        average = round(sum(values) / fixed_days, 2)
    else:
        average = round(mean(values), 2)

    return {
        "total": total,
        "average": average,
        "max": round(max(values), 2),
        "min": round(min(values), 2),
        "latest": round(values[-1], 2),
    }