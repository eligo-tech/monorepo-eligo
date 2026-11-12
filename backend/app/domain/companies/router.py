"""Companies API."""

from __future__ import annotations

import uuid

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.companies import service
from app.domain.companies.schemas import CompanyCreate, CompanyOverviewRow, CompanyPage, CompanyRead

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyRead])
async def list_companies(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[CompanyRead]:
    rows = await service.list_companies(db, tenant_id=tenant_id, limit=limit)
    return [CompanyRead.model_validate(r) for r in rows]


@router.get("/overview", response_model=list[CompanyOverviewRow])
async def companies_overview(
    kind: Literal["all", "clients", "leads"] = Query(default="all"),
    q: str | None = Query(default=None, max_length=200),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[CompanyOverviewRow]:
    """Unternehmen (ELI-33): every company here — clients (≥1 manager) and
    lead companies (≥1 new contact from Markt) — with counts, A–Z."""
    return [CompanyOverviewRow(**r) for r in await service.overview(db, tenant_id=tenant_id, kind=kind, q=q)]


@router.get("/{company_id}/page", response_model=CompanyPage)
async def company_page(
    company_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CompanyPage:
    """One company: managers, leads, mandates, Impressum switchboard."""
    page = await service.company_page(db, tenant_id=tenant_id, company_id=company_id)
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    return CompanyPage(**page)


@router.get("/{company_id}", response_model=CompanyRead)
async def get_company(
    company_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CompanyRead:
    row = await service.get_company(db, tenant_id=tenant_id, company_id=company_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    return CompanyRead.model_validate(row)


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: CompanyCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CompanyRead:
    payload.tenant_id = tenant_id  # force the authenticated tenant
    row = await service.create_company(db, data=payload)
    return CompanyRead.model_validate(row)