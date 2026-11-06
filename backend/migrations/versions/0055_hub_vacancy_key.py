"""One vacancy across relays and sources: `hub_job_postings.vacancy_key`.

Measured 2026-11-05: 4.8% of 1,219 live Bundesagentur ads repeated an ad
already in the sample (same employer, title without the gender tag, place) —
job boards relaying one vacancy under several references. `hub/vacancy.py`
derives the key; counts and lists group by it.

A nullable column without a default: metadata-only, no rewrite of the
650k-row table. Existing open ads are keyed by the nightly backfill, not
here — one UPDATE of every row would be a deploy-time IO burst on a database
already short of disk budget. The backfill's queue is a partial index that
empties as it runs. Shared corpus, no personal data (a hash).

Revision ID: 0055
Revises: 0054
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_job_postings"
_COLUMN = "vacancy_key"
_INDEX = "ix_hub_posting_unkeyed"
_WHERE = "is_active AND vacancy_key IS NULL"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return  # fresh database: create_all already has it
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        # Same guards as 0054: fail fast on the ADD COLUMN lock rather than
        # queue every read behind it.
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("SET LOCAL statement_timeout = 0")
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(64), nullable=True))
    if not postgres:
        op.execute(f"CREATE INDEX IF NOT EXISTS {_INDEX} ON {_TABLE} (id) WHERE {_WHERE}")
        return
    # CONCURRENTLY, and an INVALID leftover from a dead build is rebuilt —
    # see 0054 for both reasons.
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '10min'")
        invalid = bind.execute(sa.text(
            "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name AND NOT i.indisvalid"
        ), {"name": _INDEX}).scalar()
        if invalid:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} ON {_TABLE} (id) WHERE {_WHERE}")
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
