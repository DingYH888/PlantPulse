"""个人中心模块路由（PRD 5.5 / 9.7 P5 接口清单）。

覆盖：
- GET /user/stats：连续打卡天数、本月打卡、总量与类型分布（PRD FR-505）。

统计范围为当前登录用户的全部植物（数据隔离），只读、无副作用；
纯计算逻辑见 app/services/checkin_calendar.py，便于单元测试复用。
"""

from datetime import datetime

from fastapi import APIRouter

from app.core.deps import CurrentUser
from app.core.response import success
from app.core.timezone import APP_TIMEZONE
from app.models.plant import Plant
from app.models.plant_record import PlantRecord
from app.services.checkin_calendar import care_type_value, summarize

router = APIRouter()


@router.get("/stats")
async def get_user_stats(user: CurrentUser) -> dict:
    """个人打卡统计（PRD 5.5.3-3）。

    streak_days：连续打卡天数（今天未打卡时从昨天回溯，留出当天补打卡余地）；
    month_*：本月打卡次数 / 打卡天数；
    total_*：累计打卡次数 / 打卡天数；
    type_counts：按类型统计，供个人中心展示养护偏好。
    """
    today = datetime.now(APP_TIMEZONE).date()
    rows = await PlantRecord.filter(user_id=user.id).values_list("record_date", "record_type")
    plant_count = await Plant.filter(user_id=user.id).count()

    return success(
        summarize(
            ((record_date, care_type_value(care_type)) for record_date, care_type in rows),
            today,
            plant_count,
        ),
        "查询成功",
    )