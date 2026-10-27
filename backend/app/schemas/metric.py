"""养护指标请求/响应模型（PRD 5.3 FR-301）。

字段与 plant_metric 表一一对应，合法区间见 PRD 5.3.3：
- 温度 -20~60℃
- 空气湿度 0~100%
- 光照 0~200000 lux
- 土壤湿度 0~100%
- pH 0~14

区间校验放在路由层，便于返回统一的中文错误提示（{"code":"400","msg":"..."}）。
"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class MetricCreate(BaseModel):
    """指标录入请求体（同一植物同一天再次录入视为覆盖更新）。

    五项指标均可选，但至少要填写一项（由路由层校验）。
    record_date 默认当天，禁止未来日期；同一天重复录入会覆盖原有指标。
    """

    temperature: float | None = Field(default=None, description="温度（℃），区间 -20~60")
    humidity: float | None = Field(default=None, description="空气湿度（%），区间 0~100")
    light: float | None = Field(default=None, description="光照（lux），区间 0~200000")
    soil_moisture: float | None = Field(default=None, description="土壤湿度（%），区间 0~100")
    ph: float | None = Field(default=None, description="土壤 pH，区间 0~14")
    record_date: date | None = Field(default=None, description="指标日期，默认当天；禁止未来日期")


class MetricOut(BaseModel):
    """单条指标响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    plant_id: int
    temperature: float | None = None
    humidity: float | None = None
    light: float | None = None
    soil_moisture: float | None = None
    ph: float | None = None
    record_time: datetime


class MetricDailyPoint(BaseModel):
    """指标按天聚合点（多条记录取平均，PRD 5.3.3 聚合口径）。"""

    date: str
    temperature: float | None = None
    humidity: float | None = None
    light: float | None = None
    soil_moisture: float | None = None
    ph: float | None = None