"""Ashby — employers' own public job boards, DACH jobs only.

A company on Ashby publishes every listed job at
`https://api.ashbyhq.com/posting-api/job-board/{slug}` — Ashby's documented
public posting API for career sites, no credentials. Its board page
`jobs.ashbyhq.com/{slug}` is allowed by robots.txt (only `/api/`, `/b/` and
`/meeting/` are disallowed there; the API host has no robots.txt).

Measured 2026-11-08, 581 DACH jobs on 15 boards of 600 sampled:

  * **The answer is a full snapshot** with the full ad text (`descriptionPlain`)
    and `publishedAt`, so a job missing from it is closed, as for Personio.
  * **Each job carries its own address**: country 99%, town 98%, postcode
    74%, street 72%. No job page is needed.
  * **No company name in the API.** The board page's `<title>` is
    "<Company> Jobs" — read once per board and kept on it.
  * **Most boards are not in DACH** (~5% of live ones have a DACH job), and a
    remote job may list 25+ countries. A job counts when its primary location
    is in DACH, or a secondary one names a DACH town; DACH as one country in a
    remote list is not a DACH job.
  * Big boards are big: 13 MB for 816 jobs (OpenAI), hence the 32 MB cap.

Ashby is not the rights holder of the ad text; the employer is. Shown with a
link to the employer's board, never described as licensed.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from app.domain.hub.adapters.base import FetchResult, SourcedCompany, SourcedPosting
from app.domain.hub.adapters.boards import BoardHttp, FeedAnswer, FeedUnreadable
from app.domain.hub.adapters.eures import staffing_signal
from app.domain.hub.adapters.personio import _NOT_A_JOB, _clean, region_code
from app.domain.hub.models import EMPLOYER, PRIVATE_RECRUITER

SOURCE_NAME = "ashby"
API = "https://api.ashbyhq.com/posting-api/job-board"
BOARD = "https://jobs.ashbyhq.com"
#: Most boards have no DACH job; such a board is looked at monthly.
ELSEWHERE_REFRESH = dt.timedelta(days=30)

#: addressCountry / a location naming only a country → the corpus spelling.
_COUNTRIES = {
    "germany": "DEUTSCHLAND", "deutschland": "DEUTSCHLAND", "de": "DEUTSCHLAND",
    "austria": "OESTERREICH", "österreich": "OESTERREICH", "oesterreich": "OESTERREICH", "at": "OESTERREICH",
    "switzerland": "SCHWEIZ", "schweiz": "SCHWEIZ", "suisse": "SCHWEIZ", "svizzera": "SCHWEIZ", "ch": "SCHWEIZ",
}
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_JOB_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_TITLE = re.compile(r"<title>\s*(.*?)\s+Jobs\s*</title>", re.IGNORECASE | re.DOTALL)
_EMPLOYMENT = {"fulltime": "full_time", "parttime": "part_time"}


def valid_slug(slug: str) -> bool:
    return bool(_SLUG.match(slug or ""))


def feed_url(slug: str) -> str:
    return f"{API}/{quote(slug, safe='')}"


def board_url(slug: str) -> str:
    return f"{BOARD}/{quote(slug, safe='')}"


def job_url(slug: str, job_id: str) -> str:
    return f"{board_url(slug)}/{quote(job_id, safe='')}"


def external_id(slug: str, job_id: str) -> str:
    """Unique across boards: "<slug>:<job id>"."""
    return f"{slug}:{job_id}"


# ---------------------------------------------------------------------------
# Parsing — pure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    job_id: str
    title: str
    #: The DACH place this job counts at, or None when it has none.
    place: dict[str, Any] | None
    text: str | None
    employment_type: str | None
    created_at: dt.datetime | None
    workplace: str | None
    #: Ashby jobs carry their address; there is no office to resolve.
    office: None = None
    company: None = None


def _str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _country(value: Any) -> str | None:
    return _COUNTRIES.get((_str(value) or "").lower())


def _place(entry: dict) -> dict[str, Any] | None:
    """One location entry → a DACH place, or None when it is not in DACH."""
    address = ((entry.get("address") or {}).get("postalAddress") or {}) if isinstance(entry, dict) else {}
    # The location label is read only when it names a country: a town alone
    # ("Berlin") without an address is rare (country is on 99% of jobs) and
    # guessing its country from the name is not worth a wrong match.
    country = _country(address.get("addressCountry")) or _country(entry.get("location"))
    if country is None:
        return None
    return {
        "country": country,
        "city": _str(address.get("addressLocality")),
        "postal_code": _str(address.get("postalCode")),
        "street": _str(address.get("streetAddress")),
        "region": _str(address.get("addressRegion")),
        "label": _str(entry.get("location")),
    }


def dach_place(job: dict) -> dict[str, Any] | None:
    """Where in DACH this job is: its primary location, or else the first
    secondary location that names a DACH town. A country alone in a remote
    list does not make a job a DACH job."""
    primary = _place(job)
    if primary:
        return primary
    for entry in job.get("secondaryLocations") or []:
        place = _place(entry) if isinstance(entry, dict) else None
        if place and place["city"]:
            return place
    return None


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
    """Every listed job. Raises `FeedUnreadable` for anything that is not the
    posting API's answer, so a broken 200 is never read as an empty board."""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise FeedUnreadable(f"not JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise FeedUnreadable("no jobs list")
    positions: dict[str, Position] = {}
    for job in data["jobs"]:
        if not isinstance(job, dict) or job.get("isListed") is False:
            continue
        job_id, title = _str(job.get("id")), _str(job.get("title"))
        if not job_id or not title or not _JOB_ID.match(job_id):
            continue
        text = _str(job.get("descriptionPlain")) or (
            _clean(job["descriptionHtml"]) if isinstance(job.get("descriptionHtml"), str) else None
        )
        positions[job_id] = Position(
            job_id=job_id,
            title=html.unescape(title),
            place=dach_place(job),
            text=text,
            employment_type=_EMPLOYMENT.get((_str(job.get("employmentType")) or "").lower()),
            created_at=_when(job.get("publishedAt")),
            workplace=_str(job.get("workplaceType")),
        )
    return list(positions.values())


