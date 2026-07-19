"""Tenant resolution — get-or-create by Clerk org id."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tenants.models import Tenant


async def get_or_create(
    session: AsyncSession, *, clerk_org_id: str, name: str | None = None
) -> Tenant:
    """Return the tenant for a Clerk org, creating it on first sight."""
    result = await session.execute(
        select(Tenant).where(Tenant.clerk_org_id == clerk_org_id)
    )
    tenant = result.scalar_one_or_none()
    if tenant is not None:
        return tenant
    tenant = Tenant(clerk_org_id=clerk_org_id, name=name)
    session.add(tenant)
    await session.flush()  # assigns id
    # Commit immediately: the org→tenant mapping must survive the request that
    # first sees this org. Without this it is rolled back at request end, so each
    # request would mint a NEW tenant id and every tenant-scoped query would miss.
    await session.commit()
    return tenant
