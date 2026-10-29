"""打卡模块路由（PRD 5.5 / 9.7 P5 接口清单，页面入口为 P2 植物记录）。

覆盖：
- POST   /checkins：新增打卡（选植物 + 类型 + 备注 + 日期 + 多图）
- GET    /checkins：打卡历史（按植物筛选，时间倒序分页）
- GET    /checkins/calendar：月历打卡数据（日历标记 + 当日记录，PRD 9.7 P5）
- PUT    /checkins/{id}：编辑打卡（个人中心「编辑」入口）
- DELETE /checkins/{id}：撤销打卡（仅限当天，PRD FR-503）

业务规则：
- 数据隔离：plant 必须属于当前用户，否则 403（PRD BR-02）；
- 日期规则：record_date 默认当天，禁止未来日期 → 400（PRD BR-04）；
- 重复打卡：同植物同类型同日允许多条（BR-03 唯一限制已按需求移除）；
- 多图方案：image_urls 数组序列化为 JSON 数组字符串，落库 image_url 单字段。

数据层：Tortoise-ORM 异步查询（backend/app/models/plant_record.py）。
"""

import json
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser
from app.core.response import BizException, success
from app.core.timezone import APP_TIMEZONE
from app.models.plant import Plant
from app.models.plant_record import PlantRecord
from app.schemas.checkin import CheckinCreate, CheckinOut, CheckinUpdate
from app.services.checkin_calendar import (
    build_calendar,
    care_type_value,
    next_month,
    parse_month,
)

router = APIRouter()


def _checkin_out(record: PlantRecord, plant_name: str | None = None) -> CheckinOut:
    """模型 → 响应 DTO：将落库的 image_url 反序列化为 images 数组。

    兼容两种情况：多图时是 JSON 数组字符串；历史脏数据/单图时直接包成单元素数组。
    plant_name 由调用方传入（列表接口批量预取，避免 N+1 查询）。
    """
    images: list[str] = []
    if record.image_url:
        try:
            data = json.loads(record.image_url)
            images = data if isinstance(data, list) else [record.image_url]
        except json.JSONDecodeError:
            images = [record.image_url]
    return CheckinOut(
        id=record.id,
        plant_id=record.plant_id,
        plant_name=plant_name,
        care_type=record.record_type.value,
        content=record.content,
        record_date=record.record_date,
        images=images,
        created_at=record.created_at,
    )


async def _get_owned_plant(plant_id: int, user_id: int) -> Plant:
    """按归属校验植物：不存在 404、非本人 403（数据隔离，PRD BR-02）。"""
    plant = await Plant.get_or_none(id=plant_id)
    if plant is None:
        raise BizException("404", "植物不存在", status_code=404)
    if plant.user_id != user_id:
        raise BizException("403", "无权操作他人的植物", status_code=403)
    return plant


@router.post("")
async def create_checkin(body: CheckinCreate, user: CurrentUser) -> dict:
    """新增打卡（PRD FR-502）。

    链路：归属校验 → 日期规则（默认今天/禁未来）→ 防重复 → 多图落库。
    """
    # 1. 数据隔离：植物必须属于当前用户
    plant = await _get_owned_plant(body.plant_id, user.id)

    # 2. 日期规则：默认当天；不允许未来日期（BR-04）
    # 统一用应用时区（APP_TIMEZONE）取"今天"，与日历/统计/撤销口径保持一致，
    # 避免服务器时区非东八区时出现"能打卡但不能撤销"的口径错位。
    today = datetime.now(APP_TIMEZONE).date()
    record_date = body.record_date or today
    if record_date > today:
        raise BizException("400", "不能为未来日期打卡", status_code=400)

    # 3. 多图序列化落库：[] → None（保持字段为空，避免存空数组字符串）
    image_url = json.dumps(body.image_urls, ensure_ascii=False) if body.image_urls else None

    record = await PlantRecord.create(
        user_id=user.id,
        plant_id=body.plant_id,
        record_type=body.care_type,
        content=body.content,
        image_url=image_url,
        record_date=record_date,
    )
    return success(_checkin_out(record, plant.name).model_dump(), "打卡成功")


