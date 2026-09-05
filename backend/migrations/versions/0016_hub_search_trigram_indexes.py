"""Make corpus search survive the arrival of ad text.

`_term_matches` matches a search word against the posting DESCRIPTION as well as
its title — deliberately, because a stack is named in the requirements far more
often than in the headline. That predicate was cheap while descriptions were
empty. It stopped being cheap once the nightly pass filled them in: 90,450 rows
carrying ~2.4 KB each, in a 518 MB table with no text index at all.

`lower(description) LIKE '%term%'` cannot use a b-tree — leading wildcard, and
`lower()` hides the column anyway — so every search sequentially scanned the
whole table. Measured against the live corpus: one term, one COUNT, 70s. And
`search_employers` evaluates that predicate three times per request (candidate
subquery, grouped roll-up, evidence list), so a single-word search ran minutes
and the UI simply spun on "sucht im Korpus…" until the proxy gave up.

pg_trgm with GIN indexes makes exactly these `LIKE '%…%'` predicates
index-accelerated while keeping the semantics identical — substring matching,
not stemmed full-text. The indexes are on the same `lower(...)` expressions the
query writes, so the planner can match them without touching the query.

Trigram indexes need a term of at least 3 characters to help; shorter terms fall
back to a scan, which is the pre-existing behaviour and no worse.

Scope: SHORT columns only. `lower(description)` is ~220 MB and its GIN build is
the one that blows past any sane deploy window, so it is deliberately left out.
Nothing needs it while `SEARCH_AD_TEXT` is False, because the predicate does not
touch the column at all. Indexing description belongs with the change that turns
that flag back on, where the build can be done deliberately rather than inside a
release that is holding the API down while it runs.

Postgres only: SQLite (tests) has neither the extension nor the problem.

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (index name, table, indexed expression) — the expressions mirror
# `_term_matches` and the `city` filter in app/domain/hub/service.py exactly.
_INDEXES = [
    ("ix_hub_posting_title_trgm", "hub_job_postings", "lower(title)"),
    ("ix_hub_posting_occupation_trgm", "hub_job_postings", "lower(occupation)"),
    ("ix_hub_company_name_trgm", "hub_companies", "lower(name)"),
    ("ix_hub_company_city_trgm", "hub_companies", "lower(city)"),
    # The company-match branch scans this with a leading wildcard too, which the
    # existing b-tree ix_hub_company_normalized_name cannot serve.
    ("ix_hub_company_normname_trgm", "hub_companies", "normalized_name"),
]


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # statement_timeout applies to DDL. This database sets it to 2min, which is
    # less than a GIN build takes: the first attempt at this migration was
    # cancelled mid-CREATE INDEX and rolled back. Because the container start
    # command is `alembic upgrade head && uvicorn`, that failure also meant the
    # API never booted. Lifted for this transaction only.
    op.execute("SET LOCAL statement_timeout = 0")
    # Fail fast rather than queue behind a long transaction holding the table.
    op.execute("SET LOCAL lock_timeout = '30s'")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, table, expr in _INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} "
            f"USING gin (({expr}) gin_trgm_ops)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for name, _table, _expr in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    # pg_trgm is left installed: other things may have come to rely on it, and
    # dropping an extension is not the business of undoing an index.
