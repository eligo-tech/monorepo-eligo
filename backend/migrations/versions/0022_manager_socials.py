"""Xing and Facebook alongside the LinkedIn column that already existed.

Worth recording why these were missing rather than simply absent: the source
spells it `linkedIn_url` — a capital I mid-word in an otherwise snake_case
schema. Probed as `linkedin_url` it is rejected like any unknown field, and the
import returns nothing for it, which is indistinguishable from a contact who
has no profile. 15 of 40 sampled managers have one.

Revision ID: 0022
Revises: 0021
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("managers")}
    for column in ("xing_url", "facebook_url"):
        if column not in existing:
            op.add_column("managers", sa.Column(column, sa.String(300), nullable=True))


def downgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("managers")}
    for column in ("xing_url", "facebook_url"):
        if column in existing:
            op.drop_column("managers", column)
