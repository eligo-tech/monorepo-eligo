"""Several phone numbers per manager, with a kind and a primary (ELI-46).

- `managers.phone_kind` — the kind of the primary number, which stays in
  `managers.phone` so every existing reader and writer (aiFind import,
  ad-contact adoption, Leads list, "Anruf erfassen") keeps working.
  Nullable: NULL reads as "other" (Sonstige). That IS the backfill for the
  numbers already stored — each existing phone is the primary "Sonstige" —
  without rewriting every manager row to say so.
- `manager_phones` — the further numbers: number, kind (mobile · direct ·
  switchboard · other), position. Classification: tenant personal data, like
  `managers`; erased with the person (`erasure.erase_manager`), FK cascades.

Fail-closed RLS like every tenant table, applied OUTSIDE the create branch:
`create_all` on startup makes tables without policies (see 0041, 0044, 0074).

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

_TABLE = "manager_phones"
_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "phone_kind" not in {c["name"] for c in inspector.get_columns("managers")}:
        op.add_column("managers", sa.Column("phone_kind", sa.String(20), nullable=True))

    if _TABLE not in set(inspector.get_table_names()):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column(
                "manager_id", sa.Uuid(),
                sa.ForeignKey("managers.id", ondelete="CASCADE"), nullable=False,
            ),
            sa.Column("number", sa.String(50), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="other"),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_manager_phones_tenant_id", _TABLE, ["tenant_id"])
        op.create_index("ix_manager_phones_manager_id", _TABLE, ["manager_id"])

    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {_TABLE} "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE in set(inspector.get_table_names()):
        op.drop_table(_TABLE)
    if "phone_kind" in {c["name"] for c in inspector.get_columns("managers")}:
        op.drop_column("managers", "phone_kind")
