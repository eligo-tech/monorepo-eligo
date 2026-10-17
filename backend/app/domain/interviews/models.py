"""One AI-assisted pre-screen interview of one candidate.

Status flow: awaiting_consent → in_progress → completed, or → withdrawn from
any state. Withdrawal erases the transcript (`turns` emptied); the receipts
keep that it happened, not what was said.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONDict, JSONList


class Interview(Base, IDMixin, TenantMixin, TimestampMixin):
    __tablename__ = "interviews"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id"), index=True, nullable=False
    )
    #: awaiting_consent | in_progress | completed | withdrawn
    status: Mapped[str] = mapped_column(
        String(20), default="awaiting_consent", nullable=False
    )
    script_version: Mapped[str] = mapped_column(String(20), nullable=False)
    started_by: Mapped[str] = mapped_column(String(200), nullable=False)

    #: The notice version the candidate agreed to, and when. NULL = no consent,
    #: and no question is asked without it.
    consent_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    consent_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consent_recorded_by: Mapped[str | None] = mapped_column(String(200), nullable=True)

    #: [{"question_key", "question", "answer", "at"}] in order.
    turns: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    #: Per-field result of the extraction: committed / review, with reason.
    outcome: Mapped[dict] = mapped_column(JSONDict, default=dict, nullable=False)

    completed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    withdrawn_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
