"""Supabase's public API roles hold nothing on our tables (review 2026-10-31 #5 D).

Supabase gives `anon` and `authenticated` — the roles its HTTP Data API runs
as — full rights on every table in `public`, TRUNCATE included, through
default privileges on the role that creates our tables (`postgres`). Eligo
never uses either role. RLS already refuses them every row; TRUNCATE ignores
RLS. Migration 0051 removes the rights and the defaults that hand them out.

CI's Postgres has no Supabase roles, so this test creates them, grants what
Supabase grants, runs 0051's statements and checks nothing is left — on the
existing tables AND on a table created afterwards. Skipped off Postgres.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.database import admin_engine, engine

pytestmark = pytest.mark.skipif(not settings.is_postgres, reason="Postgres only")

ROLES = ("anon", "authenticated")


@pytest.fixture(autouse=True)
async def _fresh_db():
    yield
    await engine.dispose()
    await admin_engine.dispose()


def _migration():
    path = Path(__file__).parents[1] / "migrations/versions/0051_revoke_public_api_roles.py"
    spec = importlib.util.spec_from_file_location("m0051", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _privileges(conn, role: str) -> list[str]:
    rows = await conn.execute(
        text(
            "SELECT table_name || ':' || privilege_type FROM information_schema.role_table_grants "
            "WHERE table_schema = 'public' AND grantee = :r"
        ),
        {"r": role},
    )
    return [r for (r,) in rows.all()]


async def test_the_public_api_roles_end_with_nothing_now_or_later() -> None:
    async with admin_engine.begin() as conn:
        for role in ROLES:
            await conn.execute(text(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                f"THEN CREATE ROLE {role} NOLOGIN; END IF; END $$"
            ))
            # What Supabase does: everything now, everything by default later.
            await conn.execute(text(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {role}"))
            await conn.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {role}"))
        assert await _privileges(conn, "anon"), "setup did not grant anything"

        for statement in _migration().statements(ROLES):
            await conn.execute(text(statement))

        await conn.execute(text("CREATE TABLE IF NOT EXISTS probe_after_0051 (id int)"))
        try:
            for role in ROLES:
                assert await _privileges(conn, role) == [], role
        finally:
            await conn.execute(text("DROP TABLE IF EXISTS probe_after_0051"))
