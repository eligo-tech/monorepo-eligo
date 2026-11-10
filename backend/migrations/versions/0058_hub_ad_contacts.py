"""Ad contacts stored nightly: `hub_ad_contacts` + the pass's queue (ELI-22).

`hub/ad_contacts.py` reads the person each open ad names ("Frau Katrin Wolter
(Pflegedienstleitung), 0395 5442681") with the deterministic parser in
`hub/contacts.py` and stores one row per person per ad, so a call list can
span the market. Measured 2026-11-10 on prod: 17.6 % of 242k employers name a
person in an active ad, 10.2 % with a phone.

Shared corpus, no tenant_id — ARCHITECTURE.md RULE 2 (decision 2026-09-18): a
person as the public ad published them, with provenance per row. Same
permissive `shared_corpus_read` policy as the other corpus tables; Supabase's
Data API roles revoked (0051).

`hub_job_postings.contacts_read_at` / `contacts_rules`: nullable, no default —
metadata-only, no rewrite of the 700k-row table. The queue index is partial
and built CONCURRENTLY (see 0054/0057 for the guards). Parser rules version 1;
a bump ships its own migration rebuilding the index with the new number.

Revision ID: 0058
Revises: 0057
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POSTINGS = "hub_job_postings"
_TABLE = "hub_ad_contacts"
_COLUMNS = {"contacts_read_at": sa.DateTime(timezone=True), "contacts_rules": sa.Integer()}
# Written out, not imported from the models: a migration must keep meaning
# what it meant when it ran.
_QUEUE = (
    "ix_hub_posting_contacts_due",
    "id",
    "is_active AND (contacts_rules IS NULL OR contacts_rules < 1 OR contacts_read_at < "
    "description_fetched_at OR contacts_read_at < source_page_fetched_at)",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    postgres = bind.dialect.name == "postgresql"
    tables = inspector.get_table_names()

    if _POSTINGS in tables:
        if postgres:
            op.execute("SET LOCAL lock_timeout = '10s'")
            op.execute("SET LOCAL statement_timeout = 0")
        existing = {c["name"] for c in inspector.get_columns(_POSTINGS)}
        for name, type_ in _COLUMNS.items():
            if name not in existing:
                op.add_column(_POSTINGS, sa.Column(name, type_, nullable=True))

    if _TABLE not in tables:  # else create_all made it
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "hub_job_posting_id", sa.Uuid(),
                sa.ForeignKey("hub_job_postings.id", ondelete="CASCADE"), nullable=False, index=True,
            ),
            sa.Column(
                "hub_company_id", sa.Uuid(),
                sa.ForeignKey("hub_companies.id", ondelete="CASCADE"), nullable=False, index=True,
            ),
            sa.Column("person_key", sa.String(120), nullable=False, index=True),
            sa.Column("full_name", sa.String(200), nullable=False),
            sa.Column("salutation", sa.String(10), nullable=True),
            sa.Column("first_name", sa.String(120), nullable=True),
            sa.Column("last_name", sa.String(120), nullable=False),
            sa.Column("role_title", sa.String(200), nullable=True),
            sa.Column("phone", sa.String(60), nullable=True),
            sa.Column("phone_kind", sa.String(20), nullable=True),
            sa.Column("email", sa.String(320), nullable=True),
            sa.Column("quote", sa.Text(), nullable=False),
            sa.Column("text_source", sa.String(10), nullable=False),
            sa.Column("source_fetched_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("hub_job_posting_id", "person_key", name="uq_hub_ad_contact_posting_person"),
        )

    name, column, where = _QUEUE
    if not postgres:
        if _POSTINGS in tables:
            op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {_POSTINGS} ({column}) WHERE {where}")
        return

    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS shared_corpus_read ON {_TABLE}")
    op.execute(f"CREATE POLICY shared_corpus_read ON {_TABLE} USING (true) WITH CHECK (true)")
    for role in ("anon", "authenticated"):
        if bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar():
            op.execute(f"REVOKE ALL ON {_TABLE} FROM {role}")

    if _POSTINGS not in tables:
        return
    # CONCURRENTLY, and an INVALID leftover from a dead build is rebuilt — 0054.
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '10min'")
        invalid = bind.execute(sa.text(
            "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name AND NOT i.indisvalid"
        ), {"name": name}).scalar()
        if invalid:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {_POSTINGS} ({column}) WHERE {where}")
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def downgrade() -> None:
    # Derived from ad texts in the corpus: the nightly pass rebuilds it.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if _TABLE in tables:
        op.drop_table(_TABLE)
    if _POSTINGS in tables:
        op.execute(f"DROP INDEX IF EXISTS {_QUEUE[0]}")
        existing = {c["name"] for c in inspector.get_columns(_POSTINGS)}
        for name in _COLUMNS:
            if name in existing:
                op.drop_column(_POSTINGS, name)
