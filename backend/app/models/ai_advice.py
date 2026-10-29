"""AI 养护建议模型（PRD 13 ai_advices 表）。

约束2：user + plant 双重归属校验，实现 AI 上下文与结果隔离（PRD 7.3）。
防幻觉字段：is_fallback（降级标注）、doc_refs（引用文档）、trace（全链路日志），见 PRD 8.4/8.5。
"""

from tortoise import fields

from app.models.base import TimestampMixin


class AiAdvice(TimestampMixin):
    """AI 生成养护建议表。"""

    user = fields.ForeignKeyField(
        "models.User",
        related_name="advices",
        on_delete=fields.CASCADE,
        description="归属用户ID（数据隔离键）",
    )
    plant = fields.ForeignKeyField(
        "models.Plant",
        related_name="advices",
        on_delete=fields.CASCADE,
        null=True,
        description="关联植物ID（可空：识别未建档场景）",
    )
    session_id = fields.CharField(
        max_length=64,
        null=True,
        db_index=True,
        description="前端会话ID（多轮对话隔离与历史会话切换键）",
    )
    input_image_url = fields.CharField(max_length=512, null=True, description="输入图片URL（图像识别入参）")
    species = fields.CharField(max_length=64, null=True, description="识别/归一化后的品种名")
    confidence = fields.DecimalField(max_digits=4, decimal_places=2, null=True, description="识别置信度（0~1，<0.6 走未知品种路径）")
    is_fallback = fields.BooleanField(default=False, description="是否降级输出（无知识库匹配时=true，前端明示通用知识）")
    content = fields.JSONField(null=True, description="建议分节内容（PRD 8.5 输出 Schema）")
    doc_refs = fields.JSONField(null=True, description="引用文档 [{doc_id,title,source_type}]（来源可追溯）")
    trace = fields.JSONField(null=True, description="全链路日志（识别结果/检索top5/打卡摘要/提示词hash）")
    feedback = fields.SmallIntField(null=True, description="用户反馈：1有用 / -1无用 / 0中性")
    status = fields.CharField(max_length=16, default="pending", description="状态：pending/success/failed/timeout")

    class Meta:
        table = "ai_advice"

    def __str__(self) -> str:
        return f"<AiAdvice id={self.id} user_id={self.user_id} is_fallback={self.is_fallback}>"