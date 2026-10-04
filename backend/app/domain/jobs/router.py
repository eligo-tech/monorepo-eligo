"""Jobs API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, get_current_tenant
from app.core.database import get_db
from app.domain.managers import service as managers_service
from app.domain.managers.schemas import (
    ManagerInteractionCreate,
    ManagerInteractionRead,
)
from app.domain.jobs import service
from app.domain.jobs.schemas import (
    CriteriaSuggestion,
    JobCreate,
    JobRead,
    JobUpdate,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobRead])
async def list_jobs(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[JobRead]:
    rows = await service.list_jobs(db, tenant_id=tenant_id, limit=limit)
    return [JobRead.model_validate(r) for r in rows]


@router.get("/{job_id}", response_model=JobRead)
async def get_job(
    job_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> JobRead:
    row = await service.get_job(db, tenant_id=tenant_id, job_id=job_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return JobRead.model_validate(row)


@router.get(
    "/{job_id}/criteria-suggestions", response_model=list[CriteriaSuggestion]
)
async def criteria_suggestions(
    job_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[CriteriaSuggestion]:
    """Muss-Kriterien this mandate's title already names.

    63 of 76 mandates in the live workspace have none, which makes the
    deterministic half of matching a no-op for most of the book. These are
    proposals drawn from the title and the workspace's own skill vocabulary —
    deterministic, explainable, and committed only by a human click.
    """
    job = await service.get_job(db, tenant_id=tenant_id, job_id=job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return [
        CriteriaSuggestion(
            skill=s.skill, evidence=s.evidence, candidates=s.candidates
        )
        for s in await service.criteria_suggestions(db, tenant_id=tenant_id, job=job)
    ]


@router.get(
    "/{job_id}/briefings", response_model=list[ManagerInteractionRead]
)
async def list_briefings(
    job_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ManagerInteractionRead]:
    """What was said about this mandate, newest first.

    Phase 2 of the Prozess-Doku is a conversation, and until now the product
    had nowhere to put it: the Suchprofil fields held the OUTCOME of the
    briefing and nothing held the briefing.
    """
    rows = await managers_service.list_for_job(db, tenant_id=tenant_id, job_id=job_id)
    return [ManagerInteractionRead.model_validate(r) for r in rows]


@router.post(
    "/{job_id}/briefings",
    response_model=ManagerInteractionRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_briefing(
    job_id: uuid.UUID,
    payload: ManagerInteractionCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ManagerInteractionRead:
    """Write down a briefing call. The contact is optional — see 0034."""
    job = await service.get_job(db, tenant_id=tenant_id, job_id=job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    payload = payload.model_copy(update={"job_id": job_id})
    row = await managers_service.log_interaction(
        db, tenant_id=tenant_id, manager_id=payload.manager_id, payload=payload
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "manager not found")
    return ManagerInteractionRead.model_validate(row)


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: JobCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> JobRead:
    payload.tenant_id = tenant_id  # force the authenticated tenant
    row = await service.create_job(db, data=payload)
    return JobRead.model_validate(row)


@router.patch("/{job_id}", response_model=JobRead)
async def update_job(
    job_id: uuid.UUID,
    payload: JobUpdate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> JobRead:
    """Edit the Suchprofil. Each changed field leaves a receipt, naming who.

    The editor used to be a query parameter — identity the browser could set.
    It comes from the verified token now.
    """
    try:
        row = await service.update_job(
            db,
            tenant_id=actor.tenant_id,
            job_id=job_id,
            patch=payload,
            editor=actor.name,
        )
    except service.InvalidBand as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return JobRead.model_validate(row)
