"""Project wire contracts."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    """A project needs a name and nothing else."""

    name: str = Field(min_length=1, max_length=120)
    note: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = None


class ProjectCompanyRead(BaseModel):
    """One employer in a project, with the corpus facts it points at.

    Rolled up across the employer's sites the way Markt shows it, so a project
    line reads "4 Standorte · 5 offene Rollen" rather than one branch's numbers.
    """

    hub_company_id: uuid.UUID
    name: str
    website_domain: str | None
    cities: list[str]
    city_count: int
    sites: int
    open_roles: int
    last_posted_at: dt.datetime | None
    note: str | None
    added_at: dt.datetime
    #: This workspace's own company row, once adopted from the corpus.
    company_id: uuid.UUID | None
    #: Contacts this workspace already holds for it.
    contact_count: int


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    note: str | None
    company_count: int = 0
    #: Companies in the project that have at least one contact in this
    #: workspace — "9 von 12 Firmen haben einen Ansprechpartner".
    companies_with_contact: int = 0
    open_roles: int = 0
    created_at: dt.datetime
    updated_at: dt.datetime


class ProjectDetail(ProjectRead):
    companies: list[ProjectCompanyRead] = Field(default_factory=list)


class AddCompaniesRequest(BaseModel):
    """Corpus companies to put in the project. Idempotent: re-adding one that
    is already there is not an error, it is a no-op."""

    hub_company_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
