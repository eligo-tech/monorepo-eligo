"""ELI-47: the briefing points a mandate had no field for.

Briefing-Bewertung counts ten points; four already had a column (Muss-
Kriterien, Gehaltsrahmen, Standort, Ansprechpartner). These six did not:

- `tasks` (Aufgaben), `interview_process` (Prozess beim Kunden),
  `vacancy_reason` (Grund der Vakanz) — text.
- `start_date` (Startdatum), `team_size` (Teamgröße) — short free text,
  because "sofort" and "6 Devs + PO" are the answers a client gives.
- `nice_to_have_skills` (Kann-Kriterien) — a list, `[]` for every existing
  row. Never a matching input.

All NULL / empty for existing mandates: nothing was asked before, and the
score says so. Columns on an existing tenant table: its fail-closed RLS
policy already covers them, so no policy changes here.

Revision ID: 0079
Revises: 0078
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0079"
down_revision: str | None = "0078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("tasks", sa.Text(), {"nullable": True}),
    ("nice_to_have_skills", sa.JSON(), {"nullable": False, "server_default": "[]"}),
    ("start_date", sa.String(120), {"nullable": True}),
    ("team_size", sa.String(120), {"nullable": True}),
    ("interview_process", sa.Text(), {"nullable": True}),
    ("vacancy_reason", sa.Text(), {"nullable": True}),
)


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("jobs")}
    for name, type_, options in _COLUMNS:
        if name not in have:
            op.add_column("jobs", sa.Column(name, type_, **options))


def downgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("jobs")}
    for name, _type, _options in reversed(_COLUMNS):
        if name in have:
            op.drop_column("jobs", name)
