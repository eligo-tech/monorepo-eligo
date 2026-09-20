"""Give the app role UPDATE on receipts back — the FK needs it, the trigger holds.

0014 made the ledger append-only two ways: triggers that refuse UPDATE/DELETE
for every connection including the owner, and a REVOKE of UPDATE and DELETE
from the application role. The REVOKE had a consequence nobody measured.

`enrichment_records.receipt_id` is a foreign key to `receipts`. Inserting an
enrichment record makes Postgres take a `FOR KEY SHARE` lock on the referenced
receipt row, and a locking read requires UPDATE privilege — so the insert fails
with `permission denied for table receipts`. Every `verify_and_commit` writes an
enrichment record, so since 0014 EVERY agent commit through the gate has failed
in production: adopting a company from Markt returned 500 and the UI said
"Übernahme fehlgeschlagen". CI never saw it because SQLite has no grants.

Restoring UPDATE does not make the ledger mutable: `receipts_no_update` and
`receipts_no_delete` refuse the operation for every role, owner included, and
0014's test proves it. DELETE stays revoked — nothing needs it.

Revision ID: 0024
Revises: 0023
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_roles(bind) -> list[str]:
    """Roles that may write receipts — i.e. the application role(s), whatever
    they are called in this environment. Derived, not hard-coded: the role name
    comes from configuration and differs per deployment."""
    rows = bind.execute(
        sa.text(
            "SELECT DISTINCT grantee FROM information_schema.role_table_grants "
            "WHERE table_name = 'receipts' AND privilege_type = 'INSERT' "
            "AND grantee NOT IN ('PUBLIC', current_user)"
        )
    ).fetchall()
    return [r[0] for r in rows if r[0] and r[0].replace("_", "").isalnum()]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite has no grants; the triggers are installed by 0014
    for role in _app_roles(bind):
        op.execute(f'GRANT UPDATE ON TABLE receipts TO "{role}"')


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for role in _app_roles(bind):
        op.execute(f'REVOKE UPDATE ON receipts FROM "{role}"')
