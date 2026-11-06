"""Personio — employers' own public job feeds, Germany first.

A company that switches on Personio's job feed publishes every open position
at `https://{slug}.jobs.personio.de/xml` — no credentials, intended for other
websites to show (Personio's help centre and developer docs). The company
subdomains' robots.txt say `Allow: /`; `www.jobs.personio.de` (the marketing
host) disallows everything and is never asked. `.de` and `.com` serve the
same board, so the slug is the identity and `.de` is always used.

Measured 2026-11-06:

  * **The feed is a full snapshot** of the board's published positions, with
    the full ad text (median ~3.3 KB) and the employer's name (`subcompany`).
    A job missing from it is closed — no per-ad liveness call is needed.
  * **`office` is a town name with no country or postcode** ("Berlin",
    "Salzburg"). Each job page carries a schema.org JobPosting with the
    office's full postal address, so ONE page per office (cached on the board)
    supplies it. The postcode is what makes BA's copy of the same job the same
    company and the same vacancy — both keys are name/title + postcode.
  * **Not all of it is new.** Of 80 sampled jobs in German cities, 11 were
    found on BA for the same firm (rough name match, an undercount).
  * **Not every position is a job:** "Initiativbewerbung", "Open
    Application" — dropped and counted.

Personio is not the rights holder of the ad text; the employer is. Same class
as BA and EURES text: shown with a link to the employer's board, never
described as licensed.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.hub.adapters.base import FetchResult, SourcedCompany, SourcedPosting, SourceUnreachable
from app.domain.hub.adapters.eures import staffing_signal
from app.domain.hub.models import EMPLOYER, PRIVATE_RECRUITER

logger = get_logger(__name__)

SOURCE_NAME = "personio"
HOST = "jobs.personio.de"

#: schema.org addressCountry → the corpus spelling (BA's `land`), which is
#: also what the vacancy key's postcode is scoped by.
COUNTRIES = {"DE": "DEUTSCHLAND", "AT": "OESTERREICH", "CH": "SCHWEIZ"}

#: Positions that are an invitation, not a vacancy.
_NOT_A_JOB = re.compile(
    r"initiativbewerbung|blindbewerbung|spontanbewerbung|open application|"
    r"unsolicited application|speculative application|talent ?pool|"
    r"general application|candidature spontan",
    re.IGNORECASE,
)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
_JOB_ID = re.compile(r"^[0-9]{1,20}$")


def valid_slug(slug: str) -> bool:
    return bool(_SLUG.match(slug or ""))


def feed_url(slug: str) -> str:
    return f"https://{slug}.{HOST}/xml?language=de"


def job_url(slug: str, job_id: str) -> str:
    return f"https://{slug}.{HOST}/job/{quote(job_id, safe='')}?language=de"


def external_id(slug: str, job_id: str) -> str:
    """Unique across boards: "<slug>:<position id>"."""
    return f"{slug}:{job_id}"


# ---------------------------------------------------------------------------
# Parsing — pure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Position:
    job_id: str
    title: str
    office: str | None
    company: str | None
    text: str | None
    employment_type: str | None
    created_at: dt.datetime | None


class FeedUnreadable(Exception):
    """A 200 that is not the feed (an HTML error page, a truncated body)."""


def _clean(markup: str) -> str:
    text = re.sub(r"<(?:br|/p|/li|/div|/h\d)\s*/?>", "\n", markup, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]*$", " ", re.sub(r"<[^>]+>", " ", text))  # and a cut-off tag
    text = html.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def _when(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


_EMPLOYMENT = {"permanent": "full_time", "full-time": "full_time", "fulltime": "full_time",
               "part-time": "part_time", "parttime": "part_time"}


def parse_feed(body: bytes | str) -> list[Position]:
    """Every position in the feed. Raises `FeedUnreadable` for anything that
    is not a `<workzag-jobs>` document — an empty list must mean "no jobs"."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise FeedUnreadable(str(exc)) from exc
    if root.tag != "workzag-jobs":
        raise FeedUnreadable(f"root <{root.tag}>")
    positions: list[Position] = []
    seen: set[str] = set()
    for node in root.findall("position"):
        job_id = (node.findtext("id") or "").strip()
        title = (node.findtext("name") or "").strip()
        # Personio ids are numbers; anything else (or a repeat) is not a row we
        # can key — a duplicate would break the (source, external_id) constraint.
        if not _JOB_ID.match(job_id) or not title or job_id in seen:
            continue
        seen.add(job_id)
        sections = []
        for desc in node.iter("jobDescription"):
            head = (desc.findtext("name") or "").strip()
            body_text = _clean(desc.findtext("value") or "")
            if body_text:
                sections.append(f"{head}\n{body_text}" if head else body_text)
        schedule = (node.findtext("schedule") or "").strip().lower()
        positions.append(Position(
            job_id=job_id,
            title=title,
            office=(node.findtext("office") or "").strip() or None,
            company=(node.findtext("subcompany") or "").strip() or None,
            text="\n\n".join(sections) or None,
            employment_type=_EMPLOYMENT.get(schedule),
            created_at=_when(node.findtext("createdAt")),
        ))
    return positions


