"""打卡模块请求/响应模型（PRD 9.7 P5 接口清单，页面入口为 P2 植物记录）。

业务口径：
- care_type 使用 PRD 枚举 watering/fertilizing/pruning/repotting/pest_control/other；
- 一次打卡支持多图：请求用 image_urls 数组，服务端序列化为 JSON 数组字符串
  落库到 plant_record.image_url 单字段（多图方案，PRD 字段不变）。
"""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.plant_record import RecordType


class CheckinCreate(BaseModel):
    """新增打卡请求体（PRD FR-502）。

    校验规则：plant_id 必须属于当前用户（403）；record_date 默认当天且不允许
    未来日期（400，BR-04）；同植物同类型同日重复打卡（409，BR-03）。
    """

    plant_id: int = Field(description="植物ID（必须属于当前登录用户）")
    care_type: RecordType = Field(description="打卡类型（PRD care_type 枚举）")
    content: str | None = Field(default=None, max_length=512, description="备注内容（如用量、部位）")
    record_date: date | None = Field(default=None, description="打卡日期，不传默认当天；禁止未来日期")
    image_urls: list[str] | None = Field(default=None, description="打卡图片 URL 列表（多图）")


class CheckinUpdate(BaseModel):
    """编辑打卡请求体（个人中心「编辑」入口）。

    字段全部可选：仅更新请求中显式传入的字段，未传字段保持原值。
    显式传 content/image_urls 为 null 表示清空；plant_id/care_type 不接受 null。
    """

    plant_id: int | None = Field(default=None, description="植物ID（必须属于当前登录用户）")
    care_type: RecordType | None = Field(default=None, description="打卡类型（PRD care_type 枚举）")
    content: str | None = Field(default=None, max_length=512, description="备注内容，null 表示清空")
    record_date: date | None = Field(default=None, description="打卡日期；禁止未来日期")
    image_urls: list[str] | None = Field(default=None, description="图片 URL 列表，null 表示清空")


class CheckinOut(BaseModel):
    """打卡记录响应模型。

    images 由落库的 image_url 反序列化得到，前端列表/预览直接消费数组。
    """

    id: int
    plant_id: int
    plant_name: str | None = Field(default=None, description="植物名称（历史列表展示用）")
    care_type: str
    content: str | None = None
    record_date: date
    images: list[str] = []
    created_at: datetime