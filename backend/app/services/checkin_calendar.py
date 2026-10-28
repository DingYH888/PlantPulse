"""个人中心日历打卡纯计算服务（PRD 5.5 FR-501/FR-505）。

职责边界：本模块只做"月份解析 / 按天聚合 / 连续天数 / 汇总"等纯计算，
不访问数据库、不依赖 FastAPI，路由层负责查询与权限校验，便于单元测试与复用。

统计口径（PRD 5.5.3-3）：
- 连续打卡天数 = 从今天（今天无记录则从昨天）向前追溯的最长连续"有打卡记录"自然日数；
- 统计范围为当前用户的全部植物（不区分植物）。
"""

from collections import Counter
from collections.abc import Iterable
from datetime import date, timedelta

# 打卡类型 → 中文展示名（PRD care_type 枚举，与前端 CARE_TYPES 保持一致）
CARE_TYPE_LABELS: dict[str, str] = {
    "watering": "浇水",
    "fertilizing": "施肥",
    "pruning": "修剪",
    "repotting": "换盆",
    "pest_control": "病虫害防治",
    "other": "其他",
}


def care_type_value(value) -> str:
    """统一打卡类型取值：兼容 Tortoise CharEnumField 返回枚举或字符串两种情况。"""
    return value.value if hasattr(value, "value") else str(value)


def parse_month(month: str | None, today: date) -> tuple[str, date]:
    """解析并校验月份（YYYY-MM），返回 (规范化月份字符串, 当月 1 号)。

    不传月份时默认当月；格式非法（如 2026-13、2026-1）抛 ValueError，
    由路由层转换为业务码 400。
    """
    if not month:
        first = date(today.year, today.month, 1)
    else:
        try:
            # 拼接 -01 后按完整日期解析，可同时筛掉 2026-13 / 2026-1 / 非日期等非法输入
            first = date.fromisoformat(f"{month}-01")
        except ValueError as exc:
            raise ValueError("月份格式应为 YYYY-MM") from exc
    return f"{first.year:04d}-{first.month:02d}", first


def next_month(first: date) -> date:
    """返回下月 1 号，用于左闭右开区间查询（与 PRD 统计口径一致）。"""
    if first.month == 12:
        return date(first.year + 1, 1, 1)
    return date(first.year, first.month + 1, 1)


def build_calendar(rows: Iterable[tuple[date, str]]) -> list[dict]:
    """把 (打卡日期, 打卡类型) 记录聚合为按天视图，供日历标记与角标展示。

    同一天多次打卡（不同类型）合并为一条，count 为次数、types 为去重类型，
    避免前端逐条渲染造成日历单元格内容溢出。
    """
    grouped: dict[date, list[str]] = {}
    for record_date, care_type in rows:
        grouped.setdefault(record_date, []).append(care_type)

    return [
        {
            "date": record_date.isoformat(),
            "count": len(care_types),
            "types": sorted(set(care_types)),
        }
        for record_date, care_types in sorted(grouped.items())
    ]


def calc_streak(record_dates: set[date], today: date) -> int:
    """计算连续打卡天数（PRD 5.5.3-3）。

    今天有打卡 → 从今天起算；今天还没打卡 → 从昨天起算（当天未打卡不算断签，
    给用户留出当天补打卡的余地）。遇到缺失日期立刻停止。
    """
    cursor = today if today in record_dates else today - timedelta(days=1)
    streak = 0
    while cursor in record_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def summarize(rows: Iterable[tuple[date, str]], today: date, plant_count: int) -> dict:
    """汇总个人中心统计数据（连续打卡 / 本月 / 总量 / 类型分布）。

    rows 为当前用户全部打卡记录 (record_date, care_type)，一次遍历完成所有口径计算，
    避免路由层多次聚合查询。
    """
    rows = list(rows)
    record_dates = {record_date for record_date, _ in rows}
    month_rows = [
        care_type
        for record_date, care_type in rows
        if record_date.year == today.year and record_date.month == today.month
    ]
    month_dates = {
        record_date
        for record_date, _ in rows
        if record_date.year == today.year and record_date.month == today.month
    }

    type_counter = Counter(care_type for _, care_type in rows)
    type_counts = [
        {
            "type": care_type,
            "label": CARE_TYPE_LABELS.get(care_type, care_type),
            "count": count,
        }
        for care_type, count in sorted(type_counter.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "streak_days": calc_streak(record_dates, today),
        "month_checkin_count": len(month_rows),
        "month_active_days": len(month_dates),
        "total_checkin_count": len(rows),
        "total_active_days": len(record_dates),
        "plant_count": plant_count,
        "type_counts": type_counts,
    }