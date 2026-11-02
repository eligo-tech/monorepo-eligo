"""Postcondition reasons move off the receipt onto the provenance record.

The receipt ledger is append-only and hash-chained over its summary and
payload, so anything written there can never be erased. Until now the VERIFY
receipt's summary carried the free-text postcondition reasons, and a reason
can quote a value ("vorhandener Wert '…'"). They now live in
`enrichment_records.reason`, which an erasure can delete; the receipt names
the record by id. Classification unchanged: `enrichment_records` is already
personal data, tenant-scoped, RLS-policed.

Existing receipts are not touched — they are immutable. NULL for existing
records is the honest value: their reason is on their receipt.

Revision ID: 0048
Revises: 0047
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "enrichment_records"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return  # fresh database: create_all already has the column
    if "reason" not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column("reason", sa.Text(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names() and "reason" in {
        c["name"] for c in inspector.get_columns(_TABLE)
    }:
        op.drop_column(_TABLE, "reason")
