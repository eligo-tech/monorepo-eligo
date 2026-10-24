"""Pydantic v2 contracts for the jobs domain."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.common.enums import JobStatus, normalise_job_status


class JobBase(BaseModel):
    title: str
    client_company_id: uuid.UUID | None = None
    #: The Ansprechpartner at the client — who the briefing came from and who
    #: gets the shortlist. The column has existed since the first migration
    #: and was in no schema, so the mandate could only ever say "Kein
    #: Ansprechpartner hinterlegt" and point at another screen.
    #:
    #: Must be a contact at `client_company_id`; the service refuses one
    #: belonging to a different client rather than quietly storing it.
    manager_id: uuid.UUID | None = None
    location: str | None = None
    location_radius_km: int | None = None
    must_have_skills: list[str] = Field(default_factory=list)
    required_certifications: list[str] = Field(default_factory=list)
    requires_work_permit: bool = True
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "EUR"
    #: `active` or `inactive` (ELI-7). The default is what a new mandate is:
    #: somebody is only writing it down because the client asked for it.
    status: str = JobStatus.ACTIVE.value


class JobCreate(JobBase):
    tenant_id: uuid.UUID | None = None


class JobRead(JobBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    #: Set when this mandate was created as a copy — see `JobCopy`.
    copied_from_job_id: uuid.UUID | None = None
    created_at: dt.datetime
    updated_at: dt.datetime

    @field_validator("status", mode="before")
    @classmethod
    def _canonical_status(cls, value: object) -> object:
        """The cockpit must never see "open" or "closed".

        Migration 0039 rewrites those rows, but the editor sends `status`
        back on every save, so a row the migration had not reached would
        hand the old spelling straight back to a backend that no longer
        knows it. That is exactly how 18 of 79 mandates became unsaveable
        the last time this vocabulary changed; normalising on the way out
        means the browser only ever holds a word that is still a word.
        """
        return normalise_job_status(value) if isinstance(value, str) else value


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
    manager_id: uuid.UUID | None = None
    location: str | None = None
    location_radius_km: int | None = Field(default=None, ge=0)
    must_have_skills: list[str] | None = None
    required_certifications: list[str] | None = None
    requires_work_permit: bool | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = None
    status: str | None = None


class JobCopy(BaseModel):
    """Reuse an old mandate: "alte Jobs als Kopie wiederverwenden" (ELI-7).

    The other half of "inactive is final". Everything about the Suchprofil is
    carried over; nothing about the history is. An optional new title, because
    the commonest copy is the same role at the same client a year later and
    the second commonest is nearly the same role.
    """

    title: str | None = Field(default=None, max_length=200)


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


# ── Reading an advert into a Suchprofil (ELI-6) ───────────────────────────


class JobSpecRequest(BaseModel):
    """A link to an advert, or the advert pasted in.

    Both, because the link is what a recruiter has and the paste is what
    works when the advert sits behind a login or a portal that renders in
    JavaScript — which is most German applicant-tracking portals.
    """

    url: str | None = None
    text: str | None = Field(default=None, max_length=200_000)

    @model_validator(mode="after")
    def _one_of(self) -> JobSpecRequest:
        if not (self.url or "").strip() and not (self.text or "").strip():
            raise ValueError("either url or text is required")
        return self


class ProposedValue(BaseModel):
    """A value the extractor read, and how plainly the advert stated it."""

    value: str
    confidence: float


class JobSpecProposal(BaseModel):
    """What the advert appears to say. NOT a mandate.

    No `Job` is created by reading an advert. The recruiter gets a filled-in
    form and presses save, because `must_have_skills` are hard filters that
    exclude people and ARCHITECTURE.md RULE 5 keeps that decision human.
    """

    title: ProposedValue | None = None
    location: ProposedValue | None = None
    salary_min: ProposedValue | None = None
    salary_max: ProposedValue | None = None
    employment_form: ProposedValue | None = None
    must_have_skills: list[ProposedValue] = Field(default_factory=list)
    #: The advert's own words, so a proposal can be checked without
    #: reopening the link.
    excerpt: str = ""
    #: Where it came from — echoed back for the receipt the save writes.
    source_url: str | None = None

