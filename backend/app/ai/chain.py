"""LangChain LCEL 五节点编排（PRD 8.1 固定链路 / 8.4 防幻觉）。

    节点1 图像识别 → 节点2 品种归一化 → 节点3/3b 知识检索
    → 节点4 用户打卡摘要 → 节点5 LLM 个性化生成

实现约定：
1. 使用 LCEL（RunnableLambda 管道）串联，节点间用 payload dict 传递，
   每一步都把耗时与结果写入 trace，便于落库追溯（PRD 8.4 可追溯）；
2. 节点3 检索同步 SDK 放到线程池执行，避免阻塞 FastAPI 事件循环；
3. 节点5 输出经 Pydantic 校验；解析/校验失败重试 1 次（PRD 8.4 输出校验）；
4. LLM 生成失败时降级为"通用知识"输出并标注 is_fallback=true（PRD 12 可用性），
   图像识别阶段服务不可用则抛 AiUnavailableError → 接口返回 503。
"""

import asyncio
import hashlib
import json
import logging
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.runnables import RunnableLambda

from app.ai.context import build_care_context, general_knowledge_text
from app.ai.fallback import GENERAL_KNOWLEDGE, build_general_output
from app.ai.image_utils import ImageAccessError, to_model_image_url
from app.ai.json_utils import content_to_text, parse_json_payload
from app.ai.llm import get_chat_model, get_vision_model
from app.ai.prompts import (

    NEW_USER_CONTEXT,
    NO_KNOWLEDGE_CONTEXT,
    VISION_SYSTEM_PROMPT,
    advice_prompt,
)
from app.ai.question_parser import (
    SpeciesMissingError,
    extract_species,
    match_owned_plant,
    owned_plant_names,
)
from app.ai.retriever import RetrievalResult, retrieve
from app.ai.schemas import (
    SECTION_TITLES,
    AdviceSection,
    CareAdviceOutput,
    IdentifyOutput,
    normalize_section_order,
)
from app.ai.species_aliases import normalize_species
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class AiTimeoutError(RuntimeError):
    """AI 链路超过端到端时限（PRD 9.3 → 504）。"""


class AiUnavailableError(RuntimeError):
    """AI 服务不可用 / 密钥缺失（PRD 9.3 → 503）。"""



def _content_to_text(content) -> str:
    """兼容 OpenAI 兼容接口返回 str 或 content 数组两种形态。"""
    return content_to_text(content)


def _parse_json_payload(text: str) -> dict:
    """从模型输出中提取 JSON（容忍代码块包裹与前后说明文字）。"""
    return parse_json_payload(text)


