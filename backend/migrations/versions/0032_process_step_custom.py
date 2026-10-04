"""A process may add a step of its own, and take one out.

The nine steps of `docs/process_design` are what every placement shares. A
Probearbeitstag, an Assessment Center, a second site visit are ordinary and
frequent, and a fixed checklist sends the recruiter back to the spreadsheet
for exactly the row that does not fit.

Two columns carry it:

* `label` — only a custom step has one. The canonical nine keep taking their
  label from `pipeline/steps.py`, so renaming one there still renames it
  everywhere at once.
* `active` — false when this process does not have the step. A removed
  CANONICAL step must leave a row behind: the nine are a template every
  process starts from, and with no row the template would put it straight
  back. Deactivating rather than deleting also keeps whatever was recorded,
  so adding the step again is not a loss.

Both are additive and nullable/defaulted, so the container still serving
during the deploy reads the table unchanged (expand/contract —
ARCHITECTURE.md §5).

Revision ID: 0032
Revises: 0031
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns("process_steps")}


def upgrade() -> None:
    bind = op.get_bind()
    if "process_steps" not in sa.inspect(bind).get_table_names():
        return  # fresh database: create_all already has both columns
    have = _columns(bind)
    if "label" not in have:
        op.add_column(
            "process_steps", sa.Column("label", sa.String(length=80), nullable=True)
        )
    if "active" not in have:
        op.add_column(
            "process_steps",
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    have = _columns(bind)
    if "active" in have:
        op.drop_column("process_steps", "active")
    if "label" in have:
        op.drop_column("process_steps", "label")
