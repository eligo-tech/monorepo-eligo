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
    return tenant
