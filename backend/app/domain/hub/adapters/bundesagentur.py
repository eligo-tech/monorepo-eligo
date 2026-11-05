"""Bundesagentur für Arbeit — Jobsuche API adapter.

The federal employment agency's own job-search backend. It is the widest legal
source of German vacancies (~950k open postings), needs no signup, and returns
records already geocoded, which is why it is the hub's first source.

    GET {base}/pc/v6/jobs?was=&wo=&umkreis=&zeitarbeit=&pav=&page=&size=
    Header: X-API-Key: jobboerse-jobsuche

Two properties shape everything downstream:

  * ``firma`` is a free-text employer name, so the SAME company arrives under
    several spellings ("ARC-GREENLAB GmbH" / "ARC-Greenlab GmbH"). Identity is
    therefore decided by `resolution.identity_key`, never by the string.
  * ``zeitarbeit``/``pav`` exclude temp agencies and private recruiters. Left on,
    roughly 45% of a metro area's postings are staffing firms — competitors, not
    leads — so `SourceQuery.include_staffing` defaults to False. For Eligo's
    OWN sales they are exactly the leads: `SourceQuery.segment =
    "private_recruiter"` asks for `pav=true` only (temp agencies stay out), and
    those rows never reach a recruiter-facing view (`models.EMPLOYER`).

Caveat worth carrying: this endpoint is the real one the agency's own Jobbörse
uses and its client id has been publicly documented for years, but it is
community-documented (bundesAPI/jobsuche-api) rather than a contractual open-data
product with an SLA. Not something to assume is guaranteed.

Terms of use: the BA Nutzungsbedingungen 2a(3) prohibit robots/spiders and
using the interfaces to extract content for data collection and analysis. The
product owner accepted that risk on 2026-11-02 and continues as-is; it is not
resolved. Never describe BA-derived data as licensed or resellable.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime as dt
import hashlib
import json
import re
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.hub.adapters.base import (
    FetchResult,
    SourcedCompany,
    SourcedPosting,
    SourceQuery,
)

logger = get_logger(__name__)

SOURCE_NAME = "bundesagentur"


class SourceUnreachable(Exception):
    """The source did not answer at all — not the same as answering "nothing".

    A per-posting fetch that cannot reach the source must say so: marking the
    posting as attempted would retire it permanently over an outage that lasts
    an afternoon.
    """
_SEARCH_PATH = "/pc/v6/jobs"
# Full ad text lives behind a per-record call, keyed on base64 of the reference
# number. The search endpoint never returns it — which is why the corpus could
# search titles only, and why 95% of TypeScript roles were unfindable.
_DETAIL_PATH = "/pc/v4/jobdetails"


def _parse_dt(value: str | None) -> dt.datetime | None:
    """Parse the API's two shapes: ``2026-08-19`` and ``2026-08-19T07:36:52.251``.

    Returned tz-aware in UTC — the API sends no offset, and a naive datetime
    would compare falsely against the tz-aware timestamps everywhere else.
    """
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def _employment_type(record: dict[str, Any]) -> str | None:
    """Collapse the API's boolean work-time flags into one label."""
    if record.get("arbeitszeitVollzeit"):
        return "full_time"
    if any(
        record.get(key)
        for key in (
            "arbeitszeitTeilzeitFlexibel",
            "arbeitszeitTeilzeitVormittag",
            "arbeitszeitTeilzeitNachmittag",
            "arbeitszeitTeilzeitAbend",
        )
    ):
        return "part_time"
    if record.get("istGeringfuegigeBeschaeftigung"):
        return "mini_job"
    return None


def _location(record: dict[str, Any]) -> dict[str, Any]:
    """Pull the first location. v6 sends ``stellenlokationen``; older shapes
    send a flat ``arbeitsort`` — accept both so a response-format change
    degrades to missing fields rather than an exception."""
    locations = record.get("stellenlokationen") or []
    node = locations[0] if locations else (record.get("arbeitsort") or {})
    address = node.get("adresse") or node
    return {
        "postal_code": address.get("plz"),
        "city": address.get("ort"),
        "region": address.get("region"),
        "country": address.get("land"),
        "latitude": node.get("breite") or address.get("breite"),
        "longitude": node.get("laenge") or address.get("laenge"),
    }


