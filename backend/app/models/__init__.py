"""Tortoise-ORM 模型聚合入口。

新模块新增模型后需在此导出并注册到 main.py 的 TORTOISE_MODULES 列表。
"""

from app.models.ai_advice import AiAdvice
from app.models.captcha import CaptchaCode
from app.models.plant import Plant
from app.models.plant_metric import PlantMetric
from app.models.plant_record import PlantRecord, RecordType
from app.models.user import User

__all__ = [
    "AiAdvice",
    "CaptchaCode",
    "Plant",
    "PlantMetric",
    "PlantRecord",
    "RecordType",
    "User",
]