"""问题文本植物名称解析单元测试（不依赖真实 LLM）。

覆盖新交互的核心分支：
1. 问题中出现已知品种（含别名）→ 能解析出标准品种名；
2. 问题中只有"叶子发黄"等泛指 → matched=False（接口层转 400）；
3. 模型给出问题原文里不存在的名称 → 视为幻觉丢弃；
4. 用户档案里的植物名可以直接被识别；
5. 用户自己的植物档案能按名字/品种定位（数据隔离）。
"""

import pytest

from app.ai import question_parser
from app.ai.question_parser import extract_species, match_owned_plant

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """默认让 LLM 不可用，强制走规则兜底，测试结果与网络无关。"""

    async def boom(_question: str):
        raise RuntimeError("LLM 不可用")

    monkeypatch.setattr(question_parser, "_extract_with_llm", boom)


async def test_extract_known_species_from_question():
    """问题中直接写明品种：解析出标准品种名。"""
    result = await extract_species("绿萝叶子发黄怎么办")
    assert result.matched is True
    assert result.species == "绿萝"
    assert result.source == "rules"


async def test_extract_alias_species():
    """别名归一化：黄金葛 → 绿萝。"""
    result = await extract_species("黄金葛叶子发黄怎么办")
    assert result.matched is True
    assert result.species == "绿萝"


async def test_extract_missing_species():
    """问题中没有植物名称：matched=False，由接口层提示「请说明植物种类或名称」。"""
    result = await extract_species("叶子发黄怎么办")
    assert result.matched is False
    assert result.species == "未知品种"


async def test_extract_owned_plant_name():
    """用户档案里的自定义植物名可作为植物名称来源。"""
    result = await extract_species("小绿叶子发黄怎么办", known_names=["小绿"])
    assert result.matched is True
    assert result.raw_species == "小绿"


async def test_extract_rejects_hallucinated_species(monkeypatch):
    """LLM 返回问题原文中不存在的名称时视为幻觉，不能通过校验。"""

    async def fake_llm(_question: str):
        return "琴叶榕", 0.95

    monkeypatch.setattr(question_parser, "_extract_with_llm", fake_llm)
    result = await extract_species("叶子发黄怎么办")
    assert result.matched is False


async def test_extract_accepts_llm_species(monkeypatch):
    """LLM 抽取结果出现在问题原文中时直接采用。"""

    async def fake_llm(_question: str):
        return "龟背竹", 0.92

    monkeypatch.setattr(question_parser, "_extract_with_llm", fake_llm)
    result = await extract_species("龟背竹叶子发黄怎么办")
    assert result.matched is True
    assert result.species == "龟背竹"
    assert result.source == "llm"


async def test_match_owned_plant_by_name_and_species():
    """定位用户植物：优先问题里出现的植物名，其次品种归一化匹配。"""
    from app.core.security import hash_password
    from app.models.plant import Plant
    from app.models.user import User

    user = await User.create(
        nickname="qp_owner",
        password_hash=hash_password("pass1234"),
        is_active=True,
    )
    plant = await Plant.create(user_id=user.id, name="小绿", species="绿萝")
    await Plant.create(user_id=user.id, name="大绿", species="龟背竹")

    matched = await match_owned_plant(user.id, "绿萝", "小绿叶子发黄怎么办")
    assert matched is not None
    assert matched.id == plant.id

    matched_by_species = await match_owned_plant(user.id, "绿萝", "绿萝叶子发黄怎么办")
    assert matched_by_species is not None
    assert matched_by_species.id == plant.id

    # 数据隔离：他人无法匹配到该用户的植物
    other = await User.create(
        nickname="qp_other",
        password_hash=hash_password("pass1234"),
        is_active=True,
    )
    assert await match_owned_plant(other.id, "绿萝", "绿萝叶子发黄怎么办") is None