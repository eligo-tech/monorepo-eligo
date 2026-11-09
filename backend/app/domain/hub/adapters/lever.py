"""Lever — employers' own public job boards, DACH jobs only.

A company on Lever publishes every listed job at
`https://api.lever.co/v0/postings/{slug}?mode=json` — Lever's documented
public Postings API, no credentials. Boards on Lever's EU instance live only
at `api.eu.lever.co` / `jobs.eu.lever.co` (the global host answers 404 for
them), so each region is its own board system: `lever` and `lever-eu`.
Both API hosts' robots.txt: `Allow: /`, `Crawl-delay: 1` — the sync reads
one board a second. The board page host (`jobs.lever.co`) allows all agents
with `Content-Signal: search=yes, ai-train=no`; we read only its `<title>`,
for the company's name, once per board with a DACH job.

Measured 2026-11-08, all 172 EU-hosted boards: 28 with DACH jobs, 386 jobs.

  * **A full snapshot** with the full ad text (description + lists +
    closing text) and `createdAt`.
  * **`country` is an ISO code** on ~100% of jobs; the town is text
    (`categories.location`, "Graz"), read by `places.dach_place`.
  * A job whose country is elsewhere counts only when another of its
    locations names a DACH town, as for Ashby.
  * No company name in the API; the board page's `<title>` is the name.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from app.domain.hub.adapters import places
from app.domain.hub.adapters.boards import BoardHttp, FeedAnswer, FeedUnreadable
from app.domain.hub.adapters.greenhouse import _result
from app.domain.hub.adapters.personio import _clean

SOURCE_NAME = "lever"
ELSEWHERE_REFRESH = dt.timedelta(days=30)

_COUNTRIES = {"DE": places.DE, "AT": places.AT, "CH": places.CH}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_JOB_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_TITLE = re.compile(r"<title>\s*(.*?)\s*</title>", re.IGNORECASE | re.DOTALL)
_EMPLOYMENT = {"full-time": "full_time", "full time": "full_time", "vollzeit": "full_time",
               "part-time": "part_time", "part time": "part_time", "teilzeit": "part_time"}


@dataclass(frozen=True)
class Position:
    job_id: str
    title: str
    place: dict[str, Any] | None
    text: str | None
    employment_type: str | None
    created_at: dt.datetime | None
    office: None = None
    company: None = None


def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def dach_place(job: dict) -> dict[str, Any] | None:
    """Where in DACH this job is. Its own country when that is DACH (the town
    from its location text); otherwise another location naming a DACH town."""
    categories = job.get("categories") if isinstance(job.get("categories"), dict) else {}
    location = _str(categories.get("location"))
    others = [x for x in categories.get("allLocations") or [] if isinstance(x, str)]
    country = _COUNTRIES.get(_str(job.get("country")) or "")
    if country:
        place = places.dach_place(location, *others)
        if place and place["country"] == country:
            return place
        town = (location or "").split(",")[0].strip()
        if town and places._NOT_A_TOWN.search(town):
            town = ""
        return {"country": country, "city": town or None, "postal_code": None, "street": None,
                "region": None, "label": location}
    if _str(job.get("country")) is None:
        return places.dach_place(location, *others)
    # The job names a country outside DACH: its own location is that place;
    # only another location naming a DACH town makes it a DACH job.
    place = places.dach_place(*others)
    return place if place and place["city"] else None


def _text(job: dict) -> str | None:
    parts = [_str(job.get("descriptionPlain"))]
    for item in job.get("lists") or []:
        if isinstance(item, dict):
            parts.append(_str(item.get("text")))
            if isinstance(item.get("content"), str):
                parts.append(_clean(item["content"]))
    parts.append(_str(job.get("additionalPlain")))
    text = "\n\n".join(p for p in parts if p)
    return text or None


def _when(value: Any) -> dt.datetime | None:
    if isinstance(value, (int, float)) and value > 0:
        return dt.datetime.fromtimestamp(value / 1000, dt.UTC)
    return None


def parse_feed(body: bytes | str) -> list[Position]:
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise FeedUnreadable(f"not JSON: {exc}") from exc
    if not isinstance(data, list):
        raise FeedUnreadable("not a postings list")
    positions: dict[str, Position] = {}
    for job in data:
        if not isinstance(job, dict):
            continue
        job_id, title = _str(job.get("id")), _str(job.get("text"))
        if not job_id or not title or not _JOB_ID.match(job_id):
            continue
        categories = job.get("categories") if isinstance(job.get("categories"), dict) else {}
        positions[job_id] = Position(
            job_id=job_id,
            title=html.unescape(title),
            place=dach_place(job),
            text=_text(job),
            employment_type=_EMPLOYMENT.get((_str(categories.get("commitment")) or "").lower()),
            created_at=_when(job.get("createdAt")),
        )
    return list(positions.values())


def parse_company_name(page: str) -> str | None:
    match = _TITLE.search(page or "")
    name = html.unescape(match.group(1)).strip() if match else ""
    return name[:300] or None


class _Region:
    """One Lever instance — the same pure pieces `hub/ats.py` expects of a
    board module, bound to that instance's hosts."""

    SOURCE_NAME = SOURCE_NAME
    ELSEWHERE_REFRESH = ELSEWHERE_REFRESH
    parse_feed = staticmethod(parse_feed)

    def __init__(self, ats: str, api: str, board: str, prefix: str) -> None:
        self.ats, self.api, self.board, self.prefix = ats, api, board, prefix

    def valid_slug(self, slug: str) -> bool:
        """A global board called "eu" would read as the EU instance's."""
        return bool(_SLUG.match(slug or "")) and not (self.prefix == "" and slug == "eu")

    def feed_url(self, slug: str) -> str:
        return f"{self.api}/v0/postings/{quote(slug, safe='')}?mode=json"

    def board_url(self, slug: str) -> str:
        return f"{self.board}/{quote(slug, safe='')}"

    def external_id(self, slug: str, job_id: str) -> str:
        """"<slug>:<id>", and "eu:<slug>:<id>" on the EU instance, so the
        link can open the right host."""
        return f"{self.prefix}{slug}:{job_id}"

    def to_result(self, *, slug, positions, offices, fetched_at, company_name=None, content_hash=None):
        del offices
        return _result(SOURCE_NAME, self.feed_url(slug), slug, positions, fetched_at, company_name,
                       content_hash, self.external_id)


GLOBAL = _Region("lever", "https://api.lever.co", "https://jobs.lever.co", "")
EU = _Region("lever-eu", "https://api.eu.lever.co", "https://jobs.eu.lever.co", "eu:")


def job_url(external_id: str) -> str | None:
    """The job's page on its own instance, from its reference."""
    region, rest = (EU, external_id[3:]) if external_id.startswith("eu:") else (GLOBAL, external_id)
    slug, _, job_id = rest.partition(":")
    if not slug or not job_id:
        return None
    return f"{region.board_url(slug)}/{quote(job_id, safe='')}"


class LeverAdapter(BoardHttp):
    """Two calls: a board's postings, and its board page once for the name."""

    max_body = 32 * 1024 * 1024

    def __init__(self, region: _Region = GLOBAL, **kwargs) -> None:
        super().__init__(**kwargs)
        self.region = region
        self.name = region.ats

    async def fetch_feed(self, slug: str) -> FeedAnswer:
        return FeedAnswer(*await self._get(self.region.feed_url(slug)))

    async def fetch_company_name(self, slug: str) -> str | None:
        status, body = await self._get(self.region.board_url(slug))
        return parse_company_name(body.decode("utf-8", errors="replace")) if status == 200 else None
