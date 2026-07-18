"""Reporting API — funnel, dwell, and a combined overview."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.domain.reporting import service
from app.domain.reporting.schemas import (
    DwellStage,
    FunnelStage,
    ReportingOverview,
)

router = APIRouter(prefix="/reporting", tags=["reporting"])


@router.get("/funnel", response_model=list[FunnelStage])
async def funnel(
    tenant_id: uuid.UUID = Query(default=settings.default_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[FunnelStage]:
    """Applications that reached each funnel step (Beworben → Vermittelt)."""
    return await service.funnel(db, tenant_id=tenant_id)


@router.get("/dwell", response_model=list[DwellStage])
async def dwell(
    tenant_id: uuid.UUID = Query(default=settings.default_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[DwellStage]:
    """Average time applications currently in each stage have spent there."""
    return await service.dwell(db, tenant_id=tenant_id)


@router.get("/overview", response_model=ReportingOverview)
async def overview(
    tenant_id: uuid.UUID = Query(default=settings.default_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ReportingOverview:
    """One-shot payload for the Reporting tab: funnel + dwell + KPIs."""
    return await service.overview(db, tenant_id=tenant_id)