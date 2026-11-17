"""Wiedervorlagen — a dated to-do on a person (ELI-44).

"Anfang Februar wieder melden": the recruiter wrote the date into the note
and then into a calendar, by hand. A follow-up is that to-do in the record:
due on a date (a time is optional), a short text, open until somebody marks
it done — and visible on the cockpit until then.

Attached to exactly ONE person: a `managers` row (Leads are managers with
stage `bus_dev`, so one column covers both) or a candidate. The check
constraint makes "neither" and "both" impossible rather than merely unusual.

Its own table rather than another column on `manager_interactions`: the
note is what happened, the follow-up is what is still owed, and the two
have different lives — a follow-up is moved, edited and closed; a note is
not. `source_interaction_id` keeps the link to the note it came from.

Classification: tenant personal data (the text is about a person). Erased
with the person (`erasure.erase_manager` / `erase_candidate`); no receipt,
the same as the manual note it sits beside (a working record, not a claim
the verification layer vouches for).
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin

OPEN = "open"
DONE = "done"
STATUSES = (OPEN, DONE)

#: How the date was chosen: typed by hand, or offered from a note's text
#: (`dates.suggest_dates`) and confirmed by a person.
ORIGINS = ("manual", "note")

TEXT_MAX = 500


class FollowUp(Base, IDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "follow_ups"
    __table_args__ = (
        CheckConstraint(
            "(manager_id IS NULL) <> (candidate_id IS NULL)",
            name="ck_follow_ups_one_person",
        ),
        # The cockpit's to-do list: this workspace's open ones, soonest first.
        Index("ix_follow_ups_tenant_status_due", "tenant_id", "status", "due_date"),
    )

    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("managers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=True, index=True
    )
    #: The note it came from, if any. SET NULL: deleting a note must not take
    #: the open to-do with it.
    source_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("manager_interactions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    due_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    #: Local wall-clock time, when one was given ("um 9:30 anrufen").
    due_time: Mapped[dt.time | None] = mapped_column(Time, nullable=True)
    text: Mapped[str] = mapped_column(String(TEXT_MAX), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default=OPEN, server_default=OPEN, nullable=False)
    origin: Mapped[str] = mapped_column(String(10), default="manual", server_default="manual", nullable=False)

    created_by_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    done_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    done_by_user_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    done_by_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
