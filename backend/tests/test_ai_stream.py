"""AI 流式接口测试（SSE 事件序列 / 落库 / 错误帧 / 鉴权）。

测试策略与 test_ai.py 一致：AI 链路整体 mock，不真实调用 LLM / Embedding / Chroma。
只验证流式通道的编排：事件顺序、正文增量、落库与记忆写入、错误转 error 帧。

注意：沙箱无法运行 asyncio，请在本地终端执行 pytest。
"""

import json
import sys
import types

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.models.ai_advice import AiAdvice
from app.models.plant import Plant
from app.models.user import User

pytestmark = pytest.mark.asyncio

STREAM_URL = "/api/v1/ai/care-advice/stream"


# ---- 辅助函数 ----

async def _make_user(nickname: str) -> User:
    return await User.create(nickname=nickname, password_hash=hash_password("pass1234"), is_active=True)


def _auth_headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


def _sample_result(plant_id: int | None = None) -> dict:
    return {
        "species": "绿萝",
        "confidence": 0.92,
        "is_fallback": False,
        "summary": "整体状态良好",
        "sections": [
            {
                "key": "watering",
                "title": "浇水",
                "content": "表土干燥后浇透，避免积水。",
                "doc_ids": ["doc-001"],
                "source_type": "knowledge",
            }
        ],
        "warnings": [],
        "doc_refs": [{"doc_id": "doc-001", "title": "绿萝养护指南", "source": "species/绿萝.md"}],
        "trace": {"retrieval": {"hit": True}, "generate": {"status": "success", "stream": True}},
        "plant_id": plant_id,
        "status": "success",
    }


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """把完整 SSE 文本解析成 [(event, data)]。"""
    events: list[tuple[str, dict]] = []
    for frame in text.split("\n\n"):
        if not frame.strip():
            continue
        event = "message"
        data = None
        for line in frame.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:"):].strip())
        if data is not None:
            events.append((event, data))
    return events


class _FakeMemory:
    def __init__(self) -> None:
        self.saved: list[tuple[int, str, str, str]] = []

    def history_text(self, user_id: int, session_id: str) -> str:
        return "（无历史对话）"

    def append(self, user_id: int, session_id: str, user_input: str, answer: str) -> None:
        self.saved.append((user_id, session_id, user_input, answer))

    def clear(self, user_id: int, session_id: str) -> bool:
        return True


@pytest.fixture
def stream_mocks(monkeypatch):
    """注入带 stream_care_advice 的假 chain / 假 memory，并关闭限流干扰。"""
    state = types.SimpleNamespace(calls=[], error=None, memory=_FakeMemory())

    class FakeTimeoutError(RuntimeError):
        pass

    class FakeUnavailableError(RuntimeError):
        pass

    class FakeSpeciesMissingError(RuntimeError):
        pass

    fake_chain = types.ModuleType("app.ai.chain")
    fake_chain.AiTimeoutError = FakeTimeoutError
    fake_chain.AiUnavailableError = FakeUnavailableError
    fake_chain.SpeciesMissingError = FakeSpeciesMissingError

    async def fake_stream_care_advice(**kwargs):
        state.calls.append(kwargs)
        yield "stage", {"node": 0, "label": "正在理解你的问题"}
        yield "delta", {"text": "【概览】整体状态良好。"}
        yield "ping", {}
        yield "delta", {"text": "\n【浇水】表土干后浇透。"}
        if state.error is not None:
            yield "error", {"code": "400", "msg": str(state.error)}
            return
        yield "result", _sample_result(kwargs.get("plant_id"))

    fake_chain.stream_care_advice = fake_stream_care_advice
    fake_chain.get_workflow = lambda: types.SimpleNamespace(identify=None)

    fake_memory = types.ModuleType("app.ai.memory")
    fake_memory.get_memory_store = lambda: state.memory

    monkeypatch.setitem(sys.modules, "app.ai.chain", fake_chain)
    monkeypatch.setitem(sys.modules, "app.ai.memory", fake_memory)

    import app.ai.rate_limit as rate_limit_module
    from app.ai.rate_limit import SlidingWindowLimiter

    monkeypatch.setattr(rate_limit_module, "_limiter", SlidingWindowLimiter(limit=1000))
    return state


