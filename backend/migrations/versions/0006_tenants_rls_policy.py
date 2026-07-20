"""Permissive RLS policy on `tenants` so the app role can resolve org → tenant.

`tenants` is the pre-auth mapping table (clerk_org_id → tenant_id). It is read
(and created) *before* any tenant is pinned, so — unlike the data tables — it
cannot be scoped by `app.current_tenant`; it is the thing that *defines* the
tenant. Supabase auto-enables RLS on new tables, and RLS enabled with **no
policy** is default-deny. That was invisible while the app connected as the
BYPASSRLS owner, but the fail-closed change makes it connect as the NOBYPASSRLS
`eligo_app` role — which then can neither SELECT its existing tenant nor INSERT a
new one, 500-ing every request in `tenants.get_or_create`.

Add a permissive policy so the app role can look up and create its own tenant
mapping. The tenant-scoped DATA tables keep their strict `tenant_isolation`
policies (0003/0005) — isolation of candidates/jobs/etc. is unchanged.

Revision ID: 0006
Revises: 0005
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # Idempotent: RLS may already be enabled (Supabase) or not (plain Postgres).
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenants_app_all ON tenants")
    op.execute("CREATE POLICY tenants_app_all ON tenants USING (true) WITH CHECK (true)")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS tenants_app_all ON tenants")
