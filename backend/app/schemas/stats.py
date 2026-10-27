"""统计接口请求/响应模型（PRD 5.3 P3 数据图表）。

统计维度（用户确认）：
- growth   长势：按 PRD 5.3.3 阈值把每日指标折算为 0~100 健康分（折线）；
- watering 浇水：按自然日统计打卡次数（柱状）；
- fertilizing 施肥：按自然日统计打卡次数（柱状）；
- light    光照：按自然日统计平均光照 lux（柱状）。
"""

import enum

from pydantic import BaseModel, Field


class StatsDimension(str, enum.Enum):
    """统计维度枚举（请求 query 参数使用，非法值由 FastAPI 统一返回 400）。"""

    GROWTH = "growth"
    WATERING = "watering"
    FERTILIZING = "fertilizing"
    LIGHT = "light"


DIMENSION_LABELS: dict[StatsDimension, str] = {
    StatsDimension.GROWTH: "长势",
    StatsDimension.WATERING: "浇水统计",
    StatsDimension.FERTILIZING: "施肥统计",
    StatsDimension.LIGHT: "光照统计",
}


class StatsPlant(BaseModel):
    """统计对象植物简要信息。"""

    id: int
    name: str


class StatsPoint(BaseModel):
    """单个自然日的统计点。"""

    date: str = Field(description="自然日 YYYY-MM-DD")
    value: float | None = Field(default=None, description="图表值：长势分/打卡次数/平均光照")
    count: int | None = Field(default=None, description="打卡类维度的当日次数")
    content: str | None = Field(
        default=None, description="打卡备注（浇水/施肥维度；无备注时为 null，前端不展示）"
    )
    status: str | None = Field(default=None, description="长势状态：normal/attention/abnormal")
    alerts: list[str] = Field(default_factory=list, description="长势维度当日异常/待关注提示")
    metrics: dict[str, float] | None = Field(
        default=None, description="长势维度当日各项指标平均值（tooltip 展示）"
    )


class StatsSummary(BaseModel):
    """统计汇总卡片数据。"""

    total: float = Field(description="累计值：打卡累计次数 / 有数据天数")
    average: float | None = Field(default=None, description="平均值")
    max: float | None = Field(default=None, description="最大值")
    min: float | None = Field(default=None, description="最小值")
    latest: float | None = Field(default=None, description="最近一次有数据的值")


class StatsOut(BaseModel):
    """统计接口响应数据。"""

    plant: StatsPlant
    dimension: StatsDimension
    dimension_label: str
    days: int
    start_date: str
    end_date: str
    unit: str
    chart_type: str = Field(description="图表类型：line（长势）/ bar（其余维度）")
    has_data: bool
    points: list[StatsPoint]
    summary: StatsSummary