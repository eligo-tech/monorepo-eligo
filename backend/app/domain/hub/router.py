"""Information-hub API — shared corpus reads, tenant overlay, ingest trigger.

On authentication: corpus endpoints need no tenant to be *correct* (the data is
the same for everyone), but they still require a valid session, because the
corpus is an asset — the thing a shared/paywalled plan would gate. So the tenant
dependency stays on every route; it simply no longer filters the query. Where it
genuinely selects rows is the overlay routes below.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant, get_ingest_tenant
from app.core.database import get_db
from app.domain.hub import liveness, service
from app.domain.hub.adapters.factory import available_sources, get_source_adapter
from app.domain.hub.gate import PreconditionFailed
from app.domain.searches import service as searches_service
from app.domain.searches.schemas import CrawlProfile
from app.domain.hub.schemas import (
    AddBoardsRequest,
    AtsName,
    ListingRequest,
    ListingResponse,
    LivenessSource,
    MarkRequest,
    AdoptCompanyRequest,
    AgencyDetail,
    AgencyPage,
    AgencyProfileRead,
    AdoptCompanyResult,
    CompanyContacts,
    HubJobPostingHit,
    HubSearchPage,
    QueryCorrection,
    DescriptionFetchRequest,
    HubCompanyLinkRead,
    HubCorpusStats,
    HubEmployerHit,
    HubFacets,
    HubCompanyRead,
    HubJobPostingRead,
    HubObservationRead,
    IngestRequest,
    IngestSummary,
    TrackRequest,
)

router = APIRouter(prefix="/hub", tags=["hub"])


@router.get("/sources")
async def list_sources(
    _tenant_id: uuid.UUID = Depends(get_current_tenant),
) -> dict[str, list[str]]:
    """Which public sources this build can ingest from.

    Authenticated, like everything else. The answer is build metadata rather
    than anybody's data, but "harmless to leak" is a judgement that ages
    badly — the next field added to a public endpoint is the one that is not.
    """
    return {"sources": available_sources()}


# --------------------------------------------------------------------------
# Corpus (shared)
# --------------------------------------------------------------------------


@router.get("/stats", response_model=HubCorpusStats)
async def hub_stats(
    _tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> HubCorpusStats:
    """Corpus totals. Counted in the DB so the UI stops describing its own page."""
    return HubCorpusStats.model_validate(await service.corpus_stats(db))


@router.get("/facets", response_model=HubFacets)
async def hub_facets(
    _tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> HubFacets:
    """Available filter values with counts, taken from the corpus."""
    return HubFacets.model_validate(await service.corpus_facets(db))


#: A result this thin is indistinguishable from a failed search, so it earns a
#: second attempt with a corrected query. Four employers, not zero: a typo can
#: still collide with a handful of rows — two of 360,126 ads spell it
#: "Pflegefachkaft" — and those two would otherwise suppress the rescue.
_THIN_RESULT = 4


@router.get("/search", response_model=HubSearchPage)
async def search_hub_employers(
    q: str | None = Query(default=None, description="name, city, role or occupation"),
    city: str | None = None,
    region: list[str] | None = Query(default=None, description="Bundesland; repeatable"),
    berufsfeld: list[str] | None = Query(default=None, description="repeatable"),
    family: list[Literal["tech"]] | None = Query(
        default=None, description="job family (hub/families.py): tech = software, data, IT, product, design"
    ),
    min_roles: int = Query(default=0, ge=0),
    min_relevance: int = Query(
        default=1,
        ge=1,
        le=4,
        description="1 = any mention, 3 = the title names it, 4 = the title names every term",
    ),
    limit: int = Query(default=40, ge=1, le=200),
    cursor: str | None = Query(
        default=None, description="opaque; from a previous page's next_cursor"
    ),
    correct: bool = Query(
        default=True,
        description="retry a near-empty search with the corpus's own spelling",
    ),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> HubSearchPage:
    """Search the corpus and return employers, rolled up across their sites.

    This is the recruiter-facing entry point. The unrolled `/hub/companies`
    listing stays for tooling and debugging, but a directory of 13,851 rows —
    hundreds of which are the same discounter once per branch — is not a surface
    anyone can work with.
    """
    async def page(query: str | None) -> tuple[list[dict], int]:
        found = await service.search_employers(
            db,
            q=query,
            city=city,
            regions=region,
            berufsfelder=berufsfeld,
            families=family,
            min_roles=min_roles,
            limit=limit,
            cursor=cursor,
            min_relevance=min_relevance,
        )
        # Counted once, on the first page only: it does not change as the
        # reader pages, and it is a second aggregate over the same set.
        counted = (
            await service.count_employers(
                db,
                q=query,
                city=city,
                regions=region,
                berufsfelder=berufsfeld,
                families=family,
                min_relevance=min_relevance,
            )
            if cursor is None
            else 0
        )
        return found, counted

    hits, total = await page(q)

    # Spelling is checked AFTER the search, never before: resolving every term
    # up front cost 76–300 ms on searches that were already working, and this
    # screen's failure mode is a timeout.
    #
    # Two triggers, because a thin answer alone is not enough. "muenchen"
    # returns 298 employers with München in their NAME and misses the 2,973 in
    # the city — a confident-looking answer to the wrong question. So any word
    # that has another umlaut spelling is re-checked whatever the count, and
    # everything else only when the answer was thin enough to be a failure.
    corrections: list[dict] = []
    if (
        correct
        and cursor is None
        and (total <= _THIN_RESULT or service.query_may_be_misspelt(q))
    ):
        corrected, corrections = await service.resolve_query(db, q)
        if corrections:
            retried, retried_total = await page(corrected)
            if retried_total > total:
                hits, total = retried, retried_total
            else:
                corrections = []  # the other spelling was no better; say nothing

    tracked = await service.tracked_company_ids(db, tenant_id=tenant_id)
    out: list[HubEmployerHit] = []
    for hit in hits:
        item = HubEmployerHit.model_validate(
            {
                **hit,
                "matching_roles": [
                    HubJobPostingHit.model_validate(r) for r in hit["matching_roles"]
                ],
            }
        )
        # An employer counts as tracked when ANY of its sites is.
        item.tracked = any(cid in tracked for cid in hit["hub_company_ids"])
        out.append(item)
    return HubSearchPage(
        items=out,
        total=total,
        # A short page is the last page; a full one may or may not be, and
        # offering a cursor that returns nothing is cheaper than a count per page.
        next_cursor=service.encode_cursor(hits[-1]) if len(hits) == limit else None,
        corrections=[QueryCorrection(**c) for c in corrections],
    )


@router.get("/companies", response_model=list[HubCompanyRead])
async def list_hub_companies(
    q: str | None = Query(default=None, description="name substring"),
    city: str | None = None,
    hiring_only: bool = Query(default=False, description="only companies with open roles"),
    tracked_only: bool = Query(default=False, description="only ones this tenant tracks"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[HubCompanyRead]:
    rows = await service.list_companies(
        db, q=q, city=city, hiring_only=hiring_only, limit=limit, offset=offset
    )
    # One extra query annotates the shared rows with this tenant's own view,
    # instead of pushing tenant_id back into the corpus tables.
    tracked = await service.tracked_company_ids(db, tenant_id=tenant_id)
    out = []
    for row in rows:
        item = HubCompanyRead.model_validate(row)
        item.tracked = row.id in tracked
        if tracked_only and not item.tracked:
            continue
        out.append(item)
    return out


@router.get("/companies/{hub_company_id}", response_model=HubCompanyRead)
async def get_hub_company(
    hub_company_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> HubCompanyRead:
    row = await service.get_company(db, hub_company_id=hub_company_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "hub company not found")
    item = HubCompanyRead.model_validate(row)
    item.tracked = row.id in await service.tracked_company_ids(db, tenant_id=tenant_id)
    return item


@router.get(
    "/companies/{hub_company_id}/postings", response_model=list[HubJobPostingRead]
)
async def list_company_postings(
    hub_company_id: uuid.UUID,
    active_only: bool = True,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[HubJobPostingRead]:
    company = await service.get_company(db, hub_company_id=hub_company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "hub company not found")
    rows = await service.list_postings(
        db,
        hub_company_id=hub_company_id,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return [HubJobPostingRead.model_validate(r) for r in rows]


@router.get("/postings", response_model=list[HubJobPostingRead])
async def list_hub_postings(
    q: str | None = Query(default=None, description="title substring"),
    city: str | None = None,
    source: str | None = None,
    active_only: bool = True,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[HubJobPostingRead]:
    rows = await service.list_postings(
        db,
        q=q,
        city=city,
        source=source,
        active_only=active_only,
        limit=limit,
        offset=offset,
    )
    return [HubJobPostingRead.model_validate(r) for r in rows]


@router.get("/observations", response_model=list[HubObservationRead])
async def list_hub_observations(
    limit: int = Query(default=50, ge=1, le=200),
    _tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[HubObservationRead]:
    """The evidence ledger: every fetch the corpus was built from."""
    rows = await service.list_observations(db, limit=limit)
    return [HubObservationRead.model_validate(r) for r in rows]


# --------------------------------------------------------------------------
# Overlay (tenant-scoped) — where the tenant genuinely selects rows
# --------------------------------------------------------------------------


@router.post(
    "/companies/{hub_company_id}/adopt",
    response_model=AdoptCompanyResult,
    status_code=status.HTTP_201_CREATED,
)
async def adopt_hub_company(
    hub_company_id: uuid.UUID,
    payload: AdoptCompanyRequest | None = None,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> AdoptCompanyResult:
    """Take a corpus company into this workspace, optionally with a contact.

    The crossing from shared observation to system-of-record, so it goes through
    the verification gate and leaves a receipt — see `service.adopt_company`.
    """
    try:
        company, link, manager = await service.adopt_company(
            db,
            tenant_id=tenant_id,
            hub_company_id=hub_company_id,
            manager=(
                payload.manager.model_dump() if payload and payload.manager else None
            ),
        )
    except service.AlreadyAdopted as exc:
        # 409, not 400: the request was well-formed and the state is the
        # objection. The caller wants the existing id, not a validation lecture.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"already adopted as company {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return AdoptCompanyResult(
        company_id=company.id,
        company_name=company.name,
        hub_company_id=link.hub_company_id,
        manager_id=manager.id if manager else None,
        art14_outstanding=bool(manager and manager.art14_outstanding),
    )


@router.get("/links", response_model=list[HubCompanyLinkRead])
async def list_hub_links(
    relationship: str | None = None,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[HubCompanyLinkRead]:
    """This tenant's view of the corpus: what they watch, prospect, or ignore."""
    rows = await service.list_links(db, tenant_id=tenant_id, relationship=relationship)
    return [HubCompanyLinkRead.model_validate(r) for r in rows]


