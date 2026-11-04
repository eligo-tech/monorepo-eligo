"""Website checks against the Impressum: `hub_site_checks`.

One row per website candidate the agency finder has checked
(`app/domain/hub/sites.py`): the outcome, the Impressum URL, the fetch
(`hub_observations`) and the COMPANY facts it published — register, VAT,
company phone, function mailboxes. No people (decision 2026-11-04, option A).

Shared corpus — no tenant_id — with the same permissive `shared_corpus_read`
policy as the tables it complements. Only allowlisted workspaces reach it
through the API.

Revision ID: 0053
Revises: 0052
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_site_checks"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():  # else create_all made it
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("domain", sa.String(253), nullable=False, index=True),
            sa.Column("group_key", sa.String(300), nullable=False, index=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("impressum_url", sa.String(1000), nullable=True),
            sa.Column("observation_id", sa.Uuid(), sa.ForeignKey("hub_observations.id"), nullable=True),
            sa.Column("facts", sa.JSON(), nullable=False),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("domain", "group_key", name="uq_hub_site_check_domain_group"),
        )
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS shared_corpus_read ON {_TABLE}")
    op.execute(f"CREATE POLICY shared_corpus_read ON {_TABLE} USING (true) WITH CHECK (true)")
    # Supabase's Data API roles must not reach it (see 0051).
    for role in ("anon", "authenticated"):
        if bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar():
            op.execute(f"REVOKE ALL ON {_TABLE} FROM {role}")


def downgrade() -> None:
    # Derived from public pages: re-checked on the next runs if dropped.
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
