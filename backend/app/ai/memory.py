"""多轮对话记忆（LangChain ConversationBufferMemory）。

用户要求：使用 LangChain 内存记忆实现多轮 RAG，记忆不得写入向量库。
实现要点：
1. 以 (user_id, session_id) 为键隔离，避免跨用户串话（PRD 7.3）；
2. 只保存在进程内存字典中，重启即失效，不落 MySQL / Chroma；
3. 按 AI_MEMORY_MAX_TURNS 裁剪，控制提示词长度；
4. 简易 TTL + 最大会话数，防止长期运行内存无限增长。
"""

import threading
import time
import warnings

from langchain.memory import ConversationBufferMemory

from app.core.config import get_settings


class ConversationMemoryStore:
    """会话记忆容器（进程内单例）。"""

    def __init__(self, max_turns: int, ttl_seconds: int = 3600, max_sessions: int = 500):
        self._max_turns = max(1, max_turns)
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._items: dict[str, tuple[ConversationBufferMemory, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(user_id: int, session_id: str) -> str:
        """会话键：用户 ID 必须参与，保证不同用户同名 session 不串话。"""
        return f"{user_id}:{session_id or 'default'}"

    def _purge_locked(self) -> None:
        """清理过期会话与超量会话（调用方需已持锁）。"""
        now = time.time()
        expired = [key for key, (_, touched) in self._items.items() if now - touched > self._ttl_seconds]
        for key in expired:
            self._items.pop(key, None)
        if len(self._items) > self._max_sessions:
            # 按最后访问时间淘汰最旧会话
            ordered = sorted(self._items.items(), key=lambda item: item[1][1])
            for key, _ in ordered[: len(self._items) - self._max_sessions]:
                self._items.pop(key, None)

    def get(self, user_id: int, session_id: str) -> ConversationBufferMemory:
        """获取或创建会话记忆对象。"""
        key = self._key(user_id, session_id)
        with self._lock:
            self._purge_locked()
            item = self._items.get(key)
            if item is not None:
                memory, _ = item
                self._items[key] = (memory, time.time())
                return memory
            # 用户明确要求使用 ConversationBufferMemory；LangChain 0.3 会对该 API 输出弃用提示，
            # 本模块已锁定 0.3 稳定线，这里仅屏蔽日志噪音，不改变行为。
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                memory = ConversationBufferMemory(
                    memory_key="history",
                    human_prefix="用户",
                    ai_prefix="助手",
                    return_messages=False,
                    output_key="answer",
                )
            self._items[key] = (memory, time.time())
            return memory

    def history_text(self, user_id: int, session_id: str) -> str:
        """读取历史对话文本（注入本轮提示词）。"""
        memory = self.get(user_id, session_id)
        value = memory.load_memory_variables({}).get("history", "")
        return str(value).strip() or "（无历史对话）"

    def append(self, user_id: int, session_id: str, user_input: str, answer: str) -> None:
        """追加一轮对话，并按最大轮数裁剪。"""
        memory = self.get(user_id, session_id)
        memory.save_context({"input": user_input}, {"answer": answer})
        messages = memory.chat_memory.messages
        keep = self._max_turns * 2
        if len(messages) > keep:
            memory.chat_memory.messages = messages[-keep:]

    def clear(self, user_id: int, session_id: str) -> bool:
        """清除指定会话（返回是否实际存在）。"""
        key = self._key(user_id, session_id)
        with self._lock:
            return self._items.pop(key, None) is not None


# 进程内单例：FastAPI 单 worker 下共享；多 worker 部署需改用 Redis（非 v1 范围）
_memory_store: ConversationMemoryStore | None = None


def get_memory_store() -> ConversationMemoryStore:
    """获取记忆容器单例。"""
    global _memory_store
    if _memory_store is None:
        settings = get_settings()
        _memory_store = ConversationMemoryStore(max_turns=settings.AI_MEMORY_MAX_TURNS)
    return _memory_store