"""Recover `region` for postings ingested before the column existed.

0011 added `hub_job_postings.region`, so every row already in the corpus carries
NULL — which left the Bundesland filter with no options to offer and its control
greyed out.

No re-crawl is needed: the source's original record is kept verbatim in
`hub_job_postings.raw`, and it contains the address the region comes from. This
reads it back out.

That is the payoff of storing the raw payload. A corpus that discarded it would
have had to re-fetch ~24,000 postings — several thousand requests against a free
public service — to recover a field it had already been told.

`berufsfeld` is deliberately NOT backfilled here, and cannot be: the source
never returns it per record. A posting only learns its field when a crawl asks
for that field, which is what the berufsfeld shard axis does going forward.

Revision ID: 0012
Revises: 0011
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same path in both dialects, different syntax. `->>` yields text on Postgres;
# `json_extract` does on SQLite.
_SQL = {
    "postgresql": """
        UPDATE hub_job_postings
           SET region = raw->'stellenlokationen'->0->'adresse'->>'region'
         WHERE region IS NULL
           AND raw->'stellenlokationen'->0->'adresse'->>'region' IS NOT NULL
    """,
    "sqlite": """
        UPDATE hub_job_postings
           SET region = json_extract(raw, '$.stellenlokationen[0].adresse.region')
         WHERE region IS NULL
           AND json_extract(raw, '$.stellenlokationen[0].adresse.region') IS NOT NULL
    """,
}


def upgrade() -> None:
    bind = op.get_bind()
    statement = _SQL.get(bind.dialect.name)
    if statement is None:
        return
    result = bind.execute(sa.text(statement))
    print(f"backfilled region on {result.rowcount} posting(s) from stored payloads")


def downgrade() -> None:
    # Not reversed: the values are recoverable from `raw` at any time, and
    # clearing them would only re-break the filter.
    pass
