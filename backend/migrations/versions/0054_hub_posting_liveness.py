"""Liveness of hub postings: `unlisted_at`, `live_checked_at`, `closed_at`.

Measured 2026-11-05: all 648,451 postings were open and none had ever been
closed, while 125 of 300 sampled answered 404 at the Bundesagentur. A delta
crawl never re-lists an old ad, so nothing could close one.

`hub/liveness.py` now does it in two steps: a weekly full listing marks the
open ads it did not see (`unlisted_at`, a suspect only), and a nightly check
of each suspect's own detail page closes it on a 404 (`closed_at`) or records
that it answered (`live_checked_at`). Plus the checker's queue index.

Three nullable columns without defaults: metadata-only in Postgres, no
rewrite of the 650k-row table. Shared corpus, no personal data.

Revision ID: 0054
Revises: 0053
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_job_postings"
_COLUMNS = ("unlisted_at", "live_checked_at", "closed_at")
_INDEX = "ix_hub_posting_unlisted"
_WHERE = "is_active AND unlisted_at IS NOT NULL"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return  # fresh database: create_all already has them
    present = {c["name"] for c in inspector.get_columns(_TABLE)}
    for column in _COLUMNS:
        if column not in present:
            op.add_column(_TABLE, sa.Column(column, sa.DateTime(timezone=True), nullable=True))
    if bind.dialect.name == "postgresql":
        # A btree over a predicate that matches nothing yet — but the build
        # still reads the whole table. Same guards as 0016: the database's 2 min
        # statement_timeout applies to DDL, and fail fast rather than queue
        # behind a long transaction holding the table.
        op.execute("SET LOCAL statement_timeout = 0")
        op.execute("SET LOCAL lock_timeout = '30s'")
    op.execute(f"CREATE INDEX IF NOT EXISTS {_INDEX} ON {_TABLE} (unlisted_at) WHERE {_WHERE}")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    present = {c["name"] for c in inspector.get_columns(_TABLE)}
    for column in _COLUMNS:
        if column in present:
            op.drop_column(_TABLE, column)