_LD_JSON = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)
#: The page's own app data (Next.js flight chunks: a JS string literal holding
#: JSON) lists every office of the job with its postal address. Present on
#: every page measured; the schema.org block is missing on newer templates.
_OFFICE_KEY = '\\"office_addresses\\":'
_COMPANY_NAME = re.compile(r'\\"careerSiteSettings\\":\{\\"company_name\\":\\"((?:[^"\\]|\\.)*?)\\"')
_JS_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}


def _array_after(page: str, key: str, limit: int = 200_000) -> str | None:
    """The JSON array that follows `key` inside a JS string literal, decoded.

    Decodes the literal's escapes as it goes and matches brackets outside JSON
    strings, so a "]" in a street name or a nested array cannot cut it short.
    None when the key is absent or the array does not close within `limit`.
    """
    at = page.find(key)
    if at < 0:
        return None
    i, out, depth, in_string, escaped = at + len(key), [], 0, False, False
    end = min(len(page), i + limit)
    while i < end:
        ch = page[i]
        if ch == "\\":  # a JS escape: decode it
            nxt = page[i + 1] if i + 1 < end else ""
            if nxt == "u" and i + 6 <= end:
                ch, i = chr(int(page[i + 2:i + 6], 16)), i + 6
            else:
                ch, i = _JS_ESCAPES.get(nxt, nxt), i + 2
        else:
            i += 1
        out.append(ch)
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return "".join(out)
        elif depth == 0 and not ch.isspace():
            return None  # not an array
    return None


def _text(value: Any) -> str | None:
    return (str(value).strip() or None) if value else None  # " Salzburg" happens


def _address(street, postal, city, region, country) -> dict[str, Any]:
    return {
        "street": _text(street), "postal_code": _text(postal), "city": _text(city),
        "region": _text(region), "country": (_text(country) or "").upper() or None,
    }


def _unescape(literal: str) -> str:
    """A JS string literal's body → its text (the chunk is JSON inside a string)."""
    return json.loads(f'"{literal}"')


def parse_job_page(page: str) -> dict[str, Any]:
    """Office addresses and the employer's name from one job page.

    `{"offices": {office name: address}, "employer": name}`. A schema.org
    address has no office name and comes back under "" for the caller to key.
    `offices` is empty when the page names none.
    """
    offices: dict[str, dict] = {}
    employer: str | None = None
    array = _array_after(page, _OFFICE_KEY)
    if array:
        try:
            for item in json.loads(array):
                if isinstance(item, dict) and _text(item.get("name")):
                    offices[_text(item["name"])] = _address(
                        item.get("street"), item.get("zip_code"), item.get("city"),
                        item.get("state"), item.get("country"),
                    )
        except ValueError:
            offices = {}
    for block in _LD_JSON.finditer(page):
        try:
            data = json.loads(block.group(1))
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict) or item.get("@type") != "JobPosting":
                continue
            employer = employer or _text((item.get("hiringOrganization") or {}).get("name"))
            if offices:
                continue
            location = item.get("jobLocation")
            location = location[0] if isinstance(location, list) and location else location
            address = (location or {}).get("address") if isinstance(location, dict) else None
            if isinstance(address, dict):
                country = address.get("addressCountry")
                country = country.get("name") if isinstance(country, dict) else country
                # One location, no office name: the caller keys it to the office
                # it asked about.
                offices[""] = _address(
                    address.get("streetAddress"), address.get("postalCode"),
                    address.get("addressLocality"), address.get("addressRegion"), country,
                )
    if employer is None:
        named = _COMPANY_NAME.search(page)
        if named:
            try:
                employer = _text(_unescape(named.group(1)))
            except ValueError:
                employer = None
    return {"offices": offices, "employer": employer}


_FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "AE", "Ö": "OE", "Ü": "UE"})


def region_code(region: str | None) -> str | None:
    """"Baden-Württemberg" → BADEN_WUERTTEMBERG: the Bundesagentur's spelling,
    so the Markt filter treats both sources as one."""
    if not region:
        return None
    return re.sub(r"[^A-Z]+", "_", region.translate(_FOLD).upper()).strip("_") or None


def to_result(
    *, slug: str, positions: list[Position], offices: dict[str, dict], fetched_at: dt.datetime,
    company_name: str | None = None, content_hash: str | None = None,
) -> tuple[FetchResult, list[str]]:
    """The snapshot as a `FetchResult`, plus the DACH ids it lists.

    The id list is what the next snapshot diffs against — every DACH position,
    including ones the gate may reject later: closing is about the BOARD no
    longer listing a job, not about whether we stored it.
    """
    postings: list[SourcedPosting] = []
    dropped: dict[str, int] = {}
    listed: list[str] = []

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for pos in positions:
        if _NOT_A_JOB.search(pos.title):
            drop("not a vacancy (open application)")
            continue
        address = offices.get(pos.office or "") or {}
        country = COUNTRIES.get(address.get("country") or "")
        if country is None:
            drop("office outside DACH or without an address")
            continue
        ext = external_id(slug, pos.job_id)
        listed.append(ext)
        employer = pos.company or company_name
        if not employer:
            drop("employer not named")
            continue
        signal = staffing_signal(employer, pos.text)
        city = address.get("city") or pos.office
        postal = address.get("postal_code")
        region = region_code(address.get("region"))
        postings.append(SourcedPosting(
            external_id=ext,
            title=pos.title,
            company=SourcedCompany(
                name=employer, street=address.get("street"), postal_code=postal, city=city,
                region=region, country=country,
            ),
            description=pos.text,
            region=region,
            employment_type=pos.employment_type,
            location_text=" ".join(p for p in (postal, city) if p) or None,
            postal_code=postal,
            city=city,
            country=country,
            posted_at=pos.created_at,
            raw={"board": slug, "id": pos.job_id, "office": pos.office,
                 **({"staffing_signal": signal} if signal else {})},
            segment=PRIVATE_RECRUITER if signal else EMPLOYER,
        ))
    result = FetchResult(
        source=SOURCE_NAME,
        request_url=feed_url(slug),
        fetched_at=fetched_at,
        http_status=200,
        robots_allowed=True,  # every company subdomain: "Allow: /"
        postings=postings,
        total_available=len(positions),
        content_hash=content_hash,
        dropped=dropped,
    )
    return result, listed


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


#: Larger than any feed measured (~125 KB for 29 jobs) by two orders.
MAX_BODY = 10 * 1024 * 1024
#: Status for a body over `MAX_BODY`: read as a failure, never as a feed.
TOO_LARGE = 599


@dataclass(frozen=True)
class FeedAnswer:
    status: int
    body: bytes

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.body).hexdigest()


class PersonioAdapter:
    """Two calls: a board's feed, and one job page per new office."""

    name = SOURCE_NAME

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
        """Status and body, the body read no further than `MAX_BODY`."""
        try:
            async with self._client() as client, client.stream("GET", url) as response:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BODY:
                        return TOO_LARGE, b""
                return response.status_code, bytes(body)
        except httpx.HTTPError as exc:
            raise SourceUnreachable(f"{type(exc).__name__} for {url}") from exc

    async def fetch_feed(self, slug: str) -> FeedAnswer:
        return FeedAnswer(*await self._get(feed_url(slug)))

    async def fetch_job_page(self, slug: str, job_id: str) -> str | None:
        status, body = await self._get(job_url(slug, job_id))
        return body.decode("utf-8", errors="replace") if status == 200 else None
