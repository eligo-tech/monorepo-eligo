"""Bus-Dev-Kontakte: `managers.stage` and `promoted_at` (ELI-23).

A person taken from Markt (a public ad) is a new business-development contact,
not yet a vetted manager; the recruiter moves them to Managers after the first
contact. `stage` is "bus_dev" | "manager" on the same record — nothing is
copied or deleted on the move.

Existing rows: everything is a manager (imports, hand-entered) except contacts
that came from a public ad (`source = 'public_web'`), which become bus-dev —
that is where the product owner expects them (3 rows in production).

Server default 'manager' keeps the ADD COLUMN metadata-only on Postgres.
`managers` is a tenant table with RLS already (0003/0005).

Revision ID: 0062
Revises: 0061
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0062"
down_revision: str | None = "0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "managers"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    if "stage" not in existing:
        op.add_column(_TABLE, sa.Column("stage", sa.String(20), nullable=False, server_default="manager"))
        op.execute(f"UPDATE {_TABLE} SET stage = 'bus_dev' WHERE source = 'public_web'")
    if "promoted_at" not in existing:
        op.add_column(_TABLE, sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_managers_tenant_stage ON {_TABLE} (tenant_id, stage)")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    op.execute("DROP INDEX IF EXISTS ix_managers_tenant_stage")
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    for name in ("promoted_at", "stage"):
        if name in existing:
            op.drop_column(_TABLE, name)
