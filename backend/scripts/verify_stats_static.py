"""沙箱内静态验证：统计/指标路由注册 + 纯计算逻辑（不触发 asyncio）。

用法：cd backend && ../.venv/Scripts/python.exe -m scripts.verify_stats_static
"""

import sys
from datetime import date

from app.main import app
from app.schemas.metric import MetricCreate, MetricDailyPoint
from app.services.plant_stats import (
    build_date_series,
    build_growth_point,
    describe_metric_alert,
    evaluate_metric_status,
    summarize_values,
)

# 1. 路由注册：metrics / stats 均应出现在 OpenAPI 路径中
paths = app.openapi()["paths"]
expected_paths = (
    "/api/v1/plants/{plant_id}/metrics",
    "/api/v1/plants/{plant_id}/stats",
)
for path in expected_paths:
    assert path in paths, f"路由未注册: {path}"
    print("route ok:", path)

# 2. 统计参数枚举校验
stats_params = paths["/api/v1/plants/{plant_id}/stats"]["get"]["parameters"]
dimension_param = next(p for p in stats_params if p["name"] == "dimension")
assert dimension_param["required"] is False
print("stats params ok:", [p["name"] for p in stats_params])

# 3. 指标 Schema 解析
metric = MetricCreate(temperature=25, humidity=50, light=20000, soil_moisture=45, ph=6.2)
assert metric.temperature == 25
point = MetricDailyPoint(date="2026-10-27", temperature=25)
print("metric schema ok:", metric.model_dump(), point.model_dump())

# 4. PRD 阈值判定
assert evaluate_metric_status("temperature", 25) == "normal"
assert evaluate_metric_status("temperature", 10) == "attention"
assert evaluate_metric_status("temperature", 40) == "abnormal"
assert evaluate_metric_status("light", 1000) == "abnormal"
assert evaluate_metric_status("light", 60000) == "attention"
print("threshold ok")

# 5. 长势评分与告警
all_normal = build_growth_point(
    {"temperature": 25, "humidity": 50, "soil_moisture": 45, "ph": 6.2, "light": 20000}
)
assert all_normal["value"] == 100 and all_normal["status"] == "normal", all_normal

with_abnormal_light = build_growth_point(
    {"temperature": 25, "humidity": 50, "soil_moisture": 45, "ph": 6.2, "light": 1000}
)
assert with_abnormal_light["value"] == 84.0, with_abnormal_light
assert with_abnormal_light["status"] == "abnormal"
assert any("光照" in alert for alert in with_abnormal_light["alerts"])
assert describe_metric_alert("light", 1000) == "光照偏低（1000lux）"
print("growth ok:", all_normal, with_abnormal_light)

empty = build_growth_point({})
assert empty["value"] is None and empty["status"] is None
print("empty growth ok")

# 6. 日期序列与汇总
series = build_date_series(date(2026, 10, 21), date(2026, 10, 27))
assert len(series) == 7 and series[0] == date(2026, 10, 21) and series[-1] == date(2026, 10, 27)

summary = summarize_values([1, 0, 1], fixed_days=7, total_mode="sum")
assert summary["total"] == 2 and summary["average"] == round(2 / 7, 2), summary
growth_summary = summarize_values([100, 84.0], total_mode="count")
assert growth_summary["total"] == 2 and growth_summary["average"] == 92.0, growth_summary
print("series/summary ok:", summary, growth_summary)

print("STATIC VERIFY OK")
sys.exit(0)