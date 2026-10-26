"""Tortoise-ORM 模型公共基类与时间戳混入。

- TimestampMixin：公共主键 + 时间戳字段（PRD 约束4：每个表都有创建时间字段）
  所有业务模型继承它，保证全表统一具备 id / created_at / updated_at。
"""

from tortoise import fields, models


class TimestampMixin(models.Model):
    """公共字段混入：主键 id + created_at + updated_at（抽象模型，不建表）。

    auto_now_add：创建时由 ORM 写入当前时间；
    auto_now：每次 update/save 时自动刷新 updated_at。
    """

    id = fields.BigIntField(pk=True, description="主键ID")
    created_at = fields.DatetimeField(auto_now_add=True, description="创建时间（约束4）")
    updated_at = fields.DatetimeField(auto_now=True, description="更新时间（记录变更时自动刷新）")

    class Meta:
        abstract = True