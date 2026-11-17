"""Companies taken from Markt are Leads, not clients (ELI-36).

Until this release "Übernehmen" on a Markt card created the company with
`is_client = true` and its `hub_company_link.relationship = 'client'`. Being
picked from the market makes a company a Lead (prospect); `adopt_company`
now defaults to that. This resets the rows adopted before the fix:

    companies.source LIKE 'hub:%'           adopted from the corpus
    AND is_client                           flagged client by the old default
    AND a hub_company_link of it = 'client'
    AND no mandate (jobs.client_company_id) and no promoted manager
        (managers.stage = 'manager')        nothing makes it a client yet

→ `is_client = false`. Then every 'client' link of a hub-adopted company
that is not (or no longer) a client and has neither a mandate nor a manager
→ 'prospect' — the links of the rows just reset, and any older stray one. A company with a
mandate or a manager stays a client — that is real business, and the manager
rule is the one ELI-33's linking (`companies/market.py`) uses for 'client'.
Imported or hand-made companies (source not `hub:`) are not touched.

Idempotent: every statement filters on the state it changes, so a second run
matches nothing. Runs on the admin connection (BYPASSRLS owner, see
`migrations/env.py`), so it reaches every workspace. Prints nothing.

`downgrade` is a no-op on purpose: after the upgrade there is no record of
which prospects were clients by the old default and which were adopted as
prospects (ELI-22 leads always were), so "restoring" would wrongly promote
those. The old flag was a default, not a decision anyone made.

Revision ID: 0075
Revises: 0074
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0075"
down_revision: str | None = "0074"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOT_YET_A_CLIENT = """
    c.source LIKE 'hub:%'
    AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.client_company_id = c.id)
    AND NOT EXISTS (SELECT 1 FROM managers m WHERE m.company_id = c.id AND m.stage = 'manager')
"""

#: In order; the second relies on the first having run in the same transaction.
STATEMENTS: tuple[str, ...] = (
    f"""
    UPDATE companies SET is_client = false
    WHERE id IN (
        SELECT c.id FROM companies c
        WHERE c.is_client = true AND {_NOT_YET_A_CLIENT}
          AND EXISTS (
            SELECT 1 FROM hub_company_link l
            WHERE l.company_id = c.id AND l.relationship = 'client'
          )
    )
    """,
    f"""
    UPDATE hub_company_link SET relationship = 'prospect'
    WHERE relationship = 'client'
      AND company_id IN (
        SELECT c.id FROM companies c WHERE c.is_client = false AND {_NOT_YET_A_CLIENT}
      )
    """,
)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if not {"companies", "hub_company_link", "jobs", "managers"} <= tables:
        return  # fresh database: nothing was adopted under the old default
    for statement in STATEMENTS:
        op.execute(sa.text(statement))


def downgrade() -> None:
    """No-op — see the module docstring."""
    return None
