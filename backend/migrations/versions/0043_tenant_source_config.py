"""Which instance of a source a workspace is on.

The aiFind connector carried one customer's Keycloak realm and subdomain as
module constants, so the product could serve exactly one customer of that
vendor — and the second workspace to connect the same system would have sent
its credentials to the first one's realm. Those are properties of the
customer, not of the integration, so they move to the row that already holds
that workspace's credential and import scope.

**No backfill, deliberately.** Writing the existing customer's realm into this
file would move the hardcoding from a constant into a migration rather than
remove it, and this repository is not where any one workspace's address
belongs. The column therefore starts empty everywhere, the connector raises a
named error instead of guessing, and the value is entered once through the
settings screen. A configured source whose config is empty fails its next run
with "aiFind braucht die Angabe der eigenen Instanz" — loudly, before the
login, rather than as "Login abgelehnt" against somebody else's realm.

Not secret, so no encryption: a hostname is not a credential, and the screen
has to show which instance is connected.

Revision ID: 0043
Revises: 0042
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tenant_sources"
_COLUMN = "config"


def _json_type(bind) -> sa.types.TypeEngine:
    """JSONB on Postgres, TEXT on SQLite — the same split as `JSONDict`."""
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.JSONB()
    return sa.Text()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return  # fresh database: create_all already has the column

    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        return

    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            _json_type(bind),
            nullable=False,
            # Existing rows need a value for NOT NULL, and "{}" is the honest
            # one: nobody has named their instance yet.
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
