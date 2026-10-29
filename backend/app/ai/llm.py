"""LLM / Embedding 客户端工厂（PRD 3.2 / 8.1）。

阿里云百炼同时提供两类 OpenAI 兼容接口，本模块严格区分：
- LLM：多模态对话模型（节点1 识别 + 节点5 生成），使用 LLM_API_KEY；
- Embedding：向量化模型（入库 + 检索），使用 EMBEDDING_API_KEY。
两者互不复用 Key，避免权限混淆。

关键实现点：
1. `check_embedding_ctx_length=False`：百炼 Embedding 接口只接受原始文本，
   LangChain 默认会先用 tiktoken 转 token 数组再发送，百炼会直接报错；
2. 客户端使用 lru_cache 单例，避免每次请求重建连接池；
3. 未配置 Key 时抛出 AiConfigError，由接口层转换为可读中文错误。
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.core.config import get_settings


class AiConfigError(RuntimeError):
    """AI 配置缺失（API Key / Base URL 未填）。"""


def _ensure_value(value: str, name: str) -> str:
    """校验配置非空且不是模板占位值。"""
    if not value or value.strip() in {"", "sk-xxxxxxxx", "please-change-me"}:
        raise AiConfigError(f"{name} 未配置，请在 backend/.env 中填写")
    return value.strip()


def _thinking_kwargs(settings) -> dict:
    """关闭思考模式（Qwen3 系列默认可能开启 thinking，生成耗时可达数十秒）。

    百炼 OpenAI 兼容接口通过 extra_body 透传 enable_thinking；
    若模型不支持该参数，把 .env 的 LLM_ENABLE_THINKING 改为 true 即不发送。
    """
    if settings.LLM_ENABLE_THINKING:
        return {}
    return {"extra_body": {"enable_thinking": False}}


@lru_cache
def get_chat_model() -> ChatOpenAI:
    """生成用 LLM（节点5，使用配置的温度与较长超时）。"""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=_ensure_value(settings.LLM_API_KEY, "LLM_API_KEY"),
        base_url=settings.llm_base_url,
        temperature=settings.LLM_TEMPERATURE,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=1,
        max_tokens=settings.LLM_MAX_TOKENS,
        **_thinking_kwargs(settings),
    )


@lru_cache
def get_vision_model() -> ChatOpenAI:
    """图像识别用多模态模型（节点1）。

    温度固定 0：识别属于确定性任务，降低模型自由发挥导致的品种幻觉。
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.llm_vision_model,
        api_key=_ensure_value(settings.LLM_API_KEY, "LLM_API_KEY"),
        base_url=settings.llm_base_url,
        temperature=0,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=1,
        max_tokens=512,
        **_thinking_kwargs(settings),
    )


@lru_cache
def get_embedding_model() -> OpenAIEmbeddings:
    """Embedding 模型（节点3 检索 + 知识库入库）。"""
    settings = get_settings()
    return OpenAIEmbeddings(
        model=settings.EMBEDDING_MODEL,
        api_key=_ensure_value(settings.EMBEDDING_API_KEY, "EMBEDDING_API_KEY"),
        base_url=settings.embedding_base_url,
        timeout=settings.EMBEDDING_TIMEOUT_SECONDS,
        max_retries=1,
        check_embedding_ctx_length=False,
    )


def reset_model_cache() -> None:
    """清空模型单例缓存（切换 Base URL / 测试 mock 时使用）。"""
    get_chat_model.cache_clear()
    get_vision_model.cache_clear()
    get_embedding_model.cache_clear()