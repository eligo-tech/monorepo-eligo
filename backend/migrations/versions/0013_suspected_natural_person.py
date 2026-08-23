"""Flag corpus companies whose NAME looks like a natural person's.

RULE 2 says the shared corpus holds company-level facts only, never natural
persons. That was unenforceable: a sole trader (Einzelunternehmen, Freiberufler)
trades under their own name, so `hub_companies.name` can itself be personal data
while every column stays company-shaped. "Andreas Uwe Weiss" is in the corpus
today. No check over column NAMES finds a person sitting in a column called
`name` — which is exactly why the architecture-review grep passed.

The screen is `resolution.looks_like_natural_person`, applied here to rows
already ingested. It is a SCREEN, not a verdict, tuned to over-include: a false
positive costs a visible flag, a false negative silently keeps personal data in
a shared cross-tenant table. Nothing is hidden or deleted — acting on the flag
(suppression list, GDPR Art. 14/17) is the next step, and it needs the flag to
exist first.

Backfilled in Python because the heuristic is Python: legal-form stripping,
umlaut folding and an organisational-marker list are not expressible in SQL, and
splitting the rule across two implementations would guarantee they diverge.

Revision ID: 0013
Revises: 0012
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("hub_companies")}
    if "suspected_natural_person" not in columns:
        op.add_column(
            "hub_companies",
            sa.Column(
                "suspected_natural_person",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.create_index(
            "ix_hub_companies_suspected_natural_person",
            "hub_companies",
            ["suspected_natural_person"],
        )

    # The one screen, imported rather than reimplemented.
    from app.domain.hub.resolution import looks_like_natural_person

    rows = bind.execute(sa.text("SELECT id, name FROM hub_companies")).fetchall()
    flagged = [row[0] for row in rows if looks_like_natural_person(row[1])]
    for chunk_start in range(0, len(flagged), 500):
        chunk = flagged[chunk_start : chunk_start + 500]
        bind.execute(
            sa.text(
                "UPDATE hub_companies SET suspected_natural_person = true "
                "WHERE id IN :ids"
            ).bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": chunk},
        )
    print(
        f"screened {len(rows)} companies; {len(flagged)} look like natural persons"
    )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns("hub_companies")}
    if "suspected_natural_person" in columns:
        op.drop_index(
            "ix_hub_companies_suspected_natural_person", table_name="hub_companies"
        )
        op.drop_column("hub_companies", "suspected_natural_person")
