"""Site checks for employers: which company a check is for (ELI-30).

`hub_site_checks.hub_company_id` — set on employer checks (the Impressum
phone, VAT id and register of an employer whose ads name no website owner),
null on agency checks. Nullable, no default: no table rewrite. The index
serves the nightly queue ("not checked yet") and the company card. Deleting
the company (a suppression) deletes its checks.

Revision ID: 0066
Revises: 0065
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0066"
down_revision: str | None = "0065"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_site_checks"
_COLUMN = "hub_company_id"
_INDEX = "ix_hub_site_checks_hub_company_id"
_FK = "fk_hub_site_checks_hub_company_id"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return  # create_all builds it with the column
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Uuid(), nullable=True))
        if op.get_bind().dialect.name == "postgresql":
            op.create_foreign_key(_FK, _TABLE, "hub_companies", [_COLUMN], ["id"], ondelete="CASCADE")
    if _INDEX not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if _INDEX in {i["name"] for i in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        if op.get_bind().dialect.name == "postgresql":
            op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_FK}")
        op.drop_column(_TABLE, _COLUMN)
