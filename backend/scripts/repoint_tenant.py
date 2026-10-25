"""Point an existing workspace at a different Clerk organization.

Moving a Clerk instance from development to production mints NEW
organization ids. The data does not move — it never left — but the mapping
that reaches it does: `tenants.clerk_org_id` still names the old
organization, so the signed-in user presents an id the backend has never
seen and gets either a 403 or, with auto-provisioning on, a brand new empty
workspace. The second is worse: an empty cockpit reads as "our data is
gone" where a block reads as "call somebody".

This is the one row that fixes it. Nothing is copied and no business data
is touched; only the key that says which organization owns the workspace.

    # what would change
    .venv/bin/python -m scripts.repoint_tenant c895a6e0-… org_3LBq…

    # do it
    .venv/bin/python -m scripts.repoint_tenant c895a6e0-… org_3LBq… --apply

Dry-run by default, for the same reason `normalise_interaction_types` is:
the argument is an opaque id, a typo is invisible, and the consequence is a
workspace nobody can reach.
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from sqlalchemy import select

from app.core.database import AdminSessionLocal as SessionLocal
from app.domain.tenants.models import Tenant


def _usage() -> None:
    print(__doc__)
    raise SystemExit(2)


async def _repoint(target: str, new_org_id: str, apply: bool) -> None:
    async with SessionLocal() as session:
        rows = (await session.execute(select(Tenant))).scalars().all()

        # Accept either the tenant's uuid or the organization id it has
        # today, because both are things somebody actually has to hand.
        try:
            wanted = uuid.UUID(target)
            tenant = next((t for t in rows if t.id == wanted), None)
        except ValueError:
            tenant = next((t for t in rows if t.clerk_org_id == target), None)

        if tenant is None:
            print(f"no workspace matches {target!r}. Known:\n")
            for t in rows:
                print(f"  {t.clerk_org_id:34} {t.name or '—':28} tenant={t.id}")
            raise SystemExit(1)

        if tenant.clerk_org_id == new_org_id:
            print(f"already pointed at {new_org_id} — nothing to do.")
            return

        # The uniqueness that matters: two workspaces claiming one
        # organization means whichever row is found first wins, silently.
        clash = next(
            (t for t in rows if t.clerk_org_id == new_org_id and t.id != tenant.id),
            None,
        )
        if clash is not None:
            print(
                f"REFUSED: {new_org_id} already belongs to tenant {clash.id} "
                f"({clash.name or '—'}).\n"
                "Re-pointing would leave two workspaces claiming one "
                "organization. Delete or re-point that one first."
            )
            raise SystemExit(1)

        print(f"workspace : {tenant.id}  ({tenant.name or '—'})")
        print(f"      was : {tenant.clerk_org_id}")
        print(f"      now : {new_org_id}")

        if not apply:
            print("\n(dry run — pass --apply to write it)")
            return

        tenant.clerk_org_id = new_org_id
        await session.commit()
        print("\nre-pointed. The organization sees its data on the next request.")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        _usage()
    asyncio.run(_repoint(args[0], args[1], apply="--apply" in sys.argv[1:]))


if __name__ == "__main__":
    main()
