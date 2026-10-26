"""pytest 全局 fixture：独立测试数据库 + 异步测试客户端。

每个测试用例使用独立的临时 SQLite 文件，保证用例隔离、可重复执行。
注意：沙箱无法运行 asyncio，请在本地终端执行 pytest。
"""

import os
import tempfile

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from tortoise import Tortoise

from app.main import TORTOISE_MODULES, app


@pytest_asyncio.fixture(autouse=True)
async def db():
    """每个测试用例初始化独立数据库，结束后清理。"""
    db_path = os.path.join(tempfile.mkdtemp(), "test.db")
    await Tortoise.init(db_url=f"sqlite://{db_path}", modules=TORTOISE_MODULES)
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest_asyncio.fixture
async def client():
    """基于 ASGI 的异步测试客户端（无需真实启动服务）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c