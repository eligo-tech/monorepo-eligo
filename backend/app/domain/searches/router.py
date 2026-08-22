"""Saved-searches API.

Standing market questions belonging to one workspace. Creating one crawls
nothing — it is configuration the nightly job reads later (ARCHITECTURE.md
RULE 1).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.hub import service as hub_service
from app.domain.hub.schemas import HubEmployerHit, HubJobPostingRead
from app.domain.searches import service
from app.domain.searches.schemas import (
    SavedSearchCreate,
    SavedSearchRead,
    SavedSearchUpdate,
)

router = APIRouter(prefix="/searches", tags=["searches"])


@router.get("", response_model=list[SavedSearchRead])
async def list_saved_searches(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[SavedSearchRead]:
    rows = await service.list_searches(db, tenant_id=tenant_id)
    return [SavedSearchRead.model_validate(r) for r in rows]


@router.post("", response_model=SavedSearchRead, status_code=status.HTTP_201_CREATED)
async def create_saved_search(
    payload: SavedSearchCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> SavedSearchRead:
    """Save a standing question. Fetches nothing — the nightly job acts on it."""
    row = await service.create_search(db, tenant_id=tenant_id, data=payload)
    return SavedSearchRead.model_validate(row)


@router.patch("/{search_id}", response_model=SavedSearchRead)
async def update_saved_search(
    search_id: uuid.UUID,
    payload: SavedSearchUpdate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> SavedSearchRead:
    row = await service.update_search(
        db, tenant_id=tenant_id, search_id=search_id, data=payload
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "saved search not found")
    return SavedSearchRead.model_validate(row)


@router.delete("/{search_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_search(
    search_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    if not await service.delete_search(
        db, tenant_id=tenant_id, search_id=search_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "saved search not found")


@router.get("/{search_id}/results", response_model=list[HubEmployerHit])
async def run_saved_search(
    search_id: uuid.UUID,
    limit: int = Query(default=40, ge=1, le=200),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[HubEmployerHit]:
    """Run a profile against the corpus. Reads only — never touches a source."""
    saved = await service.get_search(db, tenant_id=tenant_id, search_id=search_id)
    if saved is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "saved search not found")

    hits = await hub_service.search_employers(
        db,
        q=saved.q,
        city=saved.city,
        regions=list(saved.regions or []),
        berufsfelder=list(saved.berufsfelder or []),
        min_roles=saved.min_roles,
        limit=limit,
    )
    tracked = await hub_service.tracked_company_ids(db, tenant_id=tenant_id)
    out: list[HubEmployerHit] = []
    for hit in hits:
        item = HubEmployerHit.model_validate(
            {
                **hit,
                "matching_roles": [
                    HubJobPostingRead.model_validate(r) for r in hit["matching_roles"]
                ],
            }
        )
        item.tracked = any(cid in tracked for cid in hit["hub_company_ids"])
        out.append(item)

    await service.record_run(
        db, tenant_id=tenant_id, search_id=search_id, result_count=len(out)
    )
    return out
