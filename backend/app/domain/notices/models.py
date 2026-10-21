"""What a candidate was told, and what they answered.

One row per notice to one person. The row is the evidence: Art. 14 obliges the
controller to inform somebody whose data was collected elsewhere, and "we have
a template that says that" is not evidence that *this* person received it. So
the subject and body are stored as sent, not re-rendered on read — a template
edited next March must not change what the record claims was sent last
October.

`status` is never set from intent. It moves to `sent` only after a provider
accepted the message, and to `opted_in`/`opted_out` only from the candidate's
own click, which is why the token is a column and not a derivation.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin


class NoticeStatus(str, enum.Enum):
    """Where one notice stands.

    `PENDING` and `FAILED` both mean nothing reached the candidate; they are
    separate because a failure needs looking at and a draft does not.
    `SENT` means a provider accepted it — not that it was delivered, and
    certainly not that it was read. There is no `DELIVERED`: we would be
    inventing it, since nothing here consumes Resend's webhooks yet.
    """

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    OPTED_IN = "opted_in"
    OPTED_OUT = "opted_out"


#: A notice in one of these has been answered; it must never be re-sent or
#: re-decided. Used by the public endpoints to make a second click idempotent
#: rather than a state change.
SETTLED_STATUSES = frozenset({NoticeStatus.OPTED_IN.value, NoticeStatus.OPTED_OUT.value})


class CandidateNotice(Base, IDMixin, TenantMixin, TimestampMixin):
    """One Art. 14 notice / opt-in request sent to one candidate."""

    __tablename__ = "candidate_notices"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    #: The address it actually went to, frozen here. The candidate's own
    #: `email` column can be corrected later, and then the record would no
    #: longer say where the notice went.
    email: Mapped[str] = mapped_column(String(320), nullable=False)

    #: The secret in the opt-in link. Unique across all workspaces — it is the
    #: only thing authorising the public endpoints, so a collision would be a
    #: cross-workspace one.
    token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    status: Mapped[str] = mapped_column(
        String(20), default=NoticeStatus.PENDING.value, nullable=False, index=True
    )

    #: Exactly what was sent. Kept verbatim — see the module docstring.
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    #: Who carried it, and their id for the message — the handle a bounce
    #: investigation starts from.
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    sent_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    responded_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Why a send failed, in the provider's words. Null unless `status` is
    #: `failed`.
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    #: The recruiter who asked for it. A notice is a consequential outbound
    #: action, so it is attributable to a person, not just to a workspace.
    requested_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    requested_by_user_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
