"""Global search API (ELI-52) — the cockpit command bar's box."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.search import service
from app.domain.search.schemas import SearchResults

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResults)
async def global_search(
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=5, ge=1, le=20),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> SearchResults:
    """Candidates, mandates, companies and contacts of this workspace whose
    name contains `q` (≥2 characters), a few per kind. Never Markt."""
    return await service.search(db, tenant_id=tenant_id, q=q, limit=limit)
