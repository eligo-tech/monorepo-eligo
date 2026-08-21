"""Information-hub API — corpus reads plus the ingest trigger."""

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
    HubCompanyRead,
    HubJobPostingRead,
    HubObservationRead,
    IngestRequest,
    IngestSummary,
)

router = APIRouter(prefix="/hub", tags=["hub"])


@router.get("/sources")
async def list_sources() -> dict[str, list[str]]:
    """Which public sources this build can ingest from."""
    return {"sources": available_sources()}


@router.get("/companies", response_model=list[HubCompanyRead])
async def list_hub_companies(
    q: str | None = Query(default=None, description="name substring"),
    city: str | None = None,
    hiring_only: bool = Query(default=False, description="only companies with open roles"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[HubCompanyRead]:
    rows = await service.list_companies(
        db,
        tenant_id=tenant_id,
        q=q,
        city=city,
        hiring_only=hiring_only,
        limit=limit,
        offset=offset,
    )
    return [HubCompanyRead.model_validate(r) for r in rows]


@router.get("/companies/{hub_company_id}", response_model=HubCompanyRead)
async def get_hub_company(
    hub_company_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> HubCompanyRead:
    row = await service.get_company(
        db, tenant_id=tenant_id, hub_company_id=hub_company_id
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "hub company not found")
    return HubCompanyRead.model_validate(row)


@router.get(
    "/companies/{hub_company_id}/postings", response_model=list[HubJobPostingRead]
)
async def list_company_postings(
    hub_company_id: uuid.UUID,
    active_only: bool = True,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[HubJobPostingRead]:
    company = await service.get_company(
        db, tenant_id=tenant_id, hub_company_id=hub_company_id
    )
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "hub company not found")
    rows = await service.list_postings(
        db,
        tenant_id=tenant_id,
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
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[HubJobPostingRead]:
    rows = await service.list_postings(
        db,
        tenant_id=tenant_id,
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
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[HubObservationRead]:
    """The evidence ledger: every fetch this tenant's corpus was built from."""
    rows = await service.list_observations(db, tenant_id=tenant_id, limit=limit)
    return [HubObservationRead.model_validate(r) for r in rows]


@router.post(
    "/ingest", response_model=IngestSummary, status_code=status.HTTP_201_CREATED
)
async def ingest_slice(
    payload: IngestRequest,
    # Machine-or-human: a scheduled backfill presents a service token, a
    # recruiter refreshing from the UI presents their Clerk JWT.
    tenant_id: uuid.UUID = Depends(get_ingest_tenant),
    db: AsyncSession = Depends(get_db),
) -> IngestSummary:
    """Ingest ONE crawl slice. A backfill is many of these, driven externally.

    Deliberately synchronous and slice-sized: it keeps the endpoint safe to point
    a scheduler at, makes each run individually auditable via its observation,
    and needs no worker infrastructure.
    """
    try:
        adapter = get_source_adapter(payload.source)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    try:
        return await service.ingest(
            db, tenant_id=tenant_id, adapter=adapter, request=payload
        )
    except PreconditionFailed as exc:
        # A blocking precondition (robots/ToS refusal, non-200 source) — the
        # observation recording the refusal is already committed.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"ingest precondition failed: {exc}"
        ) from exc
