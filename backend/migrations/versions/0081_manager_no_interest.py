"""ELI-60: "Kein Interesse" on managers.

- `no_interest_at` — when a lead was called with the outcome "Kein
  Interesse". Hides them from the Leads list by default (filter "Kein
  Interesse"), shown on the manager and company pages and in Markt; cleared
  by "Wieder als Lead aufnehmen". NULL for every existing row: the status did
  not exist before, and inferring it from old calls would hide leads nobody
  decided to hide.

A column on an existing tenant table: its fail-closed RLS policy already
covers it, so no policy changes here.

Revision ID: 0081
Revises: 0080
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0081"
down_revision: str | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("managers")}
    if "no_interest_at" not in have:
        op.add_column("managers", sa.Column("no_interest_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("managers", "no_interest_at")
