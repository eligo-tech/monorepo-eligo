"""Greenhouse — employers' own public job boards, DACH jobs only.

A company on Greenhouse publishes every listed job at
`https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true` —
Greenhouse's documented public Job Board API, no credentials; its robots.txt
disallows only `/embed/`. The same API serves boards hosted on the EU
instance (`job-boards.eu.greenhouse.io`), and `job-boards.greenhouse.io`
opens their jobs too.

Measured 2026-11-08, all 779 EU-hosted boards: 146 with DACH jobs, 2,154 jobs.

  * **A full snapshot** with the full ad text (`content`, HTML that is itself
    entity-escaped), the company's name on every job and `first_published`.
  * **The location is text** ("Munich, Bavaria, Germany"; offices repeat it);
    a postcode in ~5%. Read by `places.dach_place`.
  * Most main-host boards are not in DACH (~3% of live ones), hence a
    monthly look at such a board.

Greenhouse is not the rights holder of the ad text; the employer is. Shown
with a link to the employer's board, never described as licensed.
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
from app.domain.hub.adapters.base import FetchResult, SourcedCompany, SourcedPosting
from app.domain.hub.adapters.boards import BoardHttp, FeedAnswer, FeedUnreadable
from app.domain.hub.adapters.eures import staffing_signal
from app.domain.hub.adapters.personio import _NOT_A_JOB, _clean
from app.domain.hub.models import EMPLOYER, PRIVATE_RECRUITER

SOURCE_NAME = "greenhouse"
API = "https://boards-api.greenhouse.io/v1/boards"
#: Most boards have no DACH job; such a board is looked at monthly.
ELSEWHERE_REFRESH = dt.timedelta(days=30)

_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_JOB_ID = re.compile(r"^[0-9]{1,20}$")


def valid_slug(slug: str) -> bool:
    return bool(_SLUG.match(slug or ""))


def feed_url(slug: str) -> str:
    return f"{API}/{quote(slug, safe='')}/jobs?content=true"


def job_url(slug: str, job_id: str) -> str:
    return f"https://job-boards.greenhouse.io/{quote(slug, safe='')}/jobs/{quote(job_id, safe='')}"


def external_id(slug: str, job_id: str) -> str:
    return f"{slug}:{job_id}"


@dataclass(frozen=True)
class Position:
    job_id: str
    title: str
    place: dict[str, Any] | None
    text: str | None
    created_at: dt.datetime | None
    company: str | None
    office: None = None
    employment_type: None = None


def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _when(value: Any) -> dt.datetime | None:
    text = _str(value)
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def parse_feed(body: bytes | str) -> list[Position]:
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise FeedUnreadable(f"not JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise FeedUnreadable("no jobs list")
    positions: dict[str, Position] = {}
    for job in data["jobs"]:
        if not isinstance(job, dict):
            continue
        job_id, title = str(job.get("id") or ""), _str(job.get("title"))
        if not title or not _JOB_ID.match(job_id):
            continue
        location = _str((job.get("location") or {}).get("name")) if isinstance(job.get("location"), dict) else None
        offices = [_str(o.get("location")) or _str(o.get("name")) for o in job.get("offices") or [] if isinstance(o, dict)]
        content = job.get("content")
        positions[job_id] = Position(
            job_id=job_id,
            title=html.unescape(title),
            place=places.dach_place(location, *offices),
            text=_clean(html.unescape(content)) if isinstance(content, str) and content.strip() else None,
            created_at=_when(job.get("first_published")) or _when(job.get("updated_at")),
            company=_str(job.get("company_name")),
        )
    return list(positions.values())


def to_result(
    *, slug: str, positions: list[Position], offices: dict[str, dict], fetched_at: dt.datetime,
    company_name: str | None = None, content_hash: str | None = None,
) -> tuple[FetchResult, list[str]]:
    """The snapshot as a `FetchResult`, plus the DACH ids it lists."""
    del offices  # the location is on the job
    return _result(SOURCE_NAME, feed_url(slug), slug, positions, fetched_at, company_name, content_hash,
                   external_id)


def _result(source, request_url, slug, positions, fetched_at, company_name, content_hash, ext_id):
    """Shared by Greenhouse and Lever: one DACH posting per listed job."""
    postings: list[SourcedPosting] = []
    dropped: dict[str, int] = {}
    listed: list[str] = []

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for pos in positions:
        if _NOT_A_JOB.search(pos.title):
            drop("not a vacancy (open application)")
            continue
        place = pos.place
        if place is None:
            drop("not in DACH")
            continue
        ext = ext_id(slug, pos.job_id)
        listed.append(ext)
        employer = pos.company or company_name
        if not employer:
            drop("employer not named")
            continue
        country, city, postal = place["country"], place["city"], place["postal_code"]
        signal = staffing_signal(employer, pos.text)
        postings.append(SourcedPosting(
            external_id=ext,
            title=pos.title,
            company=SourcedCompany(
                name=employer, postal_code=postal, city=city, country=country,
                # Placed only by country: the country is the place.
                area=None if (postal or city) else f"country:{country.lower()}",
            ),
            description=pos.text,
            employment_type=pos.employment_type,
            location_text=" ".join(p for p in (postal, city) if p) or place["label"] or country,
            postal_code=postal,
            city=city,
            country=country,
            posted_at=pos.created_at,
            raw={"board": slug, "id": pos.job_id, "location": place["label"],
                 **({"staffing_signal": signal} if signal else {})},
            segment=PRIVATE_RECRUITER if signal else EMPLOYER,
        ))
    result = FetchResult(
        source=source,
        request_url=request_url,
        fetched_at=fetched_at,
        http_status=200,
        robots_allowed=True,
        postings=postings,
        total_available=len(positions),
        content_hash=content_hash,
        dropped=dropped,
    )
    return result, listed


class GreenhouseAdapter(BoardHttp):
    """One call per board: the Job Board API, with content."""

    name = SOURCE_NAME
    #: 716 KB measured for a 69-job board with content; the largest boards
    #: list hundreds of jobs.
    max_body = 32 * 1024 * 1024

    async def fetch_feed(self, slug: str) -> FeedAnswer:
        return FeedAnswer(*await self._get(feed_url(slug)))
