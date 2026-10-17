"""Interviewer agent behind a consent gate.

Two tenant-scoped tables:

* `tenant_feature_consents` — a workspace admin's acceptance (and revocation)
  of a gated feature's terms. The feature is on only while an acceptance of
  the CURRENT terms is active, the operator switch is on, and the workspace is
  allowlisted (`domain/features/service.py`).
* `interviews` — one AI pre-screen of one candidate: the candidate's consent,
  the transcript, and the per-field outcome of the extraction.

Both hold personal data or decisions about it, so both get RLS ENABLED and
FORCED with the fail-closed predicate every tenant table uses.

Revision ID: 0037
Revises: 0036
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"
_TABLES = ("tenant_feature_consents", "interviews")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "tenant_feature_consents" not in existing:
        op.create_table(
            "tenant_feature_consents",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column("feature", sa.String(40), nullable=False, index=True),
            sa.Column("terms_version", sa.String(20), nullable=False),
            sa.Column("accepted_by", sa.String(200), nullable=False),
            sa.Column("accepted_by_user_id", sa.String(120), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_by", sa.String(200), nullable=True),
            *_timestamps(),
        )

    if "interviews" not in existing:
        op.create_table(
            "interviews",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column(
                "candidate_id", sa.Uuid(), sa.ForeignKey("candidates.id"),
                nullable=False, index=True,
            ),
            sa.Column(
                "status", sa.String(20), nullable=False,
                server_default="awaiting_consent",
            ),
            sa.Column("script_version", sa.String(20), nullable=False),
            sa.Column("started_by", sa.String(200), nullable=False),
            sa.Column("consent_version", sa.String(20), nullable=True),
            sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consent_recorded_by", sa.String(200), nullable=True),
            sa.Column("turns", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("outcome", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
            *_timestamps(),
        )

    if bind.dialect.name == "postgresql":
        for table in _TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
            op.execute(
                f"CREATE POLICY tenant_isolation ON {table} "
                f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
            )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in reversed(_TABLES):
        if table in existing:
            op.drop_table(table)
