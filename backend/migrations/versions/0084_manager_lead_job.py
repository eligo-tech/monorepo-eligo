"""ELI-65: the job of a lead entered by hand.

- `managers.lead_job_title` — the vacancy a lead created with "+ Lead" is
  about (a job Markt does not hold, from a job ad elsewhere or a LinkedIn
  profile). NULL for every existing row: none of them was entered that way.

A column on an existing tenant table: its fail-closed RLS policy already
covers it, so no policy changes here.

Revision ID: 0084
Revises: 0083
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0084"
down_revision: str | None = "0083"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("managers")}
    if "lead_job_title" not in have:
        op.add_column("managers", sa.Column("lead_job_title", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("managers", "lead_job_title")
