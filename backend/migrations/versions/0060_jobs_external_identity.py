"""Ensure `ix_jobs_external_identity` exists (ELI-22 leads).

Migration 0020 created the unique index (tenant_id, external_source,
external_id) on jobs, and production has it. It was never declared on the
model, so a database built by `create_all` lacked it. The model now declares it
(an ad taken from Markt twice must be one lead); this makes every database
agree. Idempotent; the jobs table is small, no CONCURRENTLY needed.

Revision ID: 0060
Revises: 0059
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "jobs" not in sa.inspect(op.get_bind()).get_table_names():
        return
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_jobs_external_identity "
        "ON jobs (tenant_id, external_source, external_id)"
    )


def downgrade() -> None:
    # Not dropped: 0020 owns it, and production relied on it before this.
    pass
