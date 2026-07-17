"""Application ORM model — the many-to-many state machine linking a candidate
to a job as they move through the hiring pipeline."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.enums import ApplicationStatus, PipelineStage
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONList


class Application(Base, IDMixin, TenantMixin, TimestampMixin):
    """A candidate's application to a specific job."""

    __tablename__ = "applications"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id"), index=True, nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id"), index=True, nullable=False
    )

    status: Mapped[ApplicationStatus] = mapped_column(
        String(20), default=ApplicationStatus.SOURCED, nullable=False
    )
    stage: Mapped[PipelineStage] = mapped_column(
        String(20), default=PipelineStage.BEWERBUNG, nullable=False
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Append-only audit of stage/status transitions (who, from, to, when).
    history: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)