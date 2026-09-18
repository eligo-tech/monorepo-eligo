"""Partner-board page text beside the BA ad text.

A third of BA postings link to the same vacancy on a partner job board, and
those pages often name the contact the BA text leaves out. The nightly job now
reads them (adapters/partner_pages.py); this is where the result lives.

Split like the ad text itself: the attempt marker and status on the hot
`hub_job_postings` row (two narrow columns the selection query needs), the
text on the cold `hub_posting_payload` row.

Revision ID: 0023
Revises: 0022
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    postings = _columns("hub_job_postings")
    if "source_page_fetched_at" not in postings:
        op.add_column(
            "hub_job_postings",
            sa.Column("source_page_fetched_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_hub_job_postings_source_page_fetched_at",
            "hub_job_postings",
            ["source_page_fetched_at"],
        )
    if "source_page_status" not in postings:
        op.add_column(
            "hub_job_postings", sa.Column("source_page_status", sa.Integer(), nullable=True)
        )

    payload = _columns("hub_posting_payload")
    if "source_page_text" not in payload:
        op.add_column("hub_posting_payload", sa.Column("source_page_text", sa.Text(), nullable=True))
    if "source_page_url" not in payload:
        op.add_column(
            "hub_posting_payload", sa.Column("source_page_url", sa.String(1000), nullable=True)
        )
    if "source_page_observation_id" not in payload:
        # SQLite cannot ALTER a constraint in; the FK is enforced where it
        # matters (Postgres) and SQLite — CI and local — gets the plain column.
        # `create_all` builds fresh SQLite databases with the FK from the model.
        fk = (
            []
            if op.get_bind().dialect.name == "sqlite"
            else [sa.ForeignKey("hub_observations.id")]
        )
        op.add_column(
            "hub_posting_payload",
            sa.Column("source_page_observation_id", sa.Uuid(), *fk, nullable=True),
        )


def downgrade() -> None:
    payload = _columns("hub_posting_payload")
    for column in ("source_page_observation_id", "source_page_url", "source_page_text"):
        if column in payload:
            op.drop_column("hub_posting_payload", column)
    postings = _columns("hub_job_postings")
    if "source_page_status" in postings:
        op.drop_column("hub_job_postings", "source_page_status")
    if "source_page_fetched_at" in postings:
        op.drop_index("ix_hub_job_postings_source_page_fetched_at", "hub_job_postings")
        op.drop_column("hub_job_postings", "source_page_fetched_at")
