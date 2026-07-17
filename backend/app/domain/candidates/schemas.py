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