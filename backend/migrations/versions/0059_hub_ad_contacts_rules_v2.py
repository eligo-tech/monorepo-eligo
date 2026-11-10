"""Ad-contact parser rules v2: rebuild the contacts queue index (ELI-22).

`hub/contacts.py` v2 reads capitalised surnames ("Herrn Felix TSCHOHL"), "Dr.
med." titles, and refuses website headings ("Über Uns") — defects seen in the
first prod fill on 2026-11-10. `AD_CONTACT_RULES` = 2 puts every ad read under
v1 back in the queue; the partial index must name the new number or the
planner cannot use it for the pass's predicate
(`tests/test_hub_ad_contacts.py::test_the_queue_index_names_the_current_rules_version`).

No data is touched here: the nightly pass (100k ads a night) or the manual
"Hub · ad contacts" workflow re-reads the ads. Index built CONCURRENTLY under
a new name, then the old one dropped — the queue is never without an index.

Revision ID: 0059
Revises: 0058
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0059"
down_revision: str | None = "0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_job_postings"
_NAME = "ix_hub_posting_contacts_due"
_TMP = "ix_hub_posting_contacts_due_v2"


# Written out in full, not imported or formatted: a migration keeps meaning
# what it meant, and the guard test looks for the literal predicate.
_WHERE = {
    1: "is_active AND (contacts_rules IS NULL OR contacts_rules < 1 OR contacts_read_at < "
    "description_fetched_at OR contacts_read_at < source_page_fetched_at)",
    2: "is_active AND (contacts_rules IS NULL OR contacts_rules < 2 OR contacts_read_at < "
    "description_fetched_at OR contacts_read_at < source_page_fetched_at)",
}


def _rebuild(version: int) -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return
    if bind.dialect.name != "postgresql":
        op.execute(f"DROP INDEX IF EXISTS {_NAME}")
        op.execute(f"CREATE INDEX {_NAME} ON {_TABLE} (id) WHERE {_WHERE[version]}")
        return
    with op.get_context().autocommit_block():
        op.execute("SET statement_timeout = 0")
        op.execute("SET lock_timeout = '10min'")
        # A leftover from a dead build of this migration is rebuilt (0054).
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_TMP}")
        op.execute(f"CREATE INDEX CONCURRENTLY {_TMP} ON {_TABLE} (id) WHERE {_WHERE[version]}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_NAME}")
        op.execute(f"ALTER INDEX {_TMP} RENAME TO {_NAME}")
        op.execute("RESET statement_timeout")
        op.execute("RESET lock_timeout")


def upgrade() -> None:
    _rebuild(2)


def downgrade() -> None:
    _rebuild(1)
