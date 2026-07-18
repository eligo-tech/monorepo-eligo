"""Candidate ORM model — the canonical, de-duplicated person record.

``verification_score`` reflects how much of the profile has been human- or
postcondition-verified (vs. raw agent proposals) — surfaced to recruiters and
required for EU AI Act transparency about automated data.
"""

from __future__ import annotations

from sqlalchemy import Float, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.common.enums import WorkPermitStatus
from app.domain.common.mixins import IDMixin, TenantMixin, TimestampMixin
from app.domain.common.types import JSONList


class Candidate(Base, IDMixin, TenantMixin, TimestampMixin):
    """A canonical candidate profile."""

    __tablename__ = "candidates"

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    current_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    current_company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # --- Extended profile (aiFind field set) -----------------------------
    # All nullable so they can be added to an existing table without a backfill.
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sex: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name_prefix: Mapped[str | None] = mapped_column(String(40), nullable=True)
    date_of_birth: Mapped[str | None] = mapped_column(String(40), nullable=True)

    street: Mapped[str | None] = mapped_column(String(200), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)

    linkedin_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    xing_url: Mapped[str | None] = mapped_column(String(300), nullable=True)

    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    employment_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    willing_to_relocate: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notice_period: Mapped[str | None] = mapped_column(String(80), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(80), nullable=True)
    total_years_experience: Mapped[str | None] = mapped_column(String(40), nullable=True)
    current_salary: Mapped[int | None] = mapped_column(Integer, nullable=True)

    languages: Mapped[list | None] = mapped_column(JSONList, nullable=True)
    education: Mapped[list | None] = mapped_column(JSONList, nullable=True)
    working_experience: Mapped[list | None] = mapped_column(JSONList, nullable=True)

    motivation: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # De-duplication: source identity keys that were merged into this record.
    merged_identities: Mapped[list] = mapped_column(
        JSONList, default=list, nullable=False
    )
    skills: Mapped[list] = mapped_column(JSONList, default=list, nullable=False)
    work_history: Mapped[list] = mapped_column(
        JSONList, default=list, nullable=False
    )

    salary_expectation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(3), default="EUR")
    availability_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)

    work_permit: Mapped[WorkPermitStatus] = mapped_column(
        String(30), default=WorkPermitStatus.UNKNOWN, nullable=False
    )

    # 0.0-1.0 — share of the profile that is verified rather than proposed.
    verification_score: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False
    )

    # Optional embedding (JSON list on SQLite; pgvector column on Postgres).
    embedding: Mapped[list | None] = mapped_column(JSONList, nullable=True)