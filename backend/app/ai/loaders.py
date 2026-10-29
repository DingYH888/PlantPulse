"""知识库文档加载（PRD 8.1 节点3 的上游数据准备）。

支持格式：Markdown / 纯文本 / PDF / DOCX。
元数据约定见 docs/knowledge_base/README.md：

    ---
    doc_id: monstera-care-001      # 可选，默认由文件路径生成
    title: 龟背竹养护指南
    species: 龟背竹
    aliases: 龟背竹, Monstera deliciosa
    category: species              # species（品种专属）/ general（通用养护）
    ---

未写 frontmatter 时不报错，按"文件名 + 所在目录"尽力推断，
保证用户可以直接把文档丢进目录就开始入库。
"""

import hashlib
import re
from pathlib import Path

from langchain_core.documents import Document

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf", ".docx"}
# 说明类文件不参与入库，避免把使用说明当成养护知识
SKIP_FILENAMES = {"readme.md", "readme.txt", "_template.md", "_template.txt"}
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析轻量 frontmatter（只支持 key: value，避免引入 YAML 依赖）。"""
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta, text[match.end() :]


def _read_pdf(path: Path) -> list[str]:
    """逐页提取 PDF 文本；空页跳过。"""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            pages.append(text)
    return pages


def _read_docx(path: Path) -> list[str]:
    """提取 Word 正文（段落 + 表格）。"""
    from docx import Document as DocxDocument

    document = DocxDocument(str(path))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return ["\n".join(parts)] if parts else []


def _read_text(path: Path) -> list[str]:
    """读取 Markdown / TXT（UTF-8 优先，兼容 GBK）。"""
    try:
        return [path.read_text(encoding="utf-8")]
    except UnicodeDecodeError:
        return [path.read_text(encoding="gbk", errors="ignore")]


def iter_knowledge_files(root: Path) -> list[Path]:
    """递归列出可入库文档（排除隐藏文件、说明文件）。"""
    files: list[Path] = []
    if not root.exists():
        return files
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if path.name.startswith(".") or path.name.lower() in SKIP_FILENAMES:
            continue
        files.append(path)
    return files


def _build_doc_id(relative_path: Path, meta: dict[str, str]) -> str:
    """生成稳定 doc_id：优先 frontmatter，其次目录+文件名。"""
    if meta.get("doc_id"):
        return meta["doc_id"].strip()
    parts = [part for part in relative_path.with_suffix("").parts if part not in {".", ""}]
    raw = "-".join(parts) if parts else relative_path.stem
    slug = re.sub(r"[\s_]+", "-", raw).strip("-")
    # 极端情况下（纯中文文件名被清洗为空）用内容 hash 兜底
    return slug or hashlib.md5(str(relative_path).encode("utf-8")).hexdigest()[:10]


def _infer_metadata(path: Path, root: Path, meta: dict[str, str]) -> dict[str, str]:
    """合并 frontmatter 与路径推断结果。"""
    relative = path.relative_to(root)
    parent = relative.parent.as_posix()
    is_general_by_dir = parent not in {".", ""} and any(
        keyword in parent.lower() for keyword in ("general", "通用", "common")
    )
    category = meta.get("category", "").lower()
    if category not in {"species", "general"}:
        category = "general" if is_general_by_dir else "species"

    species = meta.get("species", "").strip()
    if not species and parent not in {".", ""} and not is_general_by_dir:
        species = relative.parent.name

    return {
        "source": relative.as_posix(),
        "doc_id": _build_doc_id(relative, meta),
        "title": meta.get("title", "").strip() or path.stem,
        "species": species,
        "aliases": meta.get("aliases", "").strip(),
        "category": category,
    }


def load_file(path: Path, root: Path) -> list[Document]:
    """加载单个文档；PDF 按页返回多个 Document，其余整篇一个。"""
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        blocks = _read_text(path)
    elif suffix == ".pdf":
        blocks = _read_pdf(path)
    elif suffix == ".docx":
        blocks = _read_docx(path)
    else:
        return []

    documents: list[Document] = []
    for index, block in enumerate(blocks):
        # frontmatter 只可能出现在文本类文件的首块
        meta_raw, body = _parse_frontmatter(block) if index == 0 else ({}, block)
        if not body.strip():
            continue
        metadata = _infer_metadata(path, root, meta_raw)
        metadata["file_type"] = suffix.lstrip(".")
        if suffix == ".pdf":
            metadata["page"] = index + 1
        documents.append(Document(page_content=body, metadata=metadata))
    return documents


def load_knowledge_base(root: Path) -> tuple[list[Document], list[str]]:
    """加载整个知识库目录，返回 (文档列表, 错误列表)。"""
    documents: list[Document] = []
    errors: list[str] = []
    for path in iter_knowledge_files(root):
        try:
            documents.extend(load_file(path, root))
        except Exception as exc:  # 单文件解析失败不阻断整体入库
            errors.append(f"{path.name}: {exc}")
    return documents, errors