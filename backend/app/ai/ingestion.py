"""知识库入库流水线：加载 → 切分 → 向量化 → Chroma 持久化。

幂等策略：
- 以 `source`（相对知识库根目录的路径）为业务主键；
- 入库前先按 source 删除旧切片，再写入新切片，避免重复文档污染检索结果；
- doc_id 保持稳定，便于 LLM 引用与前端展示来源。

注意：Embedding 调用有网络耗时，脚本需在本地终端执行（沙箱网络受限）。
"""

from dataclasses import dataclass, field
from pathlib import Path

from app.ai.loaders import iter_knowledge_files, load_file
from app.ai.splitter import split_documents
from app.ai.vector_store import drop_vector_store, get_vector_store
from app.core.config import get_settings

# 百炼 Embedding 单次批量上限较保守，小批量提交更稳
EMBED_BATCH_SIZE = 10


@dataclass
class IngestReport:
    """入库结果统计。"""

    files: int = 0
    documents: int = 0
    chunks: int = 0
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _delete_source(source: str) -> None:
    """删除某个源文件的全部历史切片（幂等重建）。"""
    store = get_vector_store()
    existing = store.get(where={"source": source}, include=["metadatas"])
    ids = existing.get("ids") or []
    if ids:
        store.delete(ids=ids)


def _add_in_batches(chunks: list) -> None:
    """按批次写入向量库，避免单次请求体过大触发 Embedding 接口限流。"""
    store = get_vector_store()
    for start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[start : start + EMBED_BATCH_SIZE]
        ids = [
            f"{chunk.metadata['doc_id']}::{chunk.metadata['source']}::{chunk.metadata['chunk_index']}"
            for chunk in batch
        ]
        store.add_documents(batch, ids=ids)


def ingest_knowledge_base(
    rebuild: bool = False,
    knowledge_dir: Path | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> IngestReport:
    """执行知识库入库。

    rebuild=True 时先清空整个 collection（知识库结构大改时使用）。
    """
    settings = get_settings()
    root = knowledge_dir or settings.knowledge_dir
    report = IngestReport()

    if not root.exists():
        report.errors.append(f"知识库目录不存在：{root}")
        return report

    if rebuild:
        drop_vector_store()

    files = iter_knowledge_files(root)
    report.files = len(files)
    if not files:
        report.errors.append(f"知识库目录中没有可入库文档：{root}")
        return report

    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            documents = load_file(path, root)
        except Exception as exc:
            report.errors.append(f"{relative}: {exc}")
            continue
        report.documents += len(documents)
        chunks = split_documents(documents, chunk_size, chunk_overlap)
        if not chunks:
            report.skipped.append(relative)
            continue

        # 保证同一文件内 doc_id 一致（PDF 多页共享 frontmatter doc_id）
        doc_id = chunks[0].metadata.get("doc_id", "")
        for chunk in chunks:
            chunk.metadata["doc_id"] = doc_id

        try:
            _delete_source(relative)
            _add_in_batches(chunks)
            report.chunks += len(chunks)
        except Exception as exc:
            report.errors.append(f"{relative}: 向量化失败 {exc}")


    return report


def inspect_knowledge_base() -> dict:
    """查看知识库文件与已入库源文件差异（不调用 Embedding，成本低）。"""
    settings = get_settings()
    root = settings.knowledge_dir
    disk_files = [path.relative_to(root).as_posix() for path in iter_knowledge_files(root)] if root.exists() else []
    return {"knowledge_dir": str(root), "disk_files": disk_files, "count": len(disk_files)}