# ---- 流式正常链路 ----

async def test_stream_emits_stage_delta_and_done(client: AsyncClient, stream_mocks):
    """事件顺序：stage → delta → ping → delta → done；done 带落库后的完整建议。"""
    user = await _make_user("ai_stream_ok")
    plant = await Plant.create(user_id=user.id, name="小绿", species="绿萝")

    resp = await client.post(
        STREAM_URL,
        json={"plant_id": plant.id, "question": "叶子发黄怎么办", "session_id": "s-stream"},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "stage"
    assert kinds.count("delta") == 2
    assert kinds[-1] == "done"
    assert "ping" not in kinds  # 心跳是 SSE 注释帧，不产生事件

    done = events[-1][1]
    assert done["code"] == "200"
    data = done["data"]
    assert data["species"] == "绿萝"
    assert data["plant_name"] == "小绿"
    assert data["sections"][0]["source_type"] == "knowledge"
    assert data["trace"]["generate"]["stream"] is True

    advice = await AiAdvice.get(id=data["id"])
    assert advice.user_id == user.id
    assert advice.session_id == "s-stream"
    assert advice.content["question"] == "叶子发黄怎么办"

    # 链路入参与记忆写入必须与同步接口一致
    assert stream_mocks.calls[0]["user_id"] == user.id
    assert stream_mocks.memory.saved[0][:2] == (user.id, "s-stream")


async def test_stream_delta_accumulates_to_same_content(client: AsyncClient, stream_mocks):
    """前端累计的 delta 文本应等于模型完整正文（顺序与内容不丢）。"""
    user = await _make_user("ai_stream_delta")

    resp = await client.post(
        STREAM_URL,
        json={"question": "绿萝叶子发黄怎么办", "session_id": "s-delta"},
        headers=_auth_headers(user),
    )
    events = _parse_sse(resp.text)
    text = "".join(payload["text"] for kind, payload in events if kind == "delta")
    assert text == "【概览】整体状态良好。\n【浇水】表土干后浇透。"


# ---- 错误与鉴权 ----

async def test_stream_error_frame_does_not_persist(client: AsyncClient, stream_mocks):
    """生成期业务错误以 error 帧返回，且不落库。"""
    user = await _make_user("ai_stream_error")
    stream_mocks.error = "请说明植物种类或名称"

    resp = await client.post(
        STREAM_URL,
        json={"question": "叶子发黄怎么办", "session_id": "s-error"},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "400"
    assert "请说明植物种类或名称" in events[-1][1]["msg"]
    assert await AiAdvice.filter(user_id=user.id).count() == 0


async def test_stream_requires_token(client: AsyncClient):
    """未登录时在建立流之前返回 401（保持 HTTP 语义）。"""
    resp = await client.post(STREAM_URL, json={"question": "绿萝叶子发黄怎么办"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "401"


async def test_stream_requires_question_or_image(client: AsyncClient, stream_mocks):
    """既无问题也无图片：400 中文提示（流外参数校验）。"""
    user = await _make_user("ai_stream_empty")
    resp = await client.post(STREAM_URL, json={"session_id": "s-empty"}, headers=_auth_headers(user))
    assert resp.status_code == 400
    assert "请输入养护问题或上传植物图片" in resp.json()["msg"]


async def test_stream_other_plant_forbidden(client: AsyncClient, stream_mocks):
    """使用他人植物：403（流外归属校验）。"""
    owner = await _make_user("ai_stream_owner")
    other = await _make_user("ai_stream_other")
    plant = await Plant.create(user_id=owner.id, name="别人的绿萝")

    resp = await client.post(
        STREAM_URL,
        json={"plant_id": plant.id, "question": "叶子发黄怎么办"},
        headers=_auth_headers(other),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "403"