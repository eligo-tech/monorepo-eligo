"""Pydantic v2 contracts for the companies domain."""

from __future__ import annotations

import datetime as dt
import uuid

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.hub.schemas import Switchboard


class CompanyBase(BaseModel):
    name: str
    domain: str | None = None
    industry: str | None = None
    location: str | None = None
    is_client: bool = False
    source: str | None = None
    bd_signals: dict = Field(default_factory=dict)


#: ELI-43: a person's call — "client" (Kunde) or "lead".
CompanyStatus = Literal["client", "lead"]


class CompanyCreate(CompanyBase):
    tenant_id: uuid.UUID | None = None
    #: A URL or host as typed; stored as its registrable domain.
    website: str | None = Field(default=None, max_length=500)
    #: ELI-43: when given, a person decided it — recorded through the gate
    #: and from then on what Kunden / Leads go by. Left out: `is_client` is
    #: kept as sent and the counts decide, as before.
    status: CompanyStatus | None = None

    @field_validator("name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name is required")
        if len(value) > 200:
            raise ValueError("name is too long")
        return value

    @field_validator("location", "website")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class CompanyStatusUpdate(BaseModel):
    status: CompanyStatus


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
    #: ELI-31: taken from Markt ("Übernehmen"), no contact and no manager yet.
    markt_lead: bool = False
    #: ELI-43: a person's decision (Lead / Kunde), if one was made.
    status: CompanyStatus | None = None
    last_contact_at: dt.datetime | None
    #: ELI-33: Markt sites of the same name waiting for a person's yes/no.
    to_review: int = 0


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
    #: ELI-43: Kunde / Lead — a person's decision, else what the counts say;
    #: null when neither (no manager, no lead, never decided).
    status: CompanyStatus | None = None
    #: True when `status` is a person's decision, not derived.
    status_set: bool = False


class MarketJob(BaseModel):
    title: str
    city: str | None
    posted_at: dt.datetime | None
    source: str
    url: str | None


class CareersPage(BaseModel):
    url: str
    #: "careers" (its own job board/page) or "website" (only its site).
    kind: str


class CompanyMarket(BaseModel):
    """ELI-33: the company's open jobs in Markt — every site of the employer
    it is linked to — and its careers page."""

    linked: bool
    total: int
    jobs: list[MarketJob]
    careers: CareersPage | None = None


class MarketSuggestion(BaseModel):
    """ELI-33 step 2b: a Markt site with this company's name in another or
    unknown town — for a person to confirm or dismiss."""

    hub_company_id: uuid.UUID
    name: str
    city: str | None
    postal_code: str | None
    open_ads: int
    sample_titles: list[str]


class MarketSites(BaseModel):
    hub_company_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    #: Confirming: the other sites shown and not picked — ruled out.
    dismiss_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class CompanyPage(BaseModel):
    company: CompanyCore
    managers: list[CompanyPerson]
    leads: list[CompanyPerson]
    mandates: list[CompanyMandate]
    #: ELI-30: the switchboard from the company's own Impressum, if verified.
    switchboard: Switchboard | None = None
    market: CompanyMarket
    suggestions: list[MarketSuggestion] = []
