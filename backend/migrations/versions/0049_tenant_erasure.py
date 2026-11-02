"""Erasure inside a workspace: request log, suppression list, receipt blackout.

* `erasure_requests` — that a request was handled, naming nobody.
* `tenant_suppressions` — HMAC fingerprints of an erased person's import ids
  and e-mails, which the import checks before it creates anyone.
* The receipt trigger's function is replaced so it allows exactly one update:
  an erasure blacking out a receipt that an ERASE receipt in the same
  workspace lists (see `PG_APPEND_ONLY_FUNCTION` in verification/models.py,
  which `create_all` installs on a fresh database; the test suite keeps the
  two identical). Every other UPDATE and every DELETE is still refused, for
  every role including the owner.

Fail-closed RLS on both new tables, applied outside the create branch:
`create_all` on startup makes tables without policies (see 0041).

Revision ID: 0049
Revises: 0048
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_TABLES = ("erasure_requests", "tenant_suppressions")
_MARKER = "[gelöscht — Löschantrag, DSGVO Art. 17]"

#: Frozen copy of verification.models.PG_APPEND_ONLY_FUNCTION at this revision.
FUNCTION = f"""
    CREATE OR REPLACE FUNCTION receipts_are_append_only()
    RETURNS trigger AS $$
    BEGIN
        IF TG_OP = 'UPDATE'
           AND OLD.summary <> '{_MARKER}'
           AND NEW.summary = '{_MARKER}'
           AND NEW.payload::jsonb = jsonb_build_object(
                   'erased_by', NEW.payload::jsonb ->> 'erased_by')
           AND (to_jsonb(NEW) - 'summary' - 'payload')
             = (to_jsonb(OLD) - 'summary' - 'payload')
           AND EXISTS (
                 SELECT 1 FROM receipts e
                  WHERE e.id::text = NEW.payload::jsonb ->> 'erased_by'
                    AND e.tenant_id = OLD.tenant_id
                    AND e.action = 'erase'
                    AND (e.payload::jsonb -> 'redacted') ? OLD.id::text)
        THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'receipts are append-only: % is not permitted', TG_OP;
    END;
    $$ LANGUAGE plpgsql
    """

_STRICT_FUNCTION = """
    CREATE OR REPLACE FUNCTION receipts_are_append_only()
    RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'receipts are append-only: % is not permitted', TG_OP;
    END;
    $$ LANGUAGE plpgsql
    """


def _json(bind) -> sa.types.TypeEngine:  # noqa: ANN001
    if bind.dialect.name == "postgresql":
        from sqlalchemy.dialects import postgresql

        return postgresql.JSONB()
    return sa.Text()


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "erasure_requests" not in tables:
        op.create_table(
            "erasure_requests",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("subject_type", sa.String(20), nullable=False),
            sa.Column("reason", sa.String(20), nullable=False),
            sa.Column("requested_on", sa.Date(), nullable=False),
            sa.Column("executed_by_user_id", sa.String(80), nullable=True),
            sa.Column("executed_by_name", sa.String(160), nullable=True),
            sa.Column("counts", _json(bind), nullable=False),
            sa.Column("erase_receipt_id", sa.Uuid(), nullable=True),
            *_stamps(),
        )
    if "tenant_suppressions" not in tables:
        op.create_table(
            "tenant_suppressions",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("request_id", sa.Uuid(), sa.ForeignKey("erasure_requests.id"),
                      nullable=False, index=True),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("digest", sa.String(64), nullable=False),
            sa.Column("lifted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("lifted_by_user_id", sa.String(80), nullable=True),
            sa.Column("lifted_by_name", sa.String(160), nullable=True),
            *_stamps(),
        )
        op.create_index("ix_tenant_suppressions_digest", "tenant_suppressions", ["tenant_id", "digest"])

    if bind.dialect.name == "postgresql":
        for table in _TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(
                f"CREATE POLICY tenant_isolation ON {table} "
                f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
            )
        op.execute(FUNCTION)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(_STRICT_FUNCTION)
    tables = set(sa.inspect(bind).get_table_names())
    for table in reversed(_TABLES):
        if table in tables:
            op.drop_table(table)
