"""AI 接口限流（PRD 12：AI 接口按用户 5 次/分钟）。

进程内滑动窗口实现，单 worker 下有效；多 worker 部署需换 Redis（v1 不引入额外组件）。
"""

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    """按 key 统计最近 window_seconds 内的请求次数。"""

    def __init__(self, limit: int, window_seconds: int = 60):
        self._limit = max(1, limit)
        self._window = window_seconds
        self._records: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """返回 (是否放行, 剩余可用次数)。"""
        now = time.time()
        with self._lock:
            queue = self._records.setdefault(key, deque())
            while queue and now - queue[0] >= self._window:
                queue.popleft()
            if len(queue) >= self._limit:
                return False, 0
            queue.append(now)
            return True, self._limit - len(queue)


_limiter: SlidingWindowLimiter | None = None


def get_ai_limiter() -> SlidingWindowLimiter:
    """限流器单例（阈值读取 .env）。"""
    global _limiter
    if _limiter is None:
        from app.core.config import get_settings

        _limiter = SlidingWindowLimiter(get_settings().AI_RATE_LIMIT_PER_MINUTE)
    return _limiter