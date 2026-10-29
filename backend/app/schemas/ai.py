"""AI 模块请求/响应模型（PRD 5.4 / 9.7 P4）。"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class IdentifyRequest(BaseModel):
    """图像识别请求（FR-401）。图片需先经 /upload/image 上传拿到 URL。"""

    image_url: str = Field(min_length=1, max_length=512, description="植物图片 URL（/static/... 或公网地址）")


class IdentifyResponse(BaseModel):
    """图像识别响应。"""

    candidates: list[dict] = Field(default_factory=list, description="候选品种 [{species,confidence}]")
    species: str = Field(description="归一化后的品种名，未知为“未知品种”")
    confidence: float = Field(ge=0.0, le=1.0)
    is_known: bool = Field(description="是否能在知识库/别名表中映射")
    source: str = Field(description="品种来源：vision/user/low_confidence")


class CareAdviceRequest(BaseModel):
    """生成个性化养护建议请求（FR-402）。

    交互变更（2026-10）：前端不再提供「关联植物 / 品种」两个手工选项：
    - 纯文本：由大模型从 question 中解析植物名称，解析不到返回 400；
    - 图片 + 文本：品种以 image_url 的识别结果为准，再按 question 检索知识库；
    - 仅图片：品种以识别结果为准，直接给出检索建议。
    """

    plant_id: int | None = Field(default=None, description="已建植物 ID（可选，API 兼容保留）")
    image_url: str | None = Field(default=None, max_length=512, description="植物图片 URL（可选，有图则识别）")
    species: str | None = Field(
        default=None,
        max_length=64,
        description="用户指定品种（API 兼容字段，前端不再传；品种由问题解析或图像识别决定）",
    )
    question: str | None = Field(default=None, max_length=500, description="用户问题，如“绿萝叶子发黄怎么办”")
    session_id: str | None = Field(default=None, max_length=64, description="多轮会话 ID（前端生成 UUID）")

    @model_validator(mode="after")
    def _require_question_or_image(self) -> "CareAdviceRequest":
        """必须提供问题或图片，否则无法确定品种与检索方向。"""
        if not self.image_url and not (self.question or "").strip():
            raise ValueError("请输入养护问题或上传植物图片")
        return self


class FeedbackRequest(BaseModel):
    """建议反馈（FR-407）：1 有用 / -1 无用 / 0 中性。"""

    feedback: Literal[-1, 0, 1] = Field(description="反馈值")


class AdviceSectionOut(BaseModel):
    """建议分节响应。"""

    key: str
    title: str
    content: str
    doc_ids: list[str] = Field(default_factory=list)
    source_type: str = Field(description="knowledge / general")


class AdviceOut(BaseModel):
    """AI 建议响应（PRD 8.5）。"""

    id: int
    plant_id: int | None = None
    plant_name: str | None = None
    input_image_url: str | None = None
    species: str | None = None
    confidence: float | None = None
    is_fallback: bool = False
    session_id: str | None = None
    question: str = ""
    summary: str = ""
    sections: list[AdviceSectionOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    doc_refs: list[dict] = Field(default_factory=list)
    feedback: int | None = None
    status: str = "success"
    created_at: str | None = None