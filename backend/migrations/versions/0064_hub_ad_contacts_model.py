"""Ad contacts read by a model when the rules named nobody (ELI-25).

`hub_job_postings.contacts_model_due` / `contacts_model_at`: the queue of the
model pass (`hub/contact_model.py`) — ads the contacts pass found no person
in, although they give a phone number or e-mail. `hub_ad_contacts.found_by`:
"rules" or "model", shown to the recruiter.

Both NOT NULL columns carry a constant default, which Postgres 11+ adds
without rewriting the table. The partial index is built CONCURRENTLY.

Revision ID: 0064
Revises: 0063
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064"
down_revision: str | None = "0063"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POSTINGS = "hub_job_postings"
_CONTACTS = "hub_ad_contacts"
_INDEX = "ix_hub_posting_contacts_model_due"


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if _POSTINGS in tables:
        have = _columns(_POSTINGS)
        if "contacts_model_due" not in have:
            op.add_column(
                _POSTINGS,
                sa.Column("contacts_model_due", sa.Boolean(), server_default=sa.text("false"), nullable=False),
            )
        if "contacts_model_at" not in have:
            op.add_column(_POSTINGS, sa.Column("contacts_model_at", sa.DateTime(timezone=True), nullable=True))
    if _CONTACTS in tables and "found_by" not in _columns(_CONTACTS):
        op.add_column(
            _CONTACTS, sa.Column("found_by", sa.String(10), server_default="rules", nullable=False)
        )
    if _POSTINGS not in tables:
        return
    if bind.dialect.name != "postgresql":
        op.execute(f"CREATE INDEX IF NOT EXISTS {_INDEX} ON {_POSTINGS} (id) WHERE contacts_model_due")
        return
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")  # a dead build's leftover
        op.execute(f"CREATE INDEX CONCURRENTLY {_INDEX} ON {_POSTINGS} (id) WHERE contacts_model_due")
        op.execute("RESET statement_timeout")


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if _POSTINGS in tables:
        if bind.dialect.name == "postgresql":
            with op.get_context().autocommit_block():
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX}")
        else:
            op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
        have = _columns(_POSTINGS)
        for column in ("contacts_model_at", "contacts_model_due"):
            if column in have:
                op.drop_column(_POSTINGS, column)
    if _CONTACTS in tables and "found_by" in _columns(_CONTACTS):
        op.drop_column(_CONTACTS, "found_by")
