"""What an uploaded file IS — cv / transkript / zeugnis / zertifikat.

`candidate_documents` held CVs only, so "the newest file for this candidate"
and "this candidate's CV" were the same row, and `/candidates/{id}/cv` relied
on that. The first Zeugnis uploaded would have been served as the CV.

Existing rows are backfilled to 'cv', which is not a guess: nothing else could
be uploaded before this migration.

Revision ID: 0029
Revises: 0028
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "candidate_documents" not in set(inspector.get_table_names()):
        return  # fresh database — `create_all` builds the column
    columns = {c["name"] for c in inspector.get_columns("candidate_documents")}
    if "kind" not in columns:
        op.add_column(
            "candidate_documents",
            sa.Column(
                "kind", sa.String(20), nullable=False, server_default="cv"
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "candidate_documents" not in set(inspector.get_table_names()):
        return
    if "kind" in {c["name"] for c in inspector.get_columns("candidate_documents")}:
        op.drop_column("candidate_documents", "kind")
