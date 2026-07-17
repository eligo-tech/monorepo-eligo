"""Job business logic."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.jobs.models import Job
from app.domain.jobs.schemas import JobCreate


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