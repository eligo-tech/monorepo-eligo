"""Wire contracts for interviews."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field


class InterviewStart(BaseModel):
    candidate_id: uuid.UUID


class CandidateConsentWrite(BaseModel):
    #: Must equal the notice version the candidate was shown.
    notice_version: str
    #: Explicit, not implied: the client has to send `true`.
    confirmed: bool


class AnswerWrite(BaseModel):
    text: str = Field(..., max_length=4000)


class QuestionRead(BaseModel):
    key: str
    prompt: str
    number: int
    total: int


class FieldOutcome(BaseModel):
    field: str
    value: str | None
    quote: str | None
    committed: bool
    needs_human_review: bool
    reason: str


class InterviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    status: str
    script_version: str
    started_by: str
    consent_version: str | None
    consent_at: dt.datetime | None
    turns: list[dict]
    outcome: dict
    completed_at: dt.datetime | None
    withdrawn_at: dt.datetime | None
    created_at: dt.datetime
    #: Filled by the router, not stored.
    notice: str | None = None
    notice_version: str | None = None
    next_question: QuestionRead | None = None
