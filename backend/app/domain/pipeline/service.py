"""Pipeline business logic — application creation, the status state machine,
Kanban stage moves, and the board view.

Status transitions are validated against ``ApplicationStatus.transitions()``:
illegal jumps (e.g. sourced -> placed) are rejected.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.common.enums import ApplicationStatus, PipelineStage
from app.domain.pipeline import steps as steps_mod
from app.domain.pipeline.models import (
    Application,
    ApplicationAssessment,
    ProcessStep,
)
from app.domain.pipeline.schemas import ApplicationCreate

# Display labels for the board columns (German labels are product-facing).
STAGE_LABELS: dict[PipelineStage, str] = {
    PipelineStage.BEWERBUNG: "Bewerbung",
    PipelineStage.LONG_LIST: "Long List",
    PipelineStage.SHORT_LIST: "Short List",
    PipelineStage.PRESENTED: "Presented",
    PipelineStage.INTERVIEW: "Interview",
    PipelineStage.PLACED: "Placed",
    PipelineStage.REJECTED: "Rejected",
}


class InvalidTransition(ValueError):
    """Raised when a status transition violates the state machine."""


async def list_applications(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[Application]:
    result = await session.execute(
        select(Application)
        .where(Application.tenant_id == tenant_id)
        .order_by(Application.created_at)
    )
    return list(result.scalars().all())


async def get_application(
    session: AsyncSession, *, tenant_id: uuid.UUID, application_id: uuid.UUID
) -> Application | None:
    result = await session.execute(
        select(Application).where(
            Application.tenant_id == tenant_id,
            Application.id == application_id,
        )
    )
    return result.scalar_one_or_none()


async def create_application(
    session: AsyncSession, *, data: ApplicationCreate
) -> Application:
    app = Application(
        tenant_id=data.tenant_id or settings.default_tenant_id,
        candidate_id=data.candidate_id,
        job_id=data.job_id,
        status=data.status,
        stage=data.stage,
        notes=data.notes,
        history=[
            {
                "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "event": "created",
                "status": data.status.value,
                "stage": data.stage.value,
            }
        ],
    )
    session.add(app)
    await session.commit()
    await session.refresh(app)
    return app


def _append_history(app: Application, entry: dict) -> None:
    # Reassign (not mutate in place) so SQLAlchemy detects the JSON change.
    app.history = [*app.history, entry]


async def transition_status(
    session: AsyncSession,
    *,
    app: Application,
    to_status: ApplicationStatus,
    actor: str,
) -> Application:
    """Move the application to ``to_status`` if the transition is allowed."""
    allowed = ApplicationStatus.transitions()[app.status]
    if to_status not in allowed:
        raise InvalidTransition(
            f"cannot move from {app.status.value} to {to_status.value}"
        )
    _append_history(
        app,
        {
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "event": "status",
            "from": app.status.value,
            "to": to_status.value,
            "actor": actor,
        },
    )
    app.status = to_status
    await session.commit()
    await session.refresh(app)
    return app


async def move_stage(
    session: AsyncSession,
    *,
    app: Application,
    to_stage: PipelineStage,
    actor: str,
) -> Application:
    """Move the application to a new Kanban stage."""
    _append_history(
        app,
        {
            "at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "event": "stage",
            "from": app.stage.value,
            "to": to_stage.value,
            "actor": actor,
        },
    )
    app.stage = to_stage
    await session.commit()
    await session.refresh(app)
    return app


async def board(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> dict[PipelineStage, list[Application]]:
    """Group applications by Kanban stage for the board view."""
    apps = await list_applications(session, tenant_id=tenant_id)
    grouped: dict[PipelineStage, list[Application]] = {
        stage: [] for stage in PipelineStage
    }
    for app in apps:
        grouped[app.stage].append(app)
    return grouped

# --------------------------------------------------------------------------
# Process steps — the recruiter's tracker, as data
# --------------------------------------------------------------------------


async def list_steps(
    session: AsyncSession, *, tenant_id: uuid.UUID, application_id: uuid.UUID
) -> list[ProcessStep]:
    rows = await session.execute(
        select(ProcessStep).where(
            ProcessStep.tenant_id == tenant_id,
            ProcessStep.application_id == application_id,
        )
    )
    return sorted(rows.scalars().all(), key=lambda s: (s.position, s.step_key))


def as_utc(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite hands back naive datetimes even for a timezone-aware column, so
    the API would emit different shapes on SQLite and Postgres. Every endpoint
    that returns a stored timestamp goes through this: a client comparing what
    it sent against what came back must not see two different instants."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.UTC)


def derive_stage(steps: list[ProcessStep]) -> PipelineStage:
    """The coarse Kanban stage implied by the checklist.

    Derived rather than stored twice: a board that disagrees with the process
    it summarises is worse than no board. Two rules the tracker makes plain:

      * a red cell anywhere ends the process — that is what "out" means;
      * a BOOKED interview already counts as the interview stage. The date is
        the commitment; waiting for it to happen would leave the board a week
        behind the recruiter every time.
    """
    reached = {
        s.step_key
        for s in steps
        if s.done_at is not None or s.scheduled_at is not None or s.outcome == "pass"
    }
    if any(s.outcome == "out" for s in steps):
        return PipelineStage.REJECTED
    if "vertrag" in reached:
        return PipelineStage.PLACED
    in_interview = {"interview", "feedback-2", "finaltermin", "final-vorb", "offer"}
    if reached & in_interview or any(
        key.startswith(steps_mod.EXTRA_ROUND_PREFIX) for key in reached
    ):
        return PipelineStage.INTERVIEW
    if "vorgestellt" in reached:
        return PipelineStage.PRESENTED
    return PipelineStage.BEWERBUNG


async def set_step(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    step_key: str,
    scheduled_at: dt.datetime | None = None,
    done_at: dt.datetime | None = None,
    outcome: str | None = None,
    note: str | None = None,
    clear: list[str] | None = None,
    actor: str = "recruiter",
) -> ProcessStep:
    """Create or update one step, then re-derive the application's stage.

    Idempotent per (application, step): the tracker is a checklist someone
    ticks and re-ticks, not an event log.
    """
    if not steps_mod.is_known(step_key):
        raise ValueError(f"unknown step {step_key}")
    if outcome is not None and outcome not in steps_mod.OUTCOMES:
        raise ValueError(f"unknown outcome {outcome}")

    app = await get_application(
        session, tenant_id=tenant_id, application_id=application_id
    )
    if app is None:
        raise ValueError("application not found")

    row = await session.scalar(
        select(ProcessStep).where(
            ProcessStep.tenant_id == tenant_id,
            ProcessStep.application_id == application_id,
            ProcessStep.step_key == step_key,
        )
    )
    if row is None:
        row = ProcessStep(
            tenant_id=tenant_id,
            application_id=application_id,
            step_key=step_key,
            position=steps_mod.position_for(step_key),
        )
        session.add(row)
    if scheduled_at is not None:
        row.scheduled_at = scheduled_at
    if done_at is not None:
        row.done_at = done_at
    if outcome is not None:
        row.outcome = outcome
    if note is not None:
        row.note = note or None
    for field in clear or ():
        if field not in {"scheduled_at", "done_at", "note"}:
            raise ValueError(f"cannot clear {field}")
        setattr(row, field, None)
    await session.flush()

    current = await list_steps(
        session, tenant_id=tenant_id, application_id=application_id
    )
    stage = derive_stage(current)
    if stage != app.stage:
        _append_history(
            app,
            {
                "at": dt.datetime.now(dt.UTC).isoformat(),
                "event": "stage",
                # A column-level enum comes back from the DB as a plain string,
                # so read it defensively rather than assuming `.value`.
                "from": PipelineStage(app.stage).value,
                "to": stage.value,
                "actor": actor,
                "via": f"step:{step_key}",
            },
        )
        app.stage = stage
    await session.commit()
    await session.refresh(row)
    return row


def _assessment_dict(row: ApplicationAssessment | None) -> dict | None:
    """The stored assessment as the wire contract wants it, or nothing.

    `None` means "nobody has assessed this candidate for this mandate yet" and
    the cockpit says so. An empty object would read as "assessed, score
    unknown", which is a different and wrong statement.
    """
    if row is None:
        return None
    return {
        "fit_score": row.fit_score,
        "verdict": row.verdict,
        "strengths": list(row.strengths or []),
        "risks": list(row.risks or []),
        "client_summary": row.client_summary,
        "technologies": list(row.technologies or []),
        "basis": row.basis,
        "assessed_at": as_utc(row.assessed_at),
    }


def _salary_fit_dict(candidate, job) -> dict | None:
    """The money question, answered the same way the matcher answers it."""
    from app.domain.matching.salary import salary_fit

    fit = salary_fit(
        minimum=candidate.salary_minimum,
        wish=candidate.salary_expectation,
        job_min=job.salary_min,
        job_max=job.salary_max,
        currency=job.salary_currency,
    )
    if fit.status == "unknown":
        return None
    return {
        "status": fit.status,
        "detail": fit.detail,
        "minimum": candidate.salary_minimum,
        "wish": candidate.salary_expectation,
    }


async def get_assessment(
    session: AsyncSession, *, tenant_id: uuid.UUID, application_id: uuid.UUID
) -> ApplicationAssessment | None:
    return await session.scalar(
        select(ApplicationAssessment).where(
            ApplicationAssessment.tenant_id == tenant_id,
            ApplicationAssessment.application_id == application_id,
        )
    )


async def set_assessment(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    fit_score: int | None = None,
    verdict: str | None = None,
    strengths: list[str] | None = None,
    risks: list[str] | None = None,
    client_summary: str | None = None,
    technologies: list[str] | None = None,
    basis: str | None = None,
    assessed_at: dt.datetime | None = None,
) -> ApplicationAssessment:
    """Replace the assessment of one candidate on one mandate.

    One row per application (the unique constraint says so), so re-assessing
    after the second round overwrites rather than accumulating versions the
    cockpit would then have to choose between. The receipt trail for who
    changed what lives in the verification ledger, not in duplicate rows.
    """
    if fit_score is not None and not 0 <= fit_score <= 10:
        raise ValueError("fit_score must be between 0 and 10")

    app = await get_application(
        session, tenant_id=tenant_id, application_id=application_id
    )
    if app is None:
        raise ValueError("application not found")

    row = await get_assessment(
        session, tenant_id=tenant_id, application_id=application_id
    )
    if row is None:
        row = ApplicationAssessment(
            tenant_id=tenant_id, application_id=application_id
        )
        session.add(row)
    row.fit_score = fit_score
    row.verdict = verdict
    row.strengths = list(strengths or [])
    row.risks = list(risks or [])
    row.client_summary = client_summary
    row.technologies = list(technologies or [])
    row.basis = basis
    row.assessed_at = assessed_at or dt.datetime.now(dt.UTC)
    await session.commit()
    await session.refresh(row)
    return row


async def processes(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[dict]:
    """"Laufende Prozesse", grouped by job — the tracker's own shape.

    A job appears once its first candidate has been presented, which is what
    the process doc says and what the sheet does: rows exist under a mandate
    only from the presentation onwards.
    """
    from app.domain.candidates.models import Candidate
    from app.domain.companies.models import Company
    from app.domain.jobs.models import Job

    apps = await list_applications(session, tenant_id=tenant_id)
    if not apps:
        return []
    all_steps = (
        await session.execute(
            select(ProcessStep).where(
                ProcessStep.tenant_id == tenant_id,
                ProcessStep.application_id.in_([a.id for a in apps]),
            )
        )
    ).scalars()
    by_app: dict[uuid.UUID, list[ProcessStep]] = {}
    for step in all_steps:
        by_app.setdefault(step.application_id, []).append(step)

    assessments = {
        a.application_id: a
        for a in (
            await session.execute(
                select(ApplicationAssessment).where(
                    ApplicationAssessment.tenant_id == tenant_id,
                    ApplicationAssessment.application_id.in_([a.id for a in apps]),
                )
            )
        ).scalars()
    }

    candidates = {
        c.id: c
        for c in (
            await session.execute(
                select(Candidate).where(Candidate.tenant_id == tenant_id)
            )
        ).scalars()
    }
    jobs = {
        j.id: j
        for j in (
            await session.execute(select(Job).where(Job.tenant_id == tenant_id))
        ).scalars()
    }
    companies = {
        c.id: c
        for c in (
            await session.execute(select(Company).where(Company.tenant_id == tenant_id))
        ).scalars()
    }

    grouped: dict[uuid.UUID, dict] = {}
    for app in apps:
        steps = sorted(
            by_app.get(app.id, []), key=lambda s: (s.position, s.step_key)
        )
        if not steps:
            continue  # not presented yet — the sheet has no row for it either
        job = jobs.get(app.job_id)
        candidate = candidates.get(app.candidate_id)
        if job is None or candidate is None:
            continue
        company = companies.get(job.client_company_id) if job.client_company_id else None
        entry = grouped.setdefault(
            job.id,
            {
                "job_id": job.id,
                "job_title": job.title,
                "company_id": company.id if company else None,
                "company_name": company.name if company else None,
                "location": job.location,
                "must_have_skills": list(job.must_have_skills or []),
                "salary_min": job.salary_min,
                "salary_max": job.salary_max,
                "salary_currency": job.salary_currency,
                "status": job.status,
                "candidates": [],
            },
        )
        entry["candidates"].append(
            {
                "application_id": app.id,
                "candidate_id": candidate.id,
                "candidate_name": candidate.full_name,
                "stage": app.stage,
                "presented_at": as_utc(
                    next((s.done_at for s in steps if s.step_key == "vorgestellt"), None)
                ),
                "next_appointment": min(
                    (
                        as_utc(s.scheduled_at)
                        for s in steps
                        if s.scheduled_at is not None and s.outcome == "open"
                    ),
                    default=None,
                ),
                "note": app.notes,
                "steps": [
                    {
                        "step_key": s.step_key,
                        "label": steps_mod.label_for(s.step_key),
                        "kind": steps_mod.kind_for(s.step_key),
                        "scheduled_at": as_utc(s.scheduled_at),
                        "done_at": as_utc(s.done_at),
                        "outcome": s.outcome,
                        "note": s.note,
                    }
                    for s in steps
                ],
                "assessment": _assessment_dict(assessments.get(app.id)),
                "salary_fit": _salary_fit_dict(candidate, job),
            }
        )

    out = list(grouped.values())
    for entry in out:
        entry["candidates"].sort(
            key=lambda c: (c["presented_at"] is None, c["presented_at"])
        )
    # Most recently active mandate first: where the work is today.
    out.sort(
        key=lambda e: max(
            (c["presented_at"] for c in e["candidates"] if c["presented_at"]),
            default=dt.datetime.min.replace(tzinfo=dt.UTC),
        ),
        reverse=True,
    )
    return out
