"""内置通用养护知识兜底（PRD 8.1 节点3b / 8.4 降级策略）。

使用场景：
1. 检索无命中且通用知识库也没有可用文档；
2. LLM 生成阶段异常，需要"纯知识降级输出"（PRD 12 可用性要求）。

所有内容均为通用养护常识，必须标注 source_type=general、is_fallback=true，
前端据此显示"通用知识"角标。
"""

from app.ai.schemas import AdviceSection, CareAdviceOutput

# 五类通用养护常识（避免绝对数值，表述为区间/原则，降低误导风险）
GENERAL_KNOWLEDGE: dict[str, str] = {
    "watering": "遵循“见干见湿”：表土约 2~3 厘米干燥后再浇透，避免盆底长期积水。冬季蒸发慢应减少频次，具体间隔需结合盆土、温度与通风调整。",
    "light": "多数观叶植物适合明亮散射光，避免正午强光直射。光照不足时叶片会变薄、节间拉长，可逐步移到更亮位置，忌一次性暴晒。",
    "fertilizing": "生长季可薄肥勤施，使用稀释后的通用复合肥；休眠期与刚换盆的缓苗期暂停施肥。施肥后若出现叶缘焦枯，应停止并清水冲洗盆土。",
    "temperature_humidity": "适宜温度通常为 15~28℃，避免空调直吹与温度骤变。空气干燥时可喷雾或使用加湿托盘，同时保持通风以减少病害。",
    "pest_control": "定期检查叶背与茎基部，发现介壳虫、红蜘蛛可用软刷或清水冲洗，严重时使用对应杀虫剂并隔离。保持通风、避免过湿是最有效的预防手段。",
}

GENERAL_KNOWLEDGE_TEXT = "\n".join(
    f"- {key}：{content}" for key, content in GENERAL_KNOWLEDGE.items()
)


def build_general_output(
    species: str = "未知品种",
    confidence: float = 0.0,
    warnings: list[str] | None = None,
    summary: str | None = None,
) -> CareAdviceOutput:
    """构造纯通用知识建议（is_fallback=true，所有分节 source_type=general）。"""
    titles = {
        "watering": "浇水",
        "light": "光照",
        "fertilizing": "施肥",
        "temperature_humidity": "温度与湿度",
        "pest_control": "病虫害防治",
    }
    sections = [
        AdviceSection(
            key=key,
            title=titles[key],
            content=content,
            doc_ids=[],
            source_type="general",
        )
        for key, content in GENERAL_KNOWLEDGE.items()
    ]
    return CareAdviceOutput(
        species=species or "未知品种",
        confidence=max(0.0, min(1.0, confidence)),
        is_fallback=True,
        summary=summary or "未匹配到品种专属知识，以下为通用养护建议。",
        sections=sections,
        warnings=warnings or [],
    )