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
import re
import time
from collections.abc import AsyncIterator, Awaitable

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
    advice_stream_prompt,
)
from app.ai.question_parser import (
    SpeciesMissingError,
    extract_species,
    match_owned_plant,
    owned_plant_names,
)
from app.ai.retriever import RetrievalResult, retrieve
from app.ai.schemas import (
    SECTION_KEYS,
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


# ==================== 流式：文本标记 → 结构化建议 ====================
# 流式通道不让模型输出 JSON：JSON 在 token 流里不可读、也无法边收边渲染。
# 改为「【标记】正文」的文本协议，流结束后由服务端解析成 sections，
# 并按检索片段做来源绑定 —— 模型全程不接触 doc_id，杜绝编造引用（PRD 8.4）。

# 前置节点可能长时间没有 token 输出（图像识别 / 向量检索），定期发心跳帧保活
HEARTBEAT_SECONDS = 10.0

# 模型输出的【标记】→ 固定分节 key（用包含匹配，容忍“温度与湿度建议”这类写法）
SECTION_MARKER_ALIASES: dict[str, str] = {
    "浇水": "watering",
    "水分": "watering",
    "浇灌": "watering",
    "光照": "light",
    "光线": "light",
    "阳光": "light",
    "施肥": "fertilizing",
    "肥料": "fertilizing",
    "追肥": "fertilizing",
    "温度与湿度": "temperature_humidity",
    "温湿度": "temperature_humidity",
    "温度": "temperature_humidity",
    "湿度": "temperature_humidity",
    "病虫害防治": "pest_control",
    "病虫害": "pest_control",
    "病虫": "pest_control",
}

SUMMARY_MARKERS = {"概览", "摘要", "总结", "一句话总结", "结论"}
WARNING_MARKERS = {"提示", "注意", "注意事项", "风险", "警告", "特别提醒"}

# 服务端来源绑定关键词：分节主题 ↔ 检索片段内容是否覆盖该主题
SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "watering": ("浇水", "水分", "浇透", "见干见湿", "盆土", "积水"),
    "light": ("光照", "光线", "散射光", "阳光", "日照", "遮阴", "暴晒"),
    "fertilizing": ("施肥", "肥料", "追肥", "薄肥", "复合肥", "营养"),
    "temperature_humidity": ("温度", "湿度", "通风", "越冬", "空调", "喷雾", "加湿"),
    "pest_control": ("病", "虫", "介壳", "红蜘蛛", "防治", "腐烂", "霉"),
}

_MARKER_RE = re.compile(r"【\s*([^】]{1,16}?)\s*】")


def _marker_key(marker: str) -> str | None:
    """把模型输出的标记名归一到 summary / warnings / 分节 key。"""
    name = (marker or "").strip()
    if name in SUMMARY_MARKERS:
        return "summary"
    if name in WARNING_MARKERS:
        return "warnings"
    for alias, key in SECTION_MARKER_ALIASES.items():
        if alias in name:
            return key
    return None


def _extract_marked_blocks(text: str) -> tuple[dict[str, str], list[str]]:
    """按【标记】切分流式正文，返回 ({key: 正文}, 未识别标记列表)。

    最后一段即使没有闭合标记也会被收下，保证“边生成边解析”时已输出的内容不丢。
    """
    matches = list(_MARKER_RE.finditer(text or ""))
    blocks: dict[str, str] = {}
    unknown: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        key = _marker_key(match.group(1))
        if key is None:
            unknown.append(match.group(1))
            continue
        if not body:
            continue
        blocks[key] = f"{blocks[key]}\n{body}".strip() if key in blocks else body
    return blocks, unknown


def _split_warnings(text: str | None) -> list[str]:
    """把【提示】正文按中文/英文分号和换行拆成多条；“无”视为没有风险。"""
    if not text:
        return []
    items = [item.strip() for item in re.split(r"[；;\n]+", text) if item.strip()]
    return [item for item in items if item.rstrip("。") not in {"无", "暂无"}]


def _bind_sources(section_key: str, retrieval: RetrievalResult) -> tuple[str, list[str]]:
    """服务端按主题关键词把分节绑定到本轮检索到的文档（模型不参与）。"""
    if not retrieval.chunks:
        return "general", []
    keywords = SECTION_KEYWORDS.get(section_key, ())
    doc_ids: list[str] = []
    for chunk in retrieval.chunks:
        haystack = f"{chunk.title}\n{chunk.content}"
        if any(word in haystack for word in keywords) and chunk.doc_id not in doc_ids:
            doc_ids.append(chunk.doc_id)
    if not doc_ids:
        return "general", []
    return "knowledge", doc_ids[:2]


