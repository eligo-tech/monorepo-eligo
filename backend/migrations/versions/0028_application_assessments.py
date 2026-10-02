"""The Kandidatenauswertung, as data — per candidate PER MANDATE.

`data/examples/KandidatenInfo.txt` is the artefact this table holds: a fit
score out of ten, a Kurzfazit, the strengths, the Lücken/Risiken, the text
written for the client, and the technologies that matter for THAT position.
It is keyed on the application rather than the candidate because the same
person scores differently against a different Muss-Profil.

Four columns also land on `candidates`, from
`data/examples/metadata_quailfication.txt`: the salary FLOOR (the candidate
names a minimum and a wish; only the pair tells you whether a band can work),
the profile summary, the interview availability window, and the other
processes they are running — which is both a timing risk and a sales signal.

Revision ID: 0028
Revises: 0027
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREDICATE = "tenant_id = NULLIF(current_setting('app.current_tenant', true), '')::uuid"

_CANDIDATE_COLUMNS = (
    ("salary_minimum", sa.Integer()),
    ("profile_summary", sa.Text()),
    ("interview_availability", sa.Text()),
    ("other_processes", sa.Text()),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "application_assessments" not in set(inspector.get_table_names()):
        op.create_table(
            "application_assessments",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False, index=True),
            sa.Column(
                "application_id",
                sa.Uuid(),
                sa.ForeignKey("applications.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("fit_score", sa.Integer(), nullable=True),
            sa.Column("verdict", sa.Text(), nullable=True),
            sa.Column("strengths", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("risks", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("client_summary", sa.Text(), nullable=True),
            sa.Column("technologies", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("basis", sa.String(400), nullable=True),
            sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=True),
            # Both timestamps need a server default: an INSERT that does not
            # name them must still work (see 0027, the migration that forgot).
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.UniqueConstraint(
                "application_id", name="uq_assessment_application"
            ),
        )

    # A database bootstrapped by `create_all` already has the columns, and a
    # chain replayed from zero has no `candidates` table at all — migrations
    # evolve an existing schema, they do not create the base one.
    if "candidates" in set(inspector.get_table_names()):
        existing = {c["name"] for c in inspector.get_columns("candidates")}
        for name, type_ in _CANDIDATE_COLUMNS:
            if name not in existing:
                op.add_column("candidates", sa.Column(name, type_, nullable=True))

    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE application_assessments ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE application_assessments FORCE ROW LEVEL SECURITY")
        op.execute(
            "DROP POLICY IF EXISTS tenant_isolation ON application_assessments"
        )
        op.execute(
            "CREATE POLICY tenant_isolation ON application_assessments "
            f"USING ({_PREDICATE}) WITH CHECK ({_PREDICATE})"
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "application_assessments" in set(inspector.get_table_names()):
        op.drop_table("application_assessments")
    if "candidates" in set(inspector.get_table_names()):
        existing = {c["name"] for c in inspector.get_columns("candidates")}
        for name, _type in _CANDIDATE_COLUMNS:
            if name in existing:
                op.drop_column("candidates", name)
