"""Call outcomes on the contact history: `manager_interactions.outcome` and
`next_action_at` (ELI-22 call list).

A call is already an interaction row; the call list needs how it ended
(`CallOutcome`) and when to call again. Both nullable, no default:
metadata-only on Postgres. The follow-up queue index is partial (most
interactions have no next call). Tenant table — RLS is already on it
(0003/0005); new columns need no policy of their own.

Revision ID: 0060
Revises: 0059
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "manager_interactions"
_INDEX = "ix_manager_interactions_next_action"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return  # fresh database: create_all already has it
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    if "outcome" not in existing:
        op.add_column(_TABLE, sa.Column("outcome", sa.String(30), nullable=True))
    if "next_action_at" not in existing:
        op.add_column(_TABLE, sa.Column("next_action_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX} ON {_TABLE} (tenant_id, next_action_at) "
        "WHERE next_action_at IS NOT NULL"
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    for name in ("next_action_at", "outcome"):
        if name in existing:
            op.drop_column(_TABLE, name)
