"""Move the cold posting columns out of the table search scans.

`hub_job_postings` carries what search reads — title, occupation, city, dates,
foreign keys — and every sequential scan pays for the width of the whole table.
`raw` and `description` sat in that table: 174 MB and 176 MB respectively, in a
main heap measured at **298 MB** against a 224 MB `shared_buffers`. The hot table
did not fit in cache, so scans spilled to disk on every search.

Postgres already TOASTs the biggest values out of line (208 MB of a 596 MB
total), which is why this is a smaller win than the raw column sizes suggest.
The *inline* remainder was still most of the main heap, and without it a posting
row is a few hundred bytes.

`raw` is written on every ingest and read by nothing in the codebase — it is
provenance, kept deliberately. `description` is displayed in the UI and searched
only when `SEARCH_AD_TEXT` is on. Neither belongs on the path of a query that
does not name them.

Note the space is NOT returned to the operating system by DROP COLUMN. The
follow-up is a `VACUUM FULL hub_job_postings` (or pg_repack), which takes an
exclusive lock and therefore must NOT run here: this migration executes inside
the container start command, ahead of uvicorn, so anything slow taken here is
downtime. See ADR 0001.

Revision ID: 0017
Revises: 0016
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_pg else sa.Text

    if is_pg:
        # Copying ~350 MB between tables exceeds this database's 2min
        # statement_timeout, and a cancelled migration is a container that never
        # boots (see 0016, which failed exactly that way).
        op.execute("SET LOCAL statement_timeout = 0")
        op.execute("SET LOCAL lock_timeout = '30s'")

    if "hub_posting_payload" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "hub_posting_payload",
            sa.Column(
                "hub_job_posting_id",
                sa.Uuid(),
                sa.ForeignKey("hub_job_postings.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("raw", json_type(), nullable=False, server_default="{}"),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    columns = {c["name"] for c in sa.inspect(bind).get_columns("hub_job_postings")}

    # Carry the existing values across before dropping them. Guarded on the old
    # columns still existing so a re-run is a no-op rather than an error.
    if "raw" in columns or "description" in columns:
        raw_expr = "raw" if "raw" in columns else "'{}'"
        desc_expr = "description" if "description" in columns else "NULL"
        op.execute(
            f"INSERT INTO hub_posting_payload "
            f"(hub_job_posting_id, raw, description) "
            f"SELECT id, COALESCE({raw_expr}, '{{}}'), {desc_expr} "
            # `WHERE true` is load-bearing on SQLite: after a bare SELECT its
            # parser cannot tell an upsert's ON CONFLICT from a join's ON, and
            # fails with "near DO: syntax error". Documented SQLite quirk.
            f"FROM hub_job_postings WHERE true "
            f"ON CONFLICT (hub_job_posting_id) DO NOTHING"
        )

    if "description" in columns:
        op.drop_column("hub_job_postings", "description")
    if "raw" in columns:
        op.drop_column("hub_job_postings", "raw")

    if is_pg:
        # Shared corpus, same explicitly-permissive stance as the tables this
        # one hangs off — stated rather than left looking forgotten.
        op.execute("ALTER TABLE hub_posting_payload ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE hub_posting_payload FORCE ROW LEVEL SECURITY")
        op.execute(
            "DROP POLICY IF EXISTS shared_corpus_read ON hub_posting_payload"
        )
        op.execute(
            "CREATE POLICY shared_corpus_read ON hub_posting_payload "
            "USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    json_type = sa.dialects.postgresql.JSONB if is_pg else sa.Text

    if is_pg:
        op.execute("SET LOCAL statement_timeout = 0")

    columns = {c["name"] for c in sa.inspect(bind).get_columns("hub_job_postings")}
    if "raw" not in columns:
        op.add_column(
            "hub_job_postings",
            sa.Column("raw", json_type(), nullable=False, server_default="{}"),
        )
    if "description" not in columns:
        op.add_column(
            "hub_job_postings", sa.Column("description", sa.Text(), nullable=True)
        )

    if "hub_posting_payload" in sa.inspect(bind).get_table_names():
        op.execute(
            "UPDATE hub_job_postings p SET raw = c.raw, description = c.description "
            "FROM hub_posting_payload c WHERE c.hub_job_posting_id = p.id"
        )
        op.drop_table("hub_posting_payload")
