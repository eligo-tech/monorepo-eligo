"""Routes of the call list (ELI-22) — see `hub/call_list.py`.

Workspace routes (a recruiter's session), not operator routes: they read the
shared ad contacts and write only this tenant's companies, managers and
contact history.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, get_current_tenant
from app.core.database import get_db
from app.domain.common.enums import CallOutcome
from app.domain.hub import call_list
from app.domain.hub.schemas import Switchboard

router = APIRouter(prefix="/hub/call-list", tags=["hub"])


class MarketRow(BaseModel):
    hub_company_id: uuid.UUID
    person_key: str
    company_name: str
    full_name: str
    first_name: str | None
    last_name: str
    salutation: str | None
    role_title: str | None
    phone: str | None
    phone_kind: str | None
    email: str | None
    open_ads: int
    posting_title: str
    quote: str
    source_url: str | None
    #: "named_phone" | "named" — the status box on the list.
    reach: str


class MarketPage(BaseModel):
    rows: list[MarketRow]
    has_more: bool
    offset: int
    limit: int


class FollowUpRow(BaseModel):
    manager_id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    full_name: str
    last_name: str
    role_title: str | None
    phone: str | None
    email: str | None
    outcome: str
    summary: str | None
    last_call_at: dt.datetime | None
    last_call_by: str | None
    next_action_at: dt.datetime | None
    due: bool


class LeadJob(BaseModel):
    """ELI-37: a concrete job the lead is connected to — an ad naming them
    (`posting_id`, `url`), this workspace's job taken from it or owned by
    them (`job_id`), or both."""

    title: str
    location: str | None
    url: str | None
    posting_id: uuid.UUID | None
    job_id: uuid.UUID | None


class ContactRow(BaseModel):
    manager_id: uuid.UUID
    company_id: uuid.UUID
    company_name: str
    full_name: str
    role_title: str | None
    phone: str | None
    email: str | None
    linkedin_url: str | None
    xing_url: str | None = None
    added_at: dt.datetime | None
    source: str
    source_detail: str | None
    art14_outstanding: bool
    #: ELI-32: marked "Nicht mehr kontaktieren" — shown, never due.
    do_not_contact_at: dt.datetime | None = None
    #: ELI-60: "Kein Interesse" since — only under the filter.
    no_interest_at: dt.datetime | None = None
    #: ELI-66: removed by hand — why (a code); NULL = "Kein Interesse" by call.
    removed_reason: str | None = None
    last_outcome: str | None
    last_call_at: dt.datetime | None
    last_call_by: str | None
    next_action_at: dt.datetime | None
    due: bool
    jobs: list[LeadJob] = Field(default_factory=list)
    #: ELI-62: rows of the contact history, and when the latest happened.
    note_count: int = 0
    last_note_at: dt.datetime | None = None
    #: A history row or a free-text note — "Mit Notizen".
    has_notes: bool = False


class CompanyFacet(BaseModel):
    company_id: uuid.UUID
    name: str
    contacts: int
    #: ELI-30: the company's switchboard from its own Impressum, if verified.
    switchboard: Switchboard | None = None


class NoteCounts(BaseModel):
    all: int
    none: int
    with_: int = Field(alias="with", serialization_alias="with")

    model_config = {"populate_by_name": True}


class ContactPage(BaseModel):
    rows: list[ContactRow]
    total: int
    truncated: bool
    #: ELI-62: leads per notes chip, under the other filters.
    note_counts: NoteCounts
    companies: list[CompanyFacet]
    #: ELI-60: leads hidden as "Kein Interesse" (for the filter chip).
    no_interest_total: int = 0


class CallIn(BaseModel):
    hub_company_id: uuid.UUID
    person_key: str = Field(min_length=1, max_length=120)
    outcome: CallOutcome
    summary: str | None = None
    next_action_at: dt.datetime | None = None


class CallOut(BaseModel):
    manager_id: uuid.UUID
    company_id: uuid.UUID
    interaction_id: uuid.UUID | None
    created_manager: bool
    art14_outstanding: bool


@router.get("/market", response_model=MarketPage)
async def market(
    q: str | None = Query(default=None, max_length=120),
    phone_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> MarketPage:
    """"Anrufen": persons open ads name that this workspace has not called."""
    return MarketPage(**await call_list.market(db, tenant_id=tenant_id, q=q, phone_only=phone_only, limit=limit, offset=offset))


@router.get("/contacts", response_model=ContactPage)
async def contacts(
    company_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=120),
    due_only: bool = False,
    notes: Literal["none", "with"] | None = Query(default=None, description="ELI-62: none | with"),
    no_interest: bool = Query(default=False, description='ELI-60: only the leads with "Kein Interesse"'),
    limit: int = Query(default=500, ge=1, le=1000),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ContactPage:
    """"Kontakte": every contact in this workspace — open call-backs first (ELI-38), then newest first (ELI-23)."""
    return ContactPage(**await call_list.contacts(
        db, tenant_id=tenant_id, company_id=company_id, q=q, due_only=due_only, notes=notes, no_interest=no_interest, limit=limit))


@router.get("/follow-ups", response_model=list[FollowUpRow])
async def follow_ups(
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[FollowUpRow]:
    """"Wiedervorlage": this workspace's calls, due call-backs first."""
    return [FollowUpRow(**r) for r in await call_list.follow_ups(db, tenant_id=tenant_id)]


@router.post("/calls", response_model=CallOut, status_code=status.HTTP_201_CREATED)
async def log_call(
    payload: CallIn,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> CallOut:
    """One call to a person on the list; the first takes them into the workspace."""
    try:
        result = await call_list.log_call(
            db, tenant_id=actor.tenant_id, hub_company_id=payload.hub_company_id,
            person_key=payload.person_key, outcome=payload.outcome.value, summary=payload.summary,
            next_action_at=payload.next_action_at, actor_user_id=actor.user_id, actor_name=actor.name,
        )
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.errors()[0]["msg"]) from exc
    except call_list.NotOnTheList as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no open ad of this employer names that person") from exc
    except call_list.Erased as exc:
        # Same answer as adding an erased contact by hand: the person asked to
        # be forgotten here; the recruiter is told, not the reason's details.
        raise HTTPException(status.HTTP_409_CONFLICT, "this workspace erased this person") from exc
    return CallOut(**result)
