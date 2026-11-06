"""EURES — the European job-mobility portal's own search backend, Austria and Switzerland.

EURES relays the public employment services' vacancies: in Austria almost all
come from the AMS (connection point 43), in Switzerland from SECO's job-room
(61). The portal's search is an undocumented JSON API, the one its own pages
call:

    POST https://europa.eu/eures/api/jv-searchengine/public/jv-search/search
    GET  https://europa.eu/eures/api/jv-searchengine/public/jv/id/{id}?lang=de

Measured 2026-11-06, and every number below shapes the code:

  * **10,000 results per query.** `resultsPerPage` is at most 50 and `page`
    past 200 answers HTTP 400. Austria holds 61,804 ads, Switzerland 27,791.
  * **Regions shard both countries completely.** `locationCodes` takes a
    country ("at"), a NUTS2 region ("at31") or the region facet's own
    "no region" bucket ("at-NS", 359 ads). The 10 Austrian and 8 Swiss buckets
    hold every ad; only Oberösterreich (15,401) is over the cap, and its NACE
    sections (`sectorCodes`) sum to it exactly.
  * **No town, no postcode.** An ad carries a NUTS code (`AT130`, `CH040`) at
    best. Region is the finest place there is, so the vacancy key cannot merge
    by place: in Vienna, 131 groups of same employer + same title had
    different ad text in 130 cases — different branches, not copies.
  * **Two-thirds of AMS ads hide the employer.** "siehe Beschreibung" in 1,337
    of 2,000 Vienna ads; the firm is named only in the free text. Identity is
    deterministic (RULE 5), so those ads are dropped and counted, never filed
    under a guessed employer.
  * **Connection point 1 is the Bundesagentur.** Its ads carry BA references
    (`10001-1003958088-S`) and BA is already their source, with liveness.
    Dropped and counted.
  * **No staffing filter.** BA has `zeitarbeit`/`pav`; EURES has nothing. Each
    ad is classified by `staffing_signal` below, deterministic and
    documented, and an agency's ad goes to the `private_recruiter` segment —
    never shown as an employer. Measured on 4,000 ads, see the rule.
  * **Gone is the source's own word.** A withdrawn id answers 404 with
    `se.jv.error.notAvailable`; 20 of 20 listed ads answered 200.

Terms: the portal permits re-use with acknowledgement of the source
("Quelle: EURES / ELA", shown next to every ad link). Commercial use is not
stated either way; the product owner accepted that risk on 2026-11-06, as for
BA. Never describe EURES-derived data as licensed or resellable.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import html
import json
import re
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.hub.adapters.base import (
    FetchResult,
    InvalidQuery,
    ListingPage,
    ListingUnavailable,
    SourcedCompany,
    SourcedPosting,
    SourceQuery,
    SourceUnreachable,
)
from app.domain.hub.models import EMPLOYER, PRIVATE_RECRUITER

logger = get_logger(__name__)

SOURCE_NAME = "eures"
BASE_URL = "https://europa.eu/eures"
_SEARCH_PATH = "/api/jv-searchengine/public/jv-search/search"
_DETAIL_PATH = "/api/jv-searchengine/public/jv/id"
#: The portal's own page for one ad, for the "Anzeige" link.
PORTAL_URL = BASE_URL + "/portal/jv-se/jv-details/{id}?lang=de"

PAGE_SIZE = 50
PAGE_CEILING = 200

# ---------------------------------------------------------------------------
# Places — spelled as the Bundesagentur spells them, so one filter covers both
# ---------------------------------------------------------------------------

#: Country code → the corpus spelling (BA writes "OESTERREICH" for its own
#: Austrian ads; one spelling means one facet).
COUNTRIES = {"at": "OESTERREICH", "ch": "SCHWEIZ"}

#: Austria's NUTS2 regions are its Bundesländer.
_AT_STATES = {
    "at11": "BURGENLAND", "at12": "NIEDEROESTERREICH", "at13": "WIEN",
    "at21": "KAERNTEN", "at22": "STEIERMARK", "at31": "OBEROESTERREICH",
    "at32": "SALZBURG", "at33": "TIROL", "at34": "VORARLBERG",
}
#: Switzerland's NUTS2 are seven "Grossregionen"; the canton is NUTS3.
_CH_REGIONS = ("ch01", "ch02", "ch03", "ch04", "ch05", "ch06", "ch07")
_CH_CANTONS = {
    "ch011": "WAADT", "ch012": "WALLIS", "ch013": "GENF", "ch021": "BERN",
    "ch022": "FREIBURG", "ch023": "SOLOTHURN", "ch024": "NEUENBURG", "ch025": "JURA",
    "ch031": "BASEL_STADT", "ch032": "BASEL_LANDSCHAFT", "ch033": "AARGAU",
    "ch040": "ZUERICH", "ch051": "GLARUS", "ch052": "SCHAFFHAUSEN",
    "ch053": "APPENZELL_AUSSERRHODEN", "ch054": "APPENZELL_INNERRHODEN",
    "ch055": "ST_GALLEN", "ch056": "GRAUBUENDEN", "ch057": "THURGAU",
    "ch061": "LUZERN", "ch062": "URI", "ch063": "SCHWYZ", "ch064": "OBWALDEN",
    "ch065": "NIDWALDEN", "ch066": "ZUG", "ch070": "TESSIN",
}
#: Every location bucket the crawl reads: each region plus "no region". Together
#: they hold every ad of the two countries (measured, see the module doc).
REGIONS: tuple[str, ...] = (
    *sorted(_AT_STATES), "at-NS", *_CH_REGIONS, "ch-NS",
)
_LOCATIONS = frozenset({*COUNTRIES, *REGIONS})
#: NACE Rev. 2.1 sections A–V plus the facet's "not stated" bucket. "v" is
#: real: the 2026-11-06 Austrian facet held one ad there.
SECTORS: tuple[str, ...] = (*"abcdefghijklmnopqrstuv", "NS")
#: Published windows the search has. `IngestRequest` only lets 0/1/7/14/28
#: through; the rest are refused here rather than widened to "everything".
_WINDOWS = {0: "LAST_DAY", 1: "LAST_DAY", 7: "LAST_WEEK"}

#: Listing filters the liveness coordinator may split by.
LISTING_DIMENSIONS = ("region", "sector")


def region_name(nuts: str | None) -> str | None:
    """`AT130` → "WIEN", `CH040` → "ZUERICH"; None for a code finer or coarser
    than we can name (a Swiss Grossregion spans several cantons)."""
    if not nuts:
        return None
    code = nuts.lower()
    if code.startswith("at"):
        return _AT_STATES.get(code[:4])
    if code.startswith("ch"):
        return _CH_CANTONS.get(code[:5]) or ("TESSIN" if code[:4] == "ch07" else None)
    return None


def _country_of(location: str | None) -> str | None:
    return location[:2] if location and location[:2] in COUNTRIES else None


# ---------------------------------------------------------------------------
# Staffing — EURES has no flag, so the ad is classified here
# ---------------------------------------------------------------------------

#: Words in a firm's NAME that mark staffing or placement in AT/CH. Narrower
#: than `agency_rank.STAFFING_NAME` on purpose: that one ranks ads already
#: known to be private-recruiter ads, this one sorts EVERY ad, and "consult",
#: "talent" or "search" in an employer's name is not evidence.
_STAFFING_NAME = re.compile(
    r"personal|personnel|überlassung|ueberlassung|zeitarbeit|temporär|temporaer|"
    r"\bint[eé]rim|staffing|recruit|headhunt|"
    # Placement only: "Versicherungsvermittlung" is a broker, an employer.
    r"(?:personal|arbeits|stellen|job)vermittlung|human resources|"
    r"ressources humaines|\bjob|job\b|\bhr\b",
    re.IGNORECASE,
)
#: An intermediary writing about THE firm it recruits for — singular only.
#: Measured on 4,000 ads: the plural ("für unsere Kunden", "im Auftrag unserer
#: Kunden") is how Kistler, ti&m, Transgourmet or Intrum describe their own
#: customers, and "Personalverleih"/"Arbeitskräfteüberlassung" turn up in
#: employers' ads too ("kein Personalverleih"). Not `agency_rank._CLIENT_PHRASE`:
#: that one runs on ads already known to be an agency's.
_PLACEMENT_PHRASE = re.compile(
    r"\bfür unseren (?:kunden|mandanten|klienten)\b|"
    r"\bunser(?:em)? (?:kunde|mandant|klient)\b|"
    r"\bunseres (?:kunden|mandanten|klienten)\b|"
    r"\bim auftrag (?:unseres|eines) (?:kunden|mandanten|klienten)\b|"
    r"\bunser(?:e|er)? (?:kundin|auftraggeberin|mandantin)\b|"
    r"\bunser(?:em|en)? auftraggeber\b|"
    r"\bfür (?:einen|eine) (?:kunden|kundin|betrieb|firma)\b|"
    r"\bfür ein unternehmen (?:in|im|aus)\b|"
    # Romandie and Ticino agencies, same singular rule.
    r"\bpour (?:le compte d')?(?:notre|un de nos|une de nos) client(?:e)?\b|"
    r"\bnotre client(?:e)? (?:est|recherche|cherche)\b|"
    r"\bper (?:un|una) (?:nostro|nostra) client[ea]\b|"
    r"\bil nostro cliente\b",
    re.IGNORECASE,
)
#: Staffing firms whose names carry no staffing word. Literal and short: each
#: was seen in the 2026-11-06 sample of 4,000 ads with ads classified as an
#: employer's, or named in the brief (Hays, Brunel, Michael Page, Randstad,
#: Adecco, Robert Half, tempster, Flexsis). "group" so ManpowerGroup matches.
_STAFFING_BRANDS = re.compile(
    r"^(?:hays|brunel|michael page|page personnel|randstad|adecco|manpower|"
    r"robert half|trenkwalder|tempster|flexsis|synergie|powerserv|akzente|"
    r"lesaco|kelly services|kelly$|gi group|experis|universal-job|coople|"
    r"asanti|workplacex|swiss link|premiumjob|consult & pepper|seiro|"
    r"stellentreff|academic work|aw_deutschschweiz|itech consult|swisslinx|"
    r"persigo|tempobrain|freestar-people|humanis|impirio|undivi|studirach|"
    r"stettler consulting|quantuvia|workmanagement|adsenvia|swissteda|"
    r"univativ|colibri people|albedis|hotelis|bigawin)(?:\b|group\b)",
    re.IGNORECASE,
)


def staffing_signal(employer: str, text: str | None) -> str | None:
    """Why this ad is an agency's — or None for an employer's own.

    Plain code, and the reason is returned so a row can say why it is where it
    is. Measured on 4,000 Vienna and Zürich ads (see the PR): what it misses
    goes in as an employer, which the module doc states as the gap.
    """
    if _STAFFING_BRANDS.search(employer.strip()):
        return "brand"
    if _STAFFING_NAME.search(employer):
        return "name"
    if text and _PLACEMENT_PHRASE.search(text):
        return "text"
    return None


# ---------------------------------------------------------------------------
# Parsing — pure
# ---------------------------------------------------------------------------

#: Employer "names" that say the name is elsewhere. Compared case-folded.
_UNNAMED = {"siehe beschreibung", "siehe inserat", "siehe stellenbeschreibung",
            "siehe text", "anonym", "chiffre", "see description"}
#: The Bundesagentur's connection point: its ads are BA's, crawled there.
_BA_CONNECTION_POINT = "1"


#: Hosts that serve MANY employers' ads. As a "website" they would merge
#: every employer using them into one company on the domain rung. None was
#: seen in 4,000 sampled ads (all 27 hosts were the firm's own); a guard.
_SHARED_HOSTS = re.compile(
    r"(?:^|\.)(?:personio\.(?:de|com)|join\.com|jobs\.ch|jobup\.ch|karriere\.at|"
    r"ams\.at|softgarden\.(?:io|de)|greenhouse\.io|lever\.co|recruitee\.com|"
    r"smartrecruiters\.com|workday\.com|myworkdayjobs\.com|successfactors\.\w+|"
    r"stepstone\.\w+|indeed\.\w+|linkedin\.com|xing\.com|arbeitsagentur\.de|"
    r"job-room\.ch|europa\.eu)$",
    re.IGNORECASE,
)


def employer_website(url: str | None) -> str | None:
    """The employer's own site, or None for a host many employers share."""
    if not url:
        return None
    host = re.sub(r"^[a-z]+://", "", url.strip().lower()).split("/")[0].split(":")[0]
    return None if not host or _SHARED_HOSTS.search(host) else url


