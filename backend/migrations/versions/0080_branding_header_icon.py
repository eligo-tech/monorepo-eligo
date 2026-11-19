"""ELI-55: the workspace's icon in the cockpit header.

Two nullable columns on `workspace_branding`: `header_icon` (bytes — PNG,
JPEG or a sanitised SVG) and its media type. A second slot next to the
cover-sheet logo, because the header is dark and the PDF is white. NULL for
every existing workspace: the header shows the Eligo mark until an admin
uploads one in Einstellungen. Columns on an existing tenant table: its
fail-closed RLS policy already covers them.

Revision ID: 0080
Revises: 0079
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0080"
down_revision: str | None = "0079"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "workspace_branding"
_COLUMNS = (
    ("header_icon", sa.LargeBinary()),
    ("header_icon_content_type", sa.String(50)),
)


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    for name, type_ in _COLUMNS:
        if name not in have:
            op.add_column(_TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_TABLE)}
    for name, _type in reversed(_COLUMNS):
        if name in have:
            op.drop_column(_TABLE, name)