def parse_response(
    payload: dict[str, Any],
    *,
    request_url: str,
    fetched_at: dt.datetime,
    http_status: int | None = 200,
    berufsfeld: str | None = None,
) -> FetchResult:
    """Pure payload → ``FetchResult``. No I/O, no DB — the unit CI exercises.

    ``berufsfeld`` is the field this slice was requested for. The API never
    returns it per record — it appears only in the response facets — so the only
    way a posting can carry one is for the crawler to stamp the shard it came
    from. Passing it here keeps that knowledge attached to the data instead of
    being thrown away at the end of the request.
    """
    records = payload.get("ergebnisliste") or []
    postings: list[SourcedPosting] = []

    for record in records:
        reference = record.get("referenznummer")
        title = (record.get("stellenangebotsTitel") or "").strip()
        employer = (record.get("firma") or "").strip()
        # A record with no reference or no employer cannot be deduplicated or
        # attributed. Dropped here rather than persisted as a nameless company;
        # the ingest summary reports the count so the loss is visible.
        if not reference or not title or not employer:
            continue

        place = _location(record)
        posted_at = _parse_dt(
            record.get("datumErsteVeroeffentlichung")
            or (record.get("veroeffentlichungszeitraum") or {}).get("von")
        )
        city = place["city"]

        postings.append(
            SourcedPosting(
                external_id=str(reference),
                title=title,
                company=SourcedCompany(
                    name=employer,
                    postal_code=place["postal_code"],
                    city=city,
                    region=place["region"],
                    country=place["country"],
                    latitude=place["latitude"],
                    longitude=place["longitude"],
                ),
                occupation=record.get("hauptberuf"),
                berufsfeld=berufsfeld,
                region=place["region"],
                employment_type=_employment_type(record),
                location_text=" ".join(
                    part for part in (place["postal_code"], city) if part
                )
                or None,
                postal_code=place["postal_code"],
                city=city,
                country=place["country"],
                latitude=place["latitude"],
                longitude=place["longitude"],
                remote_possible=record.get("homeofficemoeglich"),
                posted_at=posted_at,
                # The employer's own posting when the agency has one; it is the
                # entry point for upgrading this company to a deep ATS source.
                source_url=record.get("externeURL"),
                raw=record,
            )
        )

    return FetchResult(
        source=SOURCE_NAME,
        request_url=request_url,
        fetched_at=fetched_at,
        http_status=http_status,
        robots_allowed=True,  # documented API, not a scrape
        postings=postings,
        total_available=payload.get("maxErgebnisse"),
        facet_counts=(payload.get("facetten") or {})
        .get("berufsfeld", {})
        .get("counts", {}),
        content_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest(),
    )


def _strip_markup(text: str) -> str:
    """The field is mostly plain text but carries occasional HTML."""
    return re.sub(r"<[^>]+>", " ", text)


