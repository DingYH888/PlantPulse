"""RAG 检索与阈值过滤（PRD 8.1 节点3 / 节点3b / 8.4 阈值兜底）。

检索策略：
1. 以「标准品种名 + 用户问题」构造 Query；
2. Chroma cosine 距离转换为 1 - distance 的相关度（0~1，越大越相似）；
3. 低于 RAG_SCORE_THRESHOLD 的切片一律丢弃，不注入 LLM（防弱证据污染）；
4. 品种专属检索无命中时，回退 category=general 的通用养护文档（节点3b）；
5. 同一文档只保留得分最高的切片，按文档粒度输出 top_k。
"""

from dataclasses import dataclass, field

from app.ai.vector_store import get_vector_store
from app.core.config import get_settings


@dataclass
class RetrievedChunk:
    """单条检索结果（文档粒度）。"""

    doc_id: str
    title: str
    source: str
    content: str
    score: float
    category: str = "species"


@dataclass
class RetrievalResult:
    """一次检索的完整结果与可观测信息（写入 trace）。"""

    query: str
    threshold: float
    chunks: list[RetrievedChunk] = field(default_factory=list)
    used_general: bool = False
    error: str | None = None

    @property
    def hit(self) -> bool:
        """是否命中知识库（低于阈值视为无命中）。"""
        return bool(self.chunks)

    def context_text(self) -> str:
        """拼装注入提示词的参考文档文本（含 doc_id 便于回引）。"""
        if not self.chunks:
            return ""
        blocks = []
        for chunk in self.chunks:
            blocks.append(
                f"[doc_id={chunk.doc_id}][title={chunk.title}][score={chunk.score:.3f}]\n{chunk.content}"
            )
        return "\n\n".join(blocks)

    def doc_refs(self) -> list[dict]:
        """落库用的来源清单（PRD FR-404 / 8.5）。"""
        return [
            {
                "doc_id": chunk.doc_id,
                "title": chunk.title,
                "source": chunk.source,
                "score": round(chunk.score, 4),
                "category": chunk.category,
            }
            for chunk in self.chunks
        ]


def _convert_pairs(pairs: list[tuple], top_k: int) -> list[RetrievedChunk]:
    """把 (Document, cosine_distance) 转换为按 doc_id 去重的相关度列表。"""
    best_by_doc: dict[str, RetrievedChunk] = {}
    for document, distance in pairs:
        metadata = document.metadata or {}
        doc_id = str(metadata.get("doc_id") or metadata.get("source") or "unknown")
        # cosine distance ∈ [0, 2]；截断到 0~1，越小越不相关
        score = max(0.0, min(1.0, 1.0 - float(distance)))
        chunk = RetrievedChunk(
            doc_id=doc_id,
            title=str(metadata.get("title") or doc_id),
            source=str(metadata.get("source") or ""),
            content=document.page_content,
            score=score,
            category=str(metadata.get("category") or "species"),
        )
        previous = best_by_doc.get(doc_id)
        if previous is None or chunk.score > previous.score:
            best_by_doc[doc_id] = chunk
    ranked = sorted(best_by_doc.values(), key=lambda item: item.score, reverse=True)
    return ranked[:top_k]


def _balance_species_and_general(chunks: list[RetrievedChunk], limit: int) -> list[RetrievedChunk]:
    """品种检索时控制通用文档数量，避免通用知识挤占品种专属片段。"""
    species_chunks = [chunk for chunk in chunks if chunk.category == "species"]
    general_chunks = [chunk for chunk in chunks if chunk.category == "general"][:2]
    merged = sorted(species_chunks + general_chunks, key=lambda item: item.score, reverse=True)
    return merged[:limit]


def retrieve(
    query: str,
    top_k: int | None = None,
    threshold: float | None = None,
    category: str | None = None,
    species: str | None = None,
) -> RetrievalResult:
    """执行一次检索（同步，调用方需放到线程池避免阻塞事件循环）。

    species 已知时用 `$or(species=品种, category=general)` 过滤，
    避免"绿萝"问题命中琴叶榕/铜钱草等其他品种文档（跨品种污染）。
    """
    settings = get_settings()
    limit = top_k if top_k is not None else settings.RAG_TOP_K
    min_score = threshold if threshold is not None else settings.RAG_SCORE_THRESHOLD
    result = RetrievalResult(query=query, threshold=min_score)

    # 过滤优先级：显式 category > species 过滤 > 不过滤
    if category:
        filter_meta: dict | None = {"category": category}
    elif species and species != "未知品种":
        filter_meta = {"$or": [{"species": species}, {"category": "general"}]}
    else:
        filter_meta = None

    try:
        store = get_vector_store()
        # 多取一些候选，过滤阈值后再截断
        pairs = store.similarity_search_with_score(query, k=max(limit * 3, 10), filter=filter_meta)
        chunks = [chunk for chunk in _convert_pairs(pairs, limit) if chunk.score >= min_score]
        if filter_meta and species and not category:
            chunks = _balance_species_and_general(chunks, limit)
    except Exception as exc:  # 向量库缺失 / Embedding 接口异常
        result.error = f"向量检索失败：{exc}"
        return result

    if chunks:
        result.chunks = chunks
        return result

    # 品种名与知识库 species 元数据不完全一致时（学名/别名），
    # 去掉品种过滤再做一次全库检索，避免明明有该品种文档却被降级。
    if filter_meta and species and not category:
        try:
            pairs = store.similarity_search_with_score(query, k=max(limit * 3, 10), filter=None)
            fallback_chunks = [chunk for chunk in _convert_pairs(pairs, limit) if chunk.score >= min_score]
        except Exception as exc:
            result.error = f"全库检索失败：{exc}"
            return result
        if fallback_chunks:
            result.chunks = fallback_chunks
            return result

    # 节点3b：品种无命中时回退通用养护知识（仅在首次检索不是 general 时执行）
    if category != "general":
        general_query = f"通用养护 {query}".strip()
        try:
            pairs = store.similarity_search_with_score(general_query, k=max(limit * 2, 8), filter={"category": "general"})
            general_chunks = [chunk for chunk in _convert_pairs(pairs, limit) if chunk.score >= min_score]
        except Exception as exc:
            result.error = f"通用知识检索失败：{exc}"
            return result
        if general_chunks:
            result.chunks = general_chunks
            result.used_general = True
            result.query = general_query

    return result