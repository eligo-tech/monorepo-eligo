"""Per-user request limits (review 2026-10-31 #5 C; the MCP limit before it).

In-process sliding window: correct for the single Railway instance this runs
on. A second instance would need a shared store — the limit would then be per
instance, i.e. looser, never tighter. Limits are read from settings on every
check, so a change (or a test) takes effect without a restart.

Three windows, all per user:

* `REST` — every authenticated REST request (`rest_rate_limit_per_minute`);
* `AI` — the routes that pay an LLM per call (`ai_rate_limit_per_minute`);
* `MCP` — tool calls from an AI client (`mcp_rate_limit_per_minute`).
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable

from fastapi import Depends, HTTPException, status

from app.core.config import settings


class RateLimited(Exception):
    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class Limiter:
    WINDOW_SECONDS = 60.0

    def __init__(self, name: str, limit: Callable[[], int]) -> None:
        self.name = name
        self._limit = limit
        self._calls: dict[str, deque[float]] = {}

    def check(self, key: str) -> None:
        limit = self._limit()
        if limit <= 0:
            return  # 0 switches this window off
        now = time.monotonic()
        calls = self._calls.setdefault(key, deque())
        while calls and now - calls[0] >= self.WINDOW_SECONDS:
            calls.popleft()
        if len(calls) >= limit:
            wait = math.ceil(self.WINDOW_SECONDS - (now - calls[0]))
            raise RateLimited(
                f"Rate limit: at most {limit} {self.name} calls per minute. "
                f"Please wait {wait} s.",
                retry_after=max(1, wait),
            )
        calls.append(now)

    def reset(self) -> None:
        self._calls.clear()


REST = Limiter("Eligo", lambda: settings.rest_rate_limit_per_minute)
AI = Limiter("AI", lambda: settings.ai_rate_limit_per_minute)
MCP = Limiter("Eligo", lambda: settings.mcp_rate_limit_per_minute)


def refuse(exc: RateLimited) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        {"code": "rate_limited", "message": str(exc), "retry_after": exc.retry_after},
        headers={"Retry-After": str(exc.retry_after)},
    )


def actor_key(actor) -> str:  # noqa: ANN001 — core.auth.Actor; avoids an import cycle
    return actor.user_id or f"tenant:{actor.tenant_id}"


def _paid_ai_quota():  # noqa: ANN202
    from app.core.auth import Actor, get_current_actor

    async def check(actor: Actor = Depends(get_current_actor)) -> Actor:
        try:
            AI.check(actor_key(actor))
        except RateLimited as exc:
            raise refuse(exc) from None
        return actor

    return check


#: Dependency for routes that pay an LLM per call: CV and transcript
#: extraction, job-advert parsing.
paid_ai_quota = _paid_ai_quota()