@router.get("/companies/{hub_company_id}/contacts", response_model=CompanyContacts)
async def get_company_contacts(
    hub_company_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CompanyContacts:
    """People this employer's public ads name as contacts, with the ad lines.

    A read over ad texts already in the corpus — it fetches nothing and
    stores nothing. Saving a person is `adopt` (with a manager) or
    `POST /managers`, both explicit.
    """
    result = await service.company_contacts(
        db, tenant_id=tenant_id, hub_company_id=hub_company_id
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "hub company not found")
    return CompanyContacts.model_validate(result)


@router.put(
    "/companies/{hub_company_id}/track", response_model=HubCompanyLinkRead
)
async def track_hub_company(
    hub_company_id: uuid.UUID,
    payload: TrackRequest,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> HubCompanyLinkRead:
    """Mark this tenant's interest in a corpus company. Idempotent.

    Leaves no receipt: noting interest asserts nothing about the record. Adoption
    into `companies` is the crossing that does.
    """
    if await service.get_company(db, hub_company_id=hub_company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "hub company not found")
    link = await service.track_company(
        db,
        tenant_id=tenant_id,
        hub_company_id=hub_company_id,
        relationship=payload.relationship,
        note=payload.note,
    )
    return HubCompanyLinkRead.model_validate(link)


@router.delete(
    "/companies/{hub_company_id}/track", status_code=status.HTTP_204_NO_CONTENT
)
async def untrack_hub_company(
    hub_company_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Drop the overlay row. The corpus company itself is untouched — it is not
    this tenant's to delete."""
    removed = await service.untrack_company(
        db, tenant_id=tenant_id, hub_company_id=hub_company_id
    )
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not tracked")


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------


@router.get("/crawl-profiles", response_model=list[CrawlProfile])
async def list_crawl_profiles(
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
) -> list[CrawlProfile]:
    """Crawl directives for the nightly job — the union of saved searches.

    Operator endpoint, machine-authenticated. Deliberately returns only
    `(q, city, radius_km)`: the crawler learns WHAT to fetch, never WHO asked.
    Search terms are competitive intelligence and must not leak between
    workspaces, even though the postings they surface land in the shared corpus.

    Deduplicated, so three workspaces watching "SAP Berater" cost one crawl.
    """
    return await searches_service.list_crawl_profiles()


@router.post("/crawl-profiles/mark-crawled")
async def mark_profiles_crawled(
    profiles: list[CrawlProfile],
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
) -> dict[str, int]:
    """Stamp `last_crawled_at` after the nightly job has fetched these."""
    return {"updated": await searches_service.mark_crawled(profiles)}


@router.post("/descriptions/fetch")
async def fetch_descriptions(
    payload: DescriptionFetchRequest | None = None,
    limit: int = Query(default=200, ge=1, le=2000),
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Fill in ad text for postings that have none. Machine-only (RULE 1).

    Ordered by the union of saved searches, so the corpus gains full text where
    people actually recruit rather than uniformly across ads nobody will place.
    """
    profiles = await searches_service.list_crawl_profiles()
    terms = sorted({t for p in profiles for t in p.q.lower().split() if len(t) > 2})
    result = await service.fetch_missing_descriptions(
        db, adapter=get_source_adapter("bundesagentur"), limit=limit,
        priority_terms=terms,
        external_ids=payload.external_ids if payload else None,
        segment=payload.segment if payload else None,
    )
    return {**result, **await service.descriptions_progress(db)}


@router.post("/partner-pages/fetch")
async def fetch_partner_pages(
    # Small by default: each page is a paced request, and the whole batch runs
    # inside one HTTP call a proxy may time out. The nightly script loops.
    limit: int = Query(default=25, ge=1, le=200),
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Read partner-board pages behind `source_url`. Machine-only (RULE 1).

    One page per posting, robots.txt respected, paced per host; watched
    employers first. See `adapters/partner_pages.py` for what is skipped and why.
    """
    from app.domain.hub.adapters.partner_pages import PartnerPageFetcher

    async with PartnerPageFetcher() as fetcher:
        result = await service.fetch_missing_partner_pages(
            db, fetcher=fetcher, limit=limit
        )
    return {**result, **await service.partner_pages_progress(db)}


@router.get("/descriptions/progress")
async def descriptions_progress(
    _tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """How much of the corpus is searchable by its text."""
    return await service.descriptions_progress(db)


@router.post("/maintenance/expire-stale")
async def expire_stale_postings(
    days: int = Query(default=14, ge=1, le=365),
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Close postings no crawl has seen for `days`.

    Operator endpoint, run by the nightly job — not a user action. A delta crawl
    cannot observe a removal; only the absence of a posting over time can, which
    is what `last_seen_at` tracks.
    """
    return await service.deactivate_stale_postings(db, older_than_days=days)


# --------------------------------------------------------------------------
# Liveness — machine-only (RULE 1): the nightly job closes ads the source took
# down. A suspect from the listing, a verdict only from the ad's own page.
# --------------------------------------------------------------------------


@router.post("/liveness/listing", response_model=ListingResponse)
async def liveness_listing(
    payload: ListingRequest,
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
) -> ListingResponse:
    """One page of the source's full listing: which references exist. No write."""
    from app.domain.hub.adapters.base import InvalidQuery, ListingUnavailable, SourceUnreachable

    adapter = get_source_adapter(payload.source)
    if not hasattr(adapter, "fetch_listing"):
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "source has no full listing")
    try:
        page = await adapter.fetch_listing(
            segment=payload.segment, filters=dict(payload.filters), page=payload.page
        )
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except (SourceUnreachable, ListingUnavailable) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"listing unavailable: {exc}") from exc
    return ListingResponse(
        external_ids=page.external_ids,
        records=page.records,
        total_available=page.total_available,
        facets=page.facets,
    )


@router.get("/liveness/active")
async def liveness_active(
    segment: Literal["employer", "private_recruiter"] = "employer",
    source: LivenessSource = "bundesagentur",
    after: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=20_000, ge=1, le=50_000),
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Our open ads in reference order, with "already a suspect", keyset-paged."""
    rows = await liveness.active_ids(db, segment=segment, after=after, limit=limit, source=source)
    return {"ids": rows, "next": rows[-1][0] if len(rows) == limit else None}


@router.post("/liveness/mark")
async def liveness_mark(
    payload: MarkRequest,
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Record one listing's result: suspects in, relisted ads out."""
    return await liveness.mark(
        db, segment=payload.segment, unlisted=payload.unlisted, listed=payload.listed,
        source=payload.source,
    )


@router.post("/liveness/check")
async def liveness_check(
    limit: int = Query(default=25, ge=1, le=100),
    source: LivenessSource = "bundesagentur",
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ask the source about up to `limit` due suspects; close those it says
    it does not have. Bounded to ~60 s so it stays inside the caller's timeout."""
    adapter = get_source_adapter(source)
    if not hasattr(adapter, "check_live"):
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "source cannot check an ad")
    return await liveness.check_batch(db, adapter=adapter, limit=limit)


@router.post("/ats/boards")
async def add_ats_boards(
    payload: AddBoardsRequest,
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Record board slugs a discovery pass found. Machine-only (RULE 1)."""
    from app.domain.hub import ats

    return await ats.add_boards(db, ats=payload.ats, slugs=payload.slugs, discovered_via=payload.discovered_via)


@router.post("/ats/sync")
async def sync_ats_boards(
    limit: int = Query(default=20, ge=1, le=100),
    ats_name: AtsName = Query(default="personio", alias="ats"),
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Read up to `limit` due boards' feeds and merge them. Machine-only (RULE
    1): an outbound read of employers' public boards, ~60 s per request."""
    from app.domain.hub import ats

    return await ats.sync_due(db, adapter=ats.adapter_for(ats_name), limit=limit)


@router.post("/job-families/backfill")
async def job_families_backfill(
    limit: int = Query(default=5_000, ge=1, le=10_000),
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Label up to `limit` older open ads tech/other. Machine-only: a bounded
    corpus write the nightly job spreads over nights (disk-IO budget)."""
    from app.domain.hub import families

    return await families.backfill(db, limit=limit)


@router.post("/vacancy-keys/backfill")
async def vacancy_keys_backfill(
    limit: int = Query(default=5_000, ge=1, le=10_000),
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Key up to `limit` open ads that predate `vacancy_key`. Machine-only: a
    bounded write the nightly job spreads over nights (disk-IO budget)."""
    from app.domain.hub import vacancy

    return await vacancy.backfill(db, limit=limit)


@router.post(
    "/ingest", response_model=IngestSummary, status_code=status.HTTP_201_CREATED
)
async def ingest_slice(
    payload: IngestRequest,
    # Machine-or-human: a scheduled backfill presents a service token, a
    # recruiter refreshing from the UI presents their Clerk JWT. Either way the
    # WRITE lands in the shared corpus, not in the caller's tenant.
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> IngestSummary:
    """Ingest ONE crawl slice into the shared corpus.

    Deliberately synchronous and slice-sized: safe to point a scheduler at,
    individually auditable via its observation, and needs no worker.
    """
    try:
        adapter = get_source_adapter(payload.source)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    from app.domain.hub.adapters.base import InvalidQuery

    try:
        return await service.ingest(db, adapter=adapter, request=payload)
    except InvalidQuery as exc:
        # Refused before any request: a question this source cannot answer.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except PreconditionFailed as exc:
        # A blocking precondition (robots/ToS refusal, non-200 source) — the
        # observation recording the refusal is already committed.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"ingest precondition failed: {exc}"
        ) from exc


# --------------------------------------------------------------------------
# Agency finder — Eligo's own business development
# --------------------------------------------------------------------------
# Private recruiters are competitors to every customer. These routes answer
# only the workspaces on `agency_finder_tenants`, and 404 — not 403 — to
# everyone else, so their existence is not advertised either.


def require_agency_finder(tenant_id: uuid.UUID = Depends(get_current_tenant)) -> uuid.UUID:
    from app.core.config import settings

    allowed = {p.strip() for p in settings.agency_finder_tenants.split(",") if p.strip()}
    if str(tenant_id) not in allowed:  # empty allowlist: nobody
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    return tenant_id


def _profile_read(profile) -> AgencyProfileRead:
    return AgencyProfileRead.model_validate(
        {
            **{c: getattr(profile, c) for c in AgencyProfileRead.model_fields if c != "branches"},
            "branches": len(profile.company_ids),
        }
    )


@router.post("/agencies/refresh")
async def refresh_agency_profiles(
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Rebuild the agency finder's profiles from the corpus. Machine-only
    (RULE 1): the nightly job calls it after the private-recruiter pass."""
    from app.domain.hub import agencies

    return await agencies.refresh_profiles(db)


@router.post("/agencies/sites/check")
async def check_agency_sites(
    limit: int = Query(default=5, ge=1, le=50),
    _tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Verify agency website candidates through their Impressum. Machine-only
    (RULE 1): the nightly job calls it in small batches."""
    from app.domain.hub import sites

    async with sites.SiteFetcher() as fetcher:
        return await sites.check_agency_sites(db, fetcher=fetcher, limit=limit)


@router.get("/agencies", response_model=AgencyPage)
async def list_agencies(
    verdict: list[str] = Query(default=["agency", "unclear"]),
    region: str | None = None,
    berufsfeld: str | None = None,
    include_chains: bool = Query(default=False, description="firms over 50 open ads"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _tenant_id: uuid.UUID = Depends(get_current_tenant),
    _allowed: uuid.UUID = Depends(require_agency_finder),
    db: AsyncSession = Depends(get_db),
) -> AgencyPage:
    """Agencies as leads, best first. Clients are hidden unless asked for."""
    from app.domain.hub import agencies

    rows = await agencies.list_profiles(
        db,
        verdicts=verdict,
        region=region,
        berufsfeld=berufsfeld,
        include_chains=include_chains,
        limit=limit,
        offset=offset,
    )
    return AgencyPage(items=[_profile_read(r) for r in rows], limit=limit, offset=offset)


@router.get("/agencies/{agency_id}", response_model=AgencyDetail)
async def get_agency(
    agency_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    _allowed: uuid.UUID = Depends(require_agency_finder),
    db: AsyncSession = Depends(get_db),
) -> AgencyDetail:
    """One agency: its branches, its ads, and the contacts its ads name."""
    from app.domain.hub import agencies

    profile = await agencies.get_profile(db, agency_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    detail = await agencies.profile_detail(db, tenant_id=tenant_id, profile=profile)
    return AgencyDetail(
        profile=_profile_read(profile),
        branches=[HubCompanyRead.model_validate(b) for b in detail["branches"]],
        postings=[HubJobPostingRead.model_validate(p) for p in detail["postings"]],
        contacts=CompanyContacts.model_validate(detail["contacts"]),
    )


@router.post(
    "/agencies/{agency_id}/adopt",
    response_model=AdoptCompanyResult,
    status_code=status.HTTP_201_CREATED,
)
async def adopt_agency(
    agency_id: uuid.UUID,
    payload: AdoptCompanyRequest | None = None,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    _allowed: uuid.UUID = Depends(require_agency_finder),
    db: AsyncSession = Depends(get_db),
) -> AdoptCompanyResult:
    """Take an agency into this workspace's CRM as a lead — the same gated,
    receipted crossing as adopting an employer."""
    from app.domain.hub import agencies
    from app.domain.hub.models import PRIVATE_RECRUITER

    profile = await agencies.get_profile(db, agency_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not found")
    try:
        company, link, manager = await service.adopt_company(
            db,
            tenant_id=tenant_id,
            hub_company_id=profile.primary_company_id,
            manager=payload.manager.model_dump() if payload and payload.manager else None,
            kind=PRIVATE_RECRUITER,
        )
    except service.AlreadyAdopted as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"already adopted as company {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return AdoptCompanyResult(
        company_id=company.id,
        company_name=company.name,
        hub_company_id=link.hub_company_id,
        manager_id=manager.id if manager else None,
        art14_outstanding=bool(manager and manager.art14_outstanding),
    )
