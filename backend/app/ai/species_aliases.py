"""品种同义词归一化（PRD 8.1 节点2）。

策略：以「知识库 frontmatter 中的 species / aliases」为准，另内置常见品种
别名兜底。归一化只做映射，不猜测未知品种；未命中时 is_known=False，
走节点3b 通用知识路径（PRD 8.4 置信度兜底）。
"""

# 内置常见别名：key 为小写别名，value 为知识库标准品种名
ALIASES: dict[str, str] = {
    "绿萝": "绿萝",
    "黄金葛": "绿萝",
    "epipremnum aureum": "绿萝",
    "龟背竹": "龟背竹",
    "monstera deliciosa": "龟背竹",
    "吊兰": "吊兰",
    "chlorophytum comosum": "吊兰",
    "虎皮兰": "虎尾兰",
    "虎尾兰": "虎尾兰",
    "sansevieria trifasciata": "虎尾兰",
    "芦荟": "芦荟",
    "aloe vera": "芦荟",
    "发财树": "发财树",
    "pachira aquatica": "发财树",
    "多肉": "多肉植物",
    "多肉植物": "多肉植物",
    "succulent": "多肉植物",
    "月季": "月季",
    "玫瑰": "月季",
    "rosa chinensis": "月季",
    "君子兰": "君子兰",
    "clivia miniata": "君子兰",
    "文竹": "文竹",
    "asparagus setaceus": "文竹",
    "常春藤": "常春藤",
    "hedera helix": "常春藤",
}


def normalize_species(raw: str | None) -> tuple[str, bool]:
    """把识别/用户输入品种归一化为知识库标准名。

    返回 (标准品种名, 是否已知)。空值或未命中返回 ("未知品种", False)。
    """
    if not raw:
        return "未知品种", False
    name = raw.strip()
    if not name:
        return "未知品种", False
    mapped = ALIASES.get(name.lower()) or ALIASES.get(name)
    if mapped:
        return mapped, True
    # 未在别名表命中时保留原名称，但仍标记为未知：
    # 由检索结果决定它是否真的能在知识库中找到专属文档。
    return name, False
