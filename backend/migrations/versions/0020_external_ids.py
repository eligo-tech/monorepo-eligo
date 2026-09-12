"""Give imported rows a stable identity in their source system.

An ATS import that cannot recognise what it already imported is a duplicator.
Run it twice and every company, person and mandate exists twice; run it nightly
and the book of business doubles daily. Matching on name is not an answer —
two managers really can be called the same thing, and a company that fixes a
typo in its own name would arrive as a second account.

So each importable row records WHERE it came from: `source` names the system,
`external_id` its id there, and the pair is unique per tenant. `companies`
already had `source`; it gains `external_id` alongside.

The uniqueness is per (tenant_id, source, external_id) — NOT global. Two
workspaces can each import the same aiFind account into their own records, and
neither can see the other's.

Nullable throughout, because most rows have no external source: a candidate
someone typed in by hand belongs to no system but this one. Postgres treats
NULLs as distinct in a unique constraint, so existing rows do not collide.

Revision ID: 0020
Revises: 0019
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table -> the columns it is missing (companies already carries `source`)
_TARGETS = {
    "companies": ("external_id",),
    "managers": ("external_id", "external_source"),
    "jobs": ("external_id", "external_source"),
    "candidates": ("external_id", "external_source"),
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table, columns in _TARGETS.items():
        if table not in tables:
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column not in existing:
                op.add_column(table, sa.Column(column, sa.String(80), nullable=True))
        # `companies.source` predates this and means the same thing, so it is
        # reused rather than shadowed by a second column with a similar name.
        source_column = "source" if table == "companies" else "external_source"
        op.create_index(
            f"ix_{table}_external_identity",
            table,
            ["tenant_id", source_column, "external_id"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, columns in _TARGETS.items():
        if table not in tables:
            continue
        op.drop_index(f"ix_{table}_external_identity", table_name=table)
        existing = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column in existing:
                op.drop_column(table, column)
