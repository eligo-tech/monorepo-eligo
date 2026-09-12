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
        # Follow a rename. The name is only ever a label — the mapping is
        # `clerk_org_id`, which a rename does not touch — but a tenant list that
        # still says "recruits-test" after the org became "eligo" is a list
        # nobody trusts, and the drift is silent because this used to return
        # early. Only written when it actually changed, so the common request
        # still issues no UPDATE.
        if name and tenant.name != name:
            tenant.name = name
            await session.commit()
        return tenant
    tenant = Tenant(clerk_org_id=clerk_org_id, name=name)
    session.add(tenant)
    await session.flush()  # assigns id
    # Commit immediately: the org→tenant mapping must survive the request that
    # first sees this org. Without this it is rolled back at request end, so each
    # request would mint a NEW tenant id and every tenant-scoped query would miss.
    await session.commit()
    return tenant
