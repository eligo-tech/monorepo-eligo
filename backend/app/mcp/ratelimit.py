"""Per-user tool-call limit for `/mcp`.

In-process sliding window: right for the single Railway instance this runs on
today. A second instance would need a shared store — the limit would then be
per instance, i.e. looser, never tighter.
"""

from __future__ import annotations

import time
from collections import deque

from app.core.config import settings


class RateLimited(Exception):
    pass


class Limiter:
    WINDOW_SECONDS = 60.0

    def __init__(self) -> None:
        self._calls: dict[str, deque[float]] = {}

    def check(self, key: str) -> None:
        now = time.monotonic()
        calls = self._calls.setdefault(key, deque())
        while calls and now - calls[0] >= self.WINDOW_SECONDS:
            calls.popleft()
        if len(calls) >= settings.mcp_rate_limit_per_minute:
            raise RateLimited(
                f"Rate limit: at most {settings.mcp_rate_limit_per_minute} Eligo calls "
                "per minute. Please wait a moment."
            )
        calls.append(now)

    def reset(self) -> None:
        self._calls.clear()
