"""Tenant resolution by Clerk org id.

Two doors, deliberately different:

* :func:`get` — the REQUEST path. It looks the organization up and returns
  ``None`` when there is no workspace for it. Admission is somebody's decision,
  not a side effect of signing in.
* :func:`get_or_create` — the OPERATOR path, used by the provisioning script
  and the data-moving scripts, and by the request path only when
  ``ELIGO_AUTO_PROVISION_TENANTS`` is explicitly on.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tenants.models import Tenant


async def get(session: AsyncSession, *, clerk_org_id: str) -> Tenant | None:
    """The workspace for a Clerk org, or None if the org was never admitted."""
    result = await session.execute(
        select(Tenant).where(Tenant.clerk_org_id == clerk_org_id)
    )
    return result.scalar_one_or_none()


async def rename(session: AsyncSession, *, tenant: Tenant, name: str | None) -> Tenant:
    """Follow a Clerk org rename.

    The name is only ever a label — the mapping is `clerk_org_id`, which a
    rename does not touch — but a tenant list that still says "recruits-test"
    after the org became "eligo" is a list nobody trusts, and the drift is
    silent. Only written when it actually changed, so the common request still
    issues no UPDATE.
    """
    if name and tenant.name != name:
        tenant.name = name
        await session.commit()
    return tenant


async def get_or_create(
    session: AsyncSession, *, clerk_org_id: str, name: str | None = None
) -> Tenant:
    """Return the tenant for a Clerk org, creating it on first sight.

    Admits the organization. Only the operator path may call this — see the
    module docstring.
    """
    tenant = await get(session, clerk_org_id=clerk_org_id)
    if tenant is not None:
        return await rename(session, tenant=tenant, name=name)
    tenant = Tenant(clerk_org_id=clerk_org_id, name=name)
    session.add(tenant)
    await session.flush()  # assigns id
    # Commit immediately: the org→tenant mapping must survive the request that
    # first sees this org. Without this it is rolled back at request end, so each
    # request would mint a NEW tenant id and every tenant-scoped query would miss.
    await session.commit()
    return tenant
