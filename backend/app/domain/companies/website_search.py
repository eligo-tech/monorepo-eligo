"""A web search that PROPOSES a company's website (ELI-39 finder).

Used by `companies/impressum.py` for a workspace company with no website
candidate of its own, or whose candidates' Impressum named another firm. The
search only proposes: a result domain is kept only when its Impressum names
this company as operator (`names_firm`) and the values re-check on the page —
the same deterministic gate as every other candidate.

Third-party data flow: the query — the company's name, its town when the
record has one, and the word "Impressum" — goes to the Brave Search API
(subprocessor; ARCHITECTURE.md §GDPR, Art. 28). No person's name, address or
mailbox is ever sent; suspected sole traders are never searched (the caller
filters them out first).

Off unless `ELIGO_SEARCH_API_KEY` is set: `from_settings` then returns None
and the Impressum check behaves exactly as without a finder. Machine-only
(RULE 1) — only the scheduled check calls it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
#: Results read per query; the caller keeps at most a couple of domains.
RESULTS = 5
#: Brave's free tier allows one request per second.
MIN_INTERVAL = 1.1
TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class _NoSearchUrls(logging.Filter):
    """httpx logs every request URL at INFO — for a search, that URL holds
    the query: a workspace's client list in the logs and in error-report
    breadcrumbs. Drop those records; every other httpx line is untouched."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return "api.search.brave.com" not in record.getMessage()
        except Exception:  # noqa: BLE001 — a malformed record: drop it, never crash logging
            return False


for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_NoSearchUrls())


class WebSearch(Protocol):
    #: Queries this run may still send. The CALLER spends it, synchronously
    #: before awaiting `search`, so concurrent reads cannot overdraw it.
    remaining: int

    async def search(self, query: str) -> list[str] | None:
        """Result URLs, best first; None when the provider gave no answer
        (error, timeout) — the caller records that as a failed search."""


class BraveSearch:
    """Brave Search API client: paced (one request at a time), time-boxed,
    with the run's query budget on `remaining` for the caller to spend."""

    def __init__(
        self,
        api_key: str,
        *,
        budget: int = 0,
        min_interval: float = MIN_INTERVAL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.remaining = budget
        self._key = api_key
        self._interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0
        self._client = httpx.AsyncClient(timeout=TIMEOUT, transport=transport)

    async def __aenter__(self) -> BraveSearch:
        return self

    async def __aexit__(self, *_exc) -> None:
        await self._client.aclose()

    async def search(self, query: str) -> list[str] | None:
        async with self._lock:  # one request at a time, paced
            wait = self._last + self._interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                response = await self._client.get(
                    BRAVE_URL,
                    params={"q": query, "country": "de", "count": RESULTS},
                    headers={"X-Subscription-Token": self._key, "Accept": "application/json"},
                )
                response.raise_for_status()
                results = (response.json().get("web") or {}).get("results") or []
            except (httpx.HTTPError, ValueError, AttributeError) as exc:
                # Never the query or the key in the log.
                logger.warning("website search failed: %s", type(exc).__name__)
                return None
            finally:
                self._last = time.monotonic()
        return [r["url"] for r in results if isinstance(r, dict) and isinstance(r.get("url"), str)]


def from_settings(*, api_key: str | None, budget: int) -> BraveSearch | None:
    """The configured client, or None — no key or no budget: no search."""
    if not api_key or not api_key.strip() or budget <= 0:
        return None
    return BraveSearch(api_key.strip(), budget=budget)
