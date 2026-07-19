"""Extend Row-Level Security to the tables added after 0003.

0003 enabled RLS on the original tenant-scoped tables; `candidate_documents`
(0004) and `match_receipts` also carry a `tenant_id` and must be isolated too.
Same policy shape: rows are visible/writable only when their `tenant_id` matches
the per-transaction `app.current_tenant` GUC the backend sets. Postgres-only.

Revision ID: 0005
Revises: 0004
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ["candidate_documents", "match_receipts"]
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
