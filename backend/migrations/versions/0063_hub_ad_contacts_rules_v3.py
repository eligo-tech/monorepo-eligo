"""Ad-contact parser rules v3: rebuild the contacts queue index (ELI-25).

`hub/contacts.py` v3 reads bare names — no "Frau"/"Herr", no "Label:" — when
evidence backs them: a contact phrase before the name and a phone or e-mail
after it ("Für Fragen steht Janet Jürgens telefonisch unter …"), or a personal
e-mail that spells it. Measured on 1/16 of the open corpus: +27% ads with a
named person. `AD_CONTACT_RULES` = 3 puts every ad read under v2 back in the
queue; the partial index must name the new number
(`tests/test_hub_ad_contacts.py::test_the_queue_index_names_the_current_rules_version`).

No data is touched here: the nightly pass re-reads the ads. Index built
CONCURRENTLY under a new name, then the old one dropped (as 0059).

Revision ID: 0063
Revises: 0062
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0063"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "hub_job_postings"
_NAME = "ix_hub_posting_contacts_due"
_TMP = "ix_hub_posting_contacts_due_v3"


# Written out in full, not imported or formatted: a migration keeps meaning
# what it meant, and the guard test looks for the literal predicate.
_WHERE = {
    2: "is_active AND (contacts_rules IS NULL OR contacts_rules < 2 OR contacts_read_at < "
    "description_fetched_at OR contacts_read_at < source_page_fetched_at)",
    3: "is_active AND (contacts_rules IS NULL OR contacts_rules < 3 OR contacts_read_at < "
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
    _rebuild(3)


def downgrade() -> None:
    _rebuild(2)
