"""Add `query_key` to hub_observations — the freshness index.

`content_hash` fingerprints the RESPONSE; `query_key` fingerprints the QUESTION
(source + filters + page). With it, a caller can ask "has anyone already fetched
this exact slice recently?" and skip the network entirely.

That is what makes a per-user refresh button safe on a shared corpus: the first
recruiter to press it pays the request, and everyone else's press is answered
from the evidence ledger instead of becoming another call to a free public API.

Nullable + backfilled to NULL: existing observations predate the concept and
simply never match a freshness check, which fails safe (a real fetch happens).

Revision ID: 0009
Revises: 0008
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("hub_observations")}
    if "query_key" in columns:  # create_all already made it
        return
    op.add_column(
        "hub_observations", sa.Column("query_key", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_hub_observations_query_key", "hub_observations", ["query_key"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("hub_observations")}
    if "query_key" not in columns:
        return
    op.drop_index("ix_hub_observations_query_key", table_name="hub_observations")
    op.drop_column("hub_observations", "query_key")
