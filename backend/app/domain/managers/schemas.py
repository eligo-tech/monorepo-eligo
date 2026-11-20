"""Wire contracts for the managers domain."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.common.enums import (
    CallOutcome,
    ConfidenceSource,
    InteractionType,
    normalise_interaction_type,
)


class ManagerInteractionCreate(BaseModel):
    interaction_type: InteractionType
    occurred_at: dt.datetime | None = None
    #: No length cap. The column is TEXT, and the thing people paste here is
    #: a whole Gesprächstranskript — the one input where an arbitrary limit
    #: is guaranteed to be hit, by the longest and most valuable note
    #: somebody ever writes. A limit that truncates work is worse than a
    #: large row.
    summary: str | None = None
    candidate_id: uuid.UUID | None = None
    job_id: uuid.UUID | None = None
    #: Who was spoken to. Optional: a briefing can be recorded before the
    #: contact is in the record (see migration 0034).
    manager_id: uuid.UUID | None = None
    #: ELI-22 call list: how the call ended, and when to call again.
    outcome: CallOutcome | None = None
    next_action_at: dt.datetime | None = None
    #: ELI-32: the person asked not to be contacted again. Saved with the
    #: note, in the same transaction, with a receipt — the note is the
    #: history of the request.
    do_not_contact: bool = False

    @model_validator(mode="after")
    def _outcome_belongs_to_a_call(self) -> "ManagerInteractionCreate":
        calls = {InteractionType.BUSINESS_CALL, InteractionType.CLIENT_CALL, InteractionType.CANDIDATE_CALL}
        if self.outcome is not None and self.interaction_type not in calls:
            raise ValueError("an outcome belongs to a call")
        return self

    @model_validator(mode="after")
    def _voicemail_is_not_reached(self) -> "ManagerInteractionCreate":
        # ELI-35: "Nicht erreicht und Mailbox sind das gleiche". New calls are
        # filed under one outcome; old `voicemail` rows stay readable.
        if self.outcome == CallOutcome.VOICEMAIL:
            self.outcome = CallOutcome.NOT_REACHED
        return self

    @model_validator(mode="after")
    def _call_back_has_a_date(self) -> "ManagerInteractionCreate":
        if self.outcome == CallOutcome.CALL_BACK and self.next_action_at is None:
            raise ValueError("call_back needs next_action_at — a call-back without a date never comes due")
        return self


class ManagerInteractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    #: None for a mandate-level note written before a contact existed.
    manager_id: uuid.UUID | None
    candidate_id: uuid.UUID | None
    job_id: uuid.UUID | None
    interaction_type: str
    occurred_at: dt.datetime
    summary: str | None
    external_source: str | None = None
    outcome: str | None = None
    next_action_at: dt.datetime | None = None

    @field_validator("interaction_type", mode="before")
    @classmethod
    def _canonical(cls, value: str | None) -> str:
        """One spelling reaches the client, whatever the row holds.

        The column is free text and three vocabularies wrote into it. Doing
        this here rather than at each call site means the cockpit never has
        to know that "BD Call" and `business_call` are the same thing — and
        a kind nobody mapped ("Job Spec") still arrives under its own name
        rather than being absorbed into a neighbour.
        """
        return normalise_interaction_type(value)

    @field_validator("occurred_at")
    @classmethod
    def _aware(cls, value: dt.datetime) -> dt.datetime:
        """SQLite hands back a naive datetime even for a tz-aware column.

        Without this the same endpoint emits "…T09:00:00" on SQLite and
        "…T09:00:00Z" on Postgres, and a browser reads the first as LOCAL
        time — a briefing logged at 09:00 shows as 11:00 in summer. Same fix
        the pipeline already applies in `as_utc`.
        """
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


#: Mobil · Durchwahl · Zentrale · Sonstige (ELI-46); `models.PHONE_KINDS`.
PhoneKind = Literal["mobile", "direct", "switchboard", "other"]


class ManagerPhoneIn(BaseModel):
    number: str = Field(min_length=1, max_length=50)
    kind: PhoneKind = "other"
    is_primary: bool = False

    @field_validator("number")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("a number cannot be blank")
        return value


class ManagerPhoneRead(BaseModel):
    number: str
    kind: str
    is_primary: bool


def _phone_list(phones: list[ManagerPhoneIn] | None) -> list[ManagerPhoneIn] | None:
    """One primary at most, no number twice (digits compared). Without a
    marked primary the first number is the primary — returned first."""
    if phones is None:
        return None
    if sum(p.is_primary for p in phones) > 1:
        raise ValueError("only one number can be the primary")
    digits = [re.sub(r"\D", "", p.number) or p.number for p in phones]
    if len(set(digits)) != len(digits):
        raise ValueError("the same number is listed twice")
    if not phones:
        return phones
    primary = next((i for i, p in enumerate(phones) if p.is_primary), 0)
    ordered = [phones[primary], *phones[:primary], *phones[primary + 1:]]
    return [p.model_copy(update={"is_primary": i == 0}) for i, p in enumerate(ordered)]


class ManagerCreate(BaseModel):
    #: The person was erased here on request and has since come back of their
    #: own accord. Without it, adding someone erased is refused (409).
    override_suppression: bool = False
    company_id: uuid.UUID
    full_name: str = Field(min_length=1, max_length=200)
    #: Capped at the column widths (ELI-45): past them Postgres refuses the
    #: row and the recruiter would see a 500 instead of a 422.
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    role_title: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=300)
    #: Required in practice even though it defaults: a person record whose
    #: origin is unknown cannot be assessed for Art. 14 later.
    source: ConfidenceSource = ConfidenceSource.SELF_REPORTED
    source_detail: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class ManagerUpdate(BaseModel):
    #: Setting an address of someone erased here is refused (409) unless they
    #: came back of their own accord.
    override_suppression: bool = False
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    #: Capped at the column widths (ELI-45): past them Postgres refuses the
    #: row and the recruiter would see a 500 instead of a 422.
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    role_title: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=300)
    #: ELI-46: the whole list, replacing the stored one; the primary lands in
    #: `phone`. Send either this or `phone`, not both.
    phones: list[ManagerPhoneIn] | None = Field(default=None, max_length=20)
    notes: str | None = None
    status: str | None = None
    #: ELI-66: every field of a lead is editable — the name, the company
    #: (one of this workspace's own, checked in the service), XING and the
    #: address join the contact details above.
    company_id: uuid.UUID | None = None
    xing_url: str | None = Field(default=None, max_length=300)
    street: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, max_length=20)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)

    @field_validator("full_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        # Runs only when the field is sent: an explicit null or a blank is
        # refused (422) rather than reaching the NOT NULL column as a 500.
        if value is None or not value.strip():
            raise ValueError("a name is required")
        return value.strip()

    @field_validator("company_id")
    @classmethod
    def _company(cls, value: uuid.UUID | None) -> uuid.UUID | None:
        if value is None:
            raise ValueError("a contact always belongs to a company")
        return value

    @field_validator("phones")
    @classmethod
    def _phones(cls, value: list[ManagerPhoneIn] | None) -> list[ManagerPhoneIn] | None:
        return _phone_list(value)

    @model_validator(mode="after")
    def _phone_or_phones(self) -> "ManagerUpdate":
        if "phone" in self.model_fields_set and "phones" in self.model_fields_set:
            raise ValueError("send phone or phones, not both")
        return self


#: ELI-66: why a lead was removed — a code, never the words.
REMOVE_REASONS = ("agency", "not_relevant", "other")


class ManagerRemove(BaseModel):
    """ELI-66 "Entfernen": Personalberatung · Nicht interessant · Sonstiges."""

    reason: Literal["agency", "not_relevant", "other"]
    note: str | None = Field(default=None, max_length=500)


class ManagerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    full_name: str
    first_name: str | None
    last_name: str | None
    role_title: str | None
    department: str | None
    email: str | None
    phone: str | None
    #: ELI-46: every number, the primary (= `phone`) first.
    phones: list[ManagerPhoneRead] = Field(default_factory=list)
    linkedin_url: str | None
    xing_url: str | None = None
    facebook_url: str | None = None
    source: str
    source_detail: str | None
    art14_notified_at: dt.datetime | None
    #: Derived on the model, surfaced here so a recruiter can see the obligation
    #: rather than having to infer it from two other columns.
    art14_outstanding: bool
    notes: str | None
    status: str
    #: "bus_dev" | "manager" (ELI-23).
    stage: str = "manager"
    promoted_at: dt.datetime | None = None
    #: ELI-32: marked "Nicht mehr kontaktieren", and why (a code).
    do_not_contact_at: dt.datetime | None = None
    do_not_contact_reason: str | None = None
    #: ELI-60: "Kein Interesse" since — off the Leads list, record kept.
    no_interest_at: dt.datetime | None = None
    #: ELI-66: removed by hand — why (`agency` · `not_relevant` · `other`).
    removed_reason: str | None = None
    removed_note: str | None = None
    created_at: dt.datetime

    # --- detail, from the source's own profile ----------------------------
    #: "MNGR197" — the reference a recruiter reads out on a call.
    external_code: str | None = None
    street: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    #: What the person is open to — "Looks for: Contract".
    looks_for: str | None = None
    skills: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    #: From the source, not derived from `interactions` — it knows about contact
    #: that predates anything imported here.
    last_contact_at: dt.datetime | None = None

    #: Facts ABOUT the row rather than columns on it — how much work and how
    #: much relationship sits behind this contact. Present only on the single
    #: -manager read; the list does not pay for them.
    #: How many contacts in this workspace share this e-mail address. 1 means
    #: unique. Flagged rather than merged: the source really does hold two
    #: records, and picking a winner is the reader's call, not the importer's.
    duplicate_count: int = 1

    job_count: int = 0
    open_job_count: int = 0
    note_count: int = 0
