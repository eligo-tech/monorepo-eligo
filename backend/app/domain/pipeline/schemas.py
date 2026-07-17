"""Pydantic v2 contracts for the pipeline domain."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.enums import ApplicationStatus, PipelineStage


class ApplicationCreate(BaseModel):
    candidate_id: uuid.UUID
    job_id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    status: ApplicationStatus = ApplicationStatus.SOURCED
    stage: PipelineStage = PipelineStage.BEWERBUNG
    notes: str | None = None


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    candidate_id: uuid.UUID
    job_id: uuid.UUID
    status: ApplicationStatus
    stage: PipelineStage
    notes: str | None
    history: list[dict] = Field(default_factory=list)
    created_at: dt.datetime
    updated_at: dt.datetime


class StatusTransition(BaseModel):
    """Request to move an application to a new status (validated state machine)."""

    to_status: ApplicationStatus
    actor: str = "recruiter"


class StageMove(BaseModel):
    """Request to move an application to a new Kanban stage."""

    to_stage: PipelineStage
    actor: str = "recruiter"


class BoardColumn(BaseModel):
    """One Kanban column with its applications — the board view shape."""

    stage: PipelineStage
    label: str
    applications: list[ApplicationRead]


class PipelineBoard(BaseModel):
    columns: list[BoardColumn]