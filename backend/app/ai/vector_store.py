"""ChromaDB 向量库封装（PRD 3.2 / 8.1 节点3）。

- 持久化目录：backend/chroma_db（已 git 忽略），进程重启不丢向量；
- 距离度量：cosine，便于把 distance 线性转换为 0~1 相关度；
- Embedding 函数：百炼 qwen Embedding（见 llm.get_embedding_model）；
- 单例复用，避免并发请求反复打开底层 sqlite 连接。
"""

import threading

from langchain_chroma import Chroma

from app.ai.llm import get_embedding_model
from app.core.config import get_settings

_store: Chroma | None = None
_lock = threading.Lock()


def get_vector_store() -> Chroma:
    """获取（或初始化）Chroma 向量库单例。"""
    global _store
    if _store is not None:
        return _store
    with _lock:
        if _store is None:
            settings = get_settings()
            settings.chroma_dir.mkdir(parents=True, exist_ok=True)
            _store = Chroma(
                collection_name=settings.CHROMA_COLLECTION,
                embedding_function=get_embedding_model(),
                persist_directory=str(settings.chroma_dir),
                collection_metadata={"hnsw:space": "cosine"},
            )
        return _store


def reset_vector_store() -> None:
    """释放单例（切换向量库目录 / 测试时使用）。"""
    global _store
    with _lock:
        _store = None


def drop_vector_store() -> None:
    """删除整个 collection（重新入库前调用，慎用）。"""
    global _store
    with _lock:
        if _store is not None:
            _store.delete_collection()
        _store = None


def count_documents() -> int:
    """向量库中的切片总数（用于健康检查与入库校验）。"""
    return get_vector_store()._collection.count()


def list_sources() -> list[str]:
    """列出已入库的源文件（去重），便于排查知识库覆盖范围。"""
    result = get_vector_store().get(include=["metadatas"])
    sources = {
        str(metadata.get("source", ""))
        for metadata in (result.get("metadatas") or [])
        if metadata.get("source")
    }
    return sorted(sources)