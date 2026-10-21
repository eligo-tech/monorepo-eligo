"""Candidate notices — what a person was told, and what they answered.

One tenant-scoped table. It holds a name, an email address and a record of a
decision about that person's data, so it gets RLS ENABLED and FORCED with the
same fail-closed predicate as every other tenant table.

The token is UNIQUE across all workspaces, not per tenant: it is the only
credential on the public opt-in endpoints, so a collision would be a
cross-workspace one.

Revision ID: 0038
Revises: 0037
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_TABLE = "candidate_notices"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column(
                "candidate_id",
                sa.Uuid(),
                sa.ForeignKey("candidates.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("email", sa.String(320), nullable=False),
            sa.Column("token", sa.String(64), nullable=False, unique=True, index=True),
            sa.Column(
                "status", sa.String(20), nullable=False, server_default="pending",
                index=True,
            ),
            sa.Column("subject", sa.String(300), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("provider", sa.String(40), nullable=True),
            sa.Column("provider_message_id", sa.String(200), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failure_reason", sa.String(500), nullable=True),
            sa.Column("requested_by", sa.String(120), nullable=True),
            sa.Column("requested_by_user_id", sa.String(120), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
        )

    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {_TABLE} "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
