"""Record that ad text was REQUESTED, not merely whether it arrived.

The bulk pass selected work with `description IS NULL`. A posting whose detail
call 404s has no text to store, so it stayed NULL and was selected again on the
next batch — forever. A production run re-requested the same 25 references every
few seconds until it was cancelled, burning requests against a public service
and never terminating.

`description_fetched_at` is stamped on every attempt regardless of outcome, so
each posting is tried once and the pass can finish. The column is a timestamp
rather than a boolean so a deliberate retry policy stays possible later — a 404
today is not proof of a 404 next month.

Additive: existing rows are NULL, i.e. never attempted, which is correct.

Revision ID: 0015
Revises: 0014
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("hub_job_postings")}
    if "description_fetched_at" in columns:
        return
    op.add_column(
        "hub_job_postings",
        sa.Column("description_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_hub_job_postings_description_fetched_at",
        "hub_job_postings",
        ["description_fetched_at"],
    )
    # Postings that already carry text were plainly fetched successfully. Their
    # timestamp is unknown, so use the row's own update time rather than
    # inventing one — the value only has to be non-NULL to mean "attempted".
    op.execute(
        "UPDATE hub_job_postings SET description_fetched_at = updated_at "
        "WHERE description IS NOT NULL"
    )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("hub_job_postings")}
    if "description_fetched_at" not in columns:
        return
    op.drop_index(
        "ix_hub_job_postings_description_fetched_at", table_name="hub_job_postings"
    )
    op.drop_column("hub_job_postings", "description_fetched_at")
