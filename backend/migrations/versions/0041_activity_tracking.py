"""What each consultant did, and what they were asked to do (ELI-15).

Two tables and a backfill.

`activity_events` is the countable record: one row per thing that a KPI
measures, carrying WHO did it and WHEN it happened. The process document
sets the rule — "jede Kennzahl entsteht aus einem Ereignis, das im System
ohnehin erfasst wird" — so nothing here asks anybody to count by hand.

`activity_targets` is the Ziel, per consultant and per period, with a
workspace-wide default row (`actor_user_id IS NULL`) that anybody without
their own number inherits.

THE BACKFILL, and why it writes NULL authors. The two sources —
`manager_interactions` and `process_steps` — have existed for months and
hold real history, but neither ever recorded who wrote the row. Copying
that history in with no author is the honest import: the events are real,
the attribution genuinely does not exist, and the UI shows that bucket as
"Nicht zugeordnet". The alternative — starting the counters at zero today —
would make a workspace with a year of calls look like it had never made
one. The alternative after that — guessing an author — would put somebody's
name on work we cannot prove they did.

Reversible: `downgrade` drops both tables.

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

#: Mirrors `app.domain.activity.kpis.MANAGER_CALL_KINDS`.
_CALL_KINDS = ("business_call", "client_call")


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
    tables = set(sa.inspect(bind).get_table_names())

    if "activity_events" not in tables:
        op.create_table(
            "activity_events",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("event_type", sa.String(40), nullable=False),
            sa.Column("actor_user_id", sa.String(80), nullable=True, index=True),
            sa.Column("actor_name", sa.String(160), nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("ref_type", sa.String(30), nullable=False),
            sa.Column("ref_id", sa.Uuid(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("tenant_id", "event_type", "ref_id",
                                name="uq_activity_event_ref"),
        )
        op.create_index(
            "ix_activity_events_kind_when",
            "activity_events",
            ["tenant_id", "event_type", "occurred_at"],
        )

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

    # OUTSIDE the create branches, deliberately. `create_all` on startup
    # makes tables but no policies, so a database where it ran first would
    # otherwise keep a tenant table with RLS unenforced forever — the
    # migration would see the table, skip it, and skip the policy with it.
    # This is not hypothetical: it happened to this very table on the
    # production database before this migration shipped.
    if bind.dialect.name == "postgresql":
        _rls("activity_events")
        _rls("activity_targets")

    _backfill(bind)


def _backfill(bind) -> None:
    """History, with no author — see the module docstring."""
    tables = set(sa.inspect(bind).get_table_names())
    gen = "gen_random_uuid()" if bind.dialect.name == "postgresql" else "lower(hex(randomblob(16)))"

    if "manager_interactions" in tables:
        kinds = ", ".join(f"'{k}'" for k in _CALL_KINDS)
        op.execute(
            f"""
            INSERT INTO activity_events
                (id, tenant_id, event_type, actor_user_id, actor_name,
                 occurred_at, ref_type, ref_id, created_at, updated_at)
            SELECT {gen}, mi.tenant_id, 'manager_call', NULL, NULL,
                   mi.occurred_at, 'manager_interaction', mi.id,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
              FROM manager_interactions mi
             WHERE mi.interaction_type IN ({kinds})
               AND mi.manager_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM activity_events e
                    WHERE e.tenant_id = mi.tenant_id
                      AND e.event_type = 'manager_call'
                      AND e.ref_id = mi.id)
            """
        )

    if "process_steps" in tables:
        # Same rule the tracker itself uses: a step counts as reached on a
        # done date, a booked date or a green cell. `occurred_at` prefers
        # the date the recruiter recorded over the row's own mtime.
        op.execute(
            f"""
            INSERT INTO activity_events
                (id, tenant_id, event_type, actor_user_id, actor_name,
                 occurred_at, ref_type, ref_id, created_at, updated_at)
            SELECT {gen}, ps.tenant_id, 'candidate_presented', NULL, NULL,
                   COALESCE(ps.done_at, ps.scheduled_at, ps.created_at),
                   'process_step', ps.id,
                   CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
              FROM process_steps ps
             WHERE ps.step_key = 'vorgestellt'
               AND ps.active = true
               AND (ps.done_at IS NOT NULL
                    OR ps.scheduled_at IS NOT NULL
                    OR ps.outcome = 'pass')
               AND NOT EXISTS (
                   SELECT 1 FROM activity_events e
                    WHERE e.tenant_id = ps.tenant_id
                      AND e.event_type = 'candidate_presented'
                      AND e.ref_id = ps.id)
            """
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("activity_events", "activity_targets"):
        if table in tables:
            op.drop_table(table)
