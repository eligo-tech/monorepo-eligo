"""Partner-board pages — the "Quelle" a Bundesagentur posting links to.

About a third of BA postings carry an `externeURL`: the same vacancy on a
partner job board (jobexport, get-in-it, persy, yourfirm, stellenanzeigen, …).
Those pages often name the contact the BA text leaves out — "Deine
Ansprechperson für weitere Fragen: Kathrin Telega, Junior People & Culture
Business Partner". Reading them is what makes "Ansprechpartner finden" work for
postings whose BA text says only `bewerbung@`.

Not a listing source. It adds no postings and no companies; it fetches ONE page
per posting the corpus already holds, and stores that page's readable text next
to the BA text. So it is not a `SourceAdapter` and is not in `factory.py`.

Same split as every adapter, for the same reason:

  * `page_text(html)` is PURE — HTML in, readable text out. CI runs it against
    captured real pages with no network.
  * `PartnerPageFetcher` is the thin HTTP wrapper: robots.txt, one identified
    User-Agent, a pause between requests to the same host, and a result that
    reports failure instead of raising (a failure is evidence too).

Measured on 260 partner links from live BA postings (Sept 2026), not assumed:

  * every host's robots.txt allows the pages;
  * heyjobs.co (19% of links) answers 202 with a bot-check page and
    jobvector.de answers 403. They are refused here up front and recorded as
    such. We do not work around a site that has chosen to block crawlers.
  * jobs.ams.at (the Austrian service) renders in JavaScript — the HTML holds
    no ad text at all — so it is skipped rather than fetched for nothing.
"""

from __future__ import annotations

import asyncio
import dataclasses
import html as html_lib
import re
import time
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Hosts not fetched at all, each for a measured reason. Recorded as a status
#: so the skip is visible in the numbers rather than silent.
SKIPPED_HOSTS: dict[str, str] = {
    "www.heyjobs.co": "bot-check (HTTP 202 challenge page)",
    "heyjobs.co": "bot-check (HTTP 202 challenge page)",
    "www.jobvector.de": "blocks crawlers (HTTP 403)",
    "jobvector.de": "blocks crawlers (HTTP 403)",
    "jobs.ams.at": "rendered in JavaScript, no text in the HTML",
}

#: Status codes stored for outcomes that are not an HTTP response.
STATUS_SKIPPED = 0  # host on SKIPPED_HOSTS
STATUS_ROBOTS = 1  # disallowed by robots.txt
STATUS_ERROR = 2  # network error / timeout

#: Page text is capped: a partner page with a long company profile is not worth
#: storing whole, and the contact block sits in the ad body.
MAX_TEXT = 20_000

_BLOCK_TAGS = r"p|div|br|li|ul|ol|tr|td|th|h[1-6]|section|article|header|footer|dt|dd|table|blockquote"
_DROP = re.compile(
    r"<(script|style|noscript|svg|nav|form|iframe|template|head)\b[\s\S]*?</\1\s*>",
    re.IGNORECASE,
)


#: C0 control characters except tab and newline. Postgres refuses NUL (0x00)
#: in text outright — "invalid byte sequence for encoding UTF8: 0x00" — and
#: one gute-jobs.de page carrying one failed the whole first production batch.
#: SQLite stores it happily, which is why only production saw it.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_control(value: str) -> str:
    """Remove control characters Postgres cannot store or no reader needs."""
    return _CONTROL.sub("", value)


def page_text(html: str | None) -> str:
    """Readable text of a job page, one visual line per line.

    Line breaks are kept on purpose: the contact extractor relies on them
    ("Deine Ansprechperson\\nKathrin Telega\\nJunior People & Culture …").
    Markup is dropped, never interpreted — this is third-party content.
    """
    if not html:
        return ""
    text = _DROP.sub(" ", html)
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    text = re.sub(rf"</?(?:{_BLOCK_TAGS})\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = strip_control(html_lib.unescape(text)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    # Collapse runs of empty lines to one: a blank line is a boundary, ten are noise.
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()[:MAX_TEXT]


@dataclasses.dataclass(frozen=True)
class PartnerPage:
    """One fetch of one partner page. `status` is the HTTP code, or one of the
    STATUS_* markers when no response was obtained."""

    url: str
    final_url: str | None
    status: int
    text: str | None
    note: str | None = None


class PartnerPageFetcher:
    """Fetches partner pages politely: robots.txt, identified, paced per host.

    Use as an async context manager for a batch — one connection pool, one
    robots.txt read per host:

        async with PartnerPageFetcher() as fetcher:
            page = await fetcher.fetch(url)
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        per_host_delay: float = 1.0,
        user_agent: str | None = None,
    ) -> None:
        self._client = client
        self._delay = per_host_delay
        self._ua = user_agent or settings.hub_user_agent
        self._robots: dict[str, robotparser.RobotFileParser] = {}
        self._last_hit: dict[str, float] = {}

    async def __aenter__(self) -> PartnerPageFetcher:
        if self._client is None:
            self._client = self._new_client()
            self._owns = True
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if getattr(self, "_owns", False) and self._client is not None:
            await self._client.aclose()
            self._client = None
            self._owns = False

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": self._ua, "Accept-Language": "de"},
        )

    async def _robots_allow(self, client: httpx.AsyncClient, url: str) -> bool:
        parts = urlparse(url)
        base = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(base)
        if parser is None:
            parser = robotparser.RobotFileParser()
            try:
                r = await client.get(base + "/robots.txt")
                # No robots.txt (404) means no restrictions; a 401/403 on the
                # robots file itself is read as "disallow everything", which
                # is what the standard asks for.
                if r.status_code in (401, 403):
                    parser.parse(["User-agent: *", "Disallow: /"])
                else:
                    parser.parse(r.text.splitlines() if r.status_code == 200 else [])
            except httpx.HTTPError:
                parser.parse([])
            self._robots[base] = parser
        return parser.can_fetch(self._ua, url)

    async def _pace(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self._delay - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_hit[host] = time.monotonic()

    async def fetch(self, url: str) -> PartnerPage:
        host = urlparse(url).netloc.lower()
        if host in SKIPPED_HOSTS:
            return PartnerPage(url, None, STATUS_SKIPPED, None, SKIPPED_HOSTS[host])
        owns_client = self._client is None
        client = self._client or self._new_client()
        try:
            try:
                allowed = await self._robots_allow(client, url)
            except Exception as exc:  # noqa: BLE001 — same reasoning as below
                return PartnerPage(
                    url, None, STATUS_ERROR, None, f"robots: {type(exc).__name__}"
                )
            if not allowed:
                return PartnerPage(url, None, STATUS_ROBOTS, None, "robots.txt disallows")
            await self._pace(host)
            try:
                response = await client.get(url)
                final = strip_control(str(response.url))
                if response.status_code != 200:
                    return PartnerPage(url, final, response.status_code, None)
                text = page_text(response.text)
            except Exception as exc:  # noqa: BLE001 — one page must not end a batch
                # Not only httpx.HTTPError: a malformed partner URL raises
                # InvalidURL, a broken charset raises on `.text`. Every one of
                # them is "this page failed", recorded like a 404.
                return PartnerPage(url, None, STATUS_ERROR, None, type(exc).__name__)
            return PartnerPage(url, final, 200, text or None)
        finally:
            if owns_client:
                await client.aclose()
