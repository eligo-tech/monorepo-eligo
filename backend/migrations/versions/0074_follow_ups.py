"""Wiedervorlagen: a dated to-do on a lead, a manager or a candidate (ELI-44).

One tenant table, `follow_ups`: due date (time optional), a short text,
open/done with who and when, who wrote it, and optionally the note it came
from. Exactly one person — `manager_id` (Leads are managers) or
`candidate_id` — enforced by a check constraint. Classification: tenant
personal data; erased with the person (`erasure.erase_manager` /
`erase_candidate`).

Fail-closed RLS like every tenant table, applied OUTSIDE the create branch:
`create_all` on startup makes tables without policies, so a database where
it ran first would otherwise keep this table unpoliced (see 0041, 0044).

Revision ID: 0074
Revises: 0073
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0074"
down_revision: str | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "follow_ups"
_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("manager_id", sa.Uuid(), sa.ForeignKey("managers.id", ondelete="CASCADE"), nullable=True),
            sa.Column("candidate_id", sa.Uuid(), sa.ForeignKey("candidates.id", ondelete="CASCADE"), nullable=True),
            sa.Column(
                "source_interaction_id", sa.Uuid(),
                sa.ForeignKey("manager_interactions.id", ondelete="SET NULL"), nullable=True,
            ),
            sa.Column("due_date", sa.Date(), nullable=False),
            sa.Column("due_time", sa.Time(), nullable=True),
            sa.Column("text", sa.String(500), nullable=False),
            sa.Column("status", sa.String(10), nullable=False, server_default="open"),
            sa.Column("origin", sa.String(10), nullable=False, server_default="manual"),
            sa.Column("created_by_user_id", sa.String(80), nullable=True),
            sa.Column("created_by_name", sa.String(160), nullable=True),
            sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("done_by_user_id", sa.String(80), nullable=True),
            sa.Column("done_by_name", sa.String(160), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("(manager_id IS NULL) <> (candidate_id IS NULL)", name="ck_follow_ups_one_person"),
        )
        op.create_index("ix_follow_ups_tenant_id", _TABLE, ["tenant_id"])
        op.create_index("ix_follow_ups_manager_id", _TABLE, ["manager_id"])
        op.create_index("ix_follow_ups_candidate_id", _TABLE, ["candidate_id"])
        op.create_index("ix_follow_ups_tenant_status_due", _TABLE, ["tenant_id", "status", "due_date"])

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
