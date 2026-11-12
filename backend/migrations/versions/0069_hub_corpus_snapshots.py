"""Markt's corpus totals and filter counts, stored: `hub_corpus_snapshots`.

The weekly job computes them (37 s filters, 12.5 s totals cold on prod,
2026-11-12) and Markt reads one row, so a restart no longer makes the first
Markt load count the whole corpus. One row per name (stats · facets).

Shared corpus, derived — aggregate counts, no tenant_id, no personal data —
with the same permissive `shared_corpus_read` policy as the other hub tables;
the Data API roles are revoked (see 0051). The runtime role gets its grants
from the default privileges (`scripts/apply_rls.py`).

Revision ID: 0069
Revises: 0068
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0069"
down_revision: str | None = "0068"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_corpus_snapshots"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():  # else create_all made it
        op.create_table(
            _TABLE,
            sa.Column("name", sa.String(40), primary_key=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        )
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS shared_corpus_read ON {_TABLE}")
    op.execute(f"CREATE POLICY shared_corpus_read ON {_TABLE} USING (true) WITH CHECK (true)")
    for role in ("anon", "authenticated"):
        if bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar():
            op.execute(f"REVOKE ALL ON {_TABLE} FROM {role}")


def downgrade() -> None:
    # Derived numbers: Markt computes live until the next refresh.
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