class CareAdviceWorkflow:
    """五节点工作流（无状态，可复用单例）。

    在五节点之前增加「问题解析 / 植物定位」两个前置步骤，用于支撑
    “问题文本里不再手工选择品种”的新交互：
    0. 问题解析：纯文本时由大模型抽取植物名称，抽不到 → SpeciesMissingError；
    2.5 植物定位：按解析/识别出的品种在用户档案中匹配植物，供打卡摘要使用。
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._parser = PydanticOutputParser(pydantic_object=CareAdviceOutput)
        self._pipeline = (
            RunnableLambda(self._parse_question)
            | RunnableLambda(self._identify)
            | RunnableLambda(self._normalize)
            | RunnableLambda(self._match_plant)
            | RunnableLambda(self._retrieve)
            | RunnableLambda(self._care_context)
            | RunnableLambda(self._generate)
        )

    # ---------------- 节点0：问题解析（仅纯文本） ----------------
    async def _parse_question(self, payload: dict) -> dict:
        """纯文本问题必须先解析出植物名称；有图片时品种以图像识别为准。"""
        started = time.perf_counter()
        trace = payload["trace"]
        question = (payload.get("question") or "").strip()
        user_species = (payload.get("user_species") or "").strip()

        if user_species:
            # API 兼容：调用方显式指定品种时不再解析（前端已不再传该字段）
            trace["question_parse"] = {"node": 0, "skipped": True, "reason": "调用方已指定品种"}
            return {**payload, "species_source": "user"}

        if payload.get("image_url"):
            # 有图：品种由节点1 决定，问题文本只作为检索条件
            trace["question_parse"] = {"node": 0, "skipped": True, "reason": "有图片，品种以图像识别为准"}
            return {**payload, "species_source": "vision"}

        names = await owned_plant_names(payload["user_id"])
        parsed = await extract_species(question, names)
        trace["question_parse"] = {
            "node": 0,
            **parsed.as_trace(),
            "ms": int((time.perf_counter() - started) * 1000),
        }
        if not parsed.matched:
            # 情况一：问题里没有植物名称/种类 → 由接口层返回 400 中文提示
            raise SpeciesMissingError("请说明植物种类或名称")

        return {
            **payload,
            "user_species": parsed.species,
            "species_source": "question",
        }

    # ---------------- 节点1：图像识别 ----------------
    async def _identify(self, payload: dict) -> dict:
        """有图走多模态识别；无图时品种已由节点0 从问题文本解析。"""
        started = time.perf_counter()
        trace = payload["trace"]
        image_url = payload.get("image_url")

        if not image_url:
            trace["identify"] = {"node": 1, "skipped": True, "reason": "未上传图片，使用问题解析出的品种"}
            return {
                **payload,
                "candidates": [],
                "identify_ms": int((time.perf_counter() - started) * 1000),
            }

        try:
            data_url = to_model_image_url(image_url)
            model = get_vision_model()
            hint = payload.get("user_species") or "（无）"
            response = await model.ainvoke(
                [
                    SystemMessage(content=VISION_SYSTEM_PROMPT),
                    HumanMessage(
                        content=[
                            {"type": "text", "text": f"请识别这张图片中的植物品种。用户线索：{hint}"},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ]
                    ),
                ]
            )
            parsed = IdentifyOutput(**_parse_json_payload(_content_to_text(response.content)))
            candidates = [item.model_dump() for item in parsed.candidates]
        except ImageAccessError:
            raise
        except Exception as exc:
            # 配置缺失或接口异常：图像识别不可用（PRD 10.2.4 → 503）
            trace["identify"] = {"node": 1, "status": "failed", "error": str(exc)}
            raise AiUnavailableError(f"图像识别服务暂不可用：{exc}") from exc

        trace["identify"] = {
            "node": 1,
            "status": "success",
            "candidates": candidates,
            "ms": int((time.perf_counter() - started) * 1000),
        }
        return {**payload, "candidates": candidates, "identify_ms": int((time.perf_counter() - started) * 1000)}

    # ---------------- 节点2：品种归一化 ----------------
    async def _normalize(self, payload: dict) -> dict:
        """候选 → 标准品种名；置信度 <0.6 或无法映射 → 未知品种路径（BR-07）。"""
        started = time.perf_counter()
        trace = payload["trace"]
        candidates = payload.get("candidates") or []
        user_species = (payload.get("user_species") or "").strip()

        confidence = 0.0
        raw_species = ""
        source = "unknown"

        if user_species:
            raw_species, is_known = normalize_species(user_species)
            confidence = 1.0
            # species_source=question 表示品种来自大模型对问题文本的解析
            source = payload.get("species_source") or "user"
        elif candidates:
            best = max(candidates, key=lambda item: float(item.get("confidence", 0)))
            confidence = float(best.get("confidence", 0))
            raw_species, is_known = normalize_species(str(best.get("species", "")))
            source = "vision"
            if confidence < 0.6:
                raw_species, is_known = "未知品种", False
                source = "low_confidence"
        else:
            raw_species, is_known = "未知品种", False

        # 用户显式指定时以用户为准；视觉识别未命中别名表也保留名称用于检索，
# 是否命中知识库由节点3 的检索结果决定（命中 knowledge，未命中降级 general）。
        species = raw_species

        trace["normalize"] = {
            "node": 2,
            "species": species,
            "confidence": round(confidence, 4),
            "is_known": is_known,
            "source": source,
            "ms": int((time.perf_counter() - started) * 1000),
        }
        return {
            **payload,
            "species": species,
            "confidence": confidence,
            "is_known": is_known,
            "normalize_source": source,
        }

    # ---------------- 节点2.5：定位用户植物 ----------------
    async def _match_plant(self, payload: dict) -> dict:
        """按品种/名字在用户自己的档案中定位植物（仅用于个性化打卡摘要）。"""
        started = time.perf_counter()
        trace = payload["trace"]

        if payload.get("plant_id"):
            trace["plant_match"] = {"node": 2.5, "skipped": True, "reason": "调用方已指定植物"}
            return payload

        plant = await match_owned_plant(
            payload["user_id"],
            payload.get("species") or "",
            payload.get("question"),
        )
        trace["plant_match"] = {
            "node": 2.5,
            "matched": plant is not None,
            "plant_id": getattr(plant, "id", None),
            "plant_name": getattr(plant, "name", None),
            "source": payload.get("species_source") or "unknown",
            "ms": int((time.perf_counter() - started) * 1000),
        }
        return {**payload, "plant_id": plant.id if plant else None}

    # ---------------- 节点3：RAG 检索 ----------------
    async def _retrieve(self, payload: dict) -> dict:
        """向量检索 + 阈值过滤 + 通用知识回退（节点3 / 3b）。"""
        started = time.perf_counter()
        trace = payload["trace"]
        settings = self._settings
        question = (payload.get("question") or "").strip()
        species = payload.get("species") or "未知品种"
        # 问题解析 / 用户指定 / 高置信度识别 → 先按品种检索；低置信度或未知 → 直接走通用知识
        use_species_query = (
            species != "未知品种"
            and payload.get("normalize_source") in {"user", "question", "vision"}
            and float(payload.get("confidence") or 0) >= 0.6
        )

        if use_species_query:
            base_question = question or "浇水 光照 施肥 温度湿度 病虫害"
            # 用户问题里已含品种名时不重复拼接（如“绿萝叶子发黄怎么办”）
            query = base_question if species in base_question else f"{species} {base_question}".strip()
            category = None
        else:
            base_question = question or "浇水 光照 施肥 温度湿度 病虫害"
            query = base_question if "通用养护" in base_question else f"通用养护 {base_question}"
            category = "general"

        result: RetrievalResult = await asyncio.to_thread(
            retrieve,
            query,
            settings.RAG_TOP_K,
            settings.RAG_SCORE_THRESHOLD,
            category,
            species,
        )
        # 品种专属检索无命中时，retriever 已自动回退 general
        trace["retrieval"] = {
            "node": 3,
            "query": result.query,
            "threshold": result.threshold,
            "hit": result.hit,
            "used_general": result.used_general,
            "use_species_query": use_species_query,
            "species_filter": species if use_species_query else None,
            "count": len(result.chunks),
            "error": result.error,
            "docs": result.doc_refs(),
            "ms": int((time.perf_counter() - started) * 1000),
        }
        return {**payload, "retrieval": result}

    # ---------------- 节点4：打卡摘要 ----------------
    async def _care_context(self, payload: dict) -> dict:
        """拼接当前用户当前植物近 30 天打卡 + 近 7 天指标（数据隔离）。"""
        started = time.perf_counter()
        trace = payload["trace"]
        context = await build_care_context(payload["user_id"], payload.get("plant_id"))
        trace["care_context"] = {
            "node": 4,
            "has_plant": context["has_plant"],
            "record_counts": context["record_counts"],
            "warnings": context["warnings"],
            "ms": int((time.perf_counter() - started) * 1000),
        }
        trace["care_summary"] = context["summary"]
        return {**payload, "care_context": context}

    # ---------------- 节点5：LLM 个性化生成 ----------------
    async def _generate(self, payload: dict) -> dict:
        """注入系统提示词 + 检索上下文 + 打卡摘要，输出分节 JSON（含降级）。"""
        started = time.perf_counter()
        trace = payload["trace"]
        settings = self._settings
        retrieval: RetrievalResult = payload["retrieval"]
        context = payload["care_context"]
        species = payload["species"]
        confidence = payload["confidence"]

        if retrieval.chunks:
            knowledge_context = retrieval.context_text()
        else:
            knowledge_context = (
                f"{NO_KNOWLEDGE_CONTEXT}\n"
                f"以下是内置通用养护知识，可直接引用但必须标注 source_type=general：\n{general_knowledge_text()}"
            )

        if not context["has_plant"] and not context["record_counts"]:
            care_summary = f"{context['summary']}\n{NEW_USER_CONTEXT}"
        else:
            care_summary = context["summary"]

        history = payload.get("history") or "（无历史对话）"
        question = (payload.get("question") or "").strip() or "请给出当前季节的养护建议"
        prompt_hash = hashlib.sha256(
            f"{knowledge_context}|{care_summary}|{question}".encode("utf-8")
        ).hexdigest()[:16]
        trace["prompt_hash"] = prompt_hash

        inputs = {
            "species": species,
            "confidence": round(float(confidence), 4),
            "is_known": payload.get("is_known", False),
            "question": question,
            "care_summary": care_summary,
            "knowledge_context": knowledge_context,
            "history": history,
            "format_instructions": self._parser.get_format_instructions(),
        }

        # 生成链：提示词 | LLM | 结构化解析（LCEL）
        output: CareAdviceOutput | None = None
        llm_error = ""
        for attempt in range(2):
            try:
                chain = advice_prompt | get_chat_model() | self._parser
                candidate = await chain.ainvoke(inputs)
                output = self._finalize_output(candidate, retrieval, species, confidence)
                break
            except Exception as exc:  # 解析失败 / Schema 校验失败 / 接口异常
                llm_error = str(exc)
                if attempt == 0:
                    # 重试时强化 JSON 约束（PRD 8.4：输出校验失败重试 1 次）
                    inputs["history"] = f"{history}\n[系统] 上一轮输出不合规，请只输出严格 JSON，不要解释。"

        if output is None:
            # 降级：纯通用知识输出，仍保证前端可用（PRD 12 可用性）
            output = build_general_output(
                species=species,
                confidence=confidence,
                warnings=["AI 生成服务暂时不可用，以下为通用养护知识"],
            )
            trace["llm_error"] = llm_error

        trace["generate"] = {
            "node": 5,
            "status": "fallback" if output.is_fallback else "success",
            "model": settings.LLM_MODEL,
            "ms": int((time.perf_counter() - started) * 1000),
        }
        return {**payload, "output": output}

    # ---------------- 输出修正 ----------------
    def _finalize_output(
        self,
        output: CareAdviceOutput,
        retrieval: RetrievalResult,
        species: str,
        confidence: float,
    ) -> CareAdviceOutput:
        """服务端修正 LLM 输出，保证来源可追溯（PRD 8.4 引用绑定）。

        1. species / confidence 以工作流结果为准，避免模型改写；
        2. doc_ids 必须是本轮真实检索到的文档，否则视为编造 → 改为 general；
        3. 缺失分节用内置通用知识补齐并标注 general；
        4. is_fallback 由是否存在 knowledge 分节决定。
        """
        valid_doc_ids = {chunk.doc_id for chunk in retrieval.chunks}
        sections = []
        for section in output.sections:
            doc_ids = [doc_id for doc_id in section.doc_ids if doc_id in valid_doc_ids]
            if section.source_type == "knowledge" and not doc_ids:
                section = section.model_copy(
                    update={"source_type": "general", "doc_ids": []}
                )
            else:
                section = section.model_copy(update={"doc_ids": doc_ids})
            sections.append(section)

        existing_keys = {section.key for section in sections}
        for key, content in GENERAL_KNOWLEDGE.items():
            if key not in existing_keys:

                sections.append(
                    AdviceSection(
                        key=key,
                        title=SECTION_TITLES[key],
                        content=content,
                        doc_ids=[],
                        source_type="general",
                    )
                )

        has_knowledge = any(section.source_type == "knowledge" for section in sections)
        return output.model_copy(
            update={
                "species": species,
                "confidence": round(float(confidence), 4),
                "is_fallback": not has_knowledge,
                "sections": normalize_section_order(sections),
            }
        )

    # ---------------- 对外入口 ----------------
    async def identify(self, image_url: str, user_species: str | None = None) -> dict:
        """单独执行节点1+2（PRD FR-401 / POST /ai/identify）。"""
        payload = {
            "image_url": image_url,
            "user_species": user_species,
            "plant_species": None,
            "trace": {},
        }
        identified = await self._identify(payload)
        normalized = await self._normalize(identified)
        candidates = normalized.get("candidates") or []
        return {
            "candidates": candidates,
            "species": normalized["species"],
            "confidence": normalized["confidence"],
            "is_known": normalized["is_known"],
            "source": normalized["normalize_source"],
        }

    async def run(
        self,
        user_id: int,
        plant_id: int | None = None,
        image_url: str | None = None,
        user_species: str | None = None,
        plant_species: str | None = None,
        question: str | None = None,
        session_id: str = "default",
        history: str = "（无历史对话）",
    ) -> dict:
        """执行完整 AI-RAG 链路（带端到端超时）。

        plant_species 仅为旧调用方兼容保留，不再参与品种判定：
        有图时必须优先使用图像识别结果（本次需求变更）。
        """
        settings = self._settings
        payload = {
            "user_id": user_id,
            "plant_id": plant_id,
            "image_url": image_url,
            "user_species": user_species,
            "question": question,
            "session_id": session_id,
            "history": history,
            "trace": {
                "nodes": [],
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "_start": time.perf_counter(),
            },
        }
        try:
            result = await asyncio.wait_for(
                self._pipeline.ainvoke(payload),
                timeout=settings.AI_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            trace = payload["trace"]
            trace["timeout_seconds"] = settings.AI_TIMEOUT_SECONDS
            logger.warning(
                "AI 链路超时（%ss），节点进度：%s",
                settings.AI_TIMEOUT_SECONDS,
                json.dumps(trace, ensure_ascii=False, default=str),
            )
            raise AiTimeoutError(f"AI 生成超时（>{settings.AI_TIMEOUT_SECONDS}s）") from exc

        output: CareAdviceOutput = result["output"]
        retrieval: RetrievalResult = result["retrieval"]
        trace = result["trace"]
        trace["total_ms"] = int((time.perf_counter() - float(trace.get("_start", time.perf_counter()))) * 1000)
        trace.pop("_start", None)

        # 来源只保留被分节实际引用的文档，保证“来源列表 ↔ 分节 doc_ids”一一对应
        used_doc_ids = {doc_id for section in output.sections for doc_id in section.doc_ids}
        doc_refs = [item for item in retrieval.doc_refs() if item["doc_id"] in used_doc_ids]

        return {
            "species": output.species,
            "confidence": output.confidence,
            "is_fallback": output.is_fallback,
            "summary": output.summary,
            "sections": [section.model_dump() for section in output.sections],
            "warnings": output.warnings,
            "doc_refs": doc_refs,
            "plant_id": result.get("plant_id"),
            "trace": trace,
            "status": "success",
        }


_workflow: CareAdviceWorkflow | None = None


def get_workflow() -> CareAdviceWorkflow:
    """获取工作流单例（提示词/解析器只构建一次）。"""
    global _workflow
    if _workflow is None:
        _workflow = CareAdviceWorkflow()
    return _workflow


async def run_care_advice(**kwargs) -> dict:
    """便捷入口：供 API 层调用。"""
    return await get_workflow().run(**kwargs)