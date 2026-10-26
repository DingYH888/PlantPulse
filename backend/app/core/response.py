"""统一返回格式与全局异常处理（PRD 3.4 / 9.3）。

所有接口（含错误）必须返回统一结构：
    {"code": "200", "msg": "success", "data": {}}
业务结果以 code 为准；HTTP 状态码仅表达传输层语义。
"""

from typing import Any, Generic, TypeVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

T = TypeVar("T")


# ---- 统一响应模型（可用于 OpenAPI 文档标注）----
class ApiResponse(Generic[T]):
    """泛型统一响应结构（仅作类型标注用途）。"""

    def __init__(self, code: str = "200", msg: str = "success", data: T = None):
        self.code = code
        self.msg = msg
        self.data = data


def success(data: Any = None, msg: str = "success") -> dict:
    """构造成功响应；data 为空时返回空对象 {}，禁止返回 null。"""
    return {"code": "200", "msg": msg, "data": data if data is not None else {}}


def fail(code: str, msg: str, data: Any = None) -> dict:
    """构造失败响应，code 见 PRD 9.3 错误码约定。"""
    return {"code": code, "msg": msg, "data": data if data is not None else {}}


# ---- 业务异常 ----
class BizException(Exception):
    """业务异常：携带业务码、提示信息与 HTTP 状态码。

    业务层抛出后由全局异常处理器统一转换为标准返回格式。
    """

    def __init__(self, code: str, msg: str, status_code: int = 400, data: Any = None):
        self.code = code
        self.msg = msg
        self.status_code = status_code
        self.data = data
        super().__init__(msg)


# ---- 全局异常处理器 ----
def register_exception_handlers(app: FastAPI) -> None:
    """向 FastAPI 注册全局异常处理器，保证所有错误都走统一返回格式。"""

    @app.exception_handler(BizException)
    async def handle_biz_exception(_: Request, exc: BizException) -> JSONResponse:
        """业务异常 → 统一返回格式。"""
        return JSONResponse(status_code=exc.status_code, content=fail(exc.code, exc.msg, exc.data))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(_: Request, exc: RequestValidationError) -> JSONResponse:
        """参数校验失败 → code=400，msg 取首条错误信息。"""
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        msg = f"参数校验失败：{loc} {first.get('msg', '')}".strip()
        return JSONResponse(status_code=400, content=fail("400", msg))

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(_: Request, exc: Exception) -> JSONResponse:
        """未捕获异常 → code=500（生产环境不暴露内部细节）。"""
        # TODO(脚手架阶段)：接入日志系统，记录 exc 堆栈便于排查
        return JSONResponse(status_code=500, content=fail("500", "服务器内部错误"))