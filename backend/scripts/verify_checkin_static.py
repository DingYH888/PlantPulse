"""沙箱内静态验证：应用装配/路由注册/Schema 解析（不触发 asyncio）。"""
import sys

from app.main import app
from app.schemas.checkin import CheckinCreate, CheckinOut

# 1. 路由注册：openapi() 生成完整路径（含 /api/v1 prefix）
schema = app.openapi()
api_paths = sorted(schema["paths"].keys())
print("api routes:", api_paths)
for expected in ("/api/v1/plants", "/api/v1/checkins", "/api/v1/upload/image", "/api/v1/checkins/{...}"):
    pass
assert "/api/v1/plants" in api_paths
assert "/api/v1/checkins" in api_paths
assert "/api/v1/upload/image" in api_paths
assert any(getattr(r, "name", "") == "static" for r in app.routes), "static 未挂载"

# 2. 打卡请求/响应 Schema：枚举解析 + 多图数组
c = CheckinCreate(plant_id=1, care_type="watering", image_urls=["/static/u/a.jpg"])
print("create payload:", c.model_dump())
assert c.care_type.value == "watering", "枚举解析失败"

o = CheckinOut(
    id=1,
    plant_id=1,
    care_type="watering",
    record_date="2026-10-26",
    images=["/static/u/a.jpg"],
    created_at="2026-10-26T10:00:00",
)
print("out payload:", o.model_dump())

print("STATIC VERIFY OK")
sys.exit(0)