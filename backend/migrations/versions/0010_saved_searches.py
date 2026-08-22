"""Create the saved_searches table — a workspace's standing market questions.

Tenant-scoped and RLS-isolated like every other tenant table. The rows hold
SEARCH TERMS, which are competitive intelligence: what a recruiter is hunting
for must not leak between workspaces. The nightly job reads only a
deduplicated, unattributed union of them (see `searches/service.list_crawl_
profiles`) — what to crawl, never who asked.

Idempotent w.r.t. `create_all`: skipped if the table already exists.

Revision ID: 0010
Revises: 0009
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    bind = op.get_bind()
    if "saved_searches" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "saved_searches",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("label", sa.String(120), nullable=False),
            sa.Column("q", sa.String(200), nullable=True),
            sa.Column("city", sa.String(120), nullable=True),
            sa.Column("radius_km", sa.Integer(), nullable=True),
            sa.Column("min_roles", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("crawl_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_result_count", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", "label", name="uq_saved_search_label"),
        )

    if bind.dialect.name != "postgresql":
        return
    # Same fail-closed policy as 0003/0005: an unset GUC resolves to NULL, which
    # matches no row.
    op.execute("ALTER TABLE saved_searches ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE saved_searches FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON saved_searches")
    op.execute(
        "CREATE POLICY tenant_isolation ON saved_searches "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON saved_searches")
    if "saved_searches" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("saved_searches")
