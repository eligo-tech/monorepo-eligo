"""What the next import should fetch, decided by the workspace (ELI-14).

The slow half of an aiFind import is the per-row pass: every manager and
every candidate fetched individually for their details and their notes. It
is also the only pass that produces Gesprächsnotizen, so it cannot simply be
dropped.

Until now the choice was `with_details`, a query parameter on the operator
endpoint — one switch for every tenant in a run, set by whoever triggered
the cron, invisible to the workspace that asked for the import and
unsettable by them. A recruiter who wanted their managers loaded had no way
to say so, and a recruiter who only wanted the lists refreshed had no way to
avoid the hour.

`import_scope` moves that decision onto the request, where the person making
it is. "full" is the default and is what every existing row did, so this
migration changes no behaviour on its own.

Revision ID: 0040
Revises: 0039
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tenant_sources" not in inspector.get_table_names():
        return  # fresh database: create_all already has the column

    if "import_scope" in {c["name"] for c in inspector.get_columns("tenant_sources")}:
        return  # idempotent w.r.t. create_all

    # server_default rather than a backfill: existing rows were all doing the
    # full pass, and a default on the column keeps a row inserted by an older
    # build valid too.
    op.add_column(
        "tenant_sources",
        sa.Column(
            "import_scope",
            sa.String(length=20),
            nullable=False,
            server_default="full",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tenant_sources" not in inspector.get_table_names():
        return
    if "import_scope" in {c["name"] for c in inspector.get_columns("tenant_sources")}:
        op.drop_column("tenant_sources", "import_scope")
