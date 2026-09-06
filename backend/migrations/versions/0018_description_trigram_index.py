"""Index the ad text, now that it no longer lives in the hot table.

0016 deliberately left `description` unindexed: it was 176 MB sitting inside
`hub_job_postings`, and a GIN build over it inside the container start command
is what took the API down. 0017 moved the column to `hub_posting_payload`, so
that objection is gone — an index here cannot widen the table search scans.

What it buys, measured on the live corpus. Terms appear in the ad BODY far more
often than in the headline, which is the whole reason `_term_matches` reaches
into the text at all:

    term         in description   in title/occupation
    python                  662                    22     30x
    typescript              122                    14    8.7x
    sap                   4,418                   677    6.5x
    kotlin                   27                     9      3x

Without the index that predicate costs 18-43s and `SEARCH_AD_TEXT` has to stay
off, which loses those matches entirely.

Trigram rather than tsvector, on purpose: it preserves the existing substring
semantics exactly, so this migration changes performance and nothing else.
tsvector would be smaller and faster but is a different matcher — word
boundaries, stemming, and German compounds — and that is a product decision to
take deliberately, not a side effect of an index migration.

BUILD IT OUT OF BAND. 182 MB of text is minutes of GIN build, and this file runs
inside `alembic upgrade head && uvicorn`, where every second is downtime. Create
it by hand first and this becomes a no-op via IF NOT EXISTS; the in-migration
path exists so a fresh environment is still correct, not because it is the way
to do it on a live database.

Revision ID: 0018
Revises: 0017
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_hub_payload_description_trgm"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # statement_timeout applies to DDL; this database enforces 2min and a GIN
    # build over 182 MB exceeds it. 0016 failed exactly this way and, because a
    # failed migration means uvicorn never runs, took the whole API with it.
    op.execute("SET LOCAL statement_timeout = 0")
    op.execute("SET LOCAL lock_timeout = '30s'")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {_INDEX} ON hub_posting_payload "
        "USING gin ((lower(description)) gin_trgm_ops)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
