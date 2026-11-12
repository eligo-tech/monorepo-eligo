"""Leave room on each page so a crawl's touches are HOT updates.

Each crawl re-sees most of the corpus and bumps `last_seen_at` (an unindexed
column) on every ad and employer it sees again. Postgres can do that update in
place — no new index entries — only if the row's page has free space. At the
default fillfactor (100) pages are full, so each touch also writes into every
index (~18 on `hub_job_postings`). 85 keeps ~15% of each page free.

Metadata only: no table rewrite, a brief SHARE UPDATE EXCLUSIVE lock (reads
and writes go on). Existing pages gain the room as vacuum frees them; new
pages get it at once. Postgres only — SQLite has no fillfactor.

Revision ID: 0067
Revises: 0066
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0067"
down_revision: str | None = "0066"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("hub_job_postings", "hub_companies")


def _alter(fillfactor: int | None) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    present = set(sa.inspect(bind).get_table_names())
    for table in _TABLES:
        if table not in present:
            continue
        if fillfactor is None:
            op.execute(f"ALTER TABLE {table} RESET (fillfactor)")
        else:
            op.execute(f"ALTER TABLE {table} SET (fillfactor = {fillfactor})")


def upgrade() -> None:
    _alter(85)


def downgrade() -> None:
    _alter(None)
