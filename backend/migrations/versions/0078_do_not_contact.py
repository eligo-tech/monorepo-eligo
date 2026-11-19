"""ELI-32: "Nicht mehr kontaktieren" on managers and candidates.

- `do_not_contact_at` — when the person asked not to be contacted again
  (from a recruiter's note, or the candidate's "Nein" in the opt-in mail).
  NULL = contactable, which is every existing row: nobody was marked before.
- `do_not_contact_reason` — a code (`requested` · `opt_out_link`), never free
  text; the note carries the person's words and an erasure deletes it.

Columns on existing tenant tables: their fail-closed RLS policies already
cover them, so no policy changes here.

Revision ID: 0078
Revises: 0077
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0078"
down_revision: str | None = "0077"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("managers", "candidates")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in _TABLES:
        have = {c["name"] for c in inspector.get_columns(table)}
        if "do_not_contact_at" not in have:
            op.add_column(table, sa.Column("do_not_contact_at", sa.DateTime(timezone=True), nullable=True))
        if "do_not_contact_reason" not in have:
            op.add_column(table, sa.Column("do_not_contact_reason", sa.String(40), nullable=True))


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "do_not_contact_reason")
        op.drop_column(table, "do_not_contact_at")
