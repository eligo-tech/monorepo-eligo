"""Pydantic v2 contracts for the companies domain."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domain.hub.schemas import Switchboard


class CompanyBase(BaseModel):
    name: str
    domain: str | None = None
    industry: str | None = None
    location: str | None = None
    is_client: bool = False
    source: str | None = None
    bd_signals: dict = Field(default_factory=dict)


class CompanyCreate(CompanyBase):
    tenant_id: uuid.UUID | None = None


class CompanyRead(CompanyBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime

# --- Unternehmen (ELI-33) ----------------------------------------------------


class CompanyOverviewRow(BaseModel):
    id: uuid.UUID
    name: str
    location: str | None
    managers: int
    leads: int
    mandates: int
    last_contact_at: dt.datetime | None


class CompanyPerson(BaseModel):
    id: uuid.UUID
    full_name: str
    role_title: str | None
    email: str | None
    phone: str | None
    stage: str
    last_contact_at: dt.datetime | None


class CompanyMandate(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    location: str | None


class CompanyCore(BaseModel):
    id: uuid.UUID
    name: str
    location: str | None
    domain: str | None
    industry: str | None
    source: str | None


class CompanyPage(BaseModel):
    company: CompanyCore
    managers: list[CompanyPerson]
    leads: list[CompanyPerson]
    mandates: list[CompanyMandate]
    #: ELI-30: the switchboard from the company's own Impressum, if verified.
    switchboard: Switchboard | None = None
