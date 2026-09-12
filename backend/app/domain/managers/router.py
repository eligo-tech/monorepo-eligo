"""Managers API — thin. Validates, calls the service, maps errors to HTTP."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.managers import service
from app.domain.managers.schemas import (
    ManagerCreate,
    ManagerInteractionCreate,
    ManagerInteractionRead,
    ManagerRead,
    ManagerUpdate,
)

router = APIRouter(prefix="/managers", tags=["managers"])


@router.get("", response_model=list[ManagerRead])
async def list_managers(
    company_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, description="name, role or company"),
    limit: int = Query(default=100, ge=1, le=500),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ManagerRead]:
    rows = await service.list_managers(
        db, tenant_id=tenant_id, company_id=company_id, q=q, limit=limit
    )
    return [ManagerRead.model_validate(r) for r in rows]


@router.get("/art14-outstanding", response_model=list[ManagerRead])
async def art14_outstanding(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ManagerRead]:
    """People we hold data on who have not been informed (GDPR Art. 14).

    Declared before `/{manager_id}` so the literal path is not captured by the
    UUID route.
    """
    rows = await service.managers_owing_art14(db, tenant_id=tenant_id)
    return [ManagerRead.model_validate(r) for r in rows]


@router.get("/{manager_id}", response_model=ManagerRead)
async def get_manager(
    manager_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ManagerRead:
    row = await service.get_manager(db, tenant_id=tenant_id, manager_id=manager_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "manager not found")
    return ManagerRead.model_validate(row)


@router.post("", response_model=ManagerRead, status_code=status.HTTP_201_CREATED)
async def create_manager(
    payload: ManagerCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ManagerRead:
    try:
        row = await service.create_manager(db, tenant_id=tenant_id, payload=payload)
    except service.CompanyNotInTenant as exc:
        # 422, not 404: the company may well exist — it is simply not this
        # tenant's to attach a person to, and saying "not found" would leak
        # nothing but would also mislead the caller about what to fix.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"company {exc} does not belong to this workspace",
        ) from exc
    return ManagerRead.model_validate(row)


@router.patch("/{manager_id}", response_model=ManagerRead)
async def update_manager(
    manager_id: uuid.UUID,
    payload: ManagerUpdate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ManagerRead:
    row = await service.update_manager(
        db, tenant_id=tenant_id, manager_id=manager_id, payload=payload
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "manager not found")
    return ManagerRead.model_validate(row)


@router.post("/{manager_id}/art14-notified", response_model=ManagerRead)
async def mark_art14_notified(
    manager_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ManagerRead:
    """Record that the subject has been informed. Its own endpoint on purpose —
    it asserts something happened in the world."""
    row = await service.mark_art14_notified(
        db, tenant_id=tenant_id, manager_id=manager_id
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "manager not found")
    return ManagerRead.model_validate(row)


@router.get("/{manager_id}/interactions", response_model=list[ManagerInteractionRead])
async def list_interactions(
    manager_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ManagerInteractionRead]:
    rows = await service.list_interactions(
        db, tenant_id=tenant_id, manager_id=manager_id, limit=limit
    )
    return [ManagerInteractionRead.model_validate(r) for r in rows]


@router.post(
    "/{manager_id}/interactions",
    response_model=ManagerInteractionRead,
    status_code=status.HTTP_201_CREATED,
)
async def log_interaction(
    manager_id: uuid.UUID,
    payload: ManagerInteractionCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ManagerInteractionRead:
    row = await service.log_interaction(
        db, tenant_id=tenant_id, manager_id=manager_id, payload=payload
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "manager not found")
    return ManagerInteractionRead.model_validate(row)
