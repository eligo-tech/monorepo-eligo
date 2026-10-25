"""Row-Level Security, proved against a real Postgres.

The rest of the suite runs on SQLite, which has no RLS at all. It proves the
QUERY layer — that `list_candidates` filters by `tenant_id` — and it cannot
prove the thing that matters more: that the DATABASE refuses when the
application forgets. ADR 0002 §6 records this as owed, and names the two
checks only a real Postgres can make.

The gap was not theoretical. On 2026-10-25 `activity_targets` reached the
production database through `create_all`, which makes tables but not
policies, and sat there as the only tenant table with `force=OFF`. The whole
suite was green. It was found by a human running `apply_rls --status` and
reading the output. `test_every_tenant_table_is_locked_down` below is that
reading, automated.

Skipped unless the database is Postgres, so `pytest` on a laptop is
unaffected.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.config import settings
from app.core.database import AdminSessionLocal, SessionLocal, admin_engine, engine
from app.domain import registry  # noqa: F401 — registers every model
from app.domain.common.mixins import TenantMixin
from app.core.database import Base
from app.domain.companies.models import Company

#: Exactly what  runs in production. `SET` itself
#: takes no bind parameters, which is why this is `set_config` and not the
#: more obvious statement.
_PIN = "SELECT set_config('app.current_tenant', :t, true)"

pytestmark = pytest.mark.skipif(
    not settings.is_postgres, reason="RLS exists only on Postgres"
)


@pytest.fixture(autouse=True)
async def _fresh_db():
    """Override the suite's drop/create fixture.

    Dropping the schema would take the RLS policies with it, and this module
    exists to inspect them. The CI job applies the schema and the policies
    once, before pytest runs.
    """
    yield
    # Both engines are module-level and pool their connections, while
    # pytest-asyncio gives each test its own event loop. A pooled asyncpg
    # connection handed to the next loop raises "Event loop is closed" —
    # a teardown artefact that looks exactly like a real failure. Disposing
    # after each test keeps the pools inside the loop that made them.
    await engine.dispose()
    await admin_engine.dispose()


def _tenant_tables() -> list[str]:
    """Every table carrying a tenant_id, read off the models.

    Derived, never hand-listed — a hand-written list is how eleven tables
    went unprotected once before (see `scripts/apply_rls.tenant_tables`).
    """
    return sorted(
        t.name
        for t in Base.metadata.sorted_tables
        if any(m is TenantMixin for m in getattr(t, "_eligo_mixins", []))
        or "tenant_id" in t.c
    )


async def _company(tenant: uuid.UUID, name: str) -> None:
    """Insert one row for `tenant`, as the owner.

    Through the ORM on purpose: `is_client` and `bd_signals` are NOT NULL
    with their defaults declared on the model, not in the database, so a
    hand-written INSERT breaks the day somebody adds another such column.

    The GUC is pinned even though this is the owner connection — FORCE means
    the policy applies to the owner too, which is the whole point of it.
    """
    async with AdminSessionLocal() as s:
        await s.execute(text(_PIN), {"t": str(tenant)})
        s.add(Company(tenant_id=tenant, name=name))
        await s.commit()


# ── the check that was missing ────────────────────────────────────────────


async def test_every_tenant_table_is_locked_down() -> None:
    """RLS on, FORCE on, and a tenant_isolation policy. All three, every table.

    FORCE is the one worth saying out loud: without it the table OWNER
    bypasses the policy, and the owner is who migrations and `create_all`
    connect as. A table with `rls=on force=off` looks protected in a casual
    check and is not.
    """
    expected = _tenant_tables()
    assert expected, "no tenant-scoped tables found — the introspection is wrong"

    async with admin_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "select c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "       count(p.polname) filter (where p.polname = 'tenant_isolation') "
                    "  from pg_class c "
                    "  join pg_namespace n on n.oid = c.relnamespace "
                    "  left join pg_policy p on p.polrelid = c.oid "
                    " where n.nspname = 'public' and c.relkind = 'r' "
                    " group by 1, 2, 3"
                )
            )
        ).all()
    state = {name: (rls, force, policies) for name, rls, force, policies in rows}

    broken = []
    for table in expected:
        if table not in state:
            broken.append(f"{table}: not in the database")
            continue
        rls, force, policies = state[table]
        if not rls:
            broken.append(f"{table}: RLS not enabled")
        if not force:
            broken.append(f"{table}: FORCE off — the owner bypasses the policy")
        if not policies:
            broken.append(f"{table}: no tenant_isolation policy")
    assert broken == [], "\n".join(broken)


# ── fail-closed ───────────────────────────────────────────────────────────


async def test_no_tenant_pinned_means_no_rows() -> None:
    """An unset GUC returns nothing, not everything.

    This is the property the whole design rests on. A bug that forgets to
    pin the tenant yields an empty screen — annoying, obvious, reported. The
    alternative failure mode is another customer's data on screen, and
    nobody reports that because it looks like data.
    """
    tenant = uuid.uuid4()
    await _company(tenant, "RLS probe")

    async with SessionLocal() as s:
        # No `app.current_tenant` set on this transaction at all.
        unpinned = await s.scalar(text("select count(*) from companies"))
        await s.execute(text(_PIN), {"t": str(tenant)})
        pinned = await s.scalar(text("select count(*) from companies"))

    assert unpinned == 0, "an unpinned connection could read rows"
    assert pinned == 1, "a pinned connection could not read its own row"


async def test_one_tenant_cannot_read_anothers_rows() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    await _company(a, "Tenant A GmbH")
    await _company(b, "Tenant B GmbH")

    async with SessionLocal() as s:
        await s.execute(text(_PIN), {"t": str(a)})
        names = (await s.execute(text("select name from companies"))).scalars().all()
    assert "Tenant B GmbH" not in names


async def test_a_write_cannot_land_in_another_tenant() -> None:
    """WITH CHECK, not just USING. Reading is half the boundary."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    async with SessionLocal() as s:
        await s.execute(text(_PIN), {"t": str(mine)})
        s.add(Company(tenant_id=theirs, name="smuggled"))
        # Named rather than a blind `Exception`: a typo in the INSERT would
        # also raise, and would pass a test that accepts anything.
        with pytest.raises(ProgrammingError) as refused:
            await s.commit()
    assert "row-level security" in str(refused.value).lower()


# ── the role the app connects as ──────────────────────────────────────────


async def test_the_app_role_cannot_bypass_rls() -> None:
    """`NOBYPASSRLS`, asserted rather than assumed.

    A role with BYPASSRLS makes every policy above decorative.
    """
    async with SessionLocal() as s:
        bypasses = await s.scalar(
            text("select rolbypassrls from pg_roles where rolname = current_user")
        )
        superuser = await s.scalar(
            text("select rolsuper from pg_roles where rolname = current_user")
        )
    assert bypasses is False, "the app role can bypass RLS"
    assert superuser is False, "the app connects as a superuser"


async def test_the_app_role_is_not_the_table_owner() -> None:
    """FORCE protects against the owner; this makes sure we are not it anyway.

    Belt and braces on purpose: FORCE has been switched off by accident
    once already, and on that day this assertion is the one still standing.
    """
    async with SessionLocal() as s:
        owner = await s.scalar(
            text(
                "select pg_get_userbyid(c.relowner) from pg_class c "
                "join pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname = 'public' and c.relname = 'companies'"
            )
        )
        me = await s.scalar(text("select current_user"))
    assert owner != me, f"the app connects as the table owner ({me})"
