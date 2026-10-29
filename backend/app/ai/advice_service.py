"""AI 建议持久化与聊天会话查询（PRD 5.4.3-4 / FR-406 / FR-407）。

数据隔离：
- 所有查询强制 user_id 过滤；
- 详情/反馈校验 advice.user_id，非本人 403、不存在 404（PRD 7.3）。

聊天式历史：
- 每条 AiAdvice 通过 session_id 归属一次对话；
- 用户问题与图片 URL 保存在 content.question / input_image_url；
- 会话列表按 session_id 分组，切换会话时返回「用户消息 + AI 建议」交替的消息流。
"""

from datetime import datetime

from app.core.response import BizException
from app.models.ai_advice import AiAdvice


def _confidence_to_float(value) -> float | None:
    """Decimal → float，前端直接消费数字。"""
    return None if value is None else float(value)


def _iso(value) -> str | None:
    """统一时间字段输出（兼容 datetime 与驱动返回的原始字符串）。

    Tortoise 的聚合注解（如 Max("created_at")）在 SQLite 下返回字符串、
    在 MySQL 下返回 datetime，因此不能直接假定 value 具备 isoformat()；
    字符串再规范成标准 ISO 8601（T 分隔），避免前端 new Date() 解析失败。
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text).isoformat()
    except ValueError:
        return text


def serialize_advice(advice: AiAdvice, include_trace: bool = False) -> dict:
    """把 ORM 对象转换为统一响应结构（PRD 8.5）。"""
    content = advice.content or {}
    plant = None
    if advice.plant_id:
        try:
            plant = advice.plant
        except Exception:
            # 未 select_related 时关系不可用；只影响 plant_name，不影响主体数据
            plant = None
    data = {
        "id": advice.id,
        "session_id": advice.session_id,
        "question": content.get("question", ""),
        "plant_id": advice.plant_id,
        "plant_name": getattr(plant, "name", None) if plant else None,
        "input_image_url": advice.input_image_url,
        "species": advice.species,
        "confidence": _confidence_to_float(advice.confidence),
        "is_fallback": bool(advice.is_fallback),
        "summary": content.get("summary", ""),
        "sections": content.get("sections", []),
        "warnings": content.get("warnings", []),
        "doc_refs": advice.doc_refs or [],
        "feedback": advice.feedback,
        "status": advice.status,
        "created_at": _iso(advice.created_at),
    }
    if include_trace:
        data["trace"] = advice.trace or {}
    return data


async def save_advice(
    user_id: int,
    plant_id: int | None,
    image_url: str | None,
    result: dict,
    session_id: str | None = None,
    question: str | None = None,
) -> AiAdvice:
    """落库一次成功的 AI 建议（含用户问题、会话、识别结果、来源、trace）。"""
    advice = await AiAdvice.create(
        user_id=user_id,
        plant_id=plant_id,
        session_id=session_id,
        input_image_url=image_url,
        species=result.get("species"),
        confidence=result.get("confidence"),
        is_fallback=bool(result.get("is_fallback")),
        content={
            "question": (question or "").strip(),
            "summary": result.get("summary", ""),
            "sections": result.get("sections", []),
            "warnings": result.get("warnings", []),
        },
        doc_refs=result.get("doc_refs", []),
        trace=result.get("trace", {}),
        status=result.get("status", "success"),
    )
    return advice


async def list_advices(
    user_id: int,
    page: int,
    page_size: int,
    plant_id: int | None = None,
    session_id: str | None = None,
) -> dict:
    """分页查询当前用户的 AI 建议历史（PRD FR-406）。"""
    query = AiAdvice.filter(user_id=user_id)
    if plant_id is not None:
        query = query.filter(plant_id=plant_id)
    if session_id:
        query = query.filter(session_id=session_id)

    total = await query.count()
    advices = (
        await query.select_related("plant")
        .order_by("-id")
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {
        "items": [serialize_advice(advice) for advice in advices],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def list_sessions(user_id: int, page: int, page_size: int) -> dict:
    """聊天式会话列表：按 session_id 分组，返回标题（最新问题）与轮数。

    不使用 annotate + group_by：Tortoise 的聚合分组在 SQLite 驱动下不会下推，
    同一 session 会返回重复行；改为按 id 倒序读取轻量字段后在应用层去重，
    保证 MySQL / SQLite 行为一致（id 自增，首条出现即该会话最新记录）。
    """
    base = AiAdvice.filter(user_id=user_id, session_id__not_isnull=True)
    ordered = await base.order_by("-id").values_list("session_id", "created_at", "id")

    sessions: dict[str, dict] = {}
    for session_id, created_at, advice_id in ordered:
        slot = sessions.get(session_id)
        if slot is None:
            sessions[session_id] = {"latest_id": advice_id, "total": 1, "last_at": created_at}
        else:
            slot["total"] += 1

    offset = (page - 1) * page_size
    page_sessions = list(sessions.items())[offset : offset + page_size]

    items = []
    for session_id, slot in page_sessions:
        latest = (
            await AiAdvice.filter(id=slot["latest_id"], user_id=user_id)
            .select_related("plant")
            .first()
        )
        if latest is None:
            continue
        content = latest.content or {}
        title = (content.get("question") or "").strip() or latest.species or "未命名对话"
        plant = None
        try:
            plant = latest.plant
        except Exception:
            plant = None
        items.append(
            {
                "session_id": session_id,
                "title": title[:40],
                "plant_id": latest.plant_id,
                "plant_name": getattr(plant, "name", None) if plant else None,
                "species": latest.species,
                "is_fallback": bool(latest.is_fallback),
                "total": slot["total"],
                "updated_at": _iso(slot["last_at"]),
            }
        )


    legacy_items: list[dict] = []
    if page == 1:
        # 兼容聊天改造前的历史记录（session_id 为 NULL）：每条作为独立会话展示
        legacy = (
            await AiAdvice.filter(user_id=user_id, session_id__isnull=True)
            .select_related("plant")
            .order_by("-id")
            .limit(5)
        )
        for advice in legacy:
            content = advice.content or {}
            legacy_title = (content.get("question") or "").strip() or advice.species or "历史建议"
            plant = None
            try:
                plant = advice.plant
            except Exception:
                plant = None
            legacy_items.append(
                {
                    "session_id": f"legacy-{advice.id}",
                    "title": legacy_title[:40],
                    "plant_id": advice.plant_id,
                    "plant_name": getattr(plant, "name", None) if plant else None,
                    "species": advice.species,
                    "is_fallback": bool(advice.is_fallback),
                    "total": 1,
                    "updated_at": _iso(advice.created_at),
                }
            )

    return {
        "items": items + legacy_items,
        "total": len(sessions) + len(legacy_items),
        "page": page,
        "page_size": page_size,
    }


async def get_session_messages(user_id: int, session_id: str) -> dict:
    """读取某次会话的完整聊天记录（用户消息 + AI 建议交替）。

    legacy-{id}：兼容改造前的单条建议记录。
    """
    if session_id.startswith("legacy-"):
        try:
            legacy_id = int(session_id.removeprefix("legacy-"))
        except ValueError as exc:
            raise BizException("404", "会话不存在", status_code=404) from exc
        advice = (
            await AiAdvice.filter(id=legacy_id, user_id=user_id).select_related("plant").first()
        )
        advices = [advice] if advice else []
    else:
        advices = (
            await AiAdvice.filter(user_id=user_id, session_id=session_id)
            .select_related("plant")
            .order_by("id")
        )
    if not advices:
        raise BizException("404", "会话不存在", status_code=404)

    messages: list[dict] = []
    for advice in advices:
        content = advice.content or {}
        question = (content.get("question") or "").strip()
        messages.append(
            {
                "role": "user",
                "text": question or ("请根据图片给出养护建议" if advice.input_image_url else "请生成养护建议"),
                "image_url": advice.input_image_url,
                "created_at": _iso(advice.created_at),
            }
        )
        messages.append(
            {
                "role": "assistant",
                "advice": serialize_advice(advice),
                "created_at": _iso(advice.created_at),
            }
        )

    latest = advices[-1]
    content = latest.content or {}
    title = (content.get("question") or "").strip() or latest.species or "未命名对话"
    return {
        "session_id": session_id,
        "title": title[:40],
        "messages": messages,
        "total": len(advices),
    }


async def delete_session(user_id: int, session_id: str) -> dict:
    """删除某次会话的全部 AI 建议记录（仅本人，幂等）。

    - 普通会话：按 session_id 批量删除该用户记录；
    - legacy-{id}：改造前的单条记录（session_id 为 NULL），按 id 精确删除。
    删除条数为 0 时不报错，前端重复点击或并发删除都能安全返回。
    """
    query = AiAdvice.filter(user_id=user_id)
    if session_id.startswith("legacy-"):
        try:
            legacy_id = int(session_id.removeprefix("legacy-"))
        except ValueError as exc:
            raise BizException("404", "会话不存在", status_code=404) from exc
        deleted = await query.filter(id=legacy_id, session_id__isnull=True).delete()
    else:
        deleted = await query.filter(session_id=session_id).delete()
    return {"session_id": session_id, "deleted": deleted}


async def get_advice_detail(user_id: int, advice_id: int) -> dict:
    """获取建议详情（含来源与 trace，PRD 8.5 参考来源展示）。"""
    advice = await AiAdvice.filter(id=advice_id).select_related("plant").first()
    if advice is None:
        raise BizException("404", "AI 建议不存在", status_code=404)
    if advice.user_id != user_id:
        raise BizException("403", "无权查看他人的 AI 建议", status_code=403)
    return serialize_advice(advice, include_trace=True)


async def update_feedback(user_id: int, advice_id: int, feedback: int) -> dict:
    """回写建议反馈（FR-407）。"""
    advice = await AiAdvice.filter(id=advice_id).first()
    if advice is None:
        raise BizException("404", "AI 建议不存在", status_code=404)
    if advice.user_id != user_id:
        raise BizException("403", "无权操作他人的 AI 建议", status_code=403)
    advice.feedback = feedback
    await advice.save(update_fields=["feedback", "updated_at"])
    return {"id": advice.id, "feedback": advice.feedback}