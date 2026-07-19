"""Pydantic v2 contracts for the candidates domain.

Response shape mirrors the frontend mock data: name, email, phone,
current_title/current_company, skills[], verification_score.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.enums import WorkPermitStatus


class CandidateBase(BaseModel):
    full_name: str
    email: str | None = None
    phone: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    location: str | None = None
    skills: list[str] = Field(default_factory=list)
    work_history: list[dict] = Field(default_factory=list)
    salary_expectation: int | None = None
    salary_currency: str = "EUR"
    availability_weeks: int | None = None
    work_permit: WorkPermitStatus = WorkPermitStatus.UNKNOWN

    # Extended profile (aiFind field set) — all optional.
    first_name: str | None = None
    last_name: str | None = None
    sex: str | None = None
    name_prefix: str | None = None
    date_of_birth: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    linkedin_url: str | None = None
    xing_url: str | None = None
    industry: str | None = None
    employment_type: str | None = None
    willing_to_relocate: str | None = None
    notice_period: str | None = None
    availability: str | None = None
    total_years_experience: str | None = None
    current_salary: int | None = None
    languages: list[str] | None = None
    # Structured entries ({degree, institution, dates}) or legacy strings.
    education: list[dict] | list[str] | None = None
    working_experience: list[str] | None = None
    motivation: str | None = None
    source: str | None = None


class CandidateCreate(CandidateBase):
    tenant_id: uuid.UUID | None = None
    merged_identities: list[str] = Field(default_factory=list)


class CandidateRead(CandidateBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    merged_identities: list[str] = Field(default_factory=list)
    verification_score: float
    created_at: dt.datetime
    updated_at: dt.datetime