"""Who did it, on the receipt itself.

The ledger is append-only, hash-chained and database-enforced, and it recorded
*what* happened without ever recording *who*. "Which of our two recruiters
changed this candidate?" was therefore a question the audit trail could not
answer — the actor existed on the request and was thrown away one layer above
the write. For an EU-AI-Act traceability story that is a hole, and it showed:
answering "who opened the cockpit this morning?" for one workspace took eight
queries and a call to Clerk, and still came back unattributed.

Two columns rather than a join, matching `manager_interactions` exactly: there
is no users table, the name lives in Clerk, and a ledger view that calls an
identity provider once per row is a view nobody opens.

Backfill is deliberately NOT attempted. Every existing receipt genuinely has no
recorded author, and guessing one — "probably the only user in that workspace"
— would put a fabricated fact into the one table whose whole purpose is being
trustworthy. NULL is the honest answer and the application renders it as such.

Existing hashes stay valid: `_hash_receipt` folds the actor into the material
only when there is one, so a row with NULL in both columns hashes exactly as it
did before this migration. `verify_chain` keeps passing over the whole history.

Revision ID: 0042
Revises: 0041
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "receipts"
_INDEX = "ix_receipts_actor_user_id"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return  # fresh database: create_all already has the columns

    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    # Idempotent w.r.t. create_all, and column-by-column rather than all-or-
    # nothing: a half-applied run must be able to finish.
    if "actor_user_id" not in existing:
        op.add_column(
            _TABLE, sa.Column("actor_user_id", sa.String(length=80), nullable=True)
        )
    if "actor_name" not in existing:
        op.add_column(
            _TABLE, sa.Column("actor_name", sa.String(length=160), nullable=True)
        )

    if _INDEX not in {ix["name"] for ix in inspector.get_indexes(_TABLE)}:
        # "everything this person did" is the query this column exists for.
        op.create_index(_INDEX, _TABLE, ["actor_user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return

    if _INDEX in {ix["name"] for ix in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)

    existing = {c["name"] for c in inspector.get_columns(_TABLE)}
    for column in ("actor_name", "actor_user_id"):
        if column in existing:
            op.drop_column(_TABLE, column)
