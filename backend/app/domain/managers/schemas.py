"""Wire contracts for the managers domain."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.enums import ConfidenceSource, InteractionType


class ManagerInteractionCreate(BaseModel):
    interaction_type: InteractionType
    occurred_at: dt.datetime | None = None
    summary: str | None = Field(default=None, max_length=5000)
    candidate_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None


class ManagerInteractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    manager_id: uuid.UUID
    candidate_id: uuid.UUID | None
    job_id: uuid.UUID | None
    interaction_type: str
    occurred_at: dt.datetime
    summary: str | None
    external_source: str | None = None


class ManagerCreate(BaseModel):
    company_id: uuid.UUID
    full_name: str = Field(min_length=1, max_length=200)
    first_name: str | None = None
    last_name: str | None = None
    role_title: str | None = None
    department: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    #: Required in practice even though it defaults: a person record whose
    #: origin is unknown cannot be assessed for Art. 14 later.
    source: ConfidenceSource = ConfidenceSource.SELF_REPORTED
    source_detail: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class ManagerUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    first_name: str | None = None
    last_name: str | None = None
    role_title: str | None = None
    department: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    notes: str | None = None
    status: str | None = None


class ManagerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    full_name: str
    first_name: str | None
    last_name: str | None
    role_title: str | None
    department: str | None
    email: str | None
    phone: str | None
    linkedin_url: str | None
    source: str
    source_detail: str | None
    art14_notified_at: dt.datetime | None
    #: Derived on the model, surfaced here so a recruiter can see the obligation
    #: rather than having to infer it from two other columns.
    art14_outstanding: bool
    notes: str | None
    status: str
    created_at: dt.datetime

    # --- detail, from the source's own profile ----------------------------
    #: "MNGR197" — the reference a recruiter reads out on a call.
    external_code: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    #: What the person is open to — "Looks for: Contract".
    looks_for: str | None = None
    skills: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    #: From the source, not derived from `interactions` — it knows about contact
    #: that predates anything imported here.
    last_contact_at: dt.datetime | None = None
