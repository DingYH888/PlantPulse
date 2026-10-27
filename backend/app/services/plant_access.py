"""植物归属校验公共逻辑（数据隔离，PRD 7.3 / BR-02）。

指标、统计等模块都需要"植物必须属于当前用户"的前置校验，
统一收敛到本模块，避免每个路由重复实现导致校验口径不一致。
"""

from app.core.response import BizException
from app.models.plant import Plant


async def get_owned_plant(plant_id: int, user_id: int) -> Plant:
    """按归属加载植物：不存在 404、非本人 403。

    所有涉及单株植物的读写接口都应先调用本函数，
    禁止直接按 plant_id 查询后跳过 user_id 校验。
    """
    plant = await Plant.get_or_none(id=plant_id)
    if plant is None:
        raise BizException("404", "植物不存在", status_code=404)
    if plant.user_id != user_id:
        raise BizException("403", "无权操作他人的植物", status_code=403)
    return plant