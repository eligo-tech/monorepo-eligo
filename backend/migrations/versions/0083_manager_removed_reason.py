"""ELI-66: "Entfernen" — why a lead was removed from the Leads list.

- `removed_reason` — a code: `agency` (Personalberatung) · `not_relevant`
  (Nicht interessant) · `other` (Sonstiges).
- `removed_note` — the recruiter's optional words.

Removing reuses ELI-60's `no_interest_at` (hidden, restorable, not taken
again from Markt); these say why. NULL for every existing row. Columns on an
existing tenant table: its fail-closed RLS policy already covers them.

Revision ID: 0083
Revises: 0082
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("managers")}
    if "removed_reason" not in have:
        op.add_column("managers", sa.Column("removed_reason", sa.String(20), nullable=True))
    if "removed_note" not in have:
        op.add_column("managers", sa.Column("removed_note", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("managers", "removed_note")
    op.drop_column("managers", "removed_reason")
