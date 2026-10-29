"""AI 智能养护模块路由（PRD 5.4 / 第 8 章 / 9.7 P4 接口清单）。

接口：
- POST   /api/v1/ai/identify             图像识别（FR-401）
- POST   /api/v1/ai/care-advice          生成个性化建议（完整 AI-RAG 链路，FR-402）
- GET    /api/v1/ai/advices              建议历史（FR-406）
- GET    /api/v1/ai/advices/{id}         建议详情（含来源与 trace）
- POST   /api/v1/ai/advices/{id}/feedback 建议反馈（FR-407）
- DELETE /api/v1/ai/sessions/{session_id} 清除内存对话记忆（前端“新对话”）

鉴权：全部登录态接口；AI 接口按用户 5 次/分钟限流（PRD 12）。
依赖：LangChain 相关模块按需惰性导入，未安装时返回 503 而非拖垮整个服务。
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.ai.advice_service import (
    delete_session,
    get_advice_detail,
    get_session_messages,
    list_advices,
    list_sessions,
    save_advice,
    update_feedback,
)
from app.ai.image_utils import ImageAccessError
from app.ai.rate_limit import get_ai_limiter
from app.core.config import get_settings
from app.core.deps import CurrentUser
from app.core.response import BizException, success
from app.schemas.ai import CareAdviceRequest, FeedbackRequest, IdentifyRequest
from app.services.plant_access import get_owned_plant

router = APIRouter()
settings = get_settings()


async def enforce_ai_rate_limit(user: CurrentUser) -> None:
    """AI 接口限流依赖：超限返回 429（PRD 9.3 / 12）。"""
    allowed, _ = get_ai_limiter().allow(f"user:{user.id}")
    if not allowed:
        raise BizException("429", "AI 调用过于频繁，请稍后再试", status_code=429)


def _load_chain_module():
    """惰性导入 LangChain 编排模块，避免依赖缺失导致后端无法启动。"""
    try:
        from app.ai import chain
    except ImportError as exc:
        raise BizException(
            "503",
            "AI 模块依赖未安装，请先执行：pip install -r requirements-ai.txt",
            status_code=503,
        ) from exc
    return chain


@router.post("/identify")
async def identify_plant(
    payload: IdentifyRequest,
    user: CurrentUser,
    _: None = Depends(enforce_ai_rate_limit),
) -> dict:
    """图像识别：返回候选品种与置信度（PRD FR-401 / 8.1 节点1~2）。"""
    chain = _load_chain_module()
    try:
        result = await asyncio.wait_for(
            chain.get_workflow().identify(payload.image_url),
            timeout=settings.AI_TIMEOUT_SECONDS,
        )
    except ImageAccessError as exc:
        raise BizException("400", str(exc), status_code=400)
    except chain.AiUnavailableError as exc:
        raise BizException("503", str(exc), status_code=503)
    except asyncio.TimeoutError:
        raise BizException("504", "图像识别超时，请稍后重试", status_code=504)

    return success(result)


@router.post("/care-advice")
async def create_care_advice(
    payload: CareAdviceRequest,
    user: CurrentUser,
    _: None = Depends(enforce_ai_rate_limit),
) -> dict:
    """生成个性化养护建议（PRD FR-402，固定五节点链路）。

    长耗时（实测 40~60s）：同步返回 + 前端 loading；端到端超时按 AI_TIMEOUT_SECONDS → 504。
    """
    chain = _load_chain_module()
    from app.ai.memory import get_memory_store

    # 1. 植物归属校验（数据隔离；不存在 404、非本人 403）
    #    前端已不再手工选择植物，plant_id 仅保留 API 兼容
    plant = None
    if payload.plant_id is not None:
        plant = await get_owned_plant(payload.plant_id, user.id)

    # 2. 品种来源由链路决定：有图 → 图像识别；纯文本 → 大模型解析问题文本
    user_species = (payload.species or "").strip() or None
    session_id = (payload.session_id or "").strip() or (f"plant-{plant.id}" if plant else "default")
    memory = get_memory_store()
    history = memory.history_text(user.id, session_id)

    try:
        result = await chain.run_care_advice(
            user_id=user.id,
            plant_id=payload.plant_id,
            image_url=payload.image_url,
            user_species=user_species,
            question=payload.question,
            session_id=session_id,
            history=history,
        )
    except chain.SpeciesMissingError:
        # 情况一：纯文本问题里没有植物名称/种类（PRD 10.2.4 可定位性）
        raise BizException("400", "请说明植物种类或名称", status_code=400)
    except chain.AiTimeoutError:
        raise BizException(
            "504",
            f"生成超时（>{settings.AI_TIMEOUT_SECONDS}s），请重试",
            status_code=504,
        )
    except chain.AiUnavailableError as exc:
        raise BizException("503", str(exc), status_code=503)
    except ImageAccessError as exc:
        raise BizException("400", str(exc), status_code=400)

    # 3. 落库（FR-406 / 8.4 可追溯）+ 写入内存记忆（不落向量库）
    #    链路内按解析/识别结果自动匹配到的植物需要一并落库，保证打卡上下文可追溯
    advice_plant_id = result.get("plant_id") or payload.plant_id
    advice = await save_advice(
        user.id,
        advice_plant_id,
        payload.image_url,
        result,
        session_id=session_id,
        question=payload.question,
    )
    memory.append(
        user.id,
        session_id,
        payload.question or "请根据图片给出养护建议",
        result.get("summary", ""),
    )

    return success(await get_advice_detail(user.id, advice.id))


@router.get("/advices")
async def list_ai_advices(
    user: CurrentUser,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=10, ge=1, le=50, description="每页条数"),
    plant_id: int | None = Query(default=None, ge=1, description="按植物筛选"),
    session_id: str | None = Query(default=None, max_length=64, description="按会话筛选"),
) -> dict:
    """AI 建议历史（分页，仅本人数据）。"""
    data = await list_advices(user.id, page, page_size, plant_id, session_id)
    return success(data)


@router.get("/advices/{advice_id}")
async def get_ai_advice(advice_id: int, user: CurrentUser) -> dict:
    """建议详情（含参考来源与 trace，PRD 8.5）。"""
    return success(await get_advice_detail(user.id, advice_id))


@router.post("/advices/{advice_id}/feedback")
async def feedback_advice(advice_id: int, payload: FeedbackRequest, user: CurrentUser) -> dict:
    """建议反馈：1 有用 / -1 无用 / 0 中性（FR-407）。"""
    return success(await update_feedback(user.id, advice_id, payload.feedback))


@router.get("/sessions")
async def list_ai_sessions(
    user: CurrentUser,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=50, description="每页会话数"),
) -> dict:
    """聊天式历史会话列表（按 session_id 分组，最新对话在前）。"""
    return success(await list_sessions(user.id, page, page_size))


@router.get("/sessions/{session_id}")
async def get_ai_session(
    session_id: Annotated[str, Path(min_length=1, max_length=64)],
    user: CurrentUser,
) -> dict:
    """读取某次会话的完整消息流（用户提问 + AI 建议交替）。"""
    return success(await get_session_messages(user.id, session_id))


@router.delete("/sessions/{session_id}")
async def clear_session(
    session_id: Annotated[str, Path(min_length=1, max_length=64)],
    user: CurrentUser,
) -> dict:
    """清除当前用户的内存对话记忆（前端“新对话”按钮）。"""
    from app.ai.memory import get_memory_store

    cleared = get_memory_store().clear(user.id, session_id)
    return success({"session_id": session_id, "cleared": cleared})


@router.delete("/sessions/{session_id}/history")
async def delete_ai_session_history(
    session_id: Annotated[str, Path(min_length=1, max_length=64)],
    user: CurrentUser,
) -> dict:
    """删除某次会话的历史记录（数据库记录 + 内存记忆），仅限本人数据。"""
    from app.ai.memory import get_memory_store

    data = await delete_session(user.id, session_id)
    get_memory_store().clear(user.id, session_id)
    return success(data, "会话已删除")