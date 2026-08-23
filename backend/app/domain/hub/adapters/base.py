"""The source seam: a public source → normalized companies + postings.

Mirrors `documents/extraction`'s `CVExtractor` protocol + factory: callers
depend on `SourceAdapter`, never on a concrete board. Adding StepStone, an ATS
feed, or a CSV import is a new module plus one line in `factory.py`.

Every adapter splits into two halves on purpose:

  * ``fetch``  — does I/O, returns a ``FetchResult``.
  * ``parse``  — a PURE function from a raw payload to that ``FetchResult``.

The split is what makes ingestion testable with no network: the parser is
exercised against a captured response fixture in CI, and only the thin HTTP
wrapper is untested. It also means a payload can be re-parsed later from stored
evidence without re-fetching it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SourceQuery:
    """What to ask a source for. Not every adapter honors every field."""

    what: str | None = None            # keyword / full-text
    where: str | None = None           # city or PLZ
    # Occupational field. The best shard key this source has: 144 values, 99.4%
    # of the daily delta, and — unlike `where` — it never silently resolves to
    # a village that happens to share a state's name.
    berufsfeld: str | None = None
    radius_km: int | None = None
    published_since_days: int | None = None
    page: int = 1
    size: int = 100
    # Staffing agencies and private recruiters are *competitors*, not leads —
    # excluded by default so the corpus is end-employers.
    include_staffing: bool = False
    # Adapter-specific escape hatch (an ATS board token, a feed URL, ...).
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class SourcedCompany:
    """The employer as the source described it — pre-resolution, un-deduplicated."""

    name: str
    website_domain: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    industry: str | None = None


@dataclass
class SourcedPosting:
    """One normalized posting plus the employer it belongs to."""

    external_id: str
    title: str
    company: SourcedCompany
    description: str | None = None
    occupation: str | None = None
    # Stamped from the SHARD, not read from the record — the source never
    # returns it per posting.
    berufsfeld: str | None = None
    region: str | None = None
    employment_type: str | None = None
    location_text: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    remote_possible: bool | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    posted_at: dt.datetime | None = None
    expires_at: dt.datetime | None = None
    source_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    """One retrieval: the evidence header plus the records it yielded."""

    source: str
    request_url: str
    fetched_at: dt.datetime
    http_status: int | None = None
    robots_allowed: bool = True
    postings: list[SourcedPosting] = field(default_factory=list)
    # What the source says exists in total for this query — lets a crawler know
    # how much it has not yet seen, and drives sharding.
    total_available: int | None = None
    content_hash: str | None = None
    note: str | None = None
    # How the source says this result set divides (Bundesagentur: the
    # `berufsfeld` facet). The crawler's shard plan, straight from the API.
    facet_counts: dict[str, int] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    """Turns a query against one public source into normalized postings.

    Pure w.r.t. the database: an adapter reads no state and writes none.
    Deduplication, persistence and verification all happen downstream.
    """

    name: str

    async def fetch(self, query: SourceQuery) -> FetchResult: ...

    # Optional. A source that publishes full ad text behind a per-record call
    # implements this; callers probe with `hasattr` rather than requiring it,
    # because most feeds return everything in the listing.
    async def fetch_description(self, external_id: str) -> str | None: ...
