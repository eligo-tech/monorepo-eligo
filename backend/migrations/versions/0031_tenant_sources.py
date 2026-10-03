"""A workspace's own data sources — onboarding as a product, not a script.

Until now, connecting a customer's ATS meant an operator running
`scripts/aifind_import --tenant <uuid>` with that customer's password in their
shell environment. One table changes that: the workspace stores its own
credential (Fernet-encrypted, `app/core/secrets.py`), asks for an import, and
the scheduled runner performs it.

Tenant-scoped like every other record table: RLS enabled and FORCED, so a
workspace cannot see — let alone decrypt — another's credential even if a
query forgets its filter.

Revision ID: 0031
Revises: 0030
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    bind = op.get_bind()
    if "tenant_sources" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "tenant_sources",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("label", sa.String(160), nullable=True),
            sa.Column("username", sa.String(255), nullable=False),
            sa.Column("secret_encrypted", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column(
                "import_requested_at", sa.DateTime(timezone=True), nullable=True
            ),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_result", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.UniqueConstraint("tenant_id", "kind", name="uq_tenant_source_kind"),
        )

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE tenant_sources ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE tenant_sources FORCE ROW LEVEL SECURITY")
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_sources")
        op.execute(
            "CREATE POLICY tenant_isolation ON tenant_sources "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    if "tenant_sources" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("tenant_sources")
