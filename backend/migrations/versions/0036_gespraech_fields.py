"""Three places for what the Gesprächszusammenfassung actually says.

Section B of the Kandidatenauswertung has nine labelled lines. Eight of them
had a column; three had nowhere to land and were therefore lost every time
somebody filled the form:

* `focus_areas` — "Schwerpunkte". The two or three things the person is known
  for. A list: it is the line that opens a client presentation.
* `technical_profile` — "Technisches Know-how", as prose. NOT folded into
  `skills`: that list feeds the deterministic hard filters, and splitting a
  sentence into it on commas puts "MariaDB bekannt (persönlich nicht
  bevorzugt)" in front of a Muss-Kriterium check.
* `other_notes` — "Weitere relevante Punkte". An open list (current role,
  project history, languages, location, Besonderheiten) that must not be
  stopped by a missing slot, so: free text, no ceiling.

Additive only. Existing rows get an empty list and two NULLs, which is what
they truthfully have.

Revision ID: 0036
Revises: 0035
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: name → column. JSON rather than JSONB: the model's JSONList maps to JSON,
#: and a mismatch here would make the ORM and the table disagree on reads.
_NEW = {
    "focus_areas": sa.Column(
        "focus_areas", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
    ),
    "technical_profile": sa.Column("technical_profile", sa.Text(), nullable=True),
    "other_notes": sa.Column("other_notes", sa.Text(), nullable=True),
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "candidates" not in inspector.get_table_names():
        return  # fresh database: create_all already has them
    have = {c["name"] for c in inspector.get_columns("candidates")}
    for name, column in _NEW.items():
        if name not in have:
            op.add_column("candidates", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "candidates" not in inspector.get_table_names():
        return
    have = {c["name"] for c in inspector.get_columns("candidates")}
    for name in _NEW:
        if name in have:
            op.drop_column("candidates", name)
