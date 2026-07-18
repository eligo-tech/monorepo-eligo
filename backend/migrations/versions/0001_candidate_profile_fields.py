"""Add the extended candidate profile columns (aiFind field set).

All columns are nullable, so this applies to an existing `candidates` table
(e.g. one first created by create_all) without a backfill.

Revision ID: 0001
Revises:
Create Date: 2026-07-18
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (name, type) for every added column. JSON maps to JSONB on Postgres, TEXT on SQLite.
_COLUMNS: list[tuple[str, sa.types.TypeEngine]] = [
    ("first_name", sa.String(120)),
    ("last_name", sa.String(120)),
    ("sex", sa.String(20)),
    ("name_prefix", sa.String(40)),
    ("date_of_birth", sa.String(40)),
    ("street", sa.String(200)),
    ("postal_code", sa.String(20)),
    ("city", sa.String(120)),
    ("country", sa.String(120)),
    ("linkedin_url", sa.String(300)),
    ("xing_url", sa.String(300)),
    ("industry", sa.String(120)),
    ("employment_type", sa.String(60)),
    ("willing_to_relocate", sa.String(10)),
    ("notice_period", sa.String(80)),
    ("availability", sa.String(80)),
    ("total_years_experience", sa.String(40)),
    ("current_salary", sa.Integer()),
    ("languages", sa.JSON()),
    ("education", sa.JSON()),
    ("working_experience", sa.JSON()),
    ("motivation", sa.Text()),
    ("source", sa.String(120)),
]


def upgrade() -> None:
    if not _table_exists():
        return  # fresh DB — create_all builds candidates with these columns already
    existing = _existing_columns()
    for name, type_ in _COLUMNS:
        if name not in existing:  # idempotent: skip columns create_all already made
            op.add_column("candidates", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    if not _table_exists():
        return
    existing = _existing_columns()
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("candidates", name)


def _table_exists() -> bool:
    return "candidates" in sa.inspect(op.get_bind()).get_table_names()


def _existing_columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("candidates")}
