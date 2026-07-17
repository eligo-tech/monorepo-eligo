"""Pydantic v2 contracts for the companies domain."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


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