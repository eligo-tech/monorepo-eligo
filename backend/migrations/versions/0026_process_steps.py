"""The recruiter's tracker, as data: one row per process step.

`docs/process_design` describes a nine-step checklist per candidate per job,
and the spreadsheet it came from records a date when the candidate was
presented, a date per interview round, and a green/red cell after each round.
`applications.stage` could hold none of that — "interview" cannot say when, nor
that the client already said no.

So: one row per (application, step), carrying `scheduled_at`, `done_at`,
`outcome` and a note. The coarse Kanban stage stays on `applications` and is
DERIVED from these rows, so the board can never contradict the process.

Revision ID: 0026
Revises: 0025
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    bind = op.get_bind()
    if "process_steps" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "process_steps",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column(
                "application_id",
                sa.Uuid(),
                sa.ForeignKey("applications.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("step_key", sa.String(40), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("outcome", sa.String(10), nullable=False, server_default="open"),
            sa.Column("note", sa.Text(), nullable=True),
            # server_default, or an insert that does not name the column
            # fails — see 0027 for the migration that forgot it.
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.UniqueConstraint("application_id", "step_key", name="uq_process_step"),
        )

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE process_steps ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE process_steps FORCE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON process_steps")
        op.execute(
            "CREATE POLICY tenant_isolation ON process_steps "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    if "process_steps" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("process_steps")
