"""植物记录模块路由（PRD 5.2 / 9.7 P2 接口清单）。

覆盖：植物列表 GET /plants（登录 + 本人数据隔离），供记录页面下拉选择；
新增植物 POST /plants（手动建档，打通「无植物 → 无法打卡」的闭环）。

数据层：Tortoise-ORM 异步查询，强制 user_id 过滤（PRD 7.3 数据隔离）。
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser
from app.core.response import BizException, success
from app.models.plant import Plant
from app.schemas.plant import PlantCreate, PlantOut

router = APIRouter()


def _clean_optional_text(value: str | None) -> str | None:
    """可选文本清洗：去首尾空白，全空白视为未填写（落库 None）。"""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


@router.get("")
async def list_plants(
    user: CurrentUser,
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始")] = 1,
    page_size: Annotated[int, Query(ge=1, le=50, description="每页条数，上限 50")] = 10,
    keyword: Annotated[str | None, Query(description="按植物名称模糊筛选")] = None,
) -> dict:
    """植物列表（PRD FR-201）：仅返回当前登录用户自己的植物（数据隔离）。

    keyword 非空时按 name 模糊过滤；分页结构 data.items/total/page/page_size（PRD 9.2）。
    """
    # 1. 数据隔离：所有查询强制附加 user_id 条件（PRD 7.3）
    qs = Plant.filter(user_id=user.id)
    if keyword:
        qs = qs.filter(name__icontains=keyword)

    # 2. 分页统计与切片（新植物在前）
    total = await qs.count()
    items = await qs.order_by("-created_at").offset((page - 1) * page_size).limit(page_size)

    # 3. 组装统一分页响应
    return success(
        {
            "items": [PlantOut.model_validate(p).model_dump() for p in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        },
        "查询成功",
    )

@router.post("")
async def create_plant(body: PlantCreate, user: CurrentUser) -> dict:
    """新增植物档案（PRD FR-201）：归属当前登录用户，返回建档结果。

    名称去空白后不可为空（400）；status 走模型默认值 healthy，由规则引擎派生。
    """
    name = body.name.strip()
    if not name:
        raise BizException("400", "植物名称不能为空", status_code=400)

    plant = await Plant.create(
        user_id=user.id,
        name=name,
        species=_clean_optional_text(body.species),
        image_url=_clean_optional_text(body.image_url),
        location=_clean_optional_text(body.location),
        planted_at=body.planted_at,
        notes=_clean_optional_text(body.notes),
    )
    return success(PlantOut.model_validate(plant).model_dump(), "植物添加成功")