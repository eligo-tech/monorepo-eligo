"""Supabase's public API roles lose every right on our tables.

`anon` and `authenticated` are the roles Supabase's HTTP Data API runs as.
Supabase grants them everything on every table in `public` — select, insert,
update, delete, TRUNCATE — through default privileges on the role that
creates our tables (`postgres`; read 2026-11-03: 31 tables). Eligo never uses
either role: the frontend has no Supabase client, the API connects as
`eligo_app`. RLS already refuses them every row, but TRUNCATE ignores RLS and
row triggers, so this removes the rights instead of relying on nobody
reaching them.

Two parts, both for each role that exists (none do in CI or locally, where
this is a no-op):
1. revoke what they hold on every table and sequence in `public` today;
2. revoke the default privileges `postgres` hands them on future ones.

Production, read 2026-11-03: all 32 tables in `public` are owned by
`postgres` and there are no sequences, so every REVOKE acts on rights
`postgres` itself granted. Function EXECUTE stays: harmless without any table
right, and extension functions in `public` belong to other owners.

`service_role` is left alone on purpose (decided 2026-11-03): it is
Supabase's own admin path and bypasses RLS by design — its key must stay
secret. Defaults owned by `supabase_admin` cover only objects that role
creates; ours are created by `postgres`.

Revision ID: 0051
Revises: 0050
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES = ("anon", "authenticated")


def statements(roles: Sequence[str]) -> list[str]:
    out: list[str] = []
    for role in roles:
        out += [
            f'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM "{role}"',
            f'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM "{role}"',
            # Without FOR ROLE this is the current user — the one that runs
            # migrations and so creates every table.
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM "{role}"',
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM "{role}"',
        ]
    return out


def _existing(bind) -> list[str]:  # noqa: ANN001
    rows = bind.execute(
        sa.text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:r)"), {"r": list(ROLES)}
    ).all()
    return [r for (r,) in rows]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for statement in statements(_existing(bind)):
        op.execute(statement)


def downgrade() -> None:
    """Back to what Supabase sets up — broader than before 0051 in one way:
    it re-grants on every table, including the ones 0047 and 0050 had
    narrowed for these roles."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for role in _existing(bind):
        op.execute(f'GRANT ALL ON ALL TABLES IN SCHEMA public TO "{role}"')
        op.execute(f'GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO "{role}"')
        op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{role}"')
        op.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "{role}"')
