"""Companies API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.domain.companies import service
from app.domain.companies.schemas import CompanyCreate, CompanyRead

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyRead])
async def list_companies(
    tenant_id: uuid.UUID = Query(default=settings.default_tenant_id),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[CompanyRead]:
    rows = await service.list_companies(db, tenant_id=tenant_id, limit=limit)
    return [CompanyRead.model_validate(r) for r in rows]


@router.get("/{company_id}", response_model=CompanyRead)
async def get_company(
    company_id: uuid.UUID,
    tenant_id: uuid.UUID = Query(default=settings.default_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> CompanyRead:
    row = await service.get_company(db, tenant_id=tenant_id, company_id=company_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    return CompanyRead.model_validate(row)


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(
    payload: CompanyCreate,
    db: AsyncSession = Depends(get_db),
) -> CompanyRead:
    row = await service.create_company(db, data=payload)
    return CompanyRead.model_validate(row)