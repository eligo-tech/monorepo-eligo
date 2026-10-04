"""Notes are free text. No arbitrary ceiling on what somebody writes down.

`hub_company_link.note` was VARCHAR(1000), with a matching validator. The
limit protected nothing — the row is a note a recruiter types about a company
they watch — and the first thing it would have refused is a pasted call
summary, which is the longest and most useful note anyone writes.

The sibling cap lived in Pydantic only: `ManagerInteractionCreate.summary`
was capped at 5,000 characters while the column behind it has always been
TEXT. That one needed no DDL, just deleting the number.

`hub_observations.note` stays VARCHAR(500) on purpose: it is written by the
crawler, not by a person ("fetched 100 of 240"), and a bound on machine
output is a sanity check rather than a limit on expression.

Revision ID: 0035
Revises: 0034
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "hub_company_link" not in inspector.get_table_names():
        return  # fresh database: create_all already has TEXT
    if bind.dialect.name == "sqlite":
        return  # SQLite ignores VARCHAR lengths anyway
    op.alter_column(
        "hub_company_link",
        "note",
        existing_type=sa.String(length=1000),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    # Narrowing would truncate what people wrote, so anything longer than the
    # old ceiling is kept and the column simply stays TEXT-compatible.
    op.alter_column(
        "hub_company_link",
        "note",
        existing_type=sa.Text(),
        type_=sa.String(length=1000),
        existing_nullable=True,
        postgresql_using="left(note, 1000)",
    )
