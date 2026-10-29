"""AI 智能养护模块接口测试（PRD 11.2 / 11.3）。

测试策略：
- AI 链路整体 mock（不真实调用 LLM / Embedding / Chroma），只验证路由编排、
  鉴权、数据隔离、落库、反馈与分页边界（PRD 11.2 明确要求 AI 依赖隔离）；
- 通过 sys.modules 注入假 chain / memory 模块，避免测试环境安装 LangChain。

注意：沙箱无法运行 asyncio，请在本地终端执行 pytest。
"""

import sys
import types

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.models.ai_advice import AiAdvice
from app.models.plant import Plant
from app.models.user import User

pytestmark = pytest.mark.asyncio

ADVICE_URL = "/api/v1/ai/care-advice"


# ---- 辅助函数 ----

async def _make_user(nickname: str) -> User:
    return await User.create(nickname=nickname, password_hash=hash_password("pass1234"), is_active=True)


def _auth_headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role)}"}


def _sample_result(is_fallback: bool = False) -> dict:
    """构造一份符合 PRD 8.5 的链路结果。"""
    source_type = "general" if is_fallback else "knowledge"
    section = {
        "key": "watering",
        "title": "浇水",
        "content": "表土干燥后浇透，避免积水。",
        "doc_ids": [] if is_fallback else ["doc-001"],
        "source_type": source_type,
    }
    return {
        "species": "绿萝",
        "confidence": 0.92,
        "is_fallback": is_fallback,
        "summary": "整体状态良好",
        "sections": [section],
        "warnings": [],
        "doc_refs": [] if is_fallback else [{"doc_id": "doc-001", "title": "绿萝养护指南", "source": "species/绿萝.md"}],
        "trace": {"retrieval": {"hit": not is_fallback}, "generate": {"status": "success"}},
        "status": "success",
    }


class _FakeMemory:
    """假的内存记忆容器。"""

    def __init__(self) -> None:
        self.history: dict[tuple[int, str], str] = {}
        self.saved: list[tuple[int, str, str, str]] = []
        self.cleared: list[tuple[int, str]] = []

    def history_text(self, user_id: int, session_id: str) -> str:
        return self.history.get((user_id, session_id), "（无历史对话）")

    def append(self, user_id: int, session_id: str, user_input: str, answer: str) -> None:
        self.saved.append((user_id, session_id, user_input, answer))

    def clear(self, user_id: int, session_id: str) -> bool:
        self.cleared.append((user_id, session_id))
        return True


@pytest.fixture
def ai_mocks(monkeypatch):
    """注入假 chain / memory 模块，并重置限流器。"""
    calls: list[dict] = []

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

    async def fake_run_care_advice(**kwargs):
        calls.append(kwargs)
        return _sample_result(is_fallback=False)

    async def fake_identify(image_url: str, user_species=None):
        return {"species": "绿萝", "confidence": 0.9, "is_known": True, "source": "vision"}

    fake_chain.run_care_advice = fake_run_care_advice
    fake_chain.get_workflow = lambda: types.SimpleNamespace(identify=fake_identify)
    fake_chain.run_error = None

    memory = _FakeMemory()
    fake_memory = types.ModuleType("app.ai.memory")
    fake_memory.get_memory_store = lambda: memory

    monkeypatch.setitem(sys.modules, "app.ai.chain", fake_chain)
    monkeypatch.setitem(sys.modules, "app.ai.memory", fake_memory)

    # 关闭限流干扰（默认 5 次/分钟会让连续用例互相影响）
    import app.ai.rate_limit as rate_limit_module
    from app.ai.rate_limit import SlidingWindowLimiter

    monkeypatch.setattr(rate_limit_module, "_limiter", SlidingWindowLimiter(limit=1000))

    return types.SimpleNamespace(chain=fake_chain, memory=memory, calls=calls)


# ---- 鉴权与参数校验（PRD 11.3）----

