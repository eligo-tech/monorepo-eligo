"""Partial index for the partner-page progress counts: the tried half.

`service.partner_pages_progress` ran three counts at the end of every run
(`is_active IS true ...`), none of which an index could serve; on prod
(2026-11-16, a 2,000-page manual run) they read ~790 MB. The total is now
never-read (`ix_hub_posting_partner_due`, 0072) + tried (this index), each an
index-only count. Keyed on the status, so "read" (status 200) is counted from
the same index.

CONCURRENTLY, so the build never blocks ingest writes; an INVALID leftover
from a dead build is rebuilt (same guards as 0072).

Revision ID: 0073
Revises: 0072
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0073"
down_revision: str | None = "0072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_job_postings"
_INDEX = "ix_hub_posting_partner_seen"
_WHERE = "is_active AND source_url IS NOT NULL AND source_page_fetched_at IS NOT NULL"
_DDL = f"{_TABLE} (source_page_status) WHERE {_WHERE}"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return  # create_all builds it with the index
    if bind.dialect.name != "postgresql":
        op.execute(f"CREATE INDEX IF NOT EXISTS {_INDEX} ON {_DDL}")
        return
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
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX} ON {_DDL}")
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
        return
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
