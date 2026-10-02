"""Branchen (plural), a decidable Anstellungsform, and WHERE else they are.

`data/examples/metadata_quailfication.txt` asks for "Branchen in denen der
Kandidat tätig war" and "Festanstellung oder Freelance oder beides". The
record could express neither: one `industry` slot, and an `employment_type`
holding whatever the source said — 618 × "Permanent", 20 × "Contract,
Permanent", 10 × "Contract", plus "Founder" and "Full-time". Nothing can
filter on that.

Two columns, both backfilled from what is already there:

* `industries` — a list. Backfilled as `[industry]`, NOT split on the comma:
  "Pharma, MedTech und Gesundheitsbranche" is one label, and splitting it
  would invent two industries nobody recorded.
* `employment_form` — festanstellung | freelance | beides, normalized by the
  same function the import path uses, so a re-import agrees with the
  backfill. Rows it cannot map stay NULL and the run says how many.

`industry` and `employment_type` stay for now. This is the expand half of
expand/contract: during a deploy the previous container is still answering
requests and selects those columns, so dropping them here would 500 every
candidate query for the length of the rollout. A follow-up drops `industry`
once nothing reads it.

Revision ID: 0030
Revises: 0029
"""
from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _as_list(value: object) -> list:
    """`industries` comes back as a list on Postgres and a JSON string on
    SQLite — both have to read as "is there anything in there"."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "candidates" not in set(inspector.get_table_names()):
        return  # fresh database — `create_all` builds both columns

    columns = {c["name"] for c in inspector.get_columns("candidates")}
    if "industries" not in columns:
        op.add_column(
            "candidates",
            sa.Column("industries", sa.JSON(), nullable=False, server_default="[]"),
        )
    if "employment_form" not in columns:
        op.add_column(
            "candidates", sa.Column("employment_form", sa.String(20), nullable=True)
        )
    # The companies behind `other_processes`. The free text stays — it is what
    # the candidate said; the list is what can be counted across the pool.
    if "other_process_companies" not in columns:
        op.add_column(
            "candidates",
            sa.Column(
                "other_process_companies",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )

    # The one screen, imported rather than reimplemented — a second copy of
    # the mapping would drift from the import path within a month.
    from app.domain.candidates.employment import normalize_employment_form

    # Read the current values back so a re-run cannot overwrite industries a
    # recruiter added in the meantime.
    rows = bind.execute(
        sa.text(
            "SELECT id, industry, industries, employment_type, employment_form "
            "FROM candidates WHERE industry IS NOT NULL OR employment_type IS NOT NULL"
        )
    ).fetchall()

    filled_industries = 0
    filled_form = 0
    unmapped: set[str] = set()
    for row_id, industry, industries, employment_type, employment_form in rows:
        already = industries if isinstance(industries, list) else _as_list(industries)
        if industry and not already:
            bind.execute(
                sa.text("UPDATE candidates SET industries = :value WHERE id = :id"),
                {"value": json.dumps([industry]), "id": row_id},
            )
            filled_industries += 1
        form = normalize_employment_form(employment_type)
        if form and not employment_form:
            bind.execute(
                sa.text("UPDATE candidates SET employment_form = :form WHERE id = :id"),
                {"form": form, "id": row_id},
            )
            filled_form += 1
        elif employment_type and not form:
            unmapped.add(employment_type)

    print(
        f"backfilled {filled_industries} industry list(s), "
        f"{filled_form} Anstellungsform(en)"
    )
    if unmapped:
        # Named, not swallowed: these rows now need a human to pick.
        print(f"  ! no form for: {', '.join(sorted(unmapped))} — left NULL")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "candidates" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("candidates")}
    for name in ("other_process_companies", "employment_form", "industries"):
        if name in columns:
            op.drop_column("candidates", name)
