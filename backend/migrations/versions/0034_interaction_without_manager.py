"""A briefing belongs to the mandate, not to a contact we may not have yet.

`manager_interactions.manager_id` was NOT NULL, so the conversation that
DEFINES a mandate (Prozess-Doku, Phase 2) could only be recorded once a
contact person existed. On the live workspace the showcase mandate reads
"Kein Ansprechpartner hinterlegt" — so the one thing a recruiter most wants
to write down after the briefing call was the one thing the schema refused.

Widening to NULL is additive and reversible in practice: every existing row
has a manager, and a row without one is a mandate-level note.

Revision ID: 0034
Revises: 0033
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "manager_interactions" not in inspector.get_table_names():
        return  # fresh database: create_all already has it nullable
    column = next(
        c
        for c in inspector.get_columns("manager_interactions")
        if c["name"] == "manager_id"
    )
    if column["nullable"]:
        return
    # SQLite cannot ALTER a column; create_all made it nullable there anyway.
    if bind.dialect.name == "sqlite":
        return
    op.alter_column(
        "manager_interactions",
        "manager_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    # Rows written against a mandate alone have no contact to point at;
    # dropping them is the only way back and is why this is not routine.
    op.execute("DELETE FROM manager_interactions WHERE manager_id IS NULL")
    op.alter_column(
        "manager_interactions",
        "manager_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
