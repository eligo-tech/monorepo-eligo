"""Liveness of hub postings: `unlisted_at`, `live_checked_at`, `closed_at`, `check_due_at`.

Measured 2026-11-05: all 648,451 postings were open and none had ever been
closed, while 125 of 300 sampled answered 404 at the Bundesagentur. A delta
crawl never re-lists an old ad, so nothing could close one.

`hub/liveness.py` now does it in two steps: a weekly full listing marks the
open ads it did not see (`unlisted_at`, a suspect only), and a nightly check
of each suspect's own detail page closes it on a 404 (`closed_at`) or records
that it answered (`live_checked_at`). `check_due_at` is the queue — one
indexed sort key, so a batch reads only what is due.

Four nullable columns without defaults: metadata-only in Postgres, no
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
_COLUMNS = ("unlisted_at", "live_checked_at", "closed_at", "check_due_at")
_INDEX = "ix_hub_posting_check_due"
_WHERE = "is_active AND check_due_at IS NOT NULL"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return  # fresh database: create_all already has them
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        # ADD COLUMN takes ACCESS EXCLUSIVE for an instant; queued behind a
        # long transaction it would block every read of the table. Fail fast
        # instead — the deploy retries — and lift the 2 min statement_timeout
        # that applies to DDL here (see 0016).
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("SET LOCAL statement_timeout = 0")
    present = {c["name"] for c in inspector.get_columns(_TABLE)}
    for column in _COLUMNS:
        if column not in present:
            op.add_column(_TABLE, sa.Column(column, sa.DateTime(timezone=True), nullable=True))
    if not postgres:
        op.execute(f"CREATE INDEX IF NOT EXISTS {_INDEX} ON {_TABLE} (check_due_at, id) WHERE {_WHERE}")
        return
    # CONCURRENTLY: the build reads the whole 650k-row table, and a plain
    # CREATE INDEX would block every ingest write meanwhile. It cannot run in
    # a transaction, hence the autocommit block (and session-level settings).
    #
    # A CONCURRENTLY build that dies half-way (deploy killed, deadlock) leaves
    # an INVALID index under this name, which IF NOT EXISTS would then skip
    # forever — the queue would silently scan the table. Drop it first.
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        # It waits for older transactions; bounded, so a boot cannot hang.
        op.execute("SET lock_timeout = '10min'")
        invalid = bind.execute(sa.text(
            "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name AND NOT i.indisvalid"
        ), {"name": _INDEX}).scalar()
        if invalid:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} ON {_TABLE} (check_due_at, id) WHERE {_WHERE}")
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    present = {c["name"] for c in inspector.get_columns(_TABLE)}
    for column in _COLUMNS:
        if column in present:
            op.drop_column(_TABLE, column)