def parse_advice_text(
    text: str,
    retrieval: RetrievalResult,
    species: str,
    confidence: float,
    trace: dict | None = None,
) -> CareAdviceOutput | None:
    """把流式正文转换成结构化建议；返回 None 表示没按标记输出（触发降级）。"""
    blocks, unknown = _extract_marked_blocks(text)
    sections: list[AdviceSection] = []
    for key in SECTION_KEYS:
        body = (blocks.get(key) or "").strip()
        if not body:
            continue
        source_type, doc_ids = _bind_sources(key, retrieval)
        sections.append(
            AdviceSection(
                key=key,
                title=SECTION_TITLES[key],
                content=body[:300],
                doc_ids=doc_ids,
                source_type=source_type,
            )
        )

    if trace is not None:
        trace["stream_parse"] = {
            "blocks": sorted(blocks.keys()),
            "unknown_markers": unknown,
            "sections": [section.key for section in sections],
        }

    if not sections:
        return None

    summary = (blocks.get("summary") or "").strip() or f"以下是针对{species or '未知品种'}的养护建议。"
    return CareAdviceOutput(
        species=species or "未知品种",
        confidence=max(0.0, min(1.0, float(confidence or 0))),
        is_fallback=not any(section.source_type == "knowledge" for section in sections),
        summary=summary[:200],
        sections=sections,
        warnings=_split_warnings(blocks.get("warnings")),
    )