def parse_company_name(page: str) -> str | None:
    """"<title>n8n Jobs</title>" → "n8n"."""
    match = _TITLE.search(page or "")
    name = html.unescape(match.group(1)).strip() if match else ""
    return name[:300] or None


def to_result(
    *, slug: str, positions: list[Position], offices: dict[str, dict], fetched_at: dt.datetime,
    company_name: str | None = None, content_hash: str | None = None,
) -> tuple[FetchResult, list[str]]:
    """The snapshot as a `FetchResult`, plus the DACH ids it lists (the base
    of the next diff — listed, whether or not the gate stores it)."""
    del offices  # Ashby jobs carry their own address
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
        ext = external_id(slug, pos.job_id)
        listed.append(ext)
        if not company_name:
            drop("employer not named")
            continue
        country, city, postal = place["country"], place["city"], place["postal_code"]
        region = region_code(place["region"]) if country == "DEUTSCHLAND" else None
        signal = staffing_signal(company_name, pos.text)
        postings.append(SourcedPosting(
            external_id=ext,
            title=pos.title,
            company=SourcedCompany(
                name=company_name, street=place["street"], postal_code=postal, city=city,
                region=region, country=country,
                # A job placed only by country: the country is the place, so
                # the identity never borrows another source's town.
                area=None if (postal or city) else f"country:{country.lower()}",
            ),
            description=pos.text,
            region=region,
            employment_type=pos.employment_type,
            location_text=" ".join(p for p in (postal, city) if p) or place["label"] or country,
            postal_code=postal,
            city=city,
            country=country,
            posted_at=pos.created_at,
            raw={"board": slug, "id": pos.job_id, "location": place["label"], "workplace": pos.workplace,
                 **({"staffing_signal": signal} if signal else {})},
            segment=PRIVATE_RECRUITER if signal else EMPLOYER,
        ))
    result = FetchResult(
        source=SOURCE_NAME,
        request_url=feed_url(slug),
        fetched_at=fetched_at,
        http_status=200,
        robots_allowed=True,  # the API host has no robots.txt; Ashby documents it as public
        postings=postings,
        total_available=len(positions),
        content_hash=content_hash,
        dropped=dropped,
    )
    return result, listed


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


class AshbyAdapter(BoardHttp):
    """Two calls: a board's posting API answer, and its board page once for
    the company's name."""

    name = SOURCE_NAME
    max_body = 32 * 1024 * 1024

    async def fetch_feed(self, slug: str) -> FeedAnswer:
        return FeedAnswer(*await self._get(feed_url(slug)))

    async def fetch_company_name(self, slug: str) -> str | None:
        status, body = await self._get(board_url(slug))
        return parse_company_name(body.decode("utf-8", errors="replace")) if status == 200 else None
