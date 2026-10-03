"""Pipeline API — applications, state-machine transitions, and the board."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, get_current_tenant
from app.core.database import get_db
from app.domain.pipeline import service
from app.domain.pipeline import steps as steps_mod
from app.domain.pipeline.schemas import (
    AssessmentRead,
    AssessmentWrite,
    ProcessJobRead,
    ProcessStepRead,
    ProcessStepUpdate,
    ApplicationCreate,
    ApplicationRead,
    BoardColumn,
    PipelineBoard,
    StageMove,
    StatusTransition,
)
from app.domain.pipeline.service import STAGE_LABELS, InvalidTransition

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("/applications", response_model=list[ApplicationRead])
async def list_applications(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ApplicationRead]:
    rows = await service.list_applications(db, tenant_id=tenant_id)
    return [ApplicationRead.model_validate(r) for r in rows]


@router.post(
    "/applications",
    response_model=ApplicationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_application(
    payload: ApplicationCreate,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ApplicationRead:
    payload.tenant_id = tenant_id  # force the authenticated tenant
    row = await service.create_application(db, data=payload)
    return ApplicationRead.model_validate(row)


@router.post("/applications/{application_id}/status", response_model=ApplicationRead)
async def transition_status(
    application_id: uuid.UUID,
    payload: StatusTransition,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ApplicationRead:
    app = await service.get_application(
        db, tenant_id=tenant_id, application_id=application_id
    )
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "application not found")
    try:
        app = await service.transition_status(
            db, app=app, to_status=payload.to_status, actor=payload.actor
        )
    except InvalidTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return ApplicationRead.model_validate(app)


@router.post("/applications/{application_id}/stage", response_model=ApplicationRead)
async def move_stage(
    application_id: uuid.UUID,
    payload: StageMove,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ApplicationRead:
    app = await service.get_application(
        db, tenant_id=tenant_id, application_id=application_id
    )
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "application not found")
    app = await service.move_stage(
        db, app=app, to_stage=payload.to_stage, actor=payload.actor
    )
    return ApplicationRead.model_validate(app)


@router.get("/board", response_model=PipelineBoard)
async def board(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> PipelineBoard:
    grouped = await service.board(db, tenant_id=tenant_id)
    columns = [
        BoardColumn(
            stage=stage,
            label=STAGE_LABELS[stage],
            applications=[ApplicationRead.model_validate(a) for a in apps],
        )
        for stage, apps in grouped.items()
    ]
    return PipelineBoard(columns=columns)

@router.get("/processes", response_model=list[ProcessJobRead])
async def processes(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[ProcessJobRead]:
    """"Laufende Prozesse": every mandate with a candidate in play, grouped
    the way the recruiter's tracker groups them."""
    return [
        ProcessJobRead.model_validate(entry)
        for entry in await service.processes(db, tenant_id=tenant_id)
    ]


@router.patch(
    "/applications/{application_id}/steps/{step_key}", response_model=ProcessStepRead
)
async def set_step(
    application_id: uuid.UUID,
    step_key: str,
    payload: ProcessStepUpdate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> ProcessStepRead:
    """Set a date, a verdict or a note on one step. Idempotent per step."""
    try:
        row = await service.set_step(
            db,
            tenant_id=actor.tenant_id,
            application_id=application_id,
            step_key=step_key,
            scheduled_at=payload.scheduled_at,
            done_at=payload.done_at,
            outcome=payload.outcome,
            note=payload.note,
            clear=payload.clear,
            actor=actor.name,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return ProcessStepRead.model_validate(
        {
            "step_key": row.step_key,
            "label": steps_mod.label_for(row.step_key),
            "kind": steps_mod.kind_for(row.step_key),
            "scheduled_at": service.as_utc(row.scheduled_at),
            "done_at": service.as_utc(row.done_at),
            "outcome": row.outcome,
            "note": row.note,
        }
    )


@router.get(
    "/applications/{application_id}/assessment", response_model=AssessmentRead
)
async def read_assessment(
    application_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> AssessmentRead:
    """The Kandidatenauswertung for this candidate on this mandate."""
    row = await service.get_assessment(
        db, tenant_id=tenant_id, application_id=application_id
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no assessment yet")
    return AssessmentRead.model_validate(row)


@router.put(
    "/applications/{application_id}/assessment", response_model=AssessmentRead
)
async def write_assessment(
    application_id: uuid.UUID,
    payload: AssessmentWrite,
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> AssessmentRead:
    """Write (or rewrite) the assessment. A full replacement, by design."""
    try:
        row = await service.set_assessment(
            db,
            tenant_id=tenant_id,
            application_id=application_id,
            fit_score=payload.fit_score,
            verdict=payload.verdict,
            strengths=payload.strengths,
            risks=payload.risks,
            client_summary=payload.client_summary,
            technologies=payload.technologies,
            basis=payload.basis,
            assessed_at=payload.assessed_at,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return AssessmentRead.model_validate(row)