async def _await_with_heartbeat(awaitable: Awaitable) -> AsyncIterator[tuple[str, object]]:
    """执行一个节点协程，期间产出心跳事件，结束时产出结果。

    生成器无法 return 值，因此统一用 ("ping", None) / ("result", value) 事件回传。
    调用方提前退出时会取消底层任务，避免上游 LLM 请求悬挂。
    """
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
            if done:
                yield "result", task.result()
                return
            yield "ping", None
    finally:
        if not task.done():
            task.cancel()


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
            # 读本地图片 + base64 编码是同步磁盘 IO，放线程池避免阻塞事件循环
            data_url = await asyncio.to_thread(to_model_image_url, image_url)
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
    def _build_generation_inputs(self, payload: dict) -> tuple[dict, RetrievalResult]:
        """组装节点5 提示词入参（同步生成与流式生成共用，保证两路口径一致）。"""
        trace = payload["trace"]
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
        }
        return inputs, retrieval

    async def _generate(self, payload: dict) -> dict:
        """注入系统提示词 + 检索上下文 + 打卡摘要，输出分节 JSON（含降级）。"""
        started = time.perf_counter()
        trace = payload["trace"]
        settings = self._settings
        inputs, retrieval = self._build_generation_inputs(payload)
        species = payload["species"]
        confidence = payload["confidence"]
        history = inputs["history"]
        inputs["format_instructions"] = self._parser.get_format_instructions()

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

    async def _generate_stream(self, payload: dict) -> AsyncIterator[tuple[str, object]]:
        """流式生成：逐 token 产出正文，流结束后解析成结构化建议并回传。"""
        started = time.perf_counter()
        trace = payload["trace"]
        settings = self._settings
        inputs, retrieval = self._build_generation_inputs(payload)
        species = payload["species"]
        confidence = payload["confidence"]

        buffer: list[str] = []
        llm_error = ""
        try:
            async for chunk in (advice_stream_prompt | get_chat_model()).astream(inputs):
                text = _content_to_text(chunk.content)
                if not text:
                    continue
                buffer.append(text)
                yield "delta", {"text": text}
        except Exception as exc:  # 网络/鉴权异常：已输出的内容仍尽量解析
            llm_error = str(exc)
            logger.warning("流式生成中断（已输出 %d 字符）：%s", sum(len(item) for item in buffer), exc)

        raw = "".join(buffer)
        output = parse_advice_text(raw, retrieval, species, confidence, trace) if raw.strip() else None
        if output is None:
            # 降级：纯通用知识输出（PRD 12 可用性），前端显示“通用知识”角标
            output = build_general_output(
                species=species,
                confidence=confidence,
                warnings=["AI 生成服务暂时不可用，以下为通用养护知识"],
            )
        else:
            # 复用同步链路的服务端修正：补齐缺失分节、过滤无效 doc_ids、重算 is_fallback
            output = self._finalize_output(output, retrieval, species, confidence)

        if llm_error:
            trace["llm_error"] = llm_error
        trace["generate"] = {
            "node": 5,
            "status": "fallback" if output.is_fallback else "success",
            "model": settings.LLM_MODEL,
            "stream": True,
            "ms": int((time.perf_counter() - started) * 1000),
        }
        trace["stream_chars"] = len(raw)
        yield "output", output

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

        return self._build_result(result)

    def _build_result(self, payload: dict) -> dict:
        """把链路中间态组装成接口返回结构（同步 / 流式两路共用）。"""
        output: CareAdviceOutput = payload["output"]
        retrieval: RetrievalResult = payload["retrieval"]
        trace = payload["trace"]
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
            "plant_id": payload.get("plant_id"),
            "trace": trace,
            "status": "success",
        }

    # ---------------- 对外入口（流式） ----------------
    async def stream(
        self,
        user_id: int,
        plant_id: int | None = None,
        image_url: str | None = None,
        user_species: str | None = None,
        plant_species: str | None = None,
        question: str | None = None,
        session_id: str = "default",
        history: str = "（无历史对话）",
    ) -> AsyncIterator[tuple[str, dict]]:
        """流式执行完整 AI-RAG 链路。

        事件类型：
        - stage：前置节点进度（前端显示“正在识别 / 正在检索”等文案）；
        - ping：心跳（长耗时节点期间保活，避免代理断开）；
        - delta：节点5 的正文增量（前端逐字渲染）；
        - result：结构化建议（接口层负责落库后转成 done 事件）；
        - error：业务错误（code/msg 与同步接口一致，前端按中文提示展示）。

        前置节点必须在节点5 之前跑完：品种识别、检索、打卡摘要都是生成的输入，
        因此“真正的流式”只能覆盖节点5，前置节点用 stage 事件给出进度而不是假进度条。
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
        stages = (
            (0, "正在理解你的问题", self._parse_question),
            (1, "正在识别植物品种", self._identify),
            (2, "正在确认品种信息", self._normalize),
            (2.5, "正在匹配你的植物档案", self._match_plant),
            (3, "正在检索养护知识库", self._retrieve),
            (4, "正在读取近期打卡记录", self._care_context),
        )
        try:
            async with asyncio.timeout(settings.AI_TIMEOUT_SECONDS):
                for node, label, step in stages:
                    yield "stage", {"node": node, "label": label}
                    async for kind, value in _await_with_heartbeat(step(payload)):
                        if kind == "ping":
                            yield "ping", {}
                        else:
                            payload = value

                async for kind, value in self._generate_stream(payload):
                    if kind == "delta":
                        yield kind, value
                    else:
                        payload["output"] = value

                result = self._build_result(payload)
        except TimeoutError:
            trace = payload["trace"]
            trace["timeout_seconds"] = settings.AI_TIMEOUT_SECONDS
            logger.warning(
                "AI 流式链路超时（%ss），节点进度：%s",
                settings.AI_TIMEOUT_SECONDS,
                json.dumps(trace, ensure_ascii=False, default=str),
            )
            yield "error", {
                "code": "504",
                "msg": f"生成超时（>{settings.AI_TIMEOUT_SECONDS}s），请重试",
            }
            return
        except SpeciesMissingError as exc:
            yield "error", {"code": "400", "msg": str(exc)}
            return
        except AiUnavailableError as exc:
            yield "error", {"code": "503", "msg": str(exc)}
            return
        except ImageAccessError as exc:
            yield "error", {"code": "400", "msg": str(exc)}
            return
        except asyncio.CancelledError:
            # 前端点击「停止」会取消生成器：不落库、不写记忆，异常继续上抛由框架收尾
            raise
        except Exception as exc:
            logger.exception("AI 流式链路异常：%s", exc)
            yield "error", {"code": "500", "msg": "AI 服务异常，请稍后重试"}
            return

        yield "result", result


_workflow: CareAdviceWorkflow | None = None


def get_workflow() -> CareAdviceWorkflow:
    """获取工作流单例（提示词/解析器只构建一次）。"""
    global _workflow
    if _workflow is None:
        _workflow = CareAdviceWorkflow()
    return _workflow


async def run_care_advice(**kwargs) -> dict:
    """便捷入口：供 API 层调用（同步一次性返回）。"""
    return await get_workflow().run(**kwargs)


async def stream_care_advice(**kwargs) -> AsyncIterator[tuple[str, dict]]:
    """便捷入口：流式执行完整 AI-RAG 链路（供 SSE 接口逐事件转发）。"""
    async for event in get_workflow().stream(**kwargs):
        yield event