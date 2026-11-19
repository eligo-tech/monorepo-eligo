"""Wire contracts for erasure (GDPR Art. 17/21)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EraseRequest(BaseModel):
    #: Typed by the admin; must match the record's name. Cannot be undone.
    confirm_name: str = Field(min_length=1, max_length=200)
    reason: Literal["erasure", "objection"] = "erasure"
    #: The day the person asked.
    requested_on: dt.date
    #: ELI-32: e-mail the person a confirmation, to the address read before
    #: the erasure removes it. Off unless ticked; never stored afterwards.
    send_confirmation: bool = False

    @field_validator("requested_on")
    @classmethod
    def _not_in_the_future(cls, value: dt.date) -> dt.date:
        # One day of slack: just after midnight in Berlin it is still
        # yesterday in UTC, and the other way round.
        if value > dt.datetime.now(dt.UTC).date() + dt.timedelta(days=1):
            raise ValueError("requested_on cannot be in the future")
        return value


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
    #: Fingerprints lifted since, because the person came back of their own
    #: accord — each one lets them be created again, so the admin sees it.
    lifted: int = 0
    last_lifted_at: dt.datetime | None = None
    last_lifted_by: str | None = None
    #: ELI-32, on the erase response only: what became of the confirmation
    #: mail — "sent" · "failed" · "not_configured" · "no_email"; None when
    #: none was asked for.
    confirmation: Literal["sent", "failed", "not_configured", "no_email"] | None = None


class DoNotContactRead(BaseModel):
    """ELI-32: one person's "Nicht mehr kontaktieren" mark."""

    subject_type: Literal["manager", "candidate"]
    id: uuid.UUID
    do_not_contact_at: dt.datetime | None
    do_not_contact_reason: str | None


class ConfirmationSent(BaseModel):
    status: Literal["sent"] = "sent"
