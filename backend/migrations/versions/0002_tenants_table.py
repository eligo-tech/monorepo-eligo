"""Create the tenants table (Clerk org → tenant_id).

Nullable/idempotent: skips creation if create_all already made the table.

Revision ID: 0002
Revises: 0001
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "tenants" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("clerk_org_id", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenants_clerk_org_id", "tenants", ["clerk_org_id"], unique=True)


def downgrade() -> None:
    if "tenants" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_index("ix_tenants_clerk_org_id", table_name="tenants")
        op.drop_table("tenants")