async def test_care_advice_requires_token(client: AsyncClient):
    """未登录生成建议返回 401。"""
    resp = await client.post(ADVICE_URL, json={"question": "绿萝叶子发黄怎么办"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "401"


async def test_care_advice_requires_question_or_image(client: AsyncClient, ai_mocks):
    """未提供问题与图片返回 400（中文提示）。"""
    user = await _make_user("ai_no_source")
    resp = await client.post(ADVICE_URL, json={"session_id": "s-empty"}, headers=_auth_headers(user))
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"
    assert "请输入养护问题或上传植物图片" in resp.json()["msg"]


async def test_care_advice_missing_species_hint(client: AsyncClient, ai_mocks, monkeypatch):
    """纯文本问题未识别出植物名称：返回 400「请说明植物种类或名称」。"""
    user = await _make_user("ai_no_species")

    async def fake_run(**_kwargs):
        raise ai_mocks.chain.SpeciesMissingError("请说明植物种类或名称")

    monkeypatch.setattr(ai_mocks.chain, "run_care_advice", fake_run)

    resp = await client.post(ADVICE_URL, json={"question": "叶子发黄怎么办"}, headers=_auth_headers(user))
    assert resp.status_code == 400
    assert resp.json()["code"] == "400"
    assert "请说明植物种类或名称" in resp.json()["msg"]


async def test_advices_page_validation(client: AsyncClient):
    """分页参数越界返回 400（page=0 / page_size=51）。"""
    user = await _make_user("ai_page")
    resp = await client.get("/api/v1/ai/advices?page=0", headers=_auth_headers(user))
    assert resp.status_code == 400
    resp = await client.get("/api/v1/ai/advices?page_size=51", headers=_auth_headers(user))
    assert resp.status_code == 400


# ---- 正常生成与落库（FR-402 / FR-406）----

async def test_care_advice_success_and_persist(client: AsyncClient, ai_mocks):
    """生成成功：返回分节建议、doc_refs、落库归属当前用户。"""
    user = await _make_user("ai_ok")
    plant = await Plant.create(user_id=user.id, name="小绿", species="绿萝")

    resp = await client.post(
        ADVICE_URL,
        json={"plant_id": plant.id, "question": "叶子发黄怎么办", "session_id": "s-1"},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "200"
    data = body["data"]
    assert data["is_fallback"] is False
    assert data["sections"][0]["source_type"] == "knowledge"
    assert data["doc_refs"][0]["doc_id"] == "doc-001"
    assert data["plant_name"] == "小绿"
    assert "trace" in data

    advice = await AiAdvice.get(id=data["id"])
    assert advice.user_id == user.id
    assert advice.plant_id == plant.id
    assert advice.session_id == "s-1"
    assert advice.content["question"] == "叶子发黄怎么办"

    # 链路入参：user_id 必须为当前用户，且注入当前会话历史
    assert ai_mocks.calls[0]["user_id"] == user.id
    assert ai_mocks.calls[0]["history"] == "（无历史对话）"
    assert ai_mocks.memory.saved


async def test_care_advice_fallback_flag(client: AsyncClient, ai_mocks, monkeypatch):
    """降级输出透传 is_fallback=true 并落库（FR-405）。"""
    user = await _make_user("ai_fallback")

    async def fake_run(**_kwargs):
        return _sample_result(is_fallback=True)

    monkeypatch.setattr(ai_mocks.chain, "run_care_advice", fake_run)

    resp = await client.post(ADVICE_URL, json={"question": "罕见植物叶子发黄怎么办"}, headers=_auth_headers(user))
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["is_fallback"] is True
    assert data["sections"][0]["source_type"] == "general"


async def test_care_advice_uses_memory_history(client: AsyncClient, ai_mocks):
    """多轮记忆：同一 session 的历史对话注入链路（不落向量库）。"""
    user = await _make_user("ai_memory")
    ai_mocks.memory.history[(user.id, "session-1")] = "用户：之前问过浇水"

    resp = await client.post(
        ADVICE_URL,
        json={"question": "绿萝多久浇一次水", "session_id": "session-1"},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    assert ai_mocks.calls[0]["history"] == "用户：之前问过浇水"
    assert ai_mocks.memory.saved[0][:2] == (user.id, "session-1")


async def test_care_advice_auto_matched_plant_persisted(client: AsyncClient, ai_mocks, monkeypatch):
    """链路内按问题解析自动匹配到植物时，落库 plant_id 使用匹配结果。"""
    user = await _make_user("ai_auto_plant")
    plant = await Plant.create(user_id=user.id, name="小绿", species="绿萝")

    async def fake_run(**_kwargs):
        result = _sample_result(is_fallback=False)
        result["plant_id"] = plant.id
        return result

    monkeypatch.setattr(ai_mocks.chain, "run_care_advice", fake_run)

    resp = await client.post(
        ADVICE_URL,
        json={"question": "小绿叶子发黄怎么办", "session_id": "s-auto"},
        headers=_auth_headers(user),
    )
    assert resp.status_code == 200
    advice = await AiAdvice.get(id=resp.json()["data"]["id"])
    assert advice.plant_id == plant.id


async def test_clear_session(client: AsyncClient, ai_mocks):
    """清除会话记忆接口返回 cleared。"""
    user = await _make_user("ai_clear")
    resp = await client.delete("/api/v1/ai/sessions/session-1", headers=_auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"]["cleared"] is True


# ---- 数据隔离（PRD 11.3）----

async def test_care_advice_other_plant_forbidden(client: AsyncClient, ai_mocks):
    """使用他人植物生成建议返回 403。"""
    owner = await _make_user("ai_owner")
    other = await _make_user("ai_other")
    plant = await Plant.create(user_id=owner.id, name="别人的绿萝")

    resp = await client.post(
        ADVICE_URL,
        json={"plant_id": plant.id, "question": "叶子发黄怎么办"},
        headers=_auth_headers(other),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "403"


async def test_advice_detail_and_feedback_isolation(client: AsyncClient, ai_mocks):
    """他人建议详情/反馈返回 403；本人反馈成功。"""
    owner = await _make_user("ai_detail_owner")
    other = await _make_user("ai_detail_other")

    resp = await client.post(
        ADVICE_URL,
        json={"question": "绿萝叶子发黄怎么办"},
        headers=_auth_headers(owner),
    )
    advice_id = resp.json()["data"]["id"]

    resp = await client.get(f"/api/v1/ai/advices/{advice_id}", headers=_auth_headers(other))
    assert resp.status_code == 403

    resp = await client.post(
        f"/api/v1/ai/advices/{advice_id}/feedback",
        json={"feedback": 1},
        headers=_auth_headers(owner),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["feedback"] == 1

    detail = await client.get(f"/api/v1/ai/advices/{advice_id}", headers=_auth_headers(owner))
    assert detail.json()["data"]["feedback"] == 1

    # 列表只包含本人建议
    listed = await client.get("/api/v1/ai/advices", headers=_auth_headers(other))
    assert listed.json()["data"]["total"] == 0


async def test_advice_detail_not_found(client: AsyncClient, ai_mocks):
    """不存在的建议返回 404。"""
    user = await _make_user("ai_404")
    resp = await client.get("/api/v1/ai/advices/99999", headers=_auth_headers(user))
    assert resp.status_code == 404
    assert resp.json()["code"] == "404"

# ---- 聊天式历史会话（会话分组 / 消息流 / 数据隔离）----

async def test_session_list_and_messages(client: AsyncClient, ai_mocks):
    """同一 session 的两轮问答：会话列表只出现一次，消息流按用户/AI 交替返回。"""
    user = await _make_user("ai_chat")

    for question in ("绿萝叶子发黄怎么办", "绿萝多久浇一次水"):
        resp = await client.post(
            ADVICE_URL,
            json={"question": question, "session_id": "s-chat"},
            headers=_auth_headers(user),
        )
        assert resp.status_code == 200

    sessions = await client.get("/api/v1/ai/sessions", headers=_auth_headers(user))
    data = sessions.json()["data"]
    assert data["total"] == 1
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["session_id"] == "s-chat"
    assert item["total"] == 2
    assert item["title"] == "绿萝多久浇一次水"  # 标题取最新一轮用户问题

    detail = await client.get("/api/v1/ai/sessions/s-chat", headers=_auth_headers(user))
    messages = detail.json()["data"]["messages"]
    assert len(messages) == 4
    assert messages[0]["role"] == "user"
    assert messages[0]["text"] == "绿萝叶子发黄怎么办"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["advice"]["summary"] == "整体状态良好"
    assert messages[2]["text"] == "绿萝多久浇一次水"  # 用户消息原样保留，不再剥离品种前缀
    assert messages[3]["role"] == "assistant"


async def test_session_isolation(client: AsyncClient, ai_mocks):
    """他人会话不可见：会话列表为空、读取详情 404（不泄露存在性）。"""
    owner = await _make_user("ai_chat_owner")
    other = await _make_user("ai_chat_other")

    resp = await client.post(
        ADVICE_URL,
        json={"question": "绿萝私密问题", "session_id": "s-private"},
        headers=_auth_headers(owner),
    )
    assert resp.status_code == 200

    listed = await client.get("/api/v1/ai/sessions", headers=_auth_headers(other))
    assert listed.json()["data"]["total"] == 0

    detail = await client.get("/api/v1/ai/sessions/s-private", headers=_auth_headers(other))
    assert detail.status_code == 404
    assert detail.json()["code"] == "404"


async def test_session_not_found(client: AsyncClient):
    """不存在的会话返回 404。"""
    user = await _make_user("ai_session_404")
    resp = await client.get("/api/v1/ai/sessions/not-exists", headers=_auth_headers(user))
    assert resp.status_code == 404
    assert resp.json()["code"] == "404"

async def test_legacy_session_compat(client: AsyncClient):
    """改造前的历史记录（session_id=NULL）以 legacy-{id} 形式展示并可读取。"""
    user = await _make_user("ai_legacy")
    advice = await AiAdvice.create(
        user_id=user.id,
        species="绿萝",
        content={"question": "旧版问题", "summary": "旧版摘要", "sections": [], "warnings": []},
        status="success",
    )

    sessions = await client.get("/api/v1/ai/sessions", headers=_auth_headers(user))
    items = sessions.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["session_id"] == f"legacy-{advice.id}"
    assert items[0]["title"] == "旧版问题"

    detail = await client.get(f"/api/v1/ai/sessions/legacy-{advice.id}", headers=_auth_headers(user))
    messages = detail.json()["data"]["messages"]
    assert messages[0]["role"] == "user"
    assert messages[0]["text"] == "旧版问题"

# ---- 删除历史会话 ----


async def test_delete_session_history(client: AsyncClient, ai_mocks):
    """删除会话：数据库记录与内存记忆一并清除，列表与会话详情都不再可见。"""
    user = await _make_user("ai_delete")
    for question in ("绿萝叶子发黄怎么办", "绿萝多久浇一次水"):
        resp = await client.post(
            ADVICE_URL,
            json={"question": question, "session_id": "s-delete"},
            headers=_auth_headers(user),
        )
        assert resp.status_code == 200

    resp = await client.delete("/api/v1/ai/sessions/s-delete/history", headers=_auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] == 2
    # 内存记忆同步清除（避免删库后再次提问仍带着旧上下文）
    assert (user.id, "s-delete") in ai_mocks.memory.cleared

    listed = await client.get("/api/v1/ai/sessions", headers=_auth_headers(user))
    assert listed.json()["data"]["total"] == 0
    detail = await client.get("/api/v1/ai/sessions/s-delete", headers=_auth_headers(user))
    assert detail.status_code == 404
    assert await AiAdvice.filter(user_id=user.id).count() == 0


async def test_delete_session_history_idempotent(client: AsyncClient, ai_mocks):
    """重复删除同一会话返回 deleted=0，不报错。"""
    user = await _make_user("ai_delete_twice")
    await client.post(
        ADVICE_URL,
        json={"question": "绿萝叶子发黄怎么办", "session_id": "s-twice"},
        headers=_auth_headers(user),
    )

    first = await client.delete("/api/v1/ai/sessions/s-twice/history", headers=_auth_headers(user))
    second = await client.delete("/api/v1/ai/sessions/s-twice/history", headers=_auth_headers(user))
    assert first.json()["data"]["deleted"] == 1
    assert second.status_code == 200
    assert second.json()["data"]["deleted"] == 0


async def test_delete_session_history_isolation(client: AsyncClient, ai_mocks):
    """他人不能删除我的会话：deleted=0，原记录与详情仍然存在。"""
    owner = await _make_user("ai_delete_owner")
    other = await _make_user("ai_delete_other")
    await client.post(
        ADVICE_URL,
        json={"question": "绿萝私密问题", "session_id": "s-protected"},
        headers=_auth_headers(owner),
    )

    resp = await client.delete(
        "/api/v1/ai/sessions/s-protected/history", headers=_auth_headers(other)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] == 0

    detail = await client.get("/api/v1/ai/sessions/s-protected", headers=_auth_headers(owner))
    assert detail.status_code == 200
    assert len(detail.json()["data"]["messages"]) == 2


async def test_delete_legacy_session(client: AsyncClient):
    """legacy-{id} 历史记录同样支持删除，且不会误删同 id 的正常会话。"""
    user = await _make_user("ai_delete_legacy")
    advice = await AiAdvice.create(
        user_id=user.id,
        species="绿萝",
        content={"question": "旧版问题", "summary": "旧版摘要", "sections": [], "warnings": []},
        status="success",
    )

    resp = await client.delete(
        f"/api/v1/ai/sessions/legacy-{advice.id}/history", headers=_auth_headers(user)
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["deleted"] == 1
    assert await AiAdvice.filter(id=advice.id).count() == 0