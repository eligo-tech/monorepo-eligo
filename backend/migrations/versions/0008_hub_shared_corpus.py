"""Make the hub corpus shared; move the tenant boundary to an overlay table.

0007 created the corpus tenant-scoped. That was wrong for what the data IS:
"bayoonet AG is at 10115 Berlin and has three open roles" is a public fact,
identical for every tenant. Storing it per tenant means N copies of one truth
and N crawls of one source, and leaves no shared asset to offer.

So `hub_companies`, `hub_job_postings` and `hub_observations` lose `tenant_id`
and become shared reference data — a deliberate, documented exception to §2.3
(see backend/CLAUDE.md §2.6). The tenant boundary moves to the new
`hub_company_link`: which corpus companies a tenant watches, and which of their
own `companies` rows each maps to. That table carries `tenant_id` and gets the
standard fail-closed policy.

RLS on the shared tables is ENABLED with an explicit permissive policy rather
than switched off — same shape as 0006 for `tenants`. The app connects as one
role, so RLS cannot distinguish "the ingester" from "a reader"; write protection
is the ingest endpoint's auth, not a policy. Enabling with USING (true) states
"intentionally readable by everyone" instead of leaving a table that merely
looks forgotten.

Implemented as drop-and-recreate rather than ALTER: the tables are empty (see
the guard), SQLite cannot ALTER constraints at all, and a fresh CREATE keeps one
readable definition per table instead of a pile of dialect-specific ops.

SAFETY: refuses to run if the corpus already holds rows. Dropping `tenant_id`
would silently merge every tenant's private corpus into one shared pool — a
no-op while the tables are empty (they are; nothing has ingested), a data
incident otherwise.

Revision ID: 0008
Revises: 0007
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Children first — postings reference companies and observations.
_ORDERED = ["hub_job_postings", "hub_companies", "hub_observations"]
_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def _json_type(bind) -> sa.types.TypeEngine:
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.JSONB()
    return sa.JSON()


def _guard_empty(bind, tables: list[str]) -> None:
    """Refuse to reshape a corpus that already holds rows."""
    existing = set(sa.inspect(bind).get_table_names())
    for table in tables:
        if table not in existing:
            continue
        count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar() or 0
        if count:
            raise RuntimeError(
                f"{table} holds {count} rows — this migration would merge per-tenant "
                "corpora into one shared pool. Truncate the hub tables and re-ingest "
                "(the corpus is rebuildable from its sources by design)."
            )


def _drop_all(bind) -> None:
    existing = set(sa.inspect(bind).get_table_names())
    if "hub_company_link" in existing:
        op.drop_table("hub_company_link")
    for table in _ORDERED:
        if table in existing:
            op.drop_table(table)


def _create_observations(json_type, *, tenant_scoped: bool) -> None:
    cols = [
        sa.Column("id", sa.Uuid(), primary_key=True),
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
    ]
    if tenant_scoped:
        cols.insert(1, sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True))
    op.create_table("hub_observations", *cols)


def _create_companies(json_type, *, tenant_scoped: bool) -> None:
    cols = [
        sa.Column("id", sa.Uuid(), primary_key=True),
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
        sa.Column("open_postings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bd_signals", json_type, nullable=False, server_default="{}"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]
    identity = ["dedupe_key"]
    name_index = ["normalized_name"]
    if tenant_scoped:
        cols.insert(1, sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True))
        cols.append(sa.Column("visibility", sa.String(20), nullable=False, server_default="private"))
        cols.append(sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=True, index=True))
        identity = ["tenant_id", "dedupe_key"]
        name_index = ["tenant_id", "normalized_name"]
    cols.append(sa.UniqueConstraint(*identity, name="uq_hub_company_identity"))
    op.create_table("hub_companies", *cols)
    op.create_index("ix_hub_company_normalized_name", "hub_companies", name_index)


def _create_postings(json_type, *, tenant_scoped: bool) -> None:
    cols = [
        sa.Column("id", sa.Uuid(), primary_key=True),
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
    ]
    identity = ["source", "external_id"]
    active_index = ["hub_company_id", "is_active"]
    if tenant_scoped:
        cols.insert(1, sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True))
        identity = ["tenant_id", *identity]
        active_index = ["tenant_id", *active_index]
    cols.append(sa.UniqueConstraint(*identity, name="uq_hub_posting_source_id"))
    op.create_table("hub_job_postings", *cols)
    op.create_index("ix_hub_posting_company_active", "hub_job_postings", active_index)


def _create_link() -> None:
    op.create_table(
        "hub_company_link",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("hub_company_id", sa.Uuid(), sa.ForeignKey("hub_companies.id"), nullable=False, index=True),
        sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id"), nullable=True, index=True),
        sa.Column("relationship", sa.String(20), nullable=False, server_default="watching"),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "hub_company_id", name="uq_hub_link_tenant_company"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    _guard_empty(bind, _ORDERED)
    json_type = _json_type(bind)

    _drop_all(bind)
    _create_observations(json_type, tenant_scoped=False)
    _create_companies(json_type, tenant_scoped=False)
    _create_postings(json_type, tenant_scoped=False)
    _create_link()

    if bind.dialect.name != "postgresql":
        return
    for table in _ORDERED:
        # Explicitly permissive: shared reference data, readable by everyone.
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"DROP POLICY IF EXISTS shared_corpus_read ON {table}")
        op.execute(
            f"CREATE POLICY shared_corpus_read ON {table} "
            "USING (true) WITH CHECK (true)"
        )
    op.execute("ALTER TABLE hub_company_link ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE hub_company_link FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON hub_company_link")
    op.execute(
        "CREATE POLICY tenant_isolation ON hub_company_link "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def downgrade() -> None:
    bind = op.get_bind()
    _guard_empty(bind, _ORDERED)
    json_type = _json_type(bind)

    _drop_all(bind)
    _create_observations(json_type, tenant_scoped=True)
    _create_companies(json_type, tenant_scoped=True)
    _create_postings(json_type, tenant_scoped=True)

    if bind.dialect.name != "postgresql":
        return
    for table in _ORDERED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS shared_corpus_read ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )
