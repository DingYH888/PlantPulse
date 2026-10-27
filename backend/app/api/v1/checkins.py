"""打卡模块路由（PRD 5.5 / 9.7 P5 接口清单，页面入口为 P2 植物记录）。

覆盖：
- POST /checkins：新增打卡（选植物 + 类型 + 备注 + 日期 + 多图）
- GET  /checkins：打卡历史（按植物筛选，时间倒序分页）

业务规则：
- 数据隔离：plant 必须属于当前用户，否则 403（PRD BR-02）；
- 日期规则：record_date 默认当天，禁止未来日期 → 400（PRD BR-04）；
- 防重复：同植物同类型同日唯一 → 409（PRD BR-03）；
- 多图方案：image_urls 数组序列化为 JSON 数组字符串，落库 image_url 单字段。

数据层：Tortoise-ORM 异步查询（backend/app/models/plant_record.py）。
"""

import json
from datetime import date

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser
from app.core.response import BizException, success
from app.models.plant import Plant
from app.models.plant_record import PlantRecord
from app.schemas.checkin import CheckinCreate, CheckinOut

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
    record_date = body.record_date or date.today()
    if record_date > date.today():
        raise BizException("400", "不能为未来日期打卡", status_code=400)

    # 3. 防重复打卡（BR-03）：同植物同类型同日唯一，唯一约束兜底
    if await PlantRecord.exists(
        user_id=user.id,
        plant_id=body.plant_id,
        record_type=body.care_type,
        record_date=record_date,
    ):
        raise BizException("409", "重复打卡：该植物今天已进行过此操作", status_code=409)

    # 4. 多图序列化落库：[] → None（保持字段为空，避免存空数组字符串）
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