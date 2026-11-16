"""Partial indexes for the partner-page queue: never-read and throttled retries.

`service.fetch_missing_partner_pages` picks never-read ads with a Quelle,
newest first. Before this, each 20-ad batch seq-scanned hub_job_postings and
sorted ~134k due rows (prod EXPLAIN, 2026-11-16: Parallel Seq Scan + Sort;
~10 GB read in one weekly run). The index holds only the queue (~170k ads,
shrinking as it drains), ordered as the query reads it, so a batch is an
index walk that stops at its LIMIT.

CONCURRENTLY, so the build never blocks ingest writes; an INVALID leftover
from a dead build is rebuilt (same guards as 0054).

Revision ID: 0072
Revises: 0071
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072"
down_revision: str | None = "0071"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_job_postings"
_INDEX = "ix_hub_posting_partner_due"
_WHERE = "is_active AND source_url IS NOT NULL AND source_page_fetched_at IS NULL"
_KEY = "posted_at DESC NULLS LAST"
# The retry half: throttled pages (429/503), due again after a week. Tiny.
_RETRY_INDEX = "ix_hub_posting_partner_retry"
_RETRY_WHERE = "is_active AND source_url IS NOT NULL AND source_page_status IN (429, 503)"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return  # create_all builds it with the index
    if bind.dialect.name != "postgresql":
        # SQLite cannot index NULLS LAST; the queue index matters on Postgres only.
        op.execute(f"CREATE INDEX IF NOT EXISTS {_RETRY_INDEX} ON {_TABLE} (source_page_fetched_at) WHERE {_RETRY_WHERE}")
        return
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        # It waits for older transactions; bounded, so a boot cannot hang.
        op.execute("SET lock_timeout = '10min'")
        for name, ddl in (
            (_INDEX, f"{_TABLE} ({_KEY}) WHERE {_WHERE}"),
            (_RETRY_INDEX, f"{_TABLE} (source_page_fetched_at) WHERE {_RETRY_WHERE}"),
        ):
            invalid = bind.execute(sa.text(
                "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = :name AND NOT i.indisvalid"
            ), {"name": name}).scalar()
            if invalid:
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {ddl}")
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        op.execute(f"DROP INDEX IF EXISTS {_RETRY_INDEX}")
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_RETRY_INDEX}")
