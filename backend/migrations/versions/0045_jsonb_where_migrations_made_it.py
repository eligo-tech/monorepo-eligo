"""Make the nine migration-created JSON columns `jsonb` everywhere.

The migrations that created these columns made them `jsonb`, but the models
declared generic `JSON`, which `create_all` turns into `json`. So production
(built by migrations) had `jsonb` while a fresh database (CI, a customer's
own) had `json`. The models now declare `jsonb` for exactly these nine — see
`app/domain/common/types.py`, and `scripts/schema_drift.py`, which found it.

This converts a column ONLY where it is still `json`. On production, read
2026-11-01, all nine are already `jsonb`, so there it changes nothing. The
other 24 JSON columns stay `json` on purpose; `receipts.payload` among them,
because `jsonb` reorders keys and the receipt ledger is hash-chained.

No downgrade: going back to `json` would re-create the mismatch this fixes,
and production never had these columns as `json`.

Revision ID: 0045
Revises: 0044
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (table, column) — the nine that are `jsonb` in production.
_COLUMNS = (
    ("agent_proposals", "args"),
    ("agent_proposals", "snapshot"),
    ("hub_companies", "bd_signals"),
    ("hub_observations", "payload"),
    ("managers", "skills"),
    ("managers", "tags"),
    ("saved_searches", "berufsfelder"),
    ("saved_searches", "regions"),
    ("tenant_sources", "config"),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite stores both as TEXT; there is nothing to convert.
    for table, column in _COLUMNS:
        current = bind.execute(
            sa.text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c"
            ),
            {"t": table, "c": column},
        ).scalar()
        if current == "json":
            op.execute(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE jsonb USING "{column}"::jsonb'
            )


def downgrade() -> None:
    pass
