"""Matching ORM model — a persisted Match Receipt.

Stores both the deterministic outcome (did the candidate pass hard filters and
why not) and the soft ranking (score + reasons), so a recruiter can always see
why a candidate was or wasn't surfaced (GDPR Art. 22 contestability).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.enums import MatchStrength
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONList


class MatchReceipt(Base, IDMixin, TenantMixin, TimestampMixin):
    """The stored outcome of matching one candidate against one job."""

    __tablename__ = "match_receipts"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id"), index=True, nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id"), index=True, nullable=False
    )

    passed_hard_filters: Mapped[bool] = mapped_column(Boolean, nullable=False)
    hard_filter_failures: Mapped[list] = mapped_column(
        JSONList, default=list, nullable=False
    )

    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    strength: Mapped[MatchStrength] = mapped_column(
        String(20), default=MatchStrength.WEAK, nullable=False
    )
    # Each reason: {title, strength, evidence}.
    reasons: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)

    # Provenance of the soft ranking: "deterministic-stub" | "<llm-model-id>".
    ranker: Mapped[str] = mapped_column(
        String(80), default="deterministic-stub", nullable=False
    )