class BundesagenturAdapter:
    """`SourceAdapter` over the Jobsuche API."""

    name = SOURCE_NAME

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        user_agent: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or settings.hub_ba_base_url).rstrip("/")
        #: Tests only: lets the liveness calls run against a fake source.
        self._transport = transport
        #: Where a liveness verdict came from — recorded with each closure.
        self.detail_url_template = f"{self._base_url}{_DETAIL_PATH}/{{base64(reference)}}"
        self._api_key = api_key or settings.hub_ba_api_key
        self._timeout = timeout or settings.hub_http_timeout
        self._user_agent = user_agent or settings.hub_user_agent

    def build_params(self, query: SourceQuery) -> dict[str, Any]:
        params: dict[str, Any] = {
            "page": max(1, query.page),
            "size": min(max(1, query.size), 100),  # API caps the page size
        }
        if query.what:
            params["was"] = query.what
        if query.berufsfeld:
            params["berufsfeld"] = query.berufsfeld
        if query.where:
            params["wo"] = query.where
        if query.radius_km is not None:
            params["umkreis"] = query.radius_km
        if query.published_since_days is not None:
            # Only {0, 1, 7, 14, 28} are honoured. Every other value is ignored
            # and the API returns the UNFILTERED set — measured 2026-08-21:
            #   0 → 20,216   1 → 30,098   7 → 78,636
            #   14 → 128,810  28 → 216,462   anything else → 709,734 (all)
            # `IngestRequest` constrains the type so a bad window cannot reach
            # here, but a wrong value would silently cost a full crawl.
            params["veroeffentlichtseit"] = query.published_since_days
        if query.segment == "private_recruiter":
            # Private recruiters only. Temp agencies stay out (decision
            # 2026-11-02); the two sets are disjoint at posting level.
            params["pav"] = "true"
            params["zeitarbeit"] = "false"
        elif not query.include_staffing:
            params["zeitarbeit"] = "false"
            params["pav"] = "false"
        params.update(query.params)
        return params

    async def fetch(self, query: SourceQuery) -> FetchResult:
        url = f"{self._base_url}{_SEARCH_PATH}"
        params = self.build_params(query)
        fetched_at = dt.datetime.now(dt.UTC)
        headers = {"X-API-Key": self._api_key, "User-Agent": self._user_agent}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            # A TRANSPORT failure — the source refusing the connection, timing
            # out, or hanging up mid-response. Same class of event as an HTTP
            # error and handled the same way: returned, not raised, so it lands
            # as an observation saying the source was unreachable.
            #
            # Raising instead turned a source outage into HTTP 500 from our own
            # API: on 2026-10-02 `rest.arbeitsagentur.de` stopped answering and
            # the nightly job spent 49 minutes retrying 57 pages before failing,
            # with nothing in the corpus to say why.
            logger.warning("bundesagentur unreachable: %s for %s", type(exc).__name__, url)
            return FetchResult(
                source=self.name,
                request_url=url,
                fetched_at=fetched_at,
                http_status=None,
                note=f"source unreachable: {type(exc).__name__}",
            )

        if response.status_code != 200:
            logger.warning(
                "bundesagentur fetch failed: HTTP %s for %s",
                response.status_code,
                response.request.url,
            )
            # Returned, not raised: a failed fetch is still evidence and is
            # recorded as an observation with zero records.
            return FetchResult(
                source=self.name,
                request_url=str(response.request.url),
                fetched_at=fetched_at,
                http_status=response.status_code,
                note=f"HTTP {response.status_code}",
            )

        return parse_response(
            response.json(),
            request_url=str(response.request.url),
            fetched_at=fetched_at,
            http_status=response.status_code,
            berufsfeld=query.berufsfeld,
        )

    async def fetch_description(self, external_id: str) -> str | None:
        """Full ad text for one posting. ONE request — call it sparingly.

        Fetching the whole corpus this way would be ~26,000 requests against a
        free public service for ads nobody will place. Callers prioritise by
        saved search, so the text deepens where people actually recruit.
        """
        encoded = base64.b64encode(external_id.encode()).decode()
        url = f"{self._base_url}{_DETAIL_PATH}/{encoded}"
        headers = {"X-API-Key": self._api_key, "User-Agent": self._user_agent}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            # Unreachable is not "no text": the caller must be able to tell a
            # posting with no description from a source that is down, or it
            # stamps the posting as attempted and never asks again.
            raise SourceUnreachable(f"{type(exc).__name__} for {url}") from exc

        if response.status_code != 200:
            logger.info(
                "no detail for %s (HTTP %s)", external_id, response.status_code
            )
            return None
        payload = response.json()
        text = (
            payload.get("stellenbeschreibung")
            or payload.get("stellenangebotsBeschreibung")
            or ""
        )
        cleaned = _strip_markup(text).strip()
        return cleaned or None

    async def fetch_listing(self, *, segment: str, filters: dict[str, str], page: int) -> ListingPage:
        """One page of the FULL listing (no publication window) — references only.

        `filters` are `LISTING_DIMENSIONS` values; the caller validates them.
        """
        params = self.build_params(SourceQuery(segment=segment, page=page, size=100))
        params.update(filters)
        url = f"{self._base_url}{_SEARCH_PATH}"
        headers = {"X-API-Key": self._api_key, "User-Agent": self._user_agent}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise SourceUnreachable(f"{type(exc).__name__} for {url}") from exc
        if response.status_code != 200:
            raise ListingUnavailable(f"HTTP {response.status_code}")
        return parse_listing(response.json())

    async def check_live(self, external_id: str) -> str:
        """Is this ad still listed? "live", "gone" or "unknown" — see
        `liveness_from_response` for what counts as gone."""
        encoded = base64.b64encode(external_id.encode()).decode()
        url = f"{self._base_url}{_DETAIL_PATH}/{encoded}"
        headers = {"X-API-Key": self._api_key, "User-Agent": self._user_agent}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise SourceUnreachable(f"{type(exc).__name__} for {url}") from exc
        return liveness_from_response(response.status_code, response.text)


