"""Employers' own ATS job boards: `hub_ats_boards`.

One row per discovered board (Personio first, `app/domain/hub/ats.py`): its
status, the offices' postal addresses read once from a job page, and the last
snapshot of open job ids that the next sync diffs against.

Shared corpus — no tenant_id — with the same permissive `shared_corpus_read`
policy as the other hub tables; the Data API roles are revoked (see 0051).

Revision ID: 0056
Revises: 0055
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_ats_boards"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():  # else create_all made it
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("ats", sa.String(30), nullable=False),
            sa.Column("slug", sa.String(120), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("company_name", sa.String(300), nullable=True),
            sa.Column("discovered_via", sa.String(60), nullable=False),
            sa.Column("offices", sa.JSON(), nullable=False),
            sa.Column("open_ids", sa.JSON(), nullable=False),
            sa.Column("jobs_listed", sa.Integer(), nullable=False),
            sa.Column("jobs_dach", sa.Integer(), nullable=False),
            sa.Column("empty_streak", sa.Integer(), nullable=False),
            sa.Column("failures", sa.Integer(), nullable=False),
            sa.Column("last_http_status", sa.Integer(), nullable=True),
            sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_fetch_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("ats", "slug", name="uq_hub_ats_board"),
        )
        op.create_index("ix_hub_ats_boards_next_fetch_at", _TABLE, ["next_fetch_at"])
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS shared_corpus_read ON {_TABLE}")
    op.execute(f"CREATE POLICY shared_corpus_read ON {_TABLE} USING (true) WITH CHECK (true)")
    for role in ("anon", "authenticated"):
        if bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar():
            op.execute(f"REVOKE ALL ON {_TABLE} FROM {role}")


def downgrade() -> None:
    # Rediscovered from Common Crawl and re-synced if dropped; postings stay.
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
