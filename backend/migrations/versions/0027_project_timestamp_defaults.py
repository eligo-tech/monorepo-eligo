"""0025 created the project tables without timestamp defaults.

`projects.created_at` and `updated_at` are NOT NULL, and 0025 gave them no
`server_default`, so any INSERT that did not name them failed on Postgres with
"null value in column created_at violates not-null constraint". Production
therefore could not create a project at all.

CI never saw it: tests build their schema with `create_all` from the models,
where `TimestampMixin` carries the default. Only a database evolved by the
migration was broken — which is exactly what production is.

The models now also set the value client-side, so this migration is belt and
braces for writers that are not the ORM.

Revision ID: 0027
Revises: 0026
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("projects", "project_companies")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite cannot ALTER a default; fresh files come from create_all
    present = set(sa.inspect(bind).get_table_names())
    for table in _TABLES:
        if table not in present:
            continue
        for column in ("created_at", "updated_at"):
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT now()")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    present = set(sa.inspect(bind).get_table_names())
    for table in _TABLES:
        if table not in present:
            continue
        for column in ("created_at", "updated_at"):
            op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
