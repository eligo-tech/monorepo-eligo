"""ELI-54: employer headcount on the shared corpus (`hub_companies`).

A public company fact with its provenance — no person:

- `employees_min` / `employees_max`: inclusive bounds; max NULL is
  open-ended ("über 500" → 500, NULL).
- `employees_source` (ad_text · wikidata · eures), `employees_source_ref`
  (`<source>:<ad id>` or a Wikidata QID), `employees_evidence` (the quoted
  sentence), `employees_as_of` (when the claim was made),
  `employees_updated_at`.
- The passes' stamps: `employees_rules` + `employees_read_at` (ad-text
  pass), `employees_wikidata_at` (Wikidata pass).

All nullable, no default, no index: adding them is a catalog change on
Postgres (no rewrite of the table), and unindexed columns keep the weekly
stamps HOT updates. `hub_companies` is shared corpus with its explicit
`shared_corpus_read` policy; no RLS change.

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

_COLUMNS = (
    ("employees_min", sa.Integer()),
    ("employees_max", sa.Integer()),
    ("employees_source", sa.String(20)),
    ("employees_source_ref", sa.String(200)),
    ("employees_evidence", sa.String(500)),
    ("employees_as_of", sa.DateTime(timezone=True)),
    ("employees_updated_at", sa.DateTime(timezone=True)),
    ("employees_rules", sa.Integer()),
    ("employees_read_at", sa.DateTime(timezone=True)),
    ("employees_wikidata_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("hub_companies")}
    for name, type_ in _COLUMNS:
        if name not in have:
            op.add_column("hub_companies", sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("hub_companies")}
    for name, _type in reversed(_COLUMNS):
        if name in have:
            op.drop_column("hub_companies", name)
