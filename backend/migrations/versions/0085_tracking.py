"""ELI-64: Tracking — Umsatz, Business Development, Prozess, Cockpit tiles.

Columns on existing tenant tables (their fail-closed RLS policies already
cover them):

- `applications.fee_eur` — "Honorar (€)", entered on the Vertrag step. Umsatz
  is the sum of these over deals closed in the period. NULL for every
  existing row: no fee was ever recorded, and inventing one would be revenue
  nobody earned.
- `companies.framework_contract_on` / `_by` / `_by_name` — "Rahmenvertrag
  abgeschlossen am", set by a person on the company page.
- `managers.created_by_user_id` / `created_by_name`, the same on `jobs` —
  who created a lead or a mandate, filled from the request's actor. NULL for
  existing rows: nobody recorded it, so they count for the team only.
- `activity_targets.members` / `label` / `valid_from` — a goal shared by a
  group of consultants, and a goal that starts on a date.

One new tenant table, `tracking_preferences` (which tiles one person shows
on the Cockpit), with the fail-closed policy applied OUTSIDE the create
branch: `create_all` on startup makes tables without policies (see 0076).

Classification: tenant record. `created_by_*`, `framework_contract_by*` and
`tracking_preferences.user_id` are workspace members' ids/names — the same
kind of value `actor_user_id`/`actor_name` already hold.

Revision ID: 0083
Revises: 0082
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0083"
down_revision: str | None = "0082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tracking_preferences"
_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"

def _columns() -> dict[str, list[sa.Column]]:
    """Fresh Column objects per call: one attached to a table by
    `add_column` cannot be attached again in the same process."""
    return {
    "applications": [sa.Column("fee_eur", sa.Integer(), nullable=True)],
    "companies": [
        sa.Column("framework_contract_on", sa.Date(), nullable=True),
        sa.Column("framework_contract_by", sa.String(80), nullable=True),
        sa.Column("framework_contract_by_name", sa.String(160), nullable=True),
    ],
    "managers": [
        sa.Column("created_by_user_id", sa.String(80), nullable=True),
        sa.Column("created_by_name", sa.String(160), nullable=True),
    ],
    "jobs": [
        sa.Column("created_by_user_id", sa.String(80), nullable=True),
        sa.Column("created_by_name", sa.String(160), nullable=True),
    ],
    "activity_targets": [
        # json, as `JSONList` maps on Postgres; existing rows get "[]".
        sa.Column("members", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("label", sa.String(80), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=True),
    ],
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, columns in _columns().items():
        have = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column.name not in have:
                op.add_column(table, column)

    if _TABLE not in set(inspector.get_table_names()):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.String(80), nullable=False),
            sa.Column("tiles", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", "user_id", name="uq_tracking_preference"),
        )
        op.create_index("ix_tracking_preferences_tenant_id", _TABLE, ["tenant_id"])

    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {_TABLE} "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE in set(inspector.get_table_names()):
        op.drop_table(_TABLE)
    for table, columns in _columns().items():
        have = {c["name"] for c in inspector.get_columns(table)}
        for column in columns:
            if column.name in have:
                op.drop_column(table, column.name)