# ---------------------------------------------------------------------------
# Liveness — is an ad still listed? (`hub/liveness.py`)
# ---------------------------------------------------------------------------

#: Facets a full-listing shard may be split by. Each value of each is a filter
#: the search accepts, measured 2026-11-05 (`berufsfeld=Verkauf…&befristung=3`
#: returned exactly the 73,579 the facet promised). The coordinator only splits
#: by one whose counts SUM to the shard's total — exhaustive, so no ad falls
#: between two values; `arbeitszeit` and `eintrittsdatum` overlap and fail that.
LISTING_DIMENSIONS = ("berufsfeld", "befristung", "angebotsart", "branche", "arbeitszeit")


@dataclasses.dataclass(frozen=True)
class ListingPage:
    """One page of the full listing: which ads exist, not what they say."""

    external_ids: list[str]
    #: Records on the page, with or without a reference — what paging goes by.
    records: int
    total_available: int
    facets: dict[str, dict[str, int]]


def parse_listing(payload: dict) -> ListingPage:
    """Every reference on the page — including records the ingest gate would
    reject for a missing employer. Liveness is about the ad, not the row."""
    facets = payload.get("facetten") or {}
    records = payload.get("ergebnisliste") or []
    return ListingPage(
        external_ids=[str(r["referenznummer"]) for r in records if r.get("referenznummer")],
        records=len(records),
        total_available=int(payload.get("maxErgebnisse") or 0),
        facets={
            dim: dict((facets.get(dim) or {}).get("counts") or {})
            for dim in LISTING_DIMENSIONS
            if dim in facets
        },
    )


#: What the source itself says about a reference it does not have. Measured
#: 2026-11-05: a made-up reference → 404 with this code; 160 of 160 ads on the
#: live listing → 200.
_NOT_FOUND_CODE = "STELLENANGEBOT_NICHT_GEFUNDEN"


def liveness_from_response(status: int, body: str) -> str:
    """The detail page's answer as evidence.

    Gone only when the SOURCE says so: a 404 carrying its own not-found code. A
    bare 404 — a CDN error page, a retired path, a changed key — is about the
    route, not the ad; so is every 5xx, 429 and 403. "unknown" closes nothing.
    """
    if status == 200:
        return "live"
    if status == 404:
        try:
            messages = json.loads(body).get("messages") or []
        except (ValueError, AttributeError):
            return "unknown"
        if any(isinstance(m, dict) and m.get("code") == _NOT_FOUND_CODE for m in messages):
            return "gone"
    return "unknown"


class ListingUnavailable(Exception):
    """The source answered the listing with something other than a page."""
