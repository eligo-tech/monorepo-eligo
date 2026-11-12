"""Drop two hub_job_postings indexes nothing reads.

Every insert into hub_job_postings writes into every one of its indexes, so an
index nothing reads is pure Disk IO. Measured on prod (2026-11-12, 67 days of
stats, never reset): both had idx_scan = 0.

- ix_hub_job_postings_city: the only city filter is `lower(city) = ...`
  (service.list_postings), which a plain index on `city` cannot serve.
- ix_hub_job_postings_observation_id: an FK index, which only speeds up
  deleting observations — nothing deletes them.

CONCURRENTLY: a plain DROP INDEX takes ACCESS EXCLUSIVE and, queued behind a
running ingest, would stall every read of the table (see 0054).

Revision ID: 0068
Revises: 0067
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0068"
down_revision: str | None = "0067"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_job_postings"
_INDEXES = {
    "ix_hub_job_postings_city": "city",
    "ix_hub_job_postings_observation_id": "observation_id",
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        for name in _INDEXES:
            op.execute(f"DROP INDEX IF EXISTS {name}")
        return
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '10min'")
        for name in _INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    concurrently = "CONCURRENTLY " if op.get_bind().dialect.name == "postgresql" else ""
    if concurrently:
        with op.get_context().autocommit_block():
            for name, column in _INDEXES.items():
                op.execute(f"CREATE INDEX {concurrently}IF NOT EXISTS {name} ON {_TABLE} ({column})")
        return
    for name, column in _INDEXES.items():
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {_TABLE} ({column})")
