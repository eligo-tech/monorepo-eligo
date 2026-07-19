"""Row-Level Security — isolate every tenant-scoped table by `tenant_id`.

Postgres only (no-op on SQLite). Policies match rows against the per-transaction
GUC `app.current_tenant`, which the backend sets from the authenticated tenant on
every transaction (see app/core/database.py). `FORCE` makes the policy apply even
to the table owner (the role the app connects as). `NULLIF(..., '')::uuid` makes
an unset GUC resolve to NULL → zero rows (fail-closed).

Activate together with the GUC-setting backend: applying this while a backend
that does NOT set `app.current_tenant` is live would hide all rows and block
writes. `alembic upgrade head` runs on deploy, alongside that backend.

Revision ID: 0003
Revises: 0002
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every table carrying a tenant_id.
_TABLES = ["candidates", "jobs", "companies", "applications", "receipts", "enrichment_records"]
_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for t in _TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for t in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
