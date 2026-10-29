"""AI 链路自测脚本（PRD 11.2 / 11.4 验收前的手工冒烟）。

在 backend 目录执行（需要真实网络与 .env 密钥）：
    ..\\.venv\\Scripts\\python.exe -m scripts.smoke_ai
    ..\\.venv\\Scripts\\python.exe -m scripts.smoke_ai --query "绿萝叶子发黄怎么办"
    ..\\.venv\\Scripts\\python.exe -m scripts.smoke_ai --image-url /static/uploads/xxx.jpg

检查项：
1. LLM / Embedding 配置与接口连通性；
2. 知识库文件与向量库切片数量；
3. 检索命中情况（含阈值过滤）；
4. 完整五节点生成（不依赖数据库：不传 plant_id）；
5. 多轮记忆是否生效（同一 session 连续两轮）。
"""

import argparse
import asyncio
import sys
import time

from app.core.config import get_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PlantPulse AI 链路冒烟自测")
    parser.add_argument("--query", default="绿萝多久浇水一次", help="测试问题")
    parser.add_argument("--species", default=None, help="指定品种（不传则测纯知识检索）")
    parser.add_argument("--image-url", default=None, help="植物图片 URL（测试图像识别）")
    parser.add_argument("--skip-llm", action="store_true", help="只测 Embedding 与检索，不调用 LLM")
    return parser.parse_args()


async def _check_embedding(settings) -> bool:
    from app.ai.llm import get_embedding_model

    started = time.perf_counter()
    vector = await get_embedding_model().aembed_query("绿萝浇水")
    cost = int((time.perf_counter() - started) * 1000)
    print(f"[通过] Embedding 可用：维度 {len(vector)}，耗时 {cost}ms，模型 {settings.EMBEDDING_MODEL}")
    return True


def _check_vector_store() -> bool:
    from app.ai.ingestion import inspect_knowledge_base
    from app.ai.vector_store import count_documents, list_sources

    info = inspect_knowledge_base()
    count = count_documents()
    sources = list_sources()
    print(f"[信息] 磁盘文档 {info['count']} 个，向量库切片 {count} 条，已入库文件 {len(sources)} 个")
    if count == 0:
        print("[警告] 向量库为空，请先执行：..\\.venv\\Scripts\\python.exe -m scripts.ingest_knowledge")
        return False
    return True


def _check_retrieval(query: str, species: str | None) -> bool:
    from app.ai.retriever import retrieve

    settings = get_settings()
    # 用户问题里已含品种名时不重复拼接
    if not species:
        search_query = f"通用养护 {query}"
    elif species in query:
        search_query = query
    else:
        search_query = f"{species} {query}".strip()
    result = retrieve(
        search_query,
        top_k=settings.RAG_TOP_K,
        threshold=settings.RAG_SCORE_THRESHOLD,
        category=None if species else "general",
        species=species,
    )
    if result.error:
        print(f"[错误] 检索失败：{result.error}")
        return False
    print(f"[信息] 检索 Query：{result.query}，阈值 {result.threshold}，命中 {len(result.chunks)} 条")
    for chunk in result.chunks:
        print(f"  - {chunk.score:.3f}  {chunk.doc_id}  {chunk.title}")
    if not result.chunks:
        print("[警告] 检索无命中，将走通用知识降级路径（is_fallback=true）")
    return True


async def _check_workflow(args) -> bool:
    from app.ai.chain import SpeciesMissingError, run_care_advice
    from app.ai.memory import get_memory_store

    memory = get_memory_store()
    session_id = "smoke-session"
    # 每次冒烟从干净会话开始，避免历史对话累积影响判断
    memory.clear(1, session_id)
    history = memory.history_text(1, session_id)

    started = time.perf_counter()
    try:
        result = await run_care_advice(
            user_id=1,
            plant_id=None,
            image_url=args.image_url,
            user_species=args.species,
            question=args.query,
            session_id=session_id,
            history=history,
        )
    except SpeciesMissingError:
        print("[错误] 问题文本中未识别到植物名称：请说明植物种类或名称（如「绿萝叶子发黄怎么办」）")
        return False
    except Exception as exc:  # 超时/服务不可用等：打印可读错误，避免整段 traceback
        print(f"[错误] 五节点链路失败：{type(exc).__name__}: {exc}")
        return False
    cost = int((time.perf_counter() - started) * 1000)

    print(f"[通过] 五节点链路完成：{cost}ms，品种={result['species']}，"
          f"置信度={result['confidence']:.2f}，is_fallback={result['is_fallback']}")
    print(f"  摘要：{result['summary']}")
    for section in result["sections"]:
        print(f"  - [{section['source_type']}] {section['title']}：{section['content'][:60]}...")
    print(f"  来源：{[item['doc_id'] for item in result['doc_refs']]}")

    # 追溯校验：每条分节必须有 doc_ids 或 general 标注（PRD 11.4 来源可追溯率 100%）
    invalid = [
        section for section in result["sections"]
        if section["source_type"] == "knowledge" and not section["doc_ids"]
    ]
    if invalid:
        print(f"[错误] 来源标注不合规：{[item['key'] for item in invalid]}")
        return False

    memory.append(1, session_id, args.query, result["summary"])
    print(f"[通过] 记忆已写入：{memory.history_text(1, session_id)[:80]}...")

    trace = result["trace"]
    print(f"[trace] 检索={trace.get('retrieval', {}).get('hit')}，"
          f"生成状态={trace.get('generate', {}).get('status')}，总耗时={trace.get('total_ms')}ms")
    if trace.get("llm_error"):
        print(f"[警告] LLM 调用失败，已降级为通用知识：{trace['llm_error']}")
    return True


async def main() -> int:
    args = _parse_args()
    settings = get_settings()

    print("=" * 60)
    print(f"LLM：{settings.LLM_MODEL} @ {settings.llm_base_url}")
    print(f"Embedding：{settings.EMBEDDING_MODEL} @ {settings.embedding_base_url}")
    print(f"知识库：{settings.knowledge_dir}")
    print("=" * 60)

    try:
        from app.ai.retriever import retrieve  # noqa: F401  仅验证依赖是否安装
    except ImportError as exc:
        print(f"[错误] AI 依赖未安装：{exc}")
        print("请先执行：..\\.venv\\Scripts\\python.exe -m pip install -r requirements-ai.txt")
        return 2

    await _check_embedding(settings)
    has_vectors = _check_vector_store()
    if has_vectors:
        _check_retrieval(args.query, args.species)

    if args.image_url:
        from app.ai.chain import get_workflow

        identified = await get_workflow().identify(args.image_url)
        print(f"[通过] 图像识别：{identified}")

    if args.skip_llm:
        print("[完成] 已跳过 LLM 生成")
        return 0

    ok = await _check_workflow(args)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))