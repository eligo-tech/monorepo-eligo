"""Add `berufsfeld` + `region` to postings, and filter arrays to saved searches.

`region` (Bundesland) comes from each record's own address and is reliable —
unlike the source's `wo=` QUERY parameter, which matches place names and returns
82 postings for the whole of Hessen. Accurate to filter on, useless to shard on.

`berufsfeld` is absent from every record the source returns; it exists only in
the response facets. A posting can therefore only carry one if the crawler
stamps the shard it came from, which is why it is nullable by nature: postings
pulled by a regional sweep or a keyword slice have no field until a berufsfeld
shard returns them.

Additive and idempotent — existing rows keep NULL and gain a value the next time
a berufsfeld shard sees them.

Revision ID: 0011
Revises: 0010
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "hub_job_postings")
    if "berufsfeld" not in existing:
        op.add_column(
            "hub_job_postings", sa.Column("berufsfeld", sa.String(120), nullable=True)
        )
        op.create_index(
            "ix_hub_job_postings_berufsfeld", "hub_job_postings", ["berufsfeld"]
        )
    if "region" not in existing:
        op.add_column(
            "hub_job_postings", sa.Column("region", sa.String(120), nullable=True)
        )
        op.create_index("ix_hub_job_postings_region", "hub_job_postings", ["region"])

    saved = _columns(bind, "saved_searches")
    json_type = (
        sa.dialects.postgresql.JSONB()
        if bind.dialect.name == "postgresql"
        else sa.JSON()
    )
    for column in ("regions", "berufsfelder"):
        if column not in saved:
            op.add_column(
                "saved_searches",
                sa.Column(column, json_type, nullable=False, server_default="[]"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "berufsfeld" in _columns(bind, "hub_job_postings"):
        op.drop_index("ix_hub_job_postings_berufsfeld", table_name="hub_job_postings")
        op.drop_column("hub_job_postings", "berufsfeld")
    if "region" in _columns(bind, "hub_job_postings"):
        op.drop_index("ix_hub_job_postings_region", table_name="hub_job_postings")
        op.drop_column("hub_job_postings", "region")
    saved = _columns(bind, "saved_searches")
    for column in ("regions", "berufsfelder"):
        if column in saved:
            op.drop_column("saved_searches", column)
