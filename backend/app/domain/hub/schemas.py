"""Pydantic v2 contracts for the information hub.

Corpus reads carry no ``tenant_id`` — the corpus is shared, so there is no
tenant to report. The tenant's own view of a corpus company is a separate
contract (``HubCompanyLinkRead``) and a ``tracked`` flag on the listing.
"""

from __future__ import annotations

import datetime as dt
import uuid

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HubCompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    normalized_name: str
    legal_form: str | None
    dedupe_key: str
    # Which rung of the identity ladder matched — "vat" is proof, "name_place"
    # is a working assumption. Exposed so the UI can say which.
    resolution_basis: str
    website_domain: str | None
    street: str | None
    postal_code: str | None
    city: str | None
    region: str | None
    country: str | None
    latitude: float | None
    longitude: float | None
    register_court: str | None
    register_number: str | None
    vat_id: str | None
    vat_verified_at: dt.datetime | None
    industry: str | None
    source: str
    open_postings_count: int
    bd_signals: dict = Field(default_factory=dict)
    first_seen_at: dt.datetime
    last_seen_at: dt.datetime
    created_at: dt.datetime
    updated_at: dt.datetime

    # This tenant's overlay, filled in by the router. Not a corpus fact — the
    # same company is tracked by one tenant and not another.
    tracked: bool = False


class HubJobPostingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hub_company_id: uuid.UUID
    observation_id: uuid.UUID | None
    title: str
    description: str | None
    occupation: str | None
    employment_type: str | None
    location_text: str | None
    postal_code: str | None
    city: str | None
    country: str | None
    latitude: float | None
    longitude: float | None
    remote_possible: bool | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    posted_at: dt.datetime | None
    expires_at: dt.datetime | None
    source: str
    source_url: str | None
    external_id: str
    first_seen_at: dt.datetime
    last_seen_at: dt.datetime
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class HubObservationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    request_url: str
    http_status: int | None
    robots_allowed: bool
    record_count: int
    total_available: int | None
    content_hash: str | None
    fetched_at: dt.datetime
    note: str | None
    created_at: dt.datetime


RELATIONSHIPS = ("watching", "prospect", "client", "ignored")


class HubCompanyLinkRead(BaseModel):
    """One tenant's relationship to one corpus company."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    hub_company_id: uuid.UUID
    company_id: uuid.UUID | None
    relationship: str
    note: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class TrackRequest(BaseModel):
    relationship: Literal["watching", "prospect", "client", "ignored"] = "watching"
    note: str | None = Field(default=None, max_length=1000)


class IngestRequest(BaseModel):
    """One crawl slice. Deliberately small — a full backfill is many of these."""

    source: str = "bundesagentur"
    what: str | None = Field(default=None, description="keyword / occupation")
    where: str | None = Field(default=None, description="city, PLZ or region")
    radius_km: int | None = Field(default=None, ge=0, le=200)
    published_since_days: int | None = Field(default=None, ge=0, le=100)
    page: int = Field(default=1, ge=1)
    size: int = Field(default=100, ge=1, le=100)
    # Staffing agencies are competitors, not leads — excluded unless asked for.
    include_staffing: bool = False


class RejectedRecord(BaseModel):
    """A record the gate refused, and why. Surfaced so losses are never silent."""

    external_id: str | None = None
    company: str | None = None
    reason: str


class IngestSummary(BaseModel):
    """Outcome of one ingest slice."""

    source: str
    observation_id: uuid.UUID
    fetched: int
    total_available: int | None
    companies_created: int
    companies_matched: int
    postings_created: int
    postings_updated: int
    rejected: list[RejectedRecord] = Field(default_factory=list)
    # The gate's verdicts, in runbook order — the verification trace.
    notes: list[str] = Field(default_factory=list)
