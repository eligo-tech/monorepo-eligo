"""Application ORM model — the many-to-many state machine linking a candidate
to a job as they move through the hiring pipeline."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
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
    #: One of `PROCESS_STEP_KEYS`, an extra round ("interviewtermin_3"), or a
    #: step this process added for itself ("custom_probearbeitstag").
    step_key: Mapped[str] = mapped_column(String(40), nullable=False)
    #: Set only for a custom step — the canonical nine take their label from
    #: `steps.py`, so renaming one there renames it everywhere at once.
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: False when this process does not have the step. A removed CANONICAL
    #: step has to leave a row behind: the nine are a template every process
    #: starts from, and without the row the template would put it straight
    #: back. Deactivating also keeps whatever was recorded on it, so adding it
    #: again is not a loss.
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true"), nullable=False
    )
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


class ApplicationAssessment(Base, IDMixin, TenantMixin, TimestampMixin):
    """The Kandidatenauswertung: one candidate measured against ONE mandate.

    It hangs off the application, not the candidate, because that is what it
    is: `data/examples/KandidatenInfo.txt` scores a person against "Position 1
    – GE Software" and its sharpened Muss-Profil. The same person on another
    mandate is a different fit, a different risk list and a different text for
    the client. Storing it on the candidate would make the first mandate's
    verdict follow them everywhere.

    The four sections of the recruiter's document map one-to-one:
      A Passungsbewertung → `fit_score` / `verdict` / `strengths` / `risks`
      B Gesprächszusammenfassung → the CANDIDATE's own columns, not here
      C Kundenvorstellung → `client_summary`
      D Relevante Technologien → `technologies`

    B is deliberately absent. Kündigungsfrist, Gehalt, Wechselmotivation and
    the rest describe the person, hold across every mandate, and already have
    columns on `candidates`; copying them per application would be three
    answers to one question.

    Written today by a human (the recruiter writes it after the
    Qualifikationsgespräch). When an agent proposes one it goes through
    `verify_and_commit` like any other agent claim — `basis` is the provenance
    line that says what the assessment was read from.
    """

    __tablename__ = "application_assessments"
    __table_args__ = (
        UniqueConstraint("application_id", name="uq_assessment_application"),
    )

    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Gesamtbewertung, 0–10 as the document scores it ("8 / 10").
    fit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Kurzfazit — the one paragraph a recruiter reads before a client call.
    verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    #: "Lücken/Risiken" — kept separate from strengths because the cockpit
    #: shows them differently and a risk hidden in prose is a risk missed.
    risks: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    #: Section C, written for the client's eyes — never shown as internal text.
    client_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    technologies: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    #: Provenance: "CV (Kurzversion) + Gesprächstranskript (18.09.2026)".
    basis: Mapped[str | None] = mapped_column(String(400), nullable=True)
    assessed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
