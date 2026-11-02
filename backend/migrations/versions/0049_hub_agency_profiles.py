"""The agency finder's ranked list: `hub_agency_profiles`.

Derived from the private-recruiter corpus rows and rebuilt in full by the
nightly job — one row per agency (its branches folded together) with the
deterministic verdict, score and the evidence for both
(`app/domain/hub/agency_rank.py`).

Shared corpus — no tenant_id — with the same explicitly permissive
`shared_corpus_read` policy as the tables it is derived from. Who may SEE it is
decided in the API (`agency_finder_tenants`, fail-closed). No personal data:
counts, posting ids and company mail domains only.

Revision ID: 0049
Revises: 0048
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_agency_profiles"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():  # else create_all made it
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("group_key", sa.String(300), nullable=False, unique=True),
            sa.Column("name", sa.String(300), nullable=False),
            sa.Column("primary_company_id", sa.Uuid(), nullable=False),
            sa.Column("company_ids", sa.JSON(), nullable=False),
            sa.Column("verdict", sa.String(20), nullable=False, index=True),
            sa.Column("score", sa.Integer(), nullable=False, index=True),
            sa.Column("open_postings", sa.Integer(), nullable=False),
            sa.Column("new_28d", sa.Integer(), nullable=False),
            sa.Column("region", sa.String(80), nullable=True),
            sa.Column("city", sa.String(200), nullable=True),
            sa.Column("fields", sa.JSON(), nullable=False),
            sa.Column("reasons", sa.JSON(), nullable=False),
            sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS shared_corpus_read ON {_TABLE}")
    op.execute(f"CREATE POLICY shared_corpus_read ON {_TABLE} USING (true) WITH CHECK (true)")


def downgrade() -> None:
    # Derived data: the next nightly refresh rebuilds it, so dropping is safe.
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
