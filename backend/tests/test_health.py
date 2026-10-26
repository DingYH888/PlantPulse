"""健康检查接口单元测试：验证服务可启动、统一返回格式正确。"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_health_check(client):
    """健康检查返回统一格式且状态为 ok。"""
    resp = await client.get("/api/v1/health")

    assert resp.status_code == 200
    body = resp.json()
    # 统一返回格式（PRD 3.4）：code/msg/data 三字段齐全
    assert set(body.keys()) == {"code", "msg", "data"}
    assert body["code"] == "200"
    assert body["data"]["status"] == "ok"