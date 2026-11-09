"""Tech roles: `hub_job_postings.job_family` and `job_family_rules`.

`hub/families.py` labels an ad `tech` or `other` with deterministic rules on
its title and the Bundesagentur's occupational field; the Markt screen filters
on it. Measured 2026-11-09 on all 702,630 open ads: 33,612 tech.

A nullable column without a default: metadata-only, no rewrite of the
700k-row table. New ads are labelled at ingest; older ones by the nightly
backfill (queue: `ix_hub_posting_unclassified` — never labelled, or labelled
under an older rules version, so a rule change reaches every open ad), not here — one UPDATE of
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
_COLUMNS = {"job_family": sa.String(20), "job_family_rules": sa.Integer()}
# Written out, not imported from the models: a migration must keep meaning what
# it meant when it ran. Rules version 1; a bump ships its own migration that
# rebuilds this index with the new number.
_INDEXES = {
    "ix_hub_posting_unclassified": (
        "id", "is_active AND (job_family_rules IS NULL OR job_family_rules < 1)",
    ),
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
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    for name, type_ in _COLUMNS.items():
        if name not in existing:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))
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
    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    for name in _COLUMNS:
        if name in existing:
            op.drop_column(_TABLE, name)
