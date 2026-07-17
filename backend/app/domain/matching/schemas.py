"""Pydantic v2 contracts for the matching domain.

The ``MatchReason`` shape (title / strength / evidence) mirrors the frontend
mock: each reason a recruiter sees is backed by explicit evidence.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domain.common.enums import MatchStrength


class MatchReason(BaseModel):
    """A single human-readable reason a candidate matched, with evidence."""

    title: str
    strength: MatchStrength
    evidence: str


class MatchResult(BaseModel):
    """The result of matching one candidate against one job (a Match Receipt)."""

    model_config = ConfigDict(from_attributes=True)

    candidate_id: uuid.UUID
    job_id: uuid.UUID
    passed_hard_filters: bool
    hard_filter_failures: list[str] = Field(default_factory=list)
    score: float
    strength: MatchStrength
    reasons: list[MatchReason] = Field(default_factory=list)
    ranker: str = "deterministic-stub"


class MatchReceiptRead(MatchResult):
    """Persisted match receipt with identifiers/timestamps."""

    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: dt.datetime


class MatchJobRequest(BaseModel):
    """Match a whole candidate pool against one job."""

    job_id: uuid.UUID
    tenant_id: uuid.UUID | None = None
    include_rejected: bool = Field(
        default=False,
        description="Include candidates that failed hard filters (with reasons).",
    )
    persist: bool = Field(
        default=False, description="Persist Match Receipts to the ledger."
    )