"""知识库入库脚本（PRD 8.1 节点3）。

用法（在 backend 目录执行）：
    ..\\.venv\\Scripts\\python.exe -m scripts.ingest_knowledge
    ..\\.venv\\Scripts\\python.exe -m scripts.ingest_knowledge --rebuild
    ..\\.venv\\Scripts\\python.exe -m scripts.ingest_knowledge --dir ..\\docs\\knowledge_base\\species

说明：需要真实调用百炼 Embedding 接口，必须在本地终端执行（沙箱网络受限）。
"""

import argparse
import sys
from pathlib import Path

from app.core.config import get_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PlantPulse 知识库入库")
    parser.add_argument("--rebuild", action="store_true", help="清空向量库后全量重建")
    parser.add_argument("--dir", default=None, help="指定知识库目录（默认读取 .env KNOWLEDGE_DIR）")
    parser.add_argument("--chunk-size", type=int, default=None, help="临时覆盖切分长度")
    parser.add_argument("--chunk-overlap", type=int, default=None, help="临时覆盖切分重叠")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    settings = get_settings()

    print("=" * 60)
    print(f"知识库目录：{settings.knowledge_dir}")
    print(f"向量库目录：{settings.chroma_dir}")
    print(f"Collection：{settings.CHROMA_COLLECTION}")
    print(f"切分参数：chunk_size={args.chunk_size or settings.RAG_CHUNK_SIZE}, "
          f"overlap={args.chunk_overlap or settings.RAG_CHUNK_OVERLAP}")
    print(f"Embedding：{settings.EMBEDDING_MODEL} @ {settings.embedding_base_url}")
    print("=" * 60)

    try:
        from app.ai.ingestion import ingest_knowledge_base
    except ImportError as exc:
        print(f"[错误] AI 依赖未安装：{exc}")
        print("请先执行：..\\.venv\\Scripts\\python.exe -m pip install -r requirements-ai.txt")
        return 2

    knowledge_dir = Path(args.dir).resolve() if args.dir else None
    report = ingest_knowledge_base(
        rebuild=args.rebuild,
        knowledge_dir=knowledge_dir,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    print(f"扫描文件：{report.files}")
    print(f"解析文档：{report.documents}")
    print(f"写入切片：{report.chunks}")
    if report.skipped:
        print(f"跳过文件（无有效文本）：{len(report.skipped)}")
        for item in report.skipped:
            print(f"  - {item}")
    if report.errors:
        print(f"[错误] {len(report.errors)} 项：")
        for item in report.errors:
            print(f"  - {item}")
        return 1
    print("[完成] 知识库入库成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())