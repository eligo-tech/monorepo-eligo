"""Wire contracts for Wiedervorlagen (ELI-44)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.followups.models import TEXT_MAX


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("a follow-up needs a text")
    return value


class FollowUpCreate(BaseModel):
    manager_id: uuid.UUID | None = None
    candidate_id: uuid.UUID | None = None
    due_date: dt.date
    due_time: dt.time | None = None
    text: str = Field(max_length=TEXT_MAX)
    source_interaction_id: uuid.UUID | None = None
    origin: Literal["manual", "note"] = "manual"

    @field_validator("text")
    @classmethod
    def _stripped(cls, value: str | None) -> str | None:
        return _text(value)

    @model_validator(mode="after")
    def _one_person(self) -> "FollowUpCreate":
        if (self.manager_id is None) == (self.candidate_id is None):
            raise ValueError("a follow-up belongs to exactly one person: manager_id or candidate_id")
        return self


class FollowUpUpdate(BaseModel):
    """Every field optional; `due_time: null` clears the time."""

    due_date: dt.date | None = None
    due_time: dt.time | None = None
    text: str | None = Field(default=None, max_length=TEXT_MAX)
    status: Literal["open", "done"] | None = None

    @field_validator("text")
    @classmethod
    def _stripped(cls, value: str | None) -> str | None:
        return _text(value)


class FollowUpRead(BaseModel):
    id: uuid.UUID
    manager_id: uuid.UUID | None
    candidate_id: uuid.UUID | None
    source_interaction_id: uuid.UUID | None
    due_date: dt.date
    due_time: dt.time | None
    text: str
    status: str
    origin: str
    created_at: dt.datetime
    created_by_name: str | None
    done_at: dt.datetime | None
    done_by_name: str | None
    #: Who it is about, so the to-do list can name and link the person
    #: without a second request per row. "lead" = a manager with stage
    #: bus_dev (the Leads screen), "manager", or "candidate".
    subject_kind: Literal["lead", "manager", "candidate"]
    person_name: str
    company_id: uuid.UUID | None = None
    company_name: str | None = None


class SuggestRequest(BaseModel):
    """The note's text and the day it is about (the note's date, in the
    recruiter's own calendar)."""

    #: Capped: notes can be whole transcripts, and the reader only needs the
    #: part a follow-up date is in.
    text: str = Field(max_length=20_000)
    reference_date: dt.date


class DateSuggestionRead(BaseModel):
    due_date: dt.date
    phrase: str


class SuggestResponse(BaseModel):
    suggestions: list[DateSuggestionRead]
