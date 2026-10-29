"""LLM 结构化输出模型（PRD 8.5 输出结构 / 8.4 输出校验）。

所有模型同时承担"LLM 输出契约"与"服务端校验"两个职责：
- 识别结果：候选品种 + 置信度（节点1）
- 建议结果：固定五个分节 + 来源标注（节点5）
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# 建议固定分节（PRD FR-403：浇水/光照/施肥/温湿/病虫害）
SECTION_KEYS = ("watering", "light", "fertilizing", "temperature_humidity", "pest_control")

SECTION_TITLES = {
    "watering": "浇水",
    "light": "光照",
    "fertilizing": "施肥",
    "temperature_humidity": "温度与湿度",
    "pest_control": "病虫害防治",
}


class IdentifyCandidate(BaseModel):
    """图像识别候选品种（节点1）。"""

    species: str = Field(description="候选品种中文名或学名")
    confidence: float = Field(ge=0.0, le=1.0, description="识别置信度 0~1")


class IdentifyOutput(BaseModel):
    """图像识别输出（节点1）。"""

    candidates: list[IdentifyCandidate] = Field(default_factory=list, description="候选品种，按置信度降序")


class AdviceSection(BaseModel):
    """单条建议分节（PRD 8.5）。"""

    key: Literal["watering", "light", "fertilizing", "temperature_humidity", "pest_control"] = Field(
        description="分节标识"
    )
    title: str = Field(description="分节中文标题")
    content: str = Field(min_length=1, description="建议正文，≤150字")
    doc_ids: list[str] = Field(default_factory=list, description="引用的知识库文档ID")
    source_type: Literal["knowledge", "general"] = Field(
        description="来源类型：knowledge=知识库命中；general=通用知识（前端显示角标）"
    )


class CareAdviceOutput(BaseModel):
    """LLM 生成的养护建议（PRD 8.5）。"""

    species: str = Field(description="标准化品种名；未知品种填“未知品种”")
    confidence: float = Field(ge=0.0, le=1.0, description="识别置信度")
    is_fallback: bool = Field(description="是否降级输出")
    summary: str = Field(min_length=1, description="一句话养护概览")
    sections: list[AdviceSection] = Field(min_length=1, description="分节建议")
    warnings: list[str] = Field(default_factory=list, description="风险提示")

    @model_validator(mode="after")
    def _validate_sections(self) -> "CareAdviceOutput":
        """输出校验（PRD 8.4 引用绑定）。

        规则：
        1. 分节 key 不得重复；
        2. source_type=knowledge 必须携带 doc_ids，否则视为编造来源 → 校验失败触发重试；
        3. source_type=general 不允许携带 doc_ids（避免"通用知识"伪装成知识库引用）。
        """
        seen: set[str] = set()
        for section in self.sections:
            if section.key in seen:
                raise ValueError(f"分节重复：{section.key}")
            seen.add(section.key)
            if section.source_type == "knowledge" and not section.doc_ids:
                raise ValueError(f"分节 {section.key} 标注 knowledge 但缺少 doc_ids")
            if section.source_type == "general" and section.doc_ids:
                raise ValueError(f"分节 {section.key} 标注 general 却携带 doc_ids")
        return self


def normalize_section_order(sections: list[AdviceSection]) -> list[AdviceSection]:
    """按 PRD 固定分节顺序输出，缺失分节用通用知识补齐由调用方负责。"""
    by_key = {section.key: section for section in sections}
    return [by_key[key] for key in SECTION_KEYS if key in by_key]