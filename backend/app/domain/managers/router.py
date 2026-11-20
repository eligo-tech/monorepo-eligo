"""Managers API — thin. Validates, calls the service, maps errors to HTTP."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, get_current_tenant
from app.core.database import get_db
from app.domain.managers import service
from app.domain.managers.schemas import (
    LeadCreate,
    ManagerCreate,
    ManagerInteractionCreate,
    ManagerInteractionRead,
    ManagerRead,
    ManagerRemove,
    ManagerUpdate,
)

router = APIRouter(prefix="/managers", tags=["managers"])


@router.get("", response_model=list[ManagerRead])
async def list_managers(
    response: Response,
    company_id: uuid.UUID | None = Query(default=None),
    q: str | None = Query(default=None, description="name, role or company"),
    limit: int = Query(default=100, ge=1, le=1000),
    stage: Literal["bus_dev", "manager"] | None = Query(default=None, description="ELI-23: bus_dev | manager"),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ManagerRead]:
    """This workspace's contacts, with `X-Total-Count` for the whole set.

    Same contract as `/candidates`, for the same reason: the cockpit filters
    and ranks these rows in the browser, so a page smaller than the set turns
    every search into a search of the first N names. The count is of the
    tenant's contacts, unfiltered by `q` — "447 of 647 shown" is about the
    page, not about the query.
    """
    rows = await service.list_managers(
        db, tenant_id=tenant_id, company_id=company_id, q=q, limit=limit, stage=stage
    )
    response.headers["X-Total-Count"] = str(
        await service.count_managers(db, tenant_id=tenant_id, company_id=company_id, stage=stage)
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
    except service.NotInterested as exc:
        # ELI-60: already here, marked "Kein Interesse" — not a second record.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "no_interest", "manager_id": str(exc.manager.id),
             "no_interest_at": exc.manager.no_interest_at.isoformat() if exc.manager.no_interest_at else None},
        ) from exc
    except service.CompanyNotInTenant as exc:
        # 422, not 404: the company may well exist — it is simply not this
        # tenant's to attach a person to, and saying "not found" would leak
        # nothing but would also mislead the caller about what to fix.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"company {exc} does not belong to this workspace",
        ) from exc
    return ManagerRead.model_validate(row)


@router.post("/leads", response_model=ManagerRead, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> ManagerRead:
    """ELI-65 "+ Lead": a lead entered by hand from a job ad or a LinkedIn
    profile. 409 `{code: "lead_exists", manager_id, stage, full_name}` when
    the person is already held at that company — shown, not doubled."""
    try:
        row = await service.create_manual_lead(db, tenant_id=actor.tenant_id, payload=payload, actor=actor.name)
    except service.LeadExists as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "lead_exists", "manager_id": str(exc.manager.id), "stage": exc.manager.stage,
             "full_name": exc.manager.full_name},
        ) from exc
    return ManagerRead.model_validate(row)


@router.patch("/{manager_id}", response_model=ManagerRead)
async def update_manager(
    manager_id: uuid.UUID,
    payload: ManagerUpdate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> ManagerRead:
    try:
        row = await service.update_manager(
            db, tenant_id=actor.tenant_id, manager_id=manager_id, payload=payload, editor=actor.name
        )
    except service.CompanyNotInTenant as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"company {exc} does not belong to this workspace"
        ) from exc
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


@router.post("/{manager_id}/promote", response_model=ManagerRead)
async def promote_manager(
    manager_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ManagerRead:
    """Move a bus-dev contact to Managers after the first contact (ELI-23)."""
    row = await service.promote_manager(db, tenant_id=tenant_id, manager_id=manager_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "manager not found")
    return ManagerRead.model_validate(row)


@router.post("/{manager_id}/remove", response_model=ManagerRead)
async def remove_lead(
    manager_id: uuid.UUID,
    payload: ManagerRemove,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ManagerRead:
    """ELI-66 "Entfernen": off the Leads list with a reason — hidden, never
    deleted; undone by `DELETE /{id}/no-interest`."""
    try:
        row = await service.remove_lead(
            db, tenant_id=tenant_id, manager_id=manager_id, reason=payload.reason, note=payload.note
        )
    except service.NotALead as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "not_a_lead"}) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "manager not found")
    return ManagerRead.model_validate(row)


@router.delete("/{manager_id}/no-interest", response_model=ManagerRead)
async def revive_lead(
    manager_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ManagerRead:
    """ELI-60: "Wieder als Lead aufnehmen" — clears "Kein Interesse"."""
    row = await service.revive_lead(db, tenant_id=tenant_id, manager_id=manager_id)
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


@router.get("/{manager_id}/appointments", response_model=list[ManagerInteractionRead])
async def list_appointments(
    manager_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ManagerInteractionRead]:
    """The Termine tab (ELI-40): this manager's meetings, booked or held."""
    rows = await service.list_appointments(
        db, tenant_id=tenant_id, manager_id=manager_id, limit=limit
    )
    if rows is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "manager not found")
    return [ManagerInteractionRead.model_validate(r) for r in rows]


@router.post(
    "/{manager_id}/interactions",
    response_model=ManagerInteractionRead,
    status_code=status.HTTP_201_CREATED,
)
async def log_interaction(
    manager_id: uuid.UUID,
    payload: ManagerInteractionCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> ManagerInteractionRead:
    # ELI-15: the note IS the event, so the only thing it was missing is who
    # wrote it. Stamped on the row itself — a second table holding the same
    # call could only ever drift from this one.
    row = await service.log_interaction(
        db,
        tenant_id=actor.tenant_id,
        manager_id=manager_id,
        payload=payload,
        actor_user_id=actor.user_id,
        actor_name=actor.name,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "manager not found")
    return ManagerInteractionRead.model_validate(row)
