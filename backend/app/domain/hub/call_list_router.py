"""Routes of the call list (ELI-22) — see `hub/call_list.py`.

Workspace routes (a recruiter's session), not operator routes: they read the
shared ad contacts and write only this tenant's companies, managers and
contact history.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, get_current_tenant
from app.core.database import get_db
from app.domain.common.enums import CallOutcome
from app.domain.hub import call_list

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
    last_outcome: str | None
    last_call_at: dt.datetime | None
    last_call_by: str | None
    next_action_at: dt.datetime | None
    due: bool


class CompanyFacet(BaseModel):
    company_id: uuid.UUID
    name: str
    contacts: int


class ContactPage(BaseModel):
    rows: list[ContactRow]
    total: int
    truncated: bool
    companies: list[CompanyFacet]


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
    limit: int = Query(default=500, ge=1, le=1000),
    tenant_id: uuid.UUID = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> ContactPage:
    """"Kontakte": every contact in this workspace, newest first (ELI-23)."""
    return ContactPage(**await call_list.contacts(
        db, tenant_id=tenant_id, company_id=company_id, q=q, due_only=due_only, limit=limit))


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
