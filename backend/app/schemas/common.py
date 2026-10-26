"""通用请求/响应模型：分页结构（PRD 9.2/9.5）。"""

from typing import Generic, List, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageParams(BaseModel):
    """分页请求参数（query 传参，默认 page=1, page_size=10）。"""

    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=10, ge=1, le=50, description="每页条数，上限 50")


class PageData(BaseModel, Generic[T]):
    """分页响应数据（PRD 9.2：data.items / total / page / page_size）。"""

    items: List[T]
    total: int
    page: int
    page_size: int