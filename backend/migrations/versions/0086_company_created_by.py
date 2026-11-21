"""ELI-69: "Angelegt von" on companies.

`companies.created_by_user_id` / `created_by_name` — the account that added
the company, filled from the request's actor at insert (`CreatedByMixin`),
like `managers` and `jobs` since 0085. A column on an existing tenant table:
its fail-closed RLS policy already covers it.

No backfill here. The only proof of who created an existing row is a
creation receipt, and `receipts.subject_id` is the id as TEXT while
`companies.id` is a uuid on Postgres and 32 hex characters on SQLite — the
join is not one portable SQL statement, and one of the proofs reads the
receipt's JSON payload. So it is a separate, idempotent script:
`scripts/backfill_created_by.py`. Every row it cannot prove stays NULL.

Classification: tenant record — a workspace member's id and display name,
the same kind of value `receipts.actor_user_id`/`actor_name` hold.

Revision ID: 0086
Revises: 0085
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0086"
down_revision: str | None = "0085"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> list[sa.Column]:
    return [
        sa.Column("created_by_user_id", sa.String(80), nullable=True),
        sa.Column("created_by_name", sa.String(160), nullable=True),
    ]


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("companies")}
    for column in _columns():
        if column.name not in have:
            op.add_column("companies", column)


def downgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("companies")}
    for column in _columns():
        if column.name in have:
            op.drop_column("companies", column.name)
