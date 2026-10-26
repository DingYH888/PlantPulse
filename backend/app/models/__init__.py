"""Tortoise-ORM 模型聚合入口。

新模块新增模型后需在此导出并注册到 main.py 的 TORTOISE_MODELS 列表。
"""

from app.models.user import User
from app.models.plant import Plant

__all__ = ["User", "Plant"]