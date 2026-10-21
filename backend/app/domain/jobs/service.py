"""Job business logic."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.common.enums import (
    ConfidenceSource,
    JobStatus,
    job_status_spellings,
    normalise_job_status,
)
from app.domain.candidates.models import Candidate
from app.domain.jobs import criteria
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager
from app.domain.jobs.schemas import JobCreate, JobUpdate
from app.domain.verification import service as verification
from app.domain.verification.schemas import ProposedChange


async def list_jobs(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int = 100,
    status: str | None = None,
) -> list[Job]:
    """The workspace's mandates, optionally one status only.

    Filtering here rather than in the browser is the half of ELI-7 that was
    missing: the list is capped at `limit`, so a screen that filters what
    already arrived shows "the active ones among the first hundred" and
    labels them the active ones.
    """
    stmt = select(Job).where(Job.tenant_id == tenant_id)
    if status:
        # Every spelling that means it — see `job_status_spellings`. A row
        # still saying "closed" is an inactive mandate, and a filter that
        # misses it is worse than one that errors.
        stmt = stmt.where(Job.status.in_(job_status_spellings(status)))
    result = await session.execute(stmt.order_by(Job.title).limit(limit))
    return list(result.scalars().all())


async def get_job(
    session: AsyncSession, *, tenant_id: uuid.UUID, job_id: uuid.UUID
) -> Job | None:
    result = await session.execute(
        select(Job).where(Job.tenant_id == tenant_id, Job.id == job_id)
    )
    return result.scalar_one_or_none()


#: Columns that are UUIDs. `model_dump(mode="json")` hands them over as
#: strings, and SQLAlchemy's UUID type then raises on `value.hex` — a set
#: rather than an `if` per field, because the first one to be forgotten here
#: fails at write time and only for the one endpoint that patches it.
_UUID_FIELDS = frozenset({"client_company_id", "manager_id"})


class ContactNotAtClient(Exception):
    """The Ansprechpartner does not work at this mandate's client.

    Raised rather than silently storing it. A mandate whose contact belongs to
    a different company sends the shortlist to the wrong person, and the row
    would look perfectly valid afterwards — `manager_id` is a UUID either
    way. The tenant check is the same guard one level up.
    """


async def _check_contact(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID | None,
    company_id: uuid.UUID | None,
) -> None:
    """A contact must exist in this tenant and work at this client."""
    if manager_id is None:
        return
    manager = await session.scalar(
        select(Manager).where(Manager.tenant_id == tenant_id, Manager.id == manager_id)
    )
    if manager is None:
        raise ContactNotAtClient("contact not found in this workspace")
    if company_id is not None and manager.company_id != company_id:
        raise ContactNotAtClient("contact does not work at this client")


async def create_job(session: AsyncSession, *, data: JobCreate) -> Job:
    tenant_id = data.tenant_id or settings.default_tenant_id
    await _check_contact(
        session,
        tenant_id=tenant_id,
        manager_id=data.manager_id,
        company_id=data.client_company_id,
    )
    job = Job(
        tenant_id=tenant_id,
        title=data.title,
        client_company_id=data.client_company_id,
        manager_id=data.manager_id,
        location=data.location,
        location_radius_km=data.location_radius_km,
        must_have_skills=data.must_have_skills,
        required_certifications=data.required_certifications,
        requires_work_permit=data.requires_work_permit,
        salary_min=data.salary_min,
        salary_max=data.salary_max,
        salary_currency=data.salary_currency,
        status=data.status,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


#: What a copy carries over: the Suchprofil, which is the thing worth reusing.
#:
#: Deliberately NOT copied. `status`, because a copy of a finished mandate
#: that arrives finished is of no use to anybody. `external_id` /
#: `external_source`, because they are unique per (tenant, source, id) and a
#: copy holding them would make the next ATS import write into the copy
#: instead of the row it imported. And everything hanging off the mandate —
#: applications, process steps, briefings, feedback, receipts — because a
#: copy is a fresh search, not a fork of a history that happened to other
#: people.
_COPIED_FIELDS = (
    "title",
    "client_company_id",
    "manager_id",
    "location",
    "location_radius_km",
    "must_have_skills",
    "required_certifications",
    "requires_work_permit",
    "salary_min",
    "salary_max",
    "salary_currency",
)


def _fresh(value: object) -> object:
    """A list column is copied, not shared.

    `must_have_skills` is a mutable list. Handing the same object to two rows
    means editing one mandate's Muss-Kriterien silently edits the other's —
    and those are hard filters, so it changes who a different client is shown.
    """
    return list(value) if isinstance(value, list) else value


async def copy_job(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    title: str | None = None,
) -> Job | None:
    """A new mandate from an old one's Suchprofil (ELI-7).

    This is what makes "inaktiv ist endgültig" livable. The band, the radius,
    the Muss-Kriterien and the Ansprechpartner are the hour of work nobody
    wants to repeat, and re-typing them is how the second search arrives
    subtly different from the one that worked.

    The copy is always ACTIVE, and copying an inactive mandate is the main
    case — not an edge one.

    Returns None if the mandate does not exist for this tenant.
    """
    source = await get_job(session, tenant_id=tenant_id, job_id=job_id)
    if source is None:
        return None

    copy = Job(
        tenant_id=tenant_id,
        status=JobStatus.ACTIVE.value,
        copied_from_job_id=source.id,
        **{field: _fresh(getattr(source, field)) for field in _COPIED_FIELDS},
    )
    if title and title.strip():
        copy.title = title.strip()
    session.add(copy)
    await session.commit()
    await session.refresh(copy)
    return copy


class InvalidBand(ValueError):
    """The salary band does not describe a range."""


class ReopeningRefused(Exception):
    """An inactive mandate cannot be made active again (ELI-7).

    The recruiters' own words: "inaktiv kann nicht wieder geöffnet werden,
    muss neu angelegt werden". The point is not tidiness — a mandate carries
    a pipeline, briefings, feedback and a shortlist that were all about one
    search. Reopening it continues that search on paper while the client has
    run a new one, and the dates on the old process then describe the new
    one. `copy_job` is the way back: same Suchprofil, own history.
    """


#: Columns that must never be NULLed by a PATCH (NOT NULL in the schema).
_NON_NULLABLE = frozenset(
    {"title", "salary_currency", "status", "requires_work_permit"}
)

#: Allowed mandate states. Free text here would make the Jobs list's status
#: chips — and the cockpit's "open mandates" count — mean nothing. The set
#: itself lives in `common.enums.JobStatus`, which explains why it is these
#: three.
JOB_STATUSES = tuple(s.value for s in JobStatus)


def _as_text(value: object) -> str | None:
    """Serialise a proposed value for the provenance record (Text column)."""
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


async def update_job(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    patch: JobUpdate,
    editor: str | None = None,
) -> Job | None:
    """Edit a mandate, one verified change per field.

    Same discipline as a candidate edit: each changed field goes through
    `verify_and_commit` as a HUMAN_VERIFIED proposal, so the audit trail
    answers "who widened the salary cap, and when". That matters more here
    than on a candidate — the band and the radius are hard filters, and
    quietly moving one changes which people a client is shown.

    Returns None if the mandate does not exist for this tenant.
    """
    job = await get_job(session, tenant_id=tenant_id, job_id=job_id)
    if job is None:
        return None

    changes = patch.model_dump(exclude_unset=True, mode="json")

    # Validate against the RESULTING row, not the payload: sending only a new
    # floor must still be checked against the ceiling already stored.
    resulting_min = changes.get("salary_min", job.salary_min)
    resulting_max = changes.get("salary_max", job.salary_max)
    if (
        resulting_min is not None
        and resulting_max is not None
        and resulting_min > resulting_max
    ):
        raise InvalidBand("salary_min must not exceed salary_max")
    status_value = changes.get("status")
    if status_value is not None:
        # Normalise BEFORE validating. A row migration 0039 has not reached
        # still holds "open", and the editor sends `status` back on every
        # save — refusing the value the row itself carries is exactly how 18
        # of 79 mandates became unsaveable the last time this changed.
        # Anything that is neither current nor a stored legacy spelling
        # passes through unchanged and is refused here.
        status_value = normalise_job_status(status_value)
        if status_value not in JOB_STATUSES:
            raise InvalidBand(f"unknown status {status_value!r}")
        changes["status"] = status_value
        if (
            normalise_job_status(job.status) == JobStatus.INACTIVE.value
            and status_value == JobStatus.ACTIVE.value
        ):
            raise ReopeningRefused(
                "Ein inaktives Mandat kann nicht wieder aktiviert werden. "
                "Legen Sie es als Kopie neu an."
            )

    # Same rule as on create, and against the RESULTING row: moving a mandate
    # to another client with its old contact still attached would leave the
    # shortlist addressed to someone at the previous company.
    if "manager_id" in changes or "client_company_id" in changes:
        resulting_contact = changes.get("manager_id", job.manager_id)
        resulting_client = changes.get("client_company_id", job.client_company_id)
        await _check_contact(
            session,
            tenant_id=tenant_id,
            manager_id=uuid.UUID(str(resulting_contact)) if resulting_contact else None,
            company_id=uuid.UUID(str(resulting_client)) if resulting_client else None,
        )

    detail = f"manual edit via recruiter UI ({editor})" if editor else (
        "manual edit via recruiter UI"
    )
    for field, new_value in changes.items():
        if field in _NON_NULLABLE and (
            new_value is None or (isinstance(new_value, str) and not new_value.strip())
        ):
            continue
        current = getattr(job, field, None)
        # The payload is JSON-moded, so a uuid column arrives as a string.
        if str(current) == str(new_value) or current == new_value:
            continue

        change = ProposedChange(
            tenant_id=tenant_id,
            entity_type="job",
            entity_id=job_id,
            field=field,
            proposed_value=_as_text(new_value),
            source=ConfidenceSource.HUMAN_VERIFIED,
            source_detail=detail,
            confidence=1.0,
        )

        async def _apply(
            _session: AsyncSession,
            _change: ProposedChange,
            _field: str = field,
            _value: object = new_value,
        ) -> None:
            if _field in _UUID_FIELDS and _value is not None:
                _value = uuid.UUID(str(_value))
            setattr(job, _field, _value)

        await verification.verify_and_commit(
            session,
            change=change,
            agent="recruiter_manual_edit",
            apply_hook=_apply,
            actor=editor,
        )

    await session.commit()
    await session.refresh(job)
    return job


async def criteria_suggestions(
    session: AsyncSession, *, tenant_id: uuid.UUID, job: Job, limit: int = 8
) -> list[criteria.Suggestion]:
    """Muss-Kriterien this mandate's own title already names.

    The vocabulary is the workspace's candidates, not a canned skill list:
    a criterion is only useful if it matches the way this pool writes things
    down, and a term nobody carries filters everyone out.

    Proposals, never writes — the recruiter clicks the ones that are really
    non-negotiable, which is the same rule the agents follow.
    """
    rows = await session.execute(
        select(Candidate.skills).where(Candidate.tenant_id == tenant_id)
    )
    vocabulary = criteria.normalise_vocabulary(
        [skill for (skills,) in rows for skill in (skills or [])]
    )
    return criteria.suggest_must_have(
        job.title,
        vocabulary,
        already=list(job.must_have_skills or []),
        limit=limit,
    )
