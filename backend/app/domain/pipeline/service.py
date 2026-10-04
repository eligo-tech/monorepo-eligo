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


async def get_application_for(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> Application | None:
    """This candidate's run on this mandate, if there is one.

    The pair is unique (see `create_application`), so "is this person on
    this mandate?" has one answer.
    """
    return await session.scalar(
        select(Application).where(
            Application.tenant_id == tenant_id,
            Application.job_id == job_id,
            Application.candidate_id == candidate_id,
        )
    )


async def create_application(
    session: AsyncSession, *, data: ApplicationCreate
) -> Application:
    """Put one candidate on one job. Idempotent per pair.

    Assigning the same person to the same mandate twice is a double click,
    not a second process — and two rows would show the same candidate twice
    under one mandate with two separate step lists. The existing row comes
    back instead.
    """
    tenant_id = data.tenant_id or settings.default_tenant_id
    existing = await session.scalar(
        select(Application).where(
            Application.tenant_id == tenant_id,
            Application.candidate_id == data.candidate_id,
            Application.job_id == data.job_id,
        )
    )
    if existing is not None:
        return existing

    app = Application(
        tenant_id=tenant_id,
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
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    include_removed: bool = False,
) -> list[ProcessStep]:
    """The steps of one process, in order.

    Removed steps are left out by default — they are rows only so the nine-step
    template knows not to put them back (see `ProcessStep.active`).
    """
    stmt = select(ProcessStep).where(
        ProcessStep.tenant_id == tenant_id,
        ProcessStep.application_id == application_id,
    )
    if not include_removed:
        stmt = stmt.where(ProcessStep.active.is_(True))
    rows = await session.execute(stmt)
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
    # Ticking a step the process had removed is how you put it back — the
    # alternative is a write that silently lands on an invisible row.
    row.active = True
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


async def add_step(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    label: str,
    after: str | None = None,
    actor: str = "recruiter",
) -> ProcessStep:
    """Add a step to ONE process, positioned after an existing one.

    The nine are what every placement shares. A Probearbeitstag, an Assessment
    Center, a second site visit are real and common, and a fixed checklist
    sends the recruiter back to the spreadsheet for exactly the row that does
    not fit. `after` is a step key; None puts the new step first.

    Chronology is a position, not a date: the step may well have no date yet,
    and the order is what makes the next action readable.
    """
    label = (label or "").strip()
    if not label:
        raise ValueError("label required")
    if len(label) > 60:
        raise ValueError("label too long")

    app = await get_application(
        session, tenant_id=tenant_id, application_id=application_id
    )
    if app is None:
        raise ValueError("application not found")

    existing = await list_steps(
        session, tenant_id=tenant_id, application_id=application_id,
        include_removed=True,
    )
    taken = {s.step_key for s in existing}
    key = steps_mod.custom_key(label, taken)

    row = ProcessStep(
        tenant_id=tenant_id,
        application_id=application_id,
        step_key=key,
        label=label,
        position=_position_after(existing, after),
        active=True,
    )
    session.add(row)
    await session.flush()
    _append_history(
        app,
        {
            "at": dt.datetime.now(dt.UTC).isoformat(),
            "event": "step_added",
            "step": key,
            "label": label,
            "after": after,
            "actor": actor,
        },
    )
    await session.commit()
    await session.refresh(row)
    return row


async def remove_step(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    application_id: uuid.UUID,
    step_key: str,
    actor: str = "recruiter",
) -> None:
    """Take a step out of ONE process.

    A step that already HAPPENED is not removable: a date and a verdict are
    the record of something that took place, and deleting them would make the
    tracker lie about the past. Untick it first — that is an edit of a claim,
    which the step editor already does and the history already records.
    """
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
    if row is not None and (row.done_at is not None or row.outcome != "open"):
        raise StepHasHappened(step_key)

    if row is None:
        # A canonical step nobody has touched: the row exists only to say the
        # template must skip it from now on.
        if not steps_mod.is_known(step_key) or steps_mod.is_custom(step_key):
            raise ValueError(f"unknown step {step_key}")
        row = ProcessStep(
            tenant_id=tenant_id,
            application_id=application_id,
            step_key=step_key,
            position=steps_mod.position_for(step_key),
        )
        session.add(row)
    if steps_mod.is_custom(step_key):
        # Nothing would put it back, so there is nothing to suppress.
        await session.delete(row)
    else:
        row.active = False
    await session.flush()

    current = await list_steps(
        session, tenant_id=tenant_id, application_id=application_id
    )
    app.stage = derive_stage(current)
    _append_history(
        app,
        {
            "at": dt.datetime.now(dt.UTC).isoformat(),
            "event": "step_removed",
            "step": step_key,
            "actor": actor,
        },
    )
    await session.commit()


class StepHasHappened(Exception):
    """Raised when a removal would delete something that took place."""

    def __init__(self, step_key: str) -> None:
        super().__init__(
            f"{step_key} hat stattgefunden — erst den Eintrag löschen, dann den Schritt"
        )
        self.step_key = step_key


def _ordered_positions(rows: list[ProcessStep]) -> list[tuple[int, int, str]]:
    """(position, tie, key) for every step this process shows.

    ONE scale for everything: the canonical nine keep the template positions
    from `steps.py` whether or not they have a row yet, and an added step gets
    a position between two of them. Nothing is ever renumbered — a renumber
    would move the canonical rows that exist onto a different scale from the
    canonical steps that do not, which is precisely how an added step ends up
    rendered one slot late.
    """
    removed = {r.step_key for r in rows if not r.active}
    extra = [r for r in rows if r.active and r.step_key not in steps_mod.STEP_BY_KEY]
    canonical = [
        (steps_mod.POSITION[k], i, k)
        for i, k in enumerate(steps_mod.PROCESS_STEP_KEYS)
        if k not in removed
    ]
    # Added steps lose every tie, so inserting after X puts the new step
    # between X and whatever follows, never before X itself.
    return sorted(
        canonical + [(r.position, 1000 + i, r.step_key) for i, r in enumerate(extra)]
    )


def _process_order(rows: list[ProcessStep]) -> list[str]:
    """The step keys this process shows, in order."""
    return [k for _, _, k in _ordered_positions(rows)]


def _position_after(rows: list[ProcessStep], after: str | None) -> int:
    """A position that sorts straight after `after`, on the template scale.

    The template leaves gaps of ten, so the midpoint to the next step is
    free the first few times; past that the new step shares a position with
    its neighbour and the insertion-order tie-break keeps it stable.
    """
    order = _ordered_positions(rows)
    if after is None:
        first = order[0][0] if order else steps_mod.POSITION[steps_mod.PROCESS_STEP_KEYS[0]]
        return first - 5
    index = next((i for i, (_, _, key) in enumerate(order) if key == after), None)
    if index is None:
        raise ValueError(f"unknown step {after}")
    anchor = order[index][0]
    following = order[index + 1][0] if index + 1 < len(order) else anchor + 10
    return anchor + max(1, (following - anchor) // 2)


def _as_line(entry: object) -> str:
    """One education entry as a line, whatever shape the import left it in.

    ATS exports write `{"degree": …, "institution": …}`; the
    Gesprächszusammenfassung writes a sentence. The cockpit reads a line
    either way rather than refusing the record whose importer chose a dict.
    """
    if isinstance(entry, dict):
        parts = [str(v).strip() for v in entry.values() if str(v or "").strip()]
        return " · ".join(parts)
    return str(entry).strip()


def _profile_dict(candidate) -> dict:  # noqa: ANN001 — the Candidate model
    """Section B, read off the candidate: the summary the card leads with."""
    return {
        "profile_summary": candidate.profile_summary,
        "focus_areas": list(candidate.focus_areas or []),
        "technical_profile": candidate.technical_profile,
        "notice_period": candidate.notice_period,
        "availability": candidate.availability,
        "motivation": candidate.motivation,
        "interview_availability": candidate.interview_availability,
        "education": [
            line for entry in (candidate.education or []) if (line := _as_line(entry))
        ],
        "other_notes": candidate.other_notes,
        "other_processes": candidate.other_processes,
        "other_process_companies": list(candidate.other_process_companies or []),
        "salary_minimum": candidate.salary_minimum,
        "salary_expectation": candidate.salary_expectation,
        "current_salary": candidate.current_salary,
        "salary_currency": candidate.salary_currency,
    }


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

    A candidate appears here as soon as they are ASSIGNED to the mandate, not
    only once presented. The sheet starts at the presentation because a sheet
    has nowhere to put someone before that; the cockpit does, and the work
    between assignment and presentation — the Qualifikationsgespräch, the
    Unterlagen, the client text — is exactly what it is for. `presented_at`
    stays null until the step is ticked, so the two states remain distinct.
    """
    from app.domain.candidates.models import Candidate
    from app.domain.companies.models import Company
    from app.domain.jobs.models import Job

    apps = await list_applications(session, tenant_id=tenant_id)
    if not apps:
        return []
    # Removed rows come along: the client merges the nine-step template with
    # what this process changed, so it has to be told what was taken out.
    all_steps = (
        await session.execute(
            select(ProcessStep).where(
                ProcessStep.tenant_id == tenant_id,
                ProcessStep.application_id.in_([a.id for a in apps]),
            )
        )
    ).scalars()
    all_rows: dict[uuid.UUID, list[ProcessStep]] = {}
    by_app: dict[uuid.UUID, list[ProcessStep]] = {}
    for step in all_steps:
        all_rows.setdefault(step.application_id, []).append(step)
        if step.active:
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
                # The order THIS process has: the nine-step template merged
                # with what it added and minus what it removed. Computed once,
                # here — the client re-deriving it from positions is how the
                # two orders drift, and a step shown in the wrong place is
                # worse than one not shown at all.
                "step_order": _process_order(all_rows.get(app.id, [])),
                "steps": [
                    {
                        "step_key": s.step_key,
                        "label": steps_mod.label_for(s.step_key, s.label),
                        "position": s.position,
                        "custom": steps_mod.is_custom(s.step_key),
                        "kind": steps_mod.kind_for(s.step_key),
                        "scheduled_at": as_utc(s.scheduled_at),
                        "done_at": as_utc(s.done_at),
                        "outcome": s.outcome,
                        "note": s.note,
                    }
                    for s in steps
                ],
                "assessment": _assessment_dict(assessments.get(app.id)),
                "profile": _profile_dict(candidate),
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
