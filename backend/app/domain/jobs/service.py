"""Job business logic."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.common.enums import ConfidenceSource
from app.domain.jobs.models import Job
from app.domain.jobs.schemas import JobCreate, JobUpdate
from app.domain.verification import service as verification
from app.domain.verification.schemas import ProposedChange


async def list_jobs(
    session: AsyncSession, *, tenant_id: uuid.UUID, limit: int = 100
) -> list[Job]:
    result = await session.execute(
        select(Job)
        .where(Job.tenant_id == tenant_id)
        .order_by(Job.title)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_job(
    session: AsyncSession, *, tenant_id: uuid.UUID, job_id: uuid.UUID
) -> Job | None:
    result = await session.execute(
        select(Job).where(Job.tenant_id == tenant_id, Job.id == job_id)
    )
    return result.scalar_one_or_none()


async def create_job(session: AsyncSession, *, data: JobCreate) -> Job:
    job = Job(
        tenant_id=data.tenant_id or settings.default_tenant_id,
        title=data.title,
        client_company_id=data.client_company_id,
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


class InvalidBand(ValueError):
    """The salary band does not describe a range."""


#: Columns that must never be NULLed by a PATCH (NOT NULL in the schema).
_NON_NULLABLE = frozenset(
    {"title", "salary_currency", "status", "requires_work_permit"}
)

#: Allowed mandate states. Free text here would make the Jobs list's status
#: chips — and the cockpit's "open mandates" count — mean nothing.
JOB_STATUSES = ("open", "on_hold", "filled", "cancelled")


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
    if status_value is not None and status_value not in JOB_STATUSES:
        raise InvalidBand(f"unknown status {status_value!r}")

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
            if _field == "client_company_id" and _value is not None:
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
