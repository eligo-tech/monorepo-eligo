"""The opt-out list: `hub_suppressions`.

Erasure (GDPR Art. 17) and objection (Art. 21) in a corpus that re-ingests
every night: a tombstone every corpus write checks, so a deleted company or
name does not come back with the next crawl (ARCHITECTURE.md §3).

Shared like the corpus — no tenant_id. RLS is ENABLED with a SELECT-only
policy and deliberately NOT forced: the app role (not the owner) may read the
list and is refused every write, while the owner — the connection
`scripts/hub_suppress.py` uses — writes it. FORCE would subject the owner to
the same SELECT-only policy and leave nobody able to add a suppression.

Revision ID: 0047
Revises: 0046
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_suppressions"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():  # else create_all made it
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("scope", sa.String(20), nullable=False),
            sa.Column("key", sa.String(300), nullable=False),
            sa.Column("reason", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("scope", "key", name="uq_hub_suppression_scope_key"),
        )
    if bind.dialect.name != "postgresql":
        return
    # The policy is applied whether this migration or create_all made the table.
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS suppressions_read ON {_TABLE}")
    op.execute(f"CREATE POLICY suppressions_read ON {_TABLE} FOR SELECT USING (true)")
    # Supabase grants its Data API roles every new table by default. This list
    # names the people who asked to be left out; it has no business there.
    for role in ("anon", "authenticated"):
        exists = bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}
        ).scalar()
        if exists:
            op.execute(f"REVOKE ALL ON {_TABLE} FROM {role}")


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return
    # Dropping a filled list un-erases people: the next crawl brings every
    # suppressed record back. Refuse rather than do that silently.
    if bind.execute(sa.text(f"SELECT count(*) FROM {_TABLE}")).scalar():
        raise RuntimeError(f"{_TABLE} is not empty — export it before downgrading")
    op.drop_table(_TABLE)
