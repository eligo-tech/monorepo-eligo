"""`hub_companies.staffing_name` — Markt's "Personalberatungen ausblenden" (ELI-27).

The firm's NAME marks staffing or placement (`resolution.looks_like_staffing_firm`,
the same rule EURES sorts ads with). Set at ingest; this backfills existing rows.

Shared corpus, a fact derived from a public name — no tenant_id, no personal
data; the table's existing `shared_corpus_read` policy covers it.

Disk IO (prod Supabase is sensitive to it): adding a NOT NULL column with a
constant default is metadata-only on Postgres 11+, and the backfill reads
`id, name` once and UPDATEs only the matching rows, in chunks. No index — the
filter narrows a candidate set already chosen, and an index would cost every
`open_postings_count` update its HOT path.

Revision ID: 0070
Revises: 0069
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0070"
down_revision: str | None = "0069"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMN = "staffing_name"


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("hub_companies")}
    if _COLUMN not in columns:  # else create_all made it
        op.add_column(
            "hub_companies",
            sa.Column(_COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
        )

    # The one rule, imported rather than reimplemented. Employers only: the
    # private-recruiter segment never reaches Markt anyway.
    from app.domain.hub.resolution import looks_like_staffing_firm

    rows = bind.execute(
        sa.text(
            "SELECT id, name FROM hub_companies "
            f"WHERE kind = 'employer' AND {_COLUMN} = false"
        )
    ).fetchall()
    flagged = [row[0] for row in rows if looks_like_staffing_firm(row[1])]
    for start in range(0, len(flagged), 500):
        bind.execute(
            sa.text(
                f"UPDATE hub_companies SET {_COLUMN} = true WHERE id IN :ids"
            ).bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": flagged[start : start + 500]},
        )
    print(f"screened {len(rows)} employers; {len(flagged)} named as staffing firms")


def downgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("hub_companies")}
    if _COLUMN in columns:
        op.drop_column("hub_companies", _COLUMN)
