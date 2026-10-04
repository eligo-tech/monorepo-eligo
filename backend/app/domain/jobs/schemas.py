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


class JobUpdate(BaseModel):
    """PATCH payload for editing a mandate.

    Every field optional; only what is sent is applied. This is the Suchprofil
    — and three of these fields are **hard filter inputs**: `salary_max`,
    `location_radius_km` and `required_certifications` decide who the matcher
    excludes outright. An edit here changes who a client gets to see, so it
    goes through the verification gate and leaves a receipt, exactly like an
    edit to a candidate.
    """

    title: str | None = None
    client_company_id: uuid.UUID | None = None
    location: str | None = None
    location_radius_km: int | None = Field(default=None, ge=0)
    must_have_skills: list[str] | None = None
    required_certifications: list[str] | None = None
    requires_work_permit: bool | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = None
    status: str | None = None


class CriteriaSuggestion(BaseModel):
    """One proposed Muss-Kriterium, and the reason it is proposed.

    A proposal, not a write: hard criteria exclude people, so a human picks
    the ones that are really non-negotiable (the same rule the agents follow).
    """

    skill: str
    evidence: str
    #: How many of this workspace's candidates carry the skill — a criterion
    #: nobody has filters everyone out, so the number is part of the offer.
    candidates: int = 0
