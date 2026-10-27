"""应用统一时区（统计按"自然日"口径，PRD 5.3.3）。

Tortoise 默认 use_tz=True，数据库时间按 UTC 存取；
统计的自然日应按用户本地时区切片，否则 UTC+8 凌晨 00:00~08:00 的记录
会被归到前一天，导致浇水/光照/长势图表错位。

PRD 面向中文用户，默认使用 Asia/Shanghai；如未来部署到其他时区，
修改此常量即可，所有指标/统计路由共用同一口径。
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

APP_TIMEZONE = ZoneInfo("Asia/Shanghai")


def local_day_start(day: date) -> datetime:
    """返回应用本地时区某自然日的 00:00（带时区，交由 ORM 转 UTC 查询）。"""
    return datetime.combine(day, time.min, tzinfo=APP_TIMEZONE)


def local_day_end(day: date) -> datetime:
    """返回本地自然日次日 00:00，用于左闭右开区间查询。"""
    return local_day_start(day + timedelta(days=1))


def to_local_date(value: datetime):
    """把数据库时间转换为应用本地时区的自然日。

    兼容 Tortoise 返回 aware(UTC) 的情况；若遇到 naive datetime，
    按 use_tz=True 的存储约定视为 UTC 后再转换。
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))
    return value.astimezone(APP_TIMEZONE).date()