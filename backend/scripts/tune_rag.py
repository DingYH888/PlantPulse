"""RAG 检索调参脚本（PRD 8.6 / 用户要求的自测与调参）。

只扫描 top_k 与相似度阈值（复用同一次向量查询结果，不重复调用 Embedding）：
    ..\\.venv\\Scripts\\python.exe -m scripts.tune_rag --query "绿萝叶子发黄" --species 绿萝
    ..\\.venv\\Scripts\\python.exe -m scripts.tune_rag --query "多肉多久浇水" --top-k 3,5,8

chunk_size / chunk_overlap 变更需要重建向量库，脚本不自动执行，避免误耗 Embedding 额度：
    ..\\.venv\\Scripts\\python.exe -m scripts.ingest_knowledge --rebuild --chunk-size 400 --chunk-overlap 80
"""

import argparse
import sys

from app.core.config import get_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PlantPulse RAG 检索调参")
    parser.add_argument("--query", required=True, help="测试问题")
    parser.add_argument("--species", default=None, help="品种名（不传则检索通用知识）")
    parser.add_argument("--top-k", default="3,5,8", help="待测 top_k 列表，逗号分隔")
    parser.add_argument("--threshold", default="0.30,0.45,0.55", help="待测阈值列表，逗号分隔")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    settings = get_settings()

    try:
        from app.ai.vector_store import get_vector_store, count_documents
    except ImportError as exc:
        print(f"[错误] AI 依赖未安装：{exc}")
        return 2

    if count_documents() == 0:
        print("[错误] 向量库为空，请先执行：..\\.venv\\Scripts\\python.exe -m scripts.ingest_knowledge")
        return 1

    if not args.species:
        query = f"通用养护 {args.query}"
    elif args.species in args.query:
        query = args.query
    else:
        query = f"{args.species} {args.query}".strip()

    # 与 chain 一致的检索过滤：品种文档 + 通用知识，避免跨品种污染
    if args.species:
        filter_meta = {"$or": [{"species": args.species}, {"category": "general"}]}
    else:
        filter_meta = {"category": "general"}
    store = get_vector_store()

    print("=" * 80)
    print(f"Query：{query}")
    print(f"Filter：{filter_meta}")
    print(f"文档级候选（按相关度降序，最多 20 条）：")
    print("-" * 80)

    pairs = store.similarity_search_with_score(query, k=20, filter=filter_meta)
    ranked = []
    seen_docs: set[str] = set()
    for document, distance in pairs:
        doc_id = str(document.metadata.get("doc_id", "unknown"))
        if doc_id in seen_docs:
            continue
        seen_docs.add(doc_id)
        score = max(0.0, min(1.0, 1.0 - float(distance)))
        ranked.append((doc_id, str(document.metadata.get("title", "")), score, document.page_content[:60]))

    for doc_id, title, score, preview in ranked:
        print(f"  {score:.3f}  {doc_id:<32} {title:<20} {preview}")

    print("=" * 80)
    top_k_values = [int(value) for value in args.top_k.split(",") if value.strip()]
    threshold_values = [float(value) for value in args.threshold.split(",") if value.strip()]

    print(f"{'top_k':<8}{'threshold':<12}{'命中数':<8}{'最低分':<10}{'最高分':<10}")
    for top_k in top_k_values:
        for threshold in threshold_values:
            selected = [item for item in ranked if item[2] >= threshold][:top_k]
            scores = [item[2] for item in selected]
            min_score = f"{min(scores):.3f}" if scores else "-"
            max_score = f"{max(scores):.3f}" if scores else "-"
            print(f"{top_k:<8}{threshold:<12}{len(selected):<8}{min_score:<10}{max_score:<10}")

    print("-" * 80)
    print("建议：")
    print("1. 命中数长期为 0 → 调低阈值或补充该品种知识文档；")
    print("2. 命中很多但答非所问 → 调高阈值、减小 RAG_TOP_K；")
    print("3. 回答内容被截断/散乱 → 调小 RAG_CHUNK_SIZE（需 --rebuild 重新入库）。")
    print(f"当前 .env：top_k={settings.RAG_TOP_K}, threshold={settings.RAG_SCORE_THRESHOLD}, "
          f"chunk_size={settings.RAG_CHUNK_SIZE}, overlap={settings.RAG_CHUNK_OVERLAP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())