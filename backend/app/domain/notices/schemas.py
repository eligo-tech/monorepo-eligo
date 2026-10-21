"""Wire contracts for candidate notices."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict


class NoticeRead(BaseModel):
    """One notice as the cockpit shows it.

    `token` is absent on purpose — it is the only credential on the public
    opt-in endpoints, and a recruiter-facing payload is the wrong place for
    it. `body` is included: the point of storing what was sent is being able
    to show it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    email: str
    status: str
    subject: str
    body: str
    provider: str | None
    sent_at: dt.datetime | None
    responded_at: dt.datetime | None
    failure_reason: str | None
    requested_by: str | None
    created_at: dt.datetime


class NoticeCapability(BaseModel):
    """Whether this deployment can send at all.

    The UI reads it so a recruiter is told "not configured" instead of
    meeting a 503 behind a button that looked ready.
    """

    configured: bool
    provider: str
    sender: str | None
