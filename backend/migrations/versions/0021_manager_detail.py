"""Room for what a contact record actually holds.

`managers` was built from a list query that returned a name, a role and a
company. The source's own profile screen shows considerably more, and the parts
that matter to a recruiter are the parts that were missing: a phone number to
call, what the person is open to, when they were last spoken to, and the notes
from those conversations.

`manager_interactions` gains `external_id` for the same reason every other
imported table has one — an import that cannot recognise its own output writes
the same three notes again on every run.

`last_contact_at` is a timestamp rather than a derived MAX over interactions on
purpose: the source knows when the last contact happened, including contact
that predates anything we imported, and recomputing it from our own rows would
quietly move the date backwards.

Revision ID: 0021
Revises: 0020
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MANAGER_COLUMNS = (
    # "MNGR197" — the reference a recruiter reads out on a call.
    ("external_code", sa.String(40)),
    ("city", sa.String(120)),
    ("country", sa.String(120)),
    ("postal_code", sa.String(20)),
    ("street", sa.String(200)),
    # What the person is open to ("Looks for: Contract").
    ("looks_for", sa.String(200)),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    json_type = (
        sa.dialects.postgresql.JSONB
        if bind.dialect.name == "postgresql"
        else sa.Text
    )

    existing = {c["name"] for c in inspector.get_columns("managers")}
    for column, type_ in _MANAGER_COLUMNS:
        if column not in existing:
            op.add_column("managers", sa.Column(column, type_, nullable=True))
    if "skills" not in existing:
        op.add_column(
            "managers",
            sa.Column("skills", json_type(), nullable=False, server_default="[]"),
        )
    if "tags" not in existing:
        op.add_column(
            "managers",
            sa.Column("tags", json_type(), nullable=False, server_default="[]"),
        )
    if "last_contact_at" not in existing:
        op.add_column(
            "managers",
            sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
        )

    interactions = {c["name"] for c in inspector.get_columns("manager_interactions")}
    if "external_id" not in interactions:
        op.add_column(
            "manager_interactions", sa.Column("external_id", sa.String(80), nullable=True)
        )
        op.add_column(
            "manager_interactions",
            sa.Column("external_source", sa.String(80), nullable=True),
        )
        op.create_index(
            "ix_manager_interactions_external_identity",
            "manager_interactions",
            ["tenant_id", "external_source", "external_id"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    interactions = {c["name"] for c in inspector.get_columns("manager_interactions")}
    if "external_id" in interactions:
        op.drop_index(
            "ix_manager_interactions_external_identity",
            table_name="manager_interactions",
        )
        op.drop_column("manager_interactions", "external_source")
        op.drop_column("manager_interactions", "external_id")

    existing = {c["name"] for c in inspector.get_columns("managers")}
    for column in (
        [c for c, _ in _MANAGER_COLUMNS] + ["skills", "tags", "last_contact_at"]
    ):
        if column in existing:
            op.drop_column("managers", column)
