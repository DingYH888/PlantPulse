"""文本切分（PRD 8.1 节点3 文档预处理）。

中文文档没有空格分词，按字符长度切分更可控：
- separators 从段落 → 句子 → 标点逐级回退，尽量避免切断完整句子；
- chunk_size / chunk_overlap 由 .env 控制，调参不需要改代码；
- 每个 chunk 保留原文档全部元数据，并追加 chunk_index 便于回溯。
"""

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import get_settings

# 中文优先分隔符：段落 → 换行 → 句号/问号/感叹号 → 分号/逗号 → 空格
CHINESE_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]


def build_splitter(chunk_size: int | None = None, chunk_overlap: int | None = None) -> RecursiveCharacterTextSplitter:
    """构造递归字符切分器，并校验参数合法性。"""
    settings = get_settings()
    size = chunk_size if chunk_size is not None else settings.RAG_CHUNK_SIZE
    overlap = chunk_overlap if chunk_overlap is not None else settings.RAG_CHUNK_OVERLAP
    if size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("chunk_overlap 必须在 [0, chunk_size) 区间内")
    return RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        separators=CHINESE_SEPARATORS,
        length_function=len,
        keep_separator=True,
    )


def split_documents(
    documents: list[Document],
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[Document]:
    """切分文档，并为每个 chunk 补充 chunk_index。"""
    splitter = build_splitter(chunk_size, chunk_overlap)
    chunks: list[Document] = []
    # 全局递增序号：同一文件的多页 PDF 也保证 chunk_index 唯一（向量 ID 不冲突）
    chunk_index = 0
    for document in documents:
        pieces = splitter.split_documents([document])
        for piece in pieces:
            if not piece.page_content.strip():
                continue
            piece.metadata = {**piece.metadata, "chunk_index": chunk_index}
            chunks.append(piece)
            chunk_index += 1
    return chunks