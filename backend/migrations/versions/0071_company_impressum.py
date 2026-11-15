"""A workspace company's Impressum reading: `companies.impressum` (ELI-39).

The daily job (`companies/impressum.py`) reads the website, VAT id and
register of a company Markt cannot answer for, and records the outcome here:
status and check time, and — only when verified, through the verification
gate — the website, VAT id, register, the Impressum's URL, fetch time and
content hash. Company facts only; never a person.

Tenant record: `companies` already carries its fail-closed RLS policy, so a
new column needs none. Nullable without a default: metadata-only, no rewrite.

Revision ID: 0070
Revises: 0069
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "companies"
_COLUMN = "impressum"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return  # fresh database: create_all already has it
    if bind.dialect.name == "postgresql":
        # Fail fast on the ADD COLUMN lock rather than queue every read behind it.
        op.execute("SET LOCAL lock_timeout = '10s'")
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _COLUMN in {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
