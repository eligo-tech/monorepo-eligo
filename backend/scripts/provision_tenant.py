"""Admit a Clerk organization — give it a workspace.

Since admission stopped being a side effect of signing in (ADR 0002 §7.3), a
new organization reaches 403 until somebody runs this. That somebody is the
point: a workspace in the production database is now a decision with a name on
it, not something a stranger can mint by clicking "create organization".

    # who is admitted today
    .venv/bin/python -m scripts.provision_tenant --list

    # admit one
    .venv/bin/python -m scripts.provision_tenant org_2abc… "Eligo Labs"

The org id is in the refusal the backend logged, and in the Clerk dashboard
under Organizations. Idempotent: re-running on an admitted org only updates
the label.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AdminSessionLocal as SessionLocal
from app.domain.tenants import service as tenants_service
from app.domain.tenants.models import Tenant


async def _list() -> None:
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(Tenant).order_by(Tenant.created_at))
        ).scalars().all()
    if not rows:
        print("no organizations are admitted yet.")
        return
    print(f"{len(rows)} organization(s) admitted:\n")
    for t in rows:
        print(f"  {t.clerk_org_id:34} {t.name or '—':28} tenant={t.id}")


async def _provision(clerk_org_id: str, name: str | None) -> None:
    async with SessionLocal() as session:
        existing = await tenants_service.get(session, clerk_org_id=clerk_org_id)
        tenant = await tenants_service.get_or_create(
            session, clerk_org_id=clerk_org_id, name=name
        )
    verb = "already admitted" if existing is not None else "ADMITTED"
    print(f"{verb}: {clerk_org_id} → tenant {tenant.id} ({tenant.name or '—'})")
    if existing is None:
        print(
            "\nThe workspace is empty. Everyone Clerk shows as a member of this "
            "organization can now sign in and will share it."
        )


def _usage() -> None:
    sys.exit(
        "usage:\n"
        "  python -m scripts.provision_tenant --list\n"
        '  python -m scripts.provision_tenant <clerk_org_id> ["Display name"]'
    )


async def main() -> None:
    args = sys.argv[1:]
    if not args:
        _usage()
    if args[0] in {"--list", "-l"}:
        await _list()
        return
    org_id = args[0]
    # Guard the commonest slip: a Clerk USER id admits nothing and the mistake
    # is invisible afterwards — the workspace exists, and the people who were
    # supposed to get it still see 403.
    if not org_id.startswith("org_"):
        sys.exit(
            f"'{org_id}' is not a Clerk organization id (they start with 'org_'). "
            "A user id or a slug here would create a workspace nobody can reach."
        )
    if not settings.auth_enabled:
        print(
            "! ELIGO_AUTH_ENABLED is false here, so this process serves every "
            "request as the default tenant. Provisioning still works; just be "
            "sure you are pointed at the right database."
        )
    await _provision(org_id, args[1] if len(args) > 1 else None)


if __name__ == "__main__":
    asyncio.run(main())
