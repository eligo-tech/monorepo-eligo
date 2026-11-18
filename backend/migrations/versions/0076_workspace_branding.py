"""Workspace branding for the candidate cover sheet (ELI-20).

One tenant table, `workspace_branding`: one row per workspace (unique
`tenant_id`) holding the CI an admin sets in Einstellungen — company name,
footer line, the AGB paragraph, the primary colour, a default contact phone
and the logo. Classification: tenant record (workspace settings), no
personal data about candidates or contacts.

Fail-closed RLS like every tenant table, applied OUTSIDE the create branch:
`create_all` on startup makes tables without policies, so a database where
it ran first would otherwise keep this table unpoliced (see 0041, 0044).

Revision ID: 0076
Revises: 0075
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0076"
down_revision: str | None = "0075"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "workspace_branding"
_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("company_name", sa.String(200), nullable=True),
            sa.Column("company_line", sa.String(500), nullable=True),
            sa.Column("legal_text", sa.Text(), nullable=True),
            sa.Column("primary_color", sa.String(7), nullable=False),
            sa.Column("contact_phone", sa.String(50), nullable=True),
            sa.Column("logo", sa.LargeBinary(), nullable=True),
            sa.Column("logo_content_type", sa.String(50), nullable=True),
            sa.Column("updated_by_name", sa.String(200), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", name="uq_workspace_branding_tenant"),
        )
        op.create_index("ix_workspace_branding_tenant_id", _TABLE, ["tenant_id"])

    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {_TABLE} "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
