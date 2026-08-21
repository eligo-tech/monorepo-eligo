"""Information-hub API — shared corpus reads, tenant overlay, ingest trigger.

On authentication: corpus endpoints need no tenant to be *correct* (the data is
the same for everyone), but they still require a valid session, because the
corpus is an asset — the thing a shared/paywalled plan would gate. So the tenant
dependency stays on every route; it simply no longer filters the query. Where it
genuinely selects rows is the overlay routes below.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant, get_ingest_tenant
from app.core.database import get_db
from app.domain.hub import service
from app.domain.hub.adapters.factory import available_sources, get_source_adapter
from app.domain.hub.gate import PreconditionFailed
from app.domain.hub.schemas import (
    HubCompanyLinkRead,
    HubCompanyRead,
    HubJobPostingRead,
    HubObservationRead,
    IngestRequest,
    IngestSummary,
    TrackRequest,
)

router = APIRouter(prefix="/hub", tags=["hub"])


@router.get("/sources")
async def list_sources() -> dict[str, list[str]]:
    """Which public sources this build can ingest from."""
    return {"sources": available_sources()}


# --------------------------------------------------------------------------
# Corpus (shared)
# --------------------------------------------------------------------------


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


@router.get("/links", response_model=list[HubCompanyLinkRead])
async def list_hub_links(
    relationship: str | None = None,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[HubCompanyLinkRead]:
    """This tenant's view of the corpus: what they watch, prospect, or ignore."""
    rows = await service.list_links(db, tenant_id=tenant_id, relationship=relationship)
    return [HubCompanyLinkRead.model_validate(r) for r in rows]


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

    try:
        return await service.ingest(db, adapter=adapter, request=payload)
    except PreconditionFailed as exc:
        # A blocking precondition (robots/ToS refusal, non-200 source) — the
        # observation recording the refusal is already committed.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"ingest precondition failed: {exc}"
        ) from exc
