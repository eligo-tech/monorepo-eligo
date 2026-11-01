"""Private recruiters in the corpus: `hub_companies.kind`, `hub_job_postings.segment`.

The agency finder (Eligo's own business development) ingests private
recruiters — Bundesagentur `pav=true` — as leads. They share the corpus tables
with employers, so each row records which kind of advertiser it is. The value
is stamped at ingest from the query that returned the record: the source's
listing records carry no flag of their own.

Every existing row was ingested with `pav=false&zeitarbeit=false`, so
"employer" is the true value for all of them, not a placeholder — the server
default backfills it.

Shared corpus tables: no tenant_id, already covered by `shared_corpus_read`, no
RLS change. No personal data in either column.

Revision ID: 0046
Revises: 0045
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("hub_companies", "kind", "ix_hub_companies_kind"),
    ("hub_job_postings", "segment", None),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table, column, index in _COLUMNS:
        if table not in tables:
            continue  # fresh database: create_all already has the column
        if column not in {c["name"] for c in inspector.get_columns(table)}:
            op.add_column(
                table,
                sa.Column(
                    column,
                    sa.String(30),
                    nullable=False,
                    server_default="employer",
                ),
            )
        if index and index not in {i["name"] for i in inspector.get_indexes(table)}:
            op.create_index(index, table, [column])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table, column, index in _COLUMNS:
        if table not in tables:
            continue
        if index and index in {i["name"] for i in inspector.get_indexes(table)}:
            op.drop_index(index, table_name=table)
        if column in {c["name"] for c in inspector.get_columns(table)}:
            op.drop_column(table, column)
