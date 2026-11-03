"""Agency website candidates: `hub_agency_profiles.website_candidates`.

The agency's likely website, ranked from the domains its own ads name
(`app/domain/hub/domains.py`) — UNVERIFIED. Kept on the derived profile, never
on `hub_companies.website_domain`: measured on 200 live ads, a third of the
domains an ad names are a job board's or the client's. Only the Impressum
naming the firm (PR7) promotes a candidate to the company's website.

Derived data, rebuilt nightly; existing rows start empty. No personal data:
domains, counts and posting ids.

Revision ID: 0052
Revises: 0051
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE, _COLUMN = "hub_agency_profiles", "website_candidates"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return  # fresh database: create_all already has the column
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names() and _COLUMN in {
        c["name"] for c in inspector.get_columns(_TABLE)
    }:
        op.drop_column(_TABLE, _COLUMN)
