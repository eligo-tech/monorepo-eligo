"""Tech roles: `hub_job_postings.job_family`.

`hub/families.py` labels an ad `tech` or `other` with deterministic rules on
its title and the Bundesagentur's occupational field; the Markt screen filters
on it. Measured 2026-11-09 on all 702,630 open ads: 33,344 tech.

A nullable column without a default: metadata-only, no rewrite of the
700k-row table. New ads are labelled at ingest; older ones by the nightly
backfill (queue: `ix_hub_posting_unclassified`), not here — one UPDATE of
every row would be a deploy-time IO burst. `ix_hub_posting_tech` is the
filter's index, small by construction. Shared corpus, no personal data.

Revision ID: 0057
Revises: 0056
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_job_postings"
_COLUMN = "job_family"
_INDEXES = {
    "ix_hub_posting_unclassified": ("id", "is_active AND job_family IS NULL"),
    "ix_hub_posting_tech": ("hub_company_id", "is_active AND job_family = 'tech'"),
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return  # fresh database: create_all already has it
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        # Same guards as 0054/0055: fail fast on the ADD COLUMN lock rather
        # than queue every read behind it.
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("SET LOCAL statement_timeout = 0")
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(20), nullable=True))
    if not postgres:
        for name, (column, where) in _INDEXES.items():
            op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {_TABLE} ({column}) WHERE {where}")
        return
    # CONCURRENTLY, and an INVALID leftover from a dead build is rebuilt —
    # see 0054 for both reasons.
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '10min'")
        for name, (column, where) in _INDEXES.items():
            invalid = bind.execute(sa.text(
                "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = :name AND NOT i.indisvalid"
            ), {"name": name}).scalar()
            if invalid:
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {_TABLE} ({column}) WHERE {where}")
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    for name in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
