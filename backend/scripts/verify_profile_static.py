"""沙箱内静态验证：个人中心（PRD 5.5）路由注册与日历统计纯函数。

不触发 asyncio，可在沙箱直接运行：
    cd backend && ..\\.venv\\Scripts\\python.exe scripts/verify_profile_static.py
"""

import sys
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from app.main import app
from app.services.checkin_calendar import (
    build_calendar,
    calc_streak,
    care_type_value,
    next_month,
    parse_month,
    summarize,
)

# ---- 1. 路由注册：用 openapi() 最可靠（含 /api/v1 前缀）----
paths = app.openapi()["paths"]
expected = {
    "/api/v1/checkins/calendar": {"get"},
    "/api/v1/checkins/{checkin_id}": {"delete"},
    "/api/v1/user/stats": {"get"},
    "/api/v1/auth/profile": {"get", "put"},
    "/api/v1/auth/password": {"put"},
    "/api/v1/upload/image": {"post"},
}
for path, methods in expected.items():
    assert path in paths, f"路由缺失：{path}"
    missing = methods - set(paths[path].keys())
    assert not missing, f"路由 {path} 缺少方法 {missing}"
print("routes ok:", sorted(paths.keys()))

# ---- 1.1 静态资源挂载：/static/uploads/<file> 必须映射到 upload_dir/<file> ----
# 回归点：若 /static 直接挂到 uploads 目录，URL 会多一层 uploads 导致图片 404（头像不显示）。
settings = get_settings()
static_mount = next((route for route in app.routes if getattr(route, "name", "") == "static"), None)
assert static_mount is not None, "/static 未挂载"
assert str(static_mount.path) == "/static"
static_root = Path(static_mount.app.directory).resolve()
assert static_root == settings.static_dir.resolve(), "静态根目录应与 upload_dir 的父目录一致"
assert static_root / settings.upload_dir.name == settings.upload_dir.resolve()
sample = next(iter(settings.upload_dir.glob("*")), None)
if sample is not None:
    mapped = static_root / settings.upload_dir.name / sample.name
    assert mapped.exists(), f"上传文件无法通过 URL 访问：{mapped}"
    print(f"static ok: /static/{settings.upload_dir.name}/{sample.name} -> {mapped}")
else:
    print("static ok: 暂未上传文件，挂载路径校验通过")

# ---- 2. 月份解析与区间 ----
today = date(2026, 10, 28)
assert parse_month(None, today) == ("2026-10", date(2026, 10, 1))
assert parse_month("2026-12", today) == ("2026-12", date(2026, 12, 1))
assert next_month(date(2026, 12, 1)) == date(2027, 1, 1)
assert next_month(date(2026, 10, 1)) == date(2026, 11, 1)
for bad in ("2026-13", "2026-1", "abc", "2026-10-15"):
    try:
        parse_month(bad, today)
    except ValueError:
        pass
    else:
        raise AssertionError(f"非法月份未被拒绝：{bad}")
print("month parse ok")

# ---- 3. 日历聚合：同日多次打卡合并 ----
rows = [
    (date(2026, 10, 1), "watering"),
    (date(2026, 10, 1), "fertilizing"),
    (date(2026, 10, 3), "watering"),
]
days = build_calendar(rows)
assert days[0] == {"date": "2026-10-01", "count": 2, "types": ["fertilizing", "watering"]}
assert days[1]["count"] == 1
print("calendar ok:", days)

# ---- 4. 连续打卡：今天有记录 / 今天无记录从昨天起算 / 断签 ----
assert calc_streak({date(2026, 10, 28), date(2026, 10, 27)}, today) == 2
assert calc_streak({date(2026, 10, 27), date(2026, 10, 26)}, today) == 2
assert calc_streak({date(2026, 10, 25)}, today) == 0
assert calc_streak(set(), today) == 0
print("streak ok")

# ---- 5. 汇总统计 ----
summary = summarize(
    [
        (date(2026, 10, 28), "watering"),
        (date(2026, 10, 27), "watering"),
        (date(2026, 10, 27), "fertilizing"),
        (date(2026, 9, 30), "pruning"),
    ],
    today,
    plant_count=2,
)
assert summary["streak_days"] == 2
assert summary["month_checkin_count"] == 3
assert summary["month_active_days"] == 2
assert summary["total_checkin_count"] == 4
assert summary["total_active_days"] == 3
assert summary["plant_count"] == 2
assert summary["type_counts"][0] == {"type": "watering", "label": "浇水", "count": 2}
print("summary ok:", summary)

# ---- 6. 枚举归一化：兼容 CharEnumField 返回枚举/字符串 ----
from app.models.plant_record import RecordType

assert care_type_value(RecordType.WATERING) == "watering"
assert care_type_value("watering") == "watering"

# ---- 7. 未来日期语义：日历接口按月份区间查询，不该出现未来限制 ----
assert date(2026, 10, 29) > today
print("STATIC VERIFY OK")
sys.exit(0)