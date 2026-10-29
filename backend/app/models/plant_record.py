"""养护/打卡记录模型（表名 plant_record，PRD care_records 同源）。

约束2：user 外键数据隔离。
约束3：record_type 使用枚举类型（Tortoise CharEnumField，MySQL 存枚举值字符串）。
打卡记录同时供数据图表与 AI 工作流节点4使用（PRD 5.5.3，与 care_records 同源不冗余）。
"""

import enum

from tortoise import fields

from app.models.base import TimestampMixin


class RecordType(str, enum.Enum):
    """养护记录类型枚举（PRD care_type 取值）。

    存库值为小写字符串（如 'watering'），前端展示映射见 PRD 5.5。
    """

    WATERING = "watering"          # 浇水
    FERTILIZING = "fertilizing"    # 施肥
    PRUNING = "pruning"            # 修剪
    REPOTTING = "repotting"        # 换盆
    PEST_CONTROL = "pest_control"  # 病虫害防治
    OTHER = "other"                # 其他


class PlantRecord(TimestampMixin):
    """植物养护记录表（打卡数据源）。"""

    user = fields.ForeignKeyField(
        "models.User",
        related_name="records",
        on_delete=fields.CASCADE,
        description="归属用户ID（数据隔离键）",
    )
    plant = fields.ForeignKeyField(
        "models.Plant",
        related_name="records",
        on_delete=fields.CASCADE,
        description="所属植物ID",
    )
    record_type = fields.CharEnumField(
        RecordType,
        max_length=32,
        description="养护类型枚举（约束3）：watering/fertilizing/pruning/repotting/pest_control/other",
    )
    content = fields.CharField(max_length=512, null=True, description="备注内容（如用量、部位）")
    image_url = fields.CharField(max_length=512, null=True, description="打卡照片URL")
    record_date = fields.DateField(description="打卡日期（不允许未来日期，PRD BR-04）")

    class Meta:
        table = "plant_record"
        # 同植物同类型同日允许多条打卡（BR-03 唯一限制已按需求移除）

    def __str__(self) -> str:
        return f"<PlantRecord id={self.id} plant_id={self.plant_id} type={self.record_type}>"