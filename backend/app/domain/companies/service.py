"""Company business logic."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.companies.models import Company
from app.domain.companies.schemas import CompanyCreate


async def list_companies(
    session: AsyncSession, *, tenant_id: uuid.UUID, limit: int = 100
) -> list[Company]:
    result = await session.execute(
        select(Company)
        .where(Company.tenant_id == tenant_id)
        .order_by(Company.name)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_company(
    session: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> Company | None:
    result = await session.execute(
        select(Company).where(
            Company.tenant_id == tenant_id, Company.id == company_id
        )
    )
    return result.scalar_one_or_none()


async def create_company(
    session: AsyncSession, *, data: CompanyCreate
) -> Company:
    company = Company(
        tenant_id=data.tenant_id or settings.default_tenant_id,
        name=data.name,
        domain=data.domain,
        industry=data.industry,
        location=data.location,
        is_client=data.is_client,
        source=data.source,
        bd_signals=data.bd_signals,
    )
    session.add(company)
    await session.commit()
    await session.refresh(company)
    return company