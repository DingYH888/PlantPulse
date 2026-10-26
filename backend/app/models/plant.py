"""植物模型（PRD 13 plants 表）。

约束2：user 外键为数据隔离键，所有查询必须按 user_id 过滤，
      禁止出现不带 user_id 的跨用户查询（PRD 7.3 数据隔离策略）。
"""

from tortoise import fields

from app.models.base import TimestampMixin


class Plant(TimestampMixin):
    """植物档案表。"""

    # 归属用户：数据隔离键（PRD 7.3）
    user = fields.ForeignKeyField(
        "models.User",
        related_name="plants",
        on_delete=fields.CASCADE,
        description="归属用户ID（数据隔离键）",
    )
    name = fields.CharField(max_length=64, description="用户为植物起的名字")
    species = fields.CharField(max_length=64, null=True, description="品种（AI识别或手动填写）")
    image_url = fields.CharField(max_length=512, null=True, description="植物图片URL")
    location = fields.CharField(max_length=64, null=True, description="摆放位置（如阳台/客厅）")
    status = fields.CharField(
        max_length=16,
        default="healthy",
        description="状态：healthy/attention/abnormal（由规则引擎派生，不手动编辑）",
    )
    planted_at = fields.DateField(null=True, description="种植日期")
    notes = fields.TextField(null=True, description="用户备注")

    # 反向关系：该植物的养护记录/指标/AI 建议（级联删除，PRD 5.2.3 BR-08）
    records: fields.ReverseRelation["PlantRecord"]
    metrics: fields.ReverseRelation["PlantMetric"]
    advices: fields.ReverseRelation["AiAdvice"]

    class Meta:
        table = "plants"

    def __str__(self) -> str:
        return f"<Plant id={self.id} name={self.name!r} user_id={self.user_id}>"