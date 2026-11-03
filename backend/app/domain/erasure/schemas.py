"""Wire contracts for erasure (GDPR Art. 17/21)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EraseRequest(BaseModel):
    #: Typed by the admin; must match the record's name. Cannot be undone.
    confirm_name: str = Field(min_length=1, max_length=200)
    reason: Literal["erasure", "objection"] = "erasure"
    #: The day the person asked.
    requested_on: dt.date


class ErasureRequestRead(BaseModel):
    """One handled request. Names nobody — not even the erased record's id."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_type: str
    reason: str
    requested_on: dt.date
    created_at: dt.datetime
    executed_by_name: str | None = None
    counts: dict[str, int]
