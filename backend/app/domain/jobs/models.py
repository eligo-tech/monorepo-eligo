"""Job ORM model — a client hiring mandate."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONList


class Job(Base, IDMixin, TenantMixin, TimestampMixin):
    """A role a client wants filled."""

    __tablename__ = "jobs"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    client_company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id"), nullable=True, index=True
    )

    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Radius (km) around the location used by the deterministic location filter.
    location_radius_km: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Hard requirements evaluated deterministically before any LLM ranking.
    must_have_skills: Mapped[list] = mapped_column(
        JSONList, default=list, nullable=False
    )
    required_certifications: Mapped[list] = mapped_column(
        JSONList, default=list, nullable=False
    )
    requires_work_permit: Mapped[bool] = mapped_column(
        default=True, nullable=False
    )

    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(3), default="EUR")

    status: Mapped[str] = mapped_column(String(30), default="open", nullable=False)