"""Make the receipt ledger a ledger: no forks, no edits, no deletes.

Two defects, both of which made "append-only, hash-chained" weaker in code than
in prose.

**Forking (F2).** `append_receipt` read the chain head and then inserted, with
nothing in between. Two concurrent appends for one tenant read the same head and
produced two successors, so a perfectly valid workload made `verify_chain`
report tampering. This adds `chain_index`, a per-tenant position, and
`UNIQUE (tenant_id, chain_index)` so the database rejects the second writer
instead. The service retries; the ledger stays single-headed.

Position also stops being inferred from `created_at`, whose resolution is a
property of the clock rather than of the data.

**Mutability (F3).** The model said append-only was "enforced by convention +
service layer", while `scripts/apply_rls.py` granted the runtime role UPDATE and
DELETE on every table. A service bug or one stolen application credential was
enough to rewrite the ledger and recompute every hash — at which point the
chain proves nothing. This revokes both from the app role AND installs triggers
that refuse them regardless of who is connected, so an accident is caught even
when the actor is the owner.

Ordering matters: the backfill must run before the triggers exist, or the
migration blocks itself.

Residual, documented rather than fixed here: truncation at the head is still
invisible from inside the database. That needs an externally anchored head.

Revision ID: 0014
Revises: 0013
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    # `receipts` is created by `create_all`, not by an earlier migration, so a
    # database built purely from the Alembic chain does not have it yet. The
    # triggers are attached to the table definition itself (see
    # verification/models.py), so that path is covered; this migration exists
    # for databases where the table already holds rows.
    if "receipts" not in set(sa.inspect(bind).get_table_names()):
        return
    columns = {c["name"] for c in sa.inspect(bind).get_columns("receipts")}

    if "chain_index" not in columns:
        op.add_column(
            "receipts",
            sa.Column("chain_index", sa.Integer(), nullable=True),
        )

        # Backfill in the order the ledger was actually written. `created_at` is
        # the only evidence of that order for rows that predate this column, and
        # `id` breaks ties deterministically.
        rows = bind.execute(
            sa.text(
                "SELECT id, tenant_id FROM receipts ORDER BY tenant_id, created_at, id"
            )
        ).fetchall()
        position: dict[str, int] = {}
        for row_id, tenant_id in rows:
            key = str(tenant_id)
            index = position.get(key, 0)
            position[key] = index + 1
            bind.execute(
                sa.text("UPDATE receipts SET chain_index = :i WHERE id = :id"),
                {"i": index, "id": row_id},
            )
        print(f"assigned chain positions to {len(rows)} receipt(s)")

        if is_pg:
            op.alter_column("receipts", "chain_index", nullable=False)
        op.create_unique_constraint(
            "uq_receipt_chain_position", "receipts", ["tenant_id", "chain_index"]
        )

    # --- immutability, enforced by the database ---------------------------
    if is_pg:
        op.execute(
            """
            CREATE OR REPLACE FUNCTION receipts_are_append_only()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION
                    'receipts are append-only: % is not permitted', TG_OP;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute("DROP TRIGGER IF EXISTS receipts_no_update ON receipts")
        op.execute("DROP TRIGGER IF EXISTS receipts_no_delete ON receipts")
        op.execute(
            "CREATE TRIGGER receipts_no_update BEFORE UPDATE ON receipts "
            "FOR EACH ROW EXECUTE FUNCTION receipts_are_append_only()"
        )
        op.execute(
            "CREATE TRIGGER receipts_no_delete BEFORE DELETE ON receipts "
            "FOR EACH ROW EXECUTE FUNCTION receipts_are_append_only()"
        )
        # Belt as well as braces: the trigger catches the owner too, the revoke
        # means the application role never had the privilege in the first place.
        op.execute("REVOKE UPDATE, DELETE ON receipts FROM PUBLIC")
        for row in bind.execute(
            sa.text(
                "SELECT grantee FROM information_schema.role_table_grants "
                "WHERE table_name = 'receipts' AND privilege_type IN ('UPDATE','DELETE')"
            )
        ).fetchall():
            grantee = row[0]
            if grantee and grantee.replace("_", "").isalnum():
                op.execute(f'REVOKE UPDATE, DELETE ON receipts FROM "{grantee}"')
    else:
        # SQLite has no role separation, but it does have triggers — so the same
        # guarantee is testable in CI rather than only asserted for production.
        op.execute("DROP TRIGGER IF EXISTS receipts_no_update")
        op.execute("DROP TRIGGER IF EXISTS receipts_no_delete")
        op.execute(
            "CREATE TRIGGER receipts_no_update BEFORE UPDATE ON receipts "
            "BEGIN SELECT RAISE(ABORT, 'receipts are append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER receipts_no_delete BEFORE DELETE ON receipts "
            "BEGIN SELECT RAISE(ABORT, 'receipts are append-only'); END"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "receipts" not in set(sa.inspect(bind).get_table_names()):
        return
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS receipts_no_update ON receipts")
        op.execute("DROP TRIGGER IF EXISTS receipts_no_delete ON receipts")
        op.execute("DROP FUNCTION IF EXISTS receipts_are_append_only()")
    else:
        op.execute("DROP TRIGGER IF EXISTS receipts_no_update")
        op.execute("DROP TRIGGER IF EXISTS receipts_no_delete")
    if "chain_index" in {c["name"] for c in sa.inspect(bind).get_columns("receipts")}:
        op.drop_constraint("uq_receipt_chain_position", "receipts", type_="unique")
        op.drop_column("receipts", "chain_index")
