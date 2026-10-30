"""What a read action returns — a whitelist, not a filtered copy of the model.

Everything here reaches the user's AI vendor. So each model names the fields
it carries, and anything not named does not leave: no e-mail, phone, address,
salary, date of birth, free-text notes, motivation, CV text or work history
(plan: "v1 is read-only. No email, phone or raw CV text in any output").
Adding a field is a decision about what Anthropic or OpenAI receives; make it
here, on purpose, and `tests/test_actions_reads.py` will tell you if a marker
value starts leaking.

Every output carries `sources`: which records the answer was read from, so a
claim in the AI's reply can be traced back to a row in Eligo.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class Source(BaseModel):
    """One record an answer was read from."""

    #: candidate · job · process · posting · report
    type: str
    id: str
    #: Public URL, only for shared-corpus records that have one (postings).
    url: str | None = None


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sources: list[Source] = Field(default_factory=list)


class CandidateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    current_title: str | None = None
    current_company: str | None = None
    city: str | None = None
    skills: list[str] = Field(default_factory=list)
    availability: str | None = None
    availability_weeks: int | None = None
    notice_period: str | None = None
    work_permit: str | None = None
    #: Share of key fields with evidence behind them (0–1). Low = mostly unverified.
    verification_score: float = 0.0
    completeness_score: float = 0.0


class ProvenanceEntry(BaseModel):
    """Which field changed, when, by whom, from what source — never the value.

    The ledger's WRITE summary reads "write email='…'", so carrying it would
    send the very contact data the rest of this file keeps out.
    """

    at: dt.datetime | None = None
    actor: str | None = None
    field: str | None = None
    source: str | None = None


class CandidateList(_Out):
    candidates: list[CandidateSummary]
    total: int
    truncated: bool


class CandidateDetail(_Out):
    candidate: CandidateSummary
    profile_summary: str | None = None
    focus_areas: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    total_years_experience: str | None = None
    #: Who changed what, from the receipt ledger.
    provenance: list[ProvenanceEntry] = Field(default_factory=list)


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: str | None = None
    location: str | None = None
    location_radius_km: int | None = None
    must_have_skills: list[str] = Field(default_factory=list)
    required_certifications: list[str] = Field(default_factory=list)
    requires_work_permit: bool | None = None
    client_company_id: uuid.UUID | None = None


class JobList(_Out):
    jobs: list[JobSummary]


class JobDetail(_Out):
    job: JobSummary


class MatchReasonOut(BaseModel):
    title: str
    strength: str
    evidence: str


class MatchOut(BaseModel):
    candidate_id: uuid.UUID
    candidate_name: str
    score: float
    strength: str
    reasons: list[MatchReasonOut] = Field(default_factory=list)


class MatchList(_Out):
    job_id: uuid.UUID
    #: The hard criteria applied in plain code before any ranking.
    hard_criteria: list[str] = Field(default_factory=list)
    matches: list[MatchOut]


class StepOut(BaseModel):
    step_key: str
    label: str | None = None
    scheduled_at: dt.datetime | None = None
    done_at: dt.datetime | None = None
    outcome: str | None = None


class ProcessCandidate(BaseModel):
    application_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: str
    stage: str
    presented_at: dt.datetime | None = None
    next_appointment: dt.datetime | None = None
    steps: list[StepOut] = Field(default_factory=list)
    fit_score: float | None = None
    verdict: str | None = None


class ProcessOut(BaseModel):
    job_id: uuid.UUID
    job_title: str
    company_name: str | None = None
    status: str | None = None
    candidates: list[ProcessCandidate]


class ProcessList(_Out):
    processes: list[ProcessOut]


class Report(_Out):
    report: dict


class PostingOut(BaseModel):
    id: uuid.UUID
    title: str
    employer: str | None = None
    city: str | None = None
    posted_at: dt.datetime | None = None
    source: str
    source_url: str | None = None


class PostingList(_Out):
    postings: list[PostingOut]


class ProposalOut(_Out):
    """A change an AI client proposed. Applied only when a human confirms it in Eligo."""

    id: uuid.UUID
    kind: str
    #: pending · confirmed · declined · stale · expired
    status: str
    title: str
    created_at: dt.datetime
    expires_at: dt.datetime
    decided_at: dt.datetime | None = None
    #: What the client should tell the user.
    next_step: str

    @classmethod
    def from_row(cls, row) -> ProposalOut:  # noqa: ANN001 — AgentProposal
        from app.domain.proposals import service as proposals

        status = proposals.effective_status(row)
        return cls(
            id=row.id,
            kind=row.kind,
            status=status,
            title=row.title,
            created_at=row.created_at,
            expires_at=proposals.expires_at(row),
            decided_at=row.decided_at,
            next_step=(
                "Nothing has changed yet. Ask the user to confirm it in Eligo "
                "(the 'Vorschläge' / 'Proposals' button at the top); it expires after 7 days."
                if status == "pending"
                else f"This proposal is {status}."
            ),
            sources=[Source(type="proposal", id=str(row.id))],
        )


class ProposalList(_Out):
    proposals: list[ProposalOut]
