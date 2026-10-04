"""Two numbers instead of one that meant neither.

`verification_score` was computed by exactly one write path — the manual
edit — so on the live workspace 446 of 447 candidates scored 0.0 and the
cockpit rendered a column headed "Verif." that was 0% for everybody. And
what it computed was the share of key fields that had a VALUE, which is
completeness, not verification.

They are now separate and both honest:

* `verification_score` — share of key fields with EVIDENCE behind them: a
  committed enrichment record naming a source a reader could check. An
  imported value has none, so an imported record scores 0 on purpose.
* `completeness_score` — share of key fields that have a value at all.

This migration adds the second column and backfills it from the rows; the
verified share is recomputed by `scripts/recompute_candidate_scores.py`,
which needs the enrichment records and is therefore a script, not a DDL
statement.

Revision ID: 0033
Revises: 0032
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "candidates" not in inspector.get_table_names():
        return  # fresh database: create_all already has the column
    if "completeness_score" in {c["name"] for c in inspector.get_columns("candidates")}:
        return
    op.add_column(
        "candidates",
        sa.Column(
            "completeness_score",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "completeness_score" in {
        c["name"] for c in sa.inspect(bind).get_columns("candidates")
    }:
        op.drop_column("candidates", "completeness_score")
