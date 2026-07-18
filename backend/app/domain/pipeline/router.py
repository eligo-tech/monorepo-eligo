"""Pipeline API — applications, state-machine transitions, and the board."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.auth import get_current_tenant
from app.core.database import get_db
from app.domain.pipeline import service
from app.domain.pipeline.schemas import (
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