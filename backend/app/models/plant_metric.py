"""养护指标模型（PRD 13 plant_metrics 表）。

指标值合法区间见 PRD 5.3.3（温度 -20~60℃、湿度 0~100%、光照 0~200000 lux、
土壤湿度 0~100%、pH 0~14），由接口层校验。
"""

from tortoise import fields

from app.models.base import TimestampMixin


class PlantMetric(TimestampMixin):
    """植物养护指标记录表。"""

    user = fields.ForeignKeyField(
        "models.User",
        related_name="metrics",
        on_delete=fields.CASCADE,
        description="归属用户ID（数据隔离键）",
    )
    plant = fields.ForeignKeyField(
        "models.Plant",
        related_name="metrics",
        on_delete=fields.CASCADE,
        description="所属植物ID",
    )
    temperature = fields.DecimalField(max_digits=5, decimal_places=2, null=True, description="温度（℃），合法区间 -20~60")
    humidity = fields.DecimalField(max_digits=5, decimal_places=2, null=True, description="空气湿度（%），合法区间 0~100")
    light = fields.DecimalField(max_digits=10, decimal_places=2, null=True, description="光照（lux），合法区间 0~200000")
    soil_moisture = fields.DecimalField(max_digits=5, decimal_places=2, null=True, description="土壤湿度（%），合法区间 0~100")
    ph = fields.DecimalField(max_digits=4, decimal_places=2, null=True, description="土壤pH，合法区间 0~14")
    record_time = fields.DatetimeField(auto_now_add=True, description="指标记录时间（默认当前时间）")

    class Meta:
        table = "plant_metric"

    def __str__(self) -> str:
        return f"<PlantMetric id={self.id} plant_id={self.plant_id}>"