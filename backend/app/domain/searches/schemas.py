"""Pydantic v2 contracts for saved searches."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class SavedSearchBase(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    q: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    radius_km: int | None = Field(default=None, ge=0, le=200)
    min_roles: int = Field(default=0, ge=0)
    crawl_enabled: bool = True


class SavedSearchCreate(SavedSearchBase):
    pass


class SavedSearchUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    q: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    radius_km: int | None = Field(default=None, ge=0, le=200)
    min_roles: int | None = Field(default=None, ge=0)
    crawl_enabled: bool | None = None


class SavedSearchRead(SavedSearchBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    last_crawled_at: dt.datetime | None
    last_result_count: int | None
    created_at: dt.datetime
    updated_at: dt.datetime


class CrawlProfile(BaseModel):
    """One deduplicated crawl directive handed to the nightly job.

    Deliberately carries NO tenant_id and no label: the crawler learns what to
    fetch, never who asked for it. Search terms are competitive intelligence.
    """

    q: str
    city: str | None = None
    radius_km: int | None = None
