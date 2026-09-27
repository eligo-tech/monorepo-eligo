"""Application ORM model — the many-to-many state machine linking a candidate
to a job as they move through the hiring pipeline."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.enums import ApplicationStatus, PipelineStage
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONList


class Application(Base, IDMixin, TenantMixin, TimestampMixin):
    """A candidate's application to a specific job."""

    __tablename__ = "applications"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id"), index=True, nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id"), index=True, nullable=False
    )

    status: Mapped[ApplicationStatus] = mapped_column(
        String(20), default=ApplicationStatus.SOURCED, nullable=False
    )
    stage: Mapped[PipelineStage] = mapped_column(
        String(20), default=PipelineStage.BEWERBUNG, nullable=False
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Append-only audit of stage/status transitions (who, from, to, when).
    history: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)

class ProcessStep(Base, IDMixin, TenantMixin, TimestampMixin):
    """One checklist step of one candidate's process on one job.

    The recruiter's tracker is a spreadsheet: a row per candidate under a job,
    a date when they were presented, a date per interview, and a cell coloured
    green (through) or red (out) after each round. `docs/process_design`
    describes the same thing as nine ordered steps.

    This table is that sheet, one row per step, so the cockpit can say what the
    sheet says: *when* something is scheduled, *when* it happened, and *how it
    went*. `Application.stage` stays as the coarse Kanban position and is
    derived from these rows — one truth, two resolutions.

    Rounds beyond the ninth step are ordinary rows with their own `step_key`
    ("interviewtermin_3"): candidates do get a third interview, and a fixed
    nine-slot table would have to lose it or lie about it.
    """

    __tablename__ = "process_steps"
    __table_args__ = (
        UniqueConstraint("application_id", "step_key", name="uq_process_step"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: One of `PROCESS_STEP_KEYS`, or an extra round ("interviewtermin_3").
    step_key: Mapped[str] = mapped_column(String(40), nullable=False)
    #: Sort position. Extra rounds sit just after the step they follow.
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    #: A date in the future: the appointment. "09.09. um 11 Uhr".
    scheduled_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: When the step actually happened — for "Vorgestellt" this is the date in
    #: the sheet's first column.
    done_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: "open" | "pass" | "out" — the sheet's uncoloured / green / red cell.
    #: A red cell is why a candidate stops moving, so it is data, not a note.
    outcome: Mapped[str] = mapped_column(String(10), default="open", nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