@router.get("")
async def list_checkins(
    user: CurrentUser,
    plant_id: Annotated[int | None, Query(description="按植物筛选（可选，不传返回全部）")] = None,
    record_date: Annotated[date | None, Query(description="按日期筛选（可选）")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> dict:
    """打卡历史（PRD FR-504）：当前用户下按日期/植物筛选，日期倒序分页。

    不传 plant_id 时返回当前用户全部植物记录（前端历史卡片默认只看当天）；
    传 plant_id 时仍校验归属，避免越权枚举他人数据。
    """
    qs = PlantRecord.filter(user_id=user.id)
    if plant_id is not None:
        await _get_owned_plant(plant_id, user.id)
        qs = qs.filter(plant_id=plant_id)
    if record_date is not None:
        qs = qs.filter(record_date=record_date)

    total = await qs.count()
    records = await qs.order_by("-record_date", "-id").offset((page - 1) * page_size).limit(page_size)

    # 批量预取植物名称，避免逐条查询的 N+1 开销
    name_map: dict[int, str] = {}
    if records:
        rows = await Plant.filter(id__in={r.plant_id for r in records}).values("id", "name")
        name_map = {row["id"]: row["name"] for row in rows}

    return success(
        {
            "items": [_checkin_out(r, name_map.get(r.plant_id)).model_dump() for r in records],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        "查询成功",
    )

# 注意：/calendar 必须与 /{checkin_id} 同方法时不冲突；若后续新增 GET /{id}，
# 需保证本函数注册在它之前，否则 "calendar" 会被当作路径参数解析。
@router.get("/calendar")
async def get_checkin_calendar(
    user: CurrentUser,
    month: Annotated[str | None, Query(description="月份 YYYY-MM，不传默认当月")] = None,
) -> dict:
    """月历打卡数据（PRD FR-501 / 9.7 GET /checkins/calendar）。

    返回指定月份内有打卡记录的日期数组（含当天次数与类型），前端据此给日历
    单元格上色并显示打卡次数角标；点击日期再走 GET /checkins?record_date=... 查详情。
    """
    today = datetime.now(APP_TIMEZONE).date()
    try:
        month_key, first_day = parse_month(month, today)
    except ValueError:
        raise BizException("400", "月份格式应为 YYYY-MM", status_code=400)

    rows = await PlantRecord.filter(
        user_id=user.id,
        record_date__gte=first_day,
        record_date__lt=next_month(first_day),
    ).values_list("record_date", "record_type")

    days = build_calendar((record_date, care_type_value(care_type)) for record_date, care_type in rows)
    return success(
        {
            "month": month_key,
            "days": days,
            "checkin_count": sum(day["count"] for day in days),
            "active_days": len(days),
        },
        "查询成功",
    )


@router.put("/{checkin_id}")
async def update_checkin(checkin_id: int, body: CheckinUpdate, user: CurrentUser) -> dict:
    """编辑打卡记录（个人中心「编辑」入口）。

    - 只更新请求中显式传入的字段，未传字段保持原值；
    - content / image_urls 显式传 null 表示清空；
    - 校验顺序：不存在 404 → 非本人 403 → 新植物归属 403 → 日期禁未来 400；
    - 不校验重复打卡：同植物同类型同日允许多条（BR-03 限制已移除）。
    """
    record = await PlantRecord.get_or_none(id=checkin_id)
    if record is None:
        raise BizException("404", "打卡记录不存在", status_code=404)
    if record.user_id != user.id:
        raise BizException("403", "无权编辑他人的打卡记录", status_code=403)

    fields_set = body.model_fields_set
    plant_name: str | None = None
    if (
        "plant_id" in fields_set
        and body.plant_id is not None
        and body.plant_id != record.plant_id
    ):
        plant = await _get_owned_plant(body.plant_id, user.id)
        record.plant_id = plant.id
        plant_name = plant.name

    if "care_type" in fields_set and body.care_type is not None:
        record.record_type = body.care_type

    if "content" in fields_set:
        record.content = (body.content or "").strip() or None

    if "record_date" in fields_set and body.record_date is not None:
        today = datetime.now(APP_TIMEZONE).date()
        if body.record_date > today:
            raise BizException("400", "不能为未来日期打卡", status_code=400)
        record.record_date = body.record_date

    if "image_urls" in fields_set:
        urls = body.image_urls or []
        record.image_url = json.dumps(urls, ensure_ascii=False) if urls else None

    await record.save()

    if plant_name is None:
        # values_list() 返回 ValuesListQuery，没有 first()；改用 get_or_none 取实体
        plant = await Plant.get_or_none(id=record.plant_id)
        plant_name = plant.name if plant else None
    return success(_checkin_out(record, plant_name).model_dump(), "打卡已更新")


@router.delete("/{checkin_id}")
async def delete_checkin(checkin_id: int, user: CurrentUser) -> dict:
    """撤销打卡（PRD FR-503）：仅允许撤销当天的记录。

    校验顺序：不存在 404 → 非本人 403（数据隔离 BR-02）→ 非当天 400。
    撤销后统计与 AI 上下文随查询实时重算，无需额外同步（PRD 5.5.3-5）。
    """
    record = await PlantRecord.get_or_none(id=checkin_id)
    if record is None:
        raise BizException("404", "打卡记录不存在", status_code=404)
    if record.user_id != user.id:
        raise BizException("403", "无权撤销他人的打卡记录", status_code=403)

    today = datetime.now(APP_TIMEZONE).date()
    if record.record_date != today:
        raise BizException("400", "仅允许撤销当天的打卡记录", status_code=400)

    await record.delete()
    return success({}, "已撤销打卡")