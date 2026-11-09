"""What every employer-board reader shares (Personio, Ashby, …).

A board answer is read with redirects off and a size cap, so a moved board
reads as "no board here" and a runaway body as a failure — never as a feed.
`hub/ats.py` drives the readers; each source module supplies the parsing.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.domain.hub.adapters.base import SourceUnreachable

#: Status for a body over the reader's cap: read as a failure, never as a feed.
TOO_LARGE = 599


class FeedUnreadable(Exception):
    """A 200 that is not the feed (an HTML error page, a truncated body)."""


@dataclass(frozen=True)
class FeedAnswer:
    status: int
    body: bytes

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


class BoardHttp:
    """GET with redirects off, a size cap and our user agent."""

    #: Overridden per source, from measured answers.
    max_body = 10 * 1024 * 1024

    def __init__(
        self, *, timeout: float | None = None, user_agent: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = timeout or settings.hub_http_timeout
        self._user_agent = user_agent or settings.hub_user_agent
        #: Tests only.
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False,
            headers={"User-Agent": self._user_agent},
        )

    async def _get(self, url: str) -> tuple[int, bytes]:
        """Status and body, the body read no further than `max_body`."""
        try:
            async with self._client() as client, client.stream("GET", url) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > self.max_body:
                        return TOO_LARGE, b""
                return response.status_code, bytes(body)
        except httpx.HTTPError as exc:
            raise SourceUnreachable(f"{type(exc).__name__} for {url}") from exc
