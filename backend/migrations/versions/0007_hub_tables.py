"""Create the information-hub corpus tables and isolate them with RLS.

Three tables (see app/domain/hub/models.py): `hub_observations` (append-only
evidence of every fetch), `hub_companies` (deduplicated company corpus) and
`hub_job_postings` (external postings — market signals, deliberately separate
from `jobs`, which are client mandates driving the matcher).

All three carry a `tenant_id` and get the same fail-closed policy as every other
core table (0003/0005): rows are visible only when `tenant_id` matches the
per-transaction `app.current_tenant` GUC.

Idempotent w.r.t. `create_all`: each table is skipped if it already exists.

Revision ID: 0007
Revises: 0006
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ["hub_observations", "hub_companies", "hub_job_postings"]
_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def _json_type(bind: sa.engine.Connection) -> sa.types.TypeEngine:
    """JSONB on Postgres, portable JSON elsewhere — mirrors common/types.py."""
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.JSONB()
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    json_type = _json_type(bind)

    if "hub_observations" not in existing:
        op.create_table(
            "hub_observations",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("source", sa.String(60), nullable=False, index=True),
            sa.Column("request_url", sa.String(1000), nullable=False),
            sa.Column("http_status", sa.Integer(), nullable=True),
            sa.Column("robots_allowed", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_available", sa.Integer(), nullable=True),
            sa.Column("content_hash", sa.String(64), nullable=True),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("note", sa.String(500), nullable=True),
            sa.Column("payload", json_type, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if "hub_companies" not in existing:
        op.create_table(
            "hub_companies",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("name", sa.String(300), nullable=False),
            sa.Column("normalized_name", sa.String(300), nullable=False),
            sa.Column("legal_form", sa.String(40), nullable=True),
            sa.Column("dedupe_key", sa.String(400), nullable=False),
            sa.Column("resolution_basis", sa.String(20), nullable=False),
            sa.Column("website_domain", sa.String(255), nullable=True, index=True),
            sa.Column("street", sa.String(255), nullable=True),
            sa.Column("postal_code", sa.String(20), nullable=True),
            sa.Column("city", sa.String(120), nullable=True, index=True),
            sa.Column("region", sa.String(120), nullable=True),
            sa.Column("country", sa.String(80), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("register_court", sa.String(120), nullable=True),
            sa.Column("register_number", sa.String(40), nullable=True),
            sa.Column("vat_id", sa.String(20), nullable=True, index=True),
            sa.Column("vat_verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("industry", sa.String(120), nullable=True),
            sa.Column("source", sa.String(60), nullable=False),
            sa.Column("visibility", sa.String(20), nullable=False, server_default="private"),
            sa.Column("open_postings_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("bd_signals", json_type, nullable=False, server_default="{}"),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=True, index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_hub_company_identity"),
        )
        op.create_index(
            "ix_hub_company_normalized_name", "hub_companies", ["tenant_id", "normalized_name"]
        )

    if "hub_job_postings" not in existing:
        op.create_table(
            "hub_job_postings",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("hub_company_id", sa.Uuid(), sa.ForeignKey("hub_companies.id"), nullable=False, index=True),
            sa.Column("observation_id", sa.Uuid(), sa.ForeignKey("hub_observations.id"), nullable=True, index=True),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("occupation", sa.String(200), nullable=True),
            sa.Column("employment_type", sa.String(40), nullable=True),
            sa.Column("location_text", sa.String(200), nullable=True),
            sa.Column("postal_code", sa.String(20), nullable=True),
            sa.Column("city", sa.String(120), nullable=True, index=True),
            sa.Column("country", sa.String(80), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("remote_possible", sa.Boolean(), nullable=True),
            sa.Column("salary_min", sa.Integer(), nullable=True),
            sa.Column("salary_max", sa.Integer(), nullable=True),
            sa.Column("salary_currency", sa.String(3), nullable=True),
            sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True, index=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source", sa.String(60), nullable=False, index=True),
            sa.Column("source_url", sa.String(1000), nullable=True),
            sa.Column("external_id", sa.String(200), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("raw", json_type, nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", "source", "external_id", name="uq_hub_posting_source_id"),
        )
        op.create_index(
            "ix_hub_posting_company_active",
            "hub_job_postings",
            ["tenant_id", "hub_company_id", "is_active"],
        )

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
    if bind.dialect.name == "postgresql":
        for table in _TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    existing = set(sa.inspect(bind).get_table_names())
    # Dropped children-first: postings reference companies and observations.
    for table in ("hub_job_postings", "hub_companies", "hub_observations"):
        if table in existing:
            op.drop_table(table)
