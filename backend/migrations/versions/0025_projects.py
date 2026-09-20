"""Projects — a named set of target companies.

Markt finds employers, "Beobachten" keeps them, and a project is the grouping a
recruiter gives that work: a name, and the corpus companies under it. Two
tables, both tenant-scoped and RLS-isolated — which companies someone is
working is competitive intelligence, exactly like the saved searches in 0010.

Nothing is copied: `project_companies` points at `hub_companies`, so a
project's numbers are always the corpus's current answer.

Revision ID: 0025
Revises: 0024
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def _rls(table: str) -> None:
    """Fail-closed tenant isolation, same shape as 0003/0005/0010: an unset GUC
    resolves to NULL, so an un-pinned query returns zero rows rather than all."""
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    # Idempotent w.r.t. create_all: a fresh database already has both tables.
    if "projects" not in tables:
        op.create_table(
            "projects",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("tenant_id", "name", name="uq_project_tenant_name"),
        )
    if "project_companies" not in tables:
        op.create_table(
            "project_companies",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column(
                "project_id",
                sa.Uuid(),
                sa.ForeignKey("projects.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "hub_company_id",
                sa.Uuid(),
                sa.ForeignKey("hub_companies.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint(
                "project_id", "hub_company_id", name="uq_project_company"
            ),
        )

    _rls("projects")
    _rls("project_companies")


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "project_companies" in tables:
        op.drop_table("project_companies")
    if "projects" in tables:
        op.drop_table("projects")
