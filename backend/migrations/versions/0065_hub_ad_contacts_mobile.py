"""Ad contacts: the recruiter's mobile beside the landline (ELI-25).

`hub_ad_contacts.mobile` — a mobile number the ad writes in the same sentence
after the person's phone ("… telefonisch unter +49 5491 … oder auch über
WhatsApp unter +49 151 …"). Nullable, no default: no table rewrite. Filled as
the nightly pass re-reads the ads (`AD_CONTACT_RULES` 3 already queued them).

Revision ID: 0065
Revises: 0064
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065"
down_revision: str | None = "0064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_ad_contacts"


def _has_column() -> bool:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return True  # nothing to do
    return "mobile" in {c["name"] for c in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    if not _has_column():
        op.add_column(_TABLE, sa.Column("mobile", sa.String(60), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names() and "mobile" in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, "mobile")
