"""植物模块请求/响应模型（PRD 9.7 P2 接口清单）。

覆盖：列表项响应模型（供记录页面下拉选择「我名下的植物」使用）、
新增植物请求模型（手动建档，AI 识别后续接入时复用）。
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class PlantCreate(BaseModel):
    """新增植物请求模型（PRD FR-201，手动建档）。

    name 必填；其余字段选填。status 由规则引擎派生，不接受客户端传入。
    """

    name: str = Field(min_length=1, max_length=64, description="植物名称（必填）")
    species: str | None = Field(default=None, max_length=64, description="品种（选填）")
    image_url: str | None = Field(default=None, max_length=512, description="植物图片URL")
    location: str | None = Field(default=None, max_length=64, description="摆放位置（如阳台/客厅）")
    planted_at: date | None = Field(default=None, description="种植日期")
    notes: str | None = Field(default=None, description="备注")


class PlantOut(BaseModel):
    """植物列表项响应模型（PRD plants 表字段子集）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    species: str | None = None
    image_url: str | None = None
    location: str | None = None
    status: str = "healthy"
    planted_at: date | None = None
    notes: str | None = None