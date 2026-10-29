"""问题文本植物名称解析（AI 养护新增前置节点）。

业务需求（前端已移除「关联植物」「品种」两个手工选项）：
1. 纯文本问题：由大模型先分析问题文本中的植物名称，找不到就返回 400「请说明植物种类或名称」；
2. 图片 + 文本：品种以图像识别结果为准，本模块不参与；
3. 仅图片：品种以图像识别结果为准，随后直接检索生成建议。

职责边界：
- 本模块只负责「从自然语言中抽取植物名称」与「在用户自己的档案里定位植物」；
- 不负责检索与生成，检索仍由 retriever 按标准品种名过滤知识库；
- 规则兜底保证模型不可用（未配置 Key / 超时）时，只要问题里出现了已知品种名
  （用户植物档案名或内置别名），仍然可以继续作答。
"""

from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from app.ai.json_utils import content_to_text, parse_json_payload
from app.ai.llm import get_chat_model
from app.ai.species_aliases import ALIASES, normalize_species


class SpeciesMissingError(RuntimeError):
    """问题文本中未能识别出植物名称/种类（接口层转换为 400）。"""


# 只抽取名称，不做任何养护知识回答：降低延迟与幻觉面
QUESTION_PARSE_SYSTEM_PROMPT = """你是植物名称抽取器。请从用户问题中找出用户正在询问的植物名称或种类。
要求：
1. 输出 JSON，格式为 {{"species": "植物名称或种类", "confidence": 0.0}}；
2. species 必须是用户问题原文中出现过的名称，禁止根据常识补充或猜测；
3. 用户没有提到任何植物名称、或只说了"这盆花/我的植物"等泛指时，species 返回空字符串，confidence 填 0；
4. confidence 反映抽取的把握程度（0~1）；
5. 只输出 JSON，不要输出解释、Markdown 代码块或多余文字。"""


@dataclass
class QuestionParseResult:
    """一次问题解析的结果（供 trace 与链路节点消费）。"""

    species: str  # 归一化后的品种名；未识别为 "未知品种"
    raw_species: str  # 模型/规则抽取到的原始名称
    confidence: float
    source: str  # llm / rules / empty
    matched: bool  # 是否真正识别到植物（False 时调用方抛 SpeciesMissingError）

    def as_trace(self) -> dict:
        """转成可 JSON 落库的 dict（trace 字段不接受 dataclass）。"""
        return {
            "species": self.species,
            "raw_species": self.raw_species,
            "confidence": round(float(self.confidence), 4),
            "source": self.source,
            "matched": self.matched,
        }


async def _extract_with_llm(question: str) -> tuple[str, float]:
    """调用大模型抽取植物名称；任何异常都由调用方兜底，不向上抛。"""
    model = get_chat_model().bind(temperature=0, max_tokens=200)
    response = await model.ainvoke(
        [
            SystemMessage(content=QUESTION_PARSE_SYSTEM_PROMPT),
            HumanMessage(content=f"用户问题：{question}"),
        ]
    )
    payload = parse_json_payload(content_to_text(response.content))
    species = str(payload.get("species") or "").strip()
    try:
        confidence = float(payload.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    return species, max(0.0, min(1.0, confidence))


def _rule_extract(question: str, known_names: list[str]) -> str:
    """规则兜底：按名称长度倒序做包含匹配，优先命中更具体的名称。"""
    candidates = {name.strip() for name in known_names if name and name.strip()}
    candidates.update(alias for alias in ALIASES if alias and alias.strip())
    for name in sorted(candidates, key=len, reverse=True):
        if name in question:
            return name
    return ""


def _accept(raw_species: str, question: str, known_names: list[str]) -> bool:
    """防幻觉校验：模型给出的名称必须能在问题原文或用户档案中找到依据。"""
    if not raw_species:
        return False
    if raw_species in question:
        return True
    return any(raw_species == name for name in known_names if name)


async def extract_species(question: str, known_names: list[str] | None = None) -> QuestionParseResult:
    """从问题文本抽取并归一化植物名称。

    返回 matched=False 时表示问题中没有可用的植物名称，
    由调用方（chain 节点）抛 SpeciesMissingError 转成 400 中文提示。
    """
    text = (question or "").strip()
    names = [name for name in (known_names or []) if name]
    if not text:
        return QuestionParseResult("未知品种", "", 0.0, "empty", False)

    llm_error = ""
    try:
        raw_species, confidence = await _extract_with_llm(text)
        if _accept(raw_species, text, names):
            species, _ = normalize_species(raw_species)
            if species != "未知品种":
                return QuestionParseResult(species, raw_species, confidence or 0.9, "llm", True)
    except Exception as exc:  # noqa: BLE001 - 未配置 Key / 网络异常 / 输出不合规 → 走规则兜底
        llm_error = str(exc)

    raw_species = _rule_extract(text, names)
    if raw_species:
        species, _ = normalize_species(raw_species)
        if species != "未知品种":
            return QuestionParseResult(species, raw_species, 1.0, "rules", True)

    return QuestionParseResult("未知品种", "", 0.0, "llm_error" if llm_error else "empty", False)


async def owned_plant_names(user_id: int) -> list[str]:
    """当前用户档案中的植物名与品种（规则兜底的已知词表，严格按 user_id 隔离）。"""
    # 延迟导入，避免模块加载时就依赖 ORM（单元测试可脱离数据库使用规则逻辑）
    from app.models.plant import Plant

    plants = await Plant.filter(user_id=user_id).values_list("name", "species")
    names: list[str] = []
    for name, species in plants:
        if name:
            names.append(str(name))
        if species:
            names.append(str(species))
    return names


async def match_owned_plant(user_id: int, species: str, question: str | None = None):
    """在用户自己的植物档案里定位「要查询的植物」，用于拼接打卡摘要。

    匹配优先级：
    1. 问题原文里直接出现了植物名（用户给植物起的名字，如「小绿叶子黄了」）；
    2. 档案品种与解析出的标准品种一致（含别名归一化）。
    未命中返回 None，链路继续走通用知识 + 新用户上下文。
    """
    from app.models.plant import Plant

    plants = await Plant.filter(user_id=user_id).order_by("id")
    if not plants:
        return None

    text = (question or "").strip()
    named = sorted(
        (plant for plant in plants if plant.name),
        key=lambda plant: len(plant.name),
        reverse=True,
    )
    for plant in named:
        if plant.name in text:
            return plant

    target, _ = normalize_species(species)
    if target == "未知品种":
        return None
    for plant in plants:
        for candidate in (plant.species, plant.name):
            if not candidate:
                continue
            normalized, _ = normalize_species(str(candidate))
            if normalized == target:
                return plant
    return None