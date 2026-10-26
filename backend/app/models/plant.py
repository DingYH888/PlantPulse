"""植物模型（PRD 13 plants 表）。

status 为派生字段（healthy/attention/abnormal），由规则引擎按指标与打卡节律计算，
脚手架阶段默认 healthy，规则引擎在数据图表模块中实现。
"""

from tortoise import fields, models


class Plant(models.Model):
    """植物档案表。"""

    id = fields.BigIntField(pk=True)
    # 归属用户：user_id 为数据隔离键，所有查询必须带 user_id 过滤（PRD 7.3）
    user = fields.ForeignKeyField("models.User", related_name="plants", on_delete=fields.CASCADE)
    name = fields.CharField(max_length=64, description="用户命名")
    species = fields.CharField(max_length=64, null=True, description="品种（AI 识别/手动）")
    image_url = fields.CharField(max_length=512, null=True, description="植物图片")
    location = fields.CharField(max_length=64, null=True, description="摆放位置")
    status = fields.CharField(max_length=16, default="healthy", description="状态：healthy/attention/abnormal")
    planted_at = fields.DateField(null=True, description="种植日期")
    notes = fields.TextField(null=True, description="备注")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "plants"

    def __str__(self) -> str:
        return f"<Plant {self.id}:{self.name}>"