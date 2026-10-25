"""Who did it, and what they were asked to do (ELI-15).

Two author columns and one new table — and deliberately NOT an events table.

An earlier draft of this feature kept `activity_events`, a row per
countable action copied out of `manager_interactions` and `process_steps`.
That stored the same call twice. Two copies of one fact can disagree, and
this pair would have: deleting a note left its event behind, and any write
path that did not know about the copy would drift it silently.

What those rows actually lacked was an author. So that is what they get
here, and the KPIs count the real rows. The only thing with no home
anywhere was the Ziel, which is `activity_targets`.

`activity_events` IS DROPPED if present. On the production database it
exists because `create_all` was run against it by accident while this
feature was being built; it is empty, nothing reads it, and leaving an
unused table that looks like a second source of truth is worse than
removing it. On every other database this is a no-op.

The author columns are nullable and are NOT backfilled. Everything the
aiFind importer wrote, and everything saved before today, genuinely has no
author — the tracking screen shows that as "Nicht zugeordnet". Guessing
would put somebody's name on work we cannot prove they did.

Revision ID: 0041
Revises: 0040
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"

#: The tables whose rows ARE the events a KPI counts.
_AUTHORED = ("manager_interactions", "process_steps")


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table in _AUTHORED:
        if table not in tables:
            continue  # fresh database: create_all already has the columns
        columns = {c["name"] for c in inspector.get_columns(table)}
        if "actor_user_id" not in columns:
            op.add_column(table, sa.Column("actor_user_id", sa.String(80), nullable=True))
            op.create_index(f"ix_{table}_actor_user_id", table, ["actor_user_id"])
        if "actor_name" not in columns:
            op.add_column(table, sa.Column("actor_name", sa.String(160), nullable=True))

    if "activity_targets" not in tables:
        op.create_table(
            "activity_targets",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("actor_user_id", sa.String(80), nullable=True),
            sa.Column("kpi", sa.String(40), nullable=False),
            sa.Column("period", sa.String(10), nullable=False),
            sa.Column("value", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", "actor_user_id", "kpi", "period",
                                name="uq_activity_target"),
        )

    # The accidental table. Empty, unread, and the whole point of this
    # migration is that it should never have existed.
    if "activity_events" in tables:
        op.drop_table("activity_events")

    # OUTSIDE the create branch, deliberately. `create_all` on startup makes
    # tables but no policies, so a database where it ran first would keep a
    # tenant table with RLS unenforced forever: the migration would see the
    # table, skip it, and skip the policy with it. That is exactly how
    # `activity_targets` reached production with force=OFF.
    if bind.dialect.name == "postgresql":
        _rls("activity_targets")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "activity_targets" in tables:
        op.drop_table("activity_targets")

    for table in _AUTHORED:
        if table not in tables:
            continue
        columns = {c["name"] for c in inspector.get_columns(table)}
        if "actor_user_id" in columns:
            op.drop_index(f"ix_{table}_actor_user_id", table_name=table)
            op.drop_column(table, "actor_user_id")
        if "actor_name" in columns:
            op.drop_column(table, "actor_name")