def connection_point(ad_id: str) -> str | None:
    """The relaying service, from the id: base64 of "<reference> <point>"."""
    try:
        decoded = base64.b64decode(ad_id + "=" * (-len(ad_id) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    parts = decoded.rsplit(" ", 1)
    return parts[1] if len(parts) == 2 else None


def clean_text(text: str | None) -> str | None:
    """Ad text as a reader would see it. SECO ships markdown with entities
    escaped twice (`&amp;amp;`) and a page header; AMS ships plain HTML."""
    if not text:
        return None
    for _ in range(2):
        text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^---.*?---", " ", text, flags=re.DOTALL)  # SECO page metadata
    text = re.sub(r"\\([\\&*_\-#()\[\]])", r"\1", text)      # markdown escapes
    text = re.sub(r"[ \t ⁠]+", " ", text)
    return text.strip() or None


def _when(millis: Any) -> dt.datetime | None:
    if not isinstance(millis, (int, float)):
        return None
    return dt.datetime.fromtimestamp(millis / 1000, tz=dt.UTC)


def _employment_type(codes: list[str] | None) -> str | None:
    codes = codes or []
    if "fulltime" in codes:
        return "full_time"
    if "parttime" in codes:
        return "part_time"
    return None


def _place(record: dict[str, Any], location: str | None) -> tuple[str | None, str | None]:
    """(country, region), the same whichever bucket returned the ad.

    A multi-country ad ({"DE", "AT", "CH"}) is returned by both countries'
    buckets. Choosing by bucket would give it two identities (an empty
    company row per re-read), so the choice is fixed: Austria before
    Switzerland, then the bucket's country as a fallback.
    """
    listed = {c.lower() for c in (record.get("locationMap") or {})}
    country = next((c for c in sorted(COUNTRIES) if c in listed), None) or _country_of(location)
    if country is None:
        return None, None
    codes = (record.get("locationMap") or {}).get(country.upper()) or []
    region = next((region_name(c) for c in codes if region_name(c)), None)
    if region is None and location and location[:2] == country:
        region = region_name(location)  # the query's own region, when it has a name
    return COUNTRIES[country], region


def parse_response(
    payload: dict[str, Any],
    *,
    request_url: str,
    fetched_at: dt.datetime,
    http_status: int | None = 200,
    location: str | None = None,
) -> FetchResult:
    """Pure payload → `FetchResult`. `location` is the bucket asked for."""
    postings: list[SourcedPosting] = []
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    for record in payload.get("jvs") or []:
        ad_id = record.get("id")
        title = (record.get("title") or "").strip()
        employer = record.get("employer") or {}
        name = (employer.get("name") or "").strip()
        if not ad_id or not title:
            drop("no id or title")
            continue
        if connection_point(ad_id) == _BA_CONNECTION_POINT:
            drop("relayed from the Bundesagentur")
            continue
        if not name or re.sub(r"[^\w ]+", "", name).strip().casefold() in _UNNAMED:
            drop("employer not named")
            continue
        country, region = _place(record, location)
        description = clean_text(record.get("description"))
        signal = staffing_signal(name, description)
        raw = {k: v for k, v in record.items() if k not in ("description", "translations")}
        if signal:
            raw["staffing_signal"] = signal
        postings.append(
            SourcedPosting(
                external_id=ad_id,
                title=title,
                company=SourcedCompany(
                    name=name,
                    website_domain=employer_website(employer.get("website")),
                    # Name + region is the identity rung for an employer with
                    # no website; the region is no town, so not `city`.
                    area=f"region:{country}:{region or '-'}".lower(),
                    region=region,
                    country=country,
                ),
                description=description,
                region=region,
                employment_type=_employment_type(record.get("positionScheduleCodes")),
                country=country,
                posted_at=_when(record.get("creationDate")),
                raw=raw,
                segment=PRIVATE_RECRUITER if signal else EMPLOYER,
            )
        )

    return FetchResult(
        source=SOURCE_NAME,
        request_url=request_url,
        fetched_at=fetched_at,
        http_status=http_status,
        robots_allowed=True,  # the portal's own API, not a page scrape
        postings=postings,
        total_available=payload.get("numberRecords"),
        facet_counts=_facet(payload, "NACE_CODE"),
        dropped=dropped,
        content_hash=hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest(),
    )


def _facet(payload: dict, name: str) -> dict[str, int]:
    entries = ((payload.get("facets") or {}).get(name) or {}).get("facetEntriesList") or []
    return {e["code"]: int(e["count"]) for e in entries if e.get("count")}


def _region_facet(payload: dict) -> dict[str, int]:
    """Counts per location bucket of OUR two countries — the shard plan."""
    entries = ((payload.get("facets") or {}).get("POSITION_LOCATION") or {}).get("facetEntriesList") or []
    counts: dict[str, int] = {}
    for entry in entries:
        if entry.get("code") in COUNTRIES:
            for child in entry.get("childrenList") or []:
                if child.get("code") in _LOCATIONS and child.get("count"):
                    counts[child["code"]] = int(child["count"])
    return counts


def parse_listing(payload: dict) -> ListingPage:
    """Every id on the page — relays and unnamed employers too: liveness is
    about the ad, and an id we never stored simply matches nothing."""
    records = payload.get("jvs") or []
    return ListingPage(
        external_ids=[r["id"] for r in records if r.get("id")],
        records=len(records),
        total_available=int(payload.get("numberRecords") or 0),
        facets={"region": _region_facet(payload), "sector": _facet(payload, "NACE_CODE")},
    )


_NOT_FOUND = "se.jv.error.notAvailable"


def liveness_from_response(status: int, body: str) -> str:
    """Gone only on a 404 carrying the portal's own not-found message."""
    if status == 200:
        return "live"
    if status == 404:
        try:
            parsed = json.loads(body)
        except ValueError:
            return "unknown"
        if isinstance(parsed, dict) and parsed.get("errorMessage") == _NOT_FOUND:
            return "gone"
    return "unknown"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def build_body(
    *, location: str | None, sector: str | None, window: str | None, page: int, size: int = PAGE_SIZE
) -> dict[str, Any]:
    """The search body. Validated first: an unknown region would come back as
    an empty page, which reads exactly like "no ads"."""
    if location is not None and location not in _LOCATIONS:
        raise InvalidQuery(f"unknown EURES location {location!r}; one of {sorted(_LOCATIONS)}")
    if sector is not None and sector not in SECTORS:
        raise InvalidQuery(f"unknown NACE section {sector!r}")
    if not 1 <= page <= PAGE_CEILING:
        raise InvalidQuery(f"page {page}: the search answers pages 1–{PAGE_CEILING}")
    return {
        "resultsPerPage": min(max(1, size), PAGE_SIZE),
        "page": page,
        "sortSearch": "MOST_RECENT",
        "keywords": [],
        "publicationPeriod": window,
        "occupationUris": [], "skillUris": [], "requiredExperienceCodes": [],
        "positionScheduleCodes": [], "educationAndQualificationLevelCodes": [],
        "positionOfferingCodes": [], "euresFlagCodes": [], "otherBenefitsCodes": [],
        "requiredLanguages": [], "minNumberPost": None,
        "sectorCodes": [sector] if sector else [],
        # Never wider than our two countries.
        "locationCodes": [location] if location else sorted(COUNTRIES),
        "sessionId": "eligolabs-hub",
    }


class EuresAdapter:
    """`SourceAdapter` over the EURES search, scoped to Austria and Switzerland."""

    name = SOURCE_NAME

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        user_agent: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or BASE_URL).rstrip("/")
        self._timeout = timeout or settings.hub_http_timeout
        self._user_agent = user_agent or settings.hub_user_agent
        #: Tests only: lets every call run against a fake source.
        self._transport = transport
        #: Where a liveness verdict came from — recorded with each closure.
        self.detail_url_template = f"{self._base_url}{_DETAIL_PATH}/{{id}}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport,
            headers={"User-Agent": self._user_agent},
        )

    def query_body(self, query: SourceQuery) -> dict[str, Any]:
        if query.segment != EMPLOYER:
            # Agencies are sorted per ad (`staffing_signal`); the source has no
            # agency-only listing to ask for.
            raise InvalidQuery("EURES has no agency listing; ask for segment 'employer'")
        if query.published_since_days is None:
            window = None
        elif query.published_since_days in _WINDOWS:
            window = _WINDOWS[query.published_since_days]
        else:
            raise InvalidQuery(f"EURES has no {query.published_since_days}-day window (1 or 7)")
        return build_body(
            location=query.where, sector=query.sector, window=window,
            page=query.page, size=query.size,
        )

    async def _search(self, body: dict[str, Any]) -> httpx.Response:
        async with self._client() as client:
            return await client.post(f"{self._base_url}{_SEARCH_PATH}", json=body)

    async def fetch(self, query: SourceQuery) -> FetchResult:
        body = self.query_body(query)
        url = f"{self._base_url}{_SEARCH_PATH}"
        request_url = f"{url}?location={query.where or 'at,ch'}&sector={query.sector or ''}&page={query.page}"
        fetched_at = dt.datetime.now(dt.UTC)
        try:
            response = await self._search(body)
        except httpx.HTTPError as exc:
            logger.warning("eures unreachable: %s", type(exc).__name__)
            return FetchResult(
                source=self.name, request_url=request_url, fetched_at=fetched_at,
                http_status=None, note=f"source unreachable: {type(exc).__name__}",
            )
        if response.status_code != 200:
            logger.warning("eures fetch failed: HTTP %s", response.status_code)
            return FetchResult(
                source=self.name, request_url=request_url, fetched_at=fetched_at,
                http_status=response.status_code, note=f"HTTP {response.status_code}",
            )
        return parse_response(
            response.json(), request_url=request_url, fetched_at=fetched_at,
            http_status=200, location=query.where,
        )

    async def fetch_listing(self, *, segment: str, filters: dict[str, str], page: int) -> ListingPage:
        """One page of the full listing (no window). `segment` is ignored: the
        source lists every ad, and the agency split is ours."""
        unknown = set(filters) - set(LISTING_DIMENSIONS)
        if unknown:
            raise InvalidQuery(f"EURES listing splits by {LISTING_DIMENSIONS}, not {sorted(unknown)}")
        body = build_body(
            location=filters.get("region"), sector=filters.get("sector"), window=None, page=page
        )
        try:
            response = await self._search(body)
        except httpx.HTTPError as exc:
            raise SourceUnreachable(f"{type(exc).__name__} for the EURES search") from exc
        if response.status_code != 200:
            raise ListingUnavailable(f"HTTP {response.status_code}")
        return parse_listing(response.json())

    async def check_live(self, external_id: str) -> str:
        """"live", "gone" or "unknown" — see `liveness_from_response`."""
        url = f"{self._base_url}{_DETAIL_PATH}/{external_id}"
        try:
            async with self._client() as client:
                response = await client.get(url, params={"lang": "de"})
        except httpx.HTTPError as exc:
            raise SourceUnreachable(f"{type(exc).__name__} for {url}") from exc
        return liveness_from_response(response.status_code, response.text)
