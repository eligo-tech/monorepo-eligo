"""Changes an AI client proposed, waiting for a human in Eligo (PR 4).

One tenant table, `agent_proposals`. An MCP client (Claude) may propose a
process-step update or a candidate note; the row waits until a member of the
workspace confirms or declines it in Eligo. Classification: personal data,
tenant-scoped — a note proposal carries the note text, erased on decline.

Fail-closed RLS like every tenant table. Applied OUTSIDE the create branch:
`create_all` on startup makes tables without policies, so a database where it
ran first would otherwise keep this table unpoliced (see 0041).

Revision ID: 0044
Revises: 0043
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "agent_proposals"
_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"


def _json_type(bind) -> sa.types.TypeEngine:  # noqa: ANN001
    """JSONB on Postgres, TEXT on SQLite — the same split as `JSONDict` (see 0043)."""
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.JSONB()
    return sa.Text()


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="pending", index=True),
            sa.Column("tool", sa.String(80), nullable=False),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("args", _json_type(bind), nullable=False),
            sa.Column("snapshot", _json_type(bind), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("asked_by_user_id", sa.String(80), nullable=True, index=True),
            sa.Column("asked_by_name", sa.String(160), nullable=True),
            sa.Column("client_id", sa.String(80), nullable=True),
            sa.Column("decided_by_user_id", sa.String(80), nullable=True),
            sa.Column("decided_by_name", sa.String(160), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True),
                      server_default=sa.func.now(), nullable=False),
        )

    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {_TABLE} "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)
