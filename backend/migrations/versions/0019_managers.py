"""Managers — the hiring-side person, and the record of talking to them.

A mandate belongs to a person, not to a legal entity. `managers` is the join
that makes companies, jobs and candidates into a graph a recruiter can work.

These rows are PERSONAL DATA, which decides where they live. ARCHITECTURE.md
RULE 2 forbids natural persons in the shared `hub_*` corpus, so managers are
tenant-scoped like candidates and `company_id` references the tenant's own
`companies` row — never a corpus company. Adopting a corpus company is the gated
crossing that already leaves a receipt; a manager is added after it.

Provenance ships in this migration rather than as a later column, because it
cannot be reconstructed: once rows exist without a source, where they came from
is unknowable, and the Art. 14 obligation turns on exactly that.

Revision ID: 0019
Revises: 0018
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fail-closed: an unset GUC makes the predicate NULL, which matches no row.
# A missing tenant context yields zero rows rather than every row.
_PREDICATE = (
    "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
)
_TABLES = ("managers", "manager_interactions")


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "managers" not in existing:
        op.create_table(
            "managers",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column(
                "company_id",
                sa.Uuid(),
                sa.ForeignKey("companies.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("full_name", sa.String(200), nullable=False),
            sa.Column("first_name", sa.String(120), nullable=True),
            sa.Column("last_name", sa.String(120), nullable=True),
            sa.Column("role_title", sa.String(200), nullable=True),
            sa.Column("department", sa.String(120), nullable=True),
            sa.Column("email", sa.String(320), nullable=True, index=True),
            sa.Column("phone", sa.String(50), nullable=True),
            sa.Column("linkedin_url", sa.String(300), nullable=True),
            # provenance — see module docstring
            sa.Column(
                "source",
                sa.String(40),
                nullable=False,
                server_default="self_reported",
            ),
            sa.Column("source_detail", sa.String(500), nullable=True),
            sa.Column(
                "art14_notified_at", sa.DateTime(timezone=True), nullable=True
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "status", sa.String(30), nullable=False, server_default="active"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    if "manager_interactions" not in existing:
        op.create_table(
            "manager_interactions",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column(
                "manager_id",
                sa.Uuid(),
                sa.ForeignKey("managers.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "candidate_id",
                sa.Uuid(),
                sa.ForeignKey("candidates.id"),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "job_id",
                sa.Uuid(),
                sa.ForeignKey("jobs.id"),
                nullable=True,
                index=True,
            ),
            sa.Column("interaction_type", sa.String(30), nullable=False),
            sa.Column(
                "occurred_at",
                sa.DateTime(timezone=True),
                nullable=False,
                index=True,
            ),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    # jobs.manager_id — the mandate's owner. SQLite cannot add a constrained
    # column to an existing table, so the FK is Postgres-only; the model
    # declares it for both and `create_all` gives a fresh SQLite db the full
    # shape anyway.
    # `jobs` is created by `create_all` on a fresh database, not by a migration,
    # so on a migrations-only run from scratch it may not exist yet. Guard
    # rather than assume: this migration must be safe in both bootstrap orders.
    job_columns = (
        {c["name"] for c in sa.inspect(bind).get_columns("jobs")}
        if "jobs" in sa.inspect(bind).get_table_names()
        else set()
    )
    if "jobs" in sa.inspect(bind).get_table_names() and "manager_id" not in job_columns:
        if bind.dialect.name == "postgresql":
            op.add_column(
                "jobs",
                sa.Column(
                    "manager_id",
                    sa.Uuid(),
                    sa.ForeignKey("managers.id"),
                    nullable=True,
                ),
            )
        else:
            op.add_column("jobs", sa.Column("manager_id", sa.Uuid(), nullable=True))
        op.create_index("ix_jobs_manager_id", "jobs", ["manager_id"])

    if bind.dialect.name != "postgresql":
        return
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    job_columns = (
        {c["name"] for c in sa.inspect(bind).get_columns("jobs")}
        if "jobs" in tables
        else set()
    )
    if "manager_id" in job_columns:
        op.drop_index("ix_jobs_manager_id", table_name="jobs")
        op.drop_column("jobs", "manager_id")
    existing = tables
    if "manager_interactions" in existing:
        op.drop_table("manager_interactions")
    if "managers" in existing:
        op.drop_table("managers")
