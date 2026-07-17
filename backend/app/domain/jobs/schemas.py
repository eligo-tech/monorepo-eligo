"""Pydantic v2 contracts for the jobs domain."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class JobBase(BaseModel):
    title: str
    client_company_id: uuid.UUID | None = None
    location: str | None = None
    location_radius_km: int | None = None
    must_have_skills: list[str] = Field(default_factory=list)
    required_certifications: list[str] = Field(default_factory=list)
    requires_work_permit: bool = True
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "EUR"
    status: str = "open"


class JobCreate(JobBase):
    tenant_id: uuid.UUID | None = None


class JobRead(JobBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime