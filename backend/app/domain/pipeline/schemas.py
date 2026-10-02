"""Pydantic v2 contracts for the pipeline domain."""

from __future__ import annotations

import datetime as dt
import uuid

from typing import Literal

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

# --------------------------------------------------------------------------
# Process steps — "Laufende Prozesse" as the recruiter's tracker records it
# --------------------------------------------------------------------------


class ProcessStepRead(BaseModel):
    """One checklist step. `kind` tells the UI what the step carries:
    an appointment (date+time), a feedback verdict, or a plain milestone."""

    step_key: str
    label: str
    kind: str
    scheduled_at: dt.datetime | None
    done_at: dt.datetime | None
    #: "open" | "pass" | "out" — the tracker's uncoloured / green / red cell.
    outcome: str
    note: str | None


class ProcessStepUpdate(BaseModel):
    """Tick a step, give it a date, or record how it went.

    Every field optional: a recruiter sets the interview date today and the
    verdict next week, and forcing both at once would mean inventing one.

    Omitting a field leaves it alone, so removing a value needs its own word:
    `clear: ["scheduled_at"]` un-books an appointment. Without that, a
    cancelled interview could only be overwritten, never taken back.
    """

    scheduled_at: dt.datetime | None = None
    done_at: dt.datetime | None = None
    outcome: Literal["open", "pass", "out"] | None = None
    note: str | None = None
    clear: list[Literal["scheduled_at", "done_at", "note"]] = Field(
        default_factory=list
    )
    actor: str = "recruiter"


class AssessmentRead(BaseModel):
    """The Kandidatenauswertung as the cockpit shows it."""

    model_config = ConfigDict(from_attributes=True)

    fit_score: int | None
    verdict: str | None
    strengths: list[str]
    risks: list[str]
    client_summary: str | None
    technologies: list[str]
    basis: str | None
    assessed_at: dt.datetime | None


class AssessmentWrite(BaseModel):
    """Write the assessment of one candidate on one mandate.

    A full replacement, not a patch: the recruiter re-reads the whole
    evaluation after a round and a half-updated verdict — new risks, old
    Kurzfazit — is worse than no verdict at all.
    """

    fit_score: int | None = Field(default=None, ge=0, le=10)
    verdict: str | None = None
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    client_summary: str | None = None
    technologies: list[str] = Field(default_factory=list)
    basis: str | None = None
    assessed_at: dt.datetime | None = None


class ProcessCandidateRead(BaseModel):
    """One candidate's run at one job."""

    application_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: str
    stage: PipelineStage
    presented_at: dt.datetime | None
    #: The soonest appointment still open — what the recruiter needs on Monday.
    next_appointment: dt.datetime | None
    note: str | None
    steps: list[ProcessStepRead]
    #: Null until someone has assessed this candidate FOR THIS mandate.
    assessment: AssessmentRead | None = None


class ProcessJobRead(BaseModel):
    """One mandate with every candidate running on it, as the sheet groups them."""

    job_id: uuid.UUID
    job_title: str
    company_id: uuid.UUID | None
    company_name: str | None
    #: The Suchprofil, so the per-job view can say what is being searched for
    #: next to who is running — the two halves of one mandate.
    location: str | None = None
    must_have_skills: list[str] = Field(default_factory=list)
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    status: str | None = None
    candidates: list[ProcessCandidateRead]
