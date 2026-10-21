"""Two mandate states, and the row that says where a copy came from.

ELI-7, second half. The vocabulary was ("open", "active", "closed") and the
recruiters asked for two words: **aktiv** and **inaktiv**. Three values split
"is this live business" across two members that nothing on screen could tell
apart, and `active` had no rows anywhere — the aiFind importer only has a
boolean, so everything in the record said "open" (61 rows) or "closed" (18).

Two things happen here:

* `status` is rewritten. open → active, closed → inactive. The mapping is
  total and the ticket itself defines it, which is why this runs unattended
  where `scripts/normalise_interaction_types.py` deliberately does not: that
  one rewrites notes about people on a mapping read off a sample, this one
  renames two words whose meaning the ticket fixed.

  `jobs.status` is also **queried**, not just displayed — `LIVE_JOB_STATUSES`
  feeds the cockpit's mandate figure and a manager's `open_job_count` — so
  leaving the old spellings in place would mean every call site had to know
  both vocabularies forever. `normalise_job_status` still folds them on read,
  because a row this migration has not reached must stay editable; that is
  belt and braces, not the plan.

* `copied_from_job_id` is added. An inactive mandate is final ("inaktiv kann
  nicht wieder geöffnet werden, muss neu angelegt werden"), so working a role
  again means a new row — and without this column the new row cannot say that
  it continues the old one.

Reversible: `downgrade` puts the two old words back. It cannot know which of
the restored "open" rows a recruiter had meant as `active`, because before
this migration nothing did.

Revision ID: 0039
Revises: 0038
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: stored spelling → what it means now. Mirrors
#: `app.domain.common.enums._STORED_JOB_STATUSES`; `tests/test_job_status.py`
#: fails if the two drift apart.
_REWRITE = {"open": "active", "closed": "inactive"}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "jobs" not in inspector.get_table_names():
        return  # fresh database: create_all already has both

    if "copied_from_job_id" not in {c["name"] for c in inspector.get_columns("jobs")}:
        # No FK constraint added here on purpose: naming a self-referential
        # constraint inside a batch ALTER is what breaks SQLite, and the
        # model declares the relationship for the ORM either way. The column
        # is nullable, so existing rows are correct as they stand.
        op.add_column(
            "jobs", sa.Column("copied_from_job_id", sa.Uuid(), nullable=True)
        )
        op.create_index(
            "ix_jobs_copied_from_job_id", "jobs", ["copied_from_job_id"]
        )

    jobs = sa.table("jobs", sa.column("status", sa.String))
    for old, new in _REWRITE.items():
        op.execute(jobs.update().where(jobs.c.status == old).values(status=new))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "jobs" not in inspector.get_table_names():
        return

    jobs = sa.table("jobs", sa.column("status", sa.String))
    for old, new in _REWRITE.items():
        op.execute(jobs.update().where(jobs.c.status == new).values(status=old))

    if "copied_from_job_id" in {c["name"] for c in inspector.get_columns("jobs")}:
        op.drop_index("ix_jobs_copied_from_job_id", table_name="jobs")
        op.drop_column("jobs", "copied_from_job_id")
