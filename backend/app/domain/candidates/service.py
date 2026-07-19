"""Candidate business logic. Tenant isolation is enforced on every query."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.candidates.models import Candidate
from app.domain.candidates.schemas import CandidateCreate


async def list_candidates(
    session: AsyncSession, *, tenant_id: uuid.UUID, limit: int = 100
) -> list[Candidate]:
    result = await session.execute(
        select(Candidate)
        .where(Candidate.tenant_id == tenant_id)
        .order_by(Candidate.full_name)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_candidate(
    session: AsyncSession, *, tenant_id: uuid.UUID, candidate_id: uuid.UUID
) -> Candidate | None:
    result = await session.execute(
        select(Candidate).where(
            Candidate.tenant_id == tenant_id,
            Candidate.id == candidate_id,
        )
    )
    return result.scalar_one_or_none()


async def create_candidate(
    session: AsyncSession, *, data: CandidateCreate
) -> Candidate:
    tenant_id = data.tenant_id or settings.default_tenant_id
    candidate = Candidate(
        tenant_id=tenant_id,
        full_name=data.full_name,
        email=data.email,
        phone=data.phone,
        current_title=data.current_title,
        current_company=data.current_company,
        location=data.location,
        merged_identities=data.merged_identities,
        skills=data.skills,
        work_history=data.work_history,
        salary_expectation=data.salary_expectation,
        salary_currency=data.salary_currency,
        availability_weeks=data.availability_weeks,
        work_permit=data.work_permit,
        # Extended profile (aiFind field set) — persisted so the dossier fills in.
        first_name=data.first_name,
        last_name=data.last_name,
        sex=data.sex,
        name_prefix=data.name_prefix,
        date_of_birth=data.date_of_birth,
        street=data.street,
        postal_code=data.postal_code,
        city=data.city,
        country=data.country,
        linkedin_url=data.linkedin_url,
        xing_url=data.xing_url,
        industry=data.industry,
        employment_type=data.employment_type,
        willing_to_relocate=data.willing_to_relocate,
        notice_period=data.notice_period,
        availability=data.availability,
        total_years_experience=data.total_years_experience,
        current_salary=data.current_salary,
        languages=data.languages,
        education=data.education,
        working_experience=data.working_experience,
        motivation=data.motivation,
        source=data.source,
    )
    session.add(candidate)
    await session.flush()
    await session.commit()
    await session.refresh(candidate)
    return candidate