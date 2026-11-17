"""Wiedervorlagen API (ELI-44) — thin. Validates, calls the service, maps
errors to HTTP."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_admin_to_delete
from app.core.database import get_db
from app.domain.followups import service
from app.domain.followups.schemas import (
    DateSuggestionRead,
    FollowUpCreate,
    FollowUpRead,
    FollowUpUpdate,
    SuggestRequest,
    SuggestResponse,
)

router = APIRouter(prefix="/follow-ups", tags=["follow-ups"])


@router.get("", response_model=list[FollowUpRead])
async def list_follow_ups(
    status_: Literal["open", "done", "all"] = Query(default="open", alias="status"),
    manager_id: uuid.UUID | None = Query(default=None),
    candidate_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=service.LIST_LIMIT, ge=1, le=service.LIST_LIMIT),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[FollowUpRead]:
    """This workspace's follow-ups — by default the open ones, soonest first."""
    rows = await service.list_follow_ups(
        db, tenant_id=actor.tenant_id, status=status_, manager_id=manager_id, candidate_id=candidate_id, limit=limit
    )
    return [FollowUpRead(**r) for r in rows]


@router.post("/suggest", response_model=SuggestResponse)
async def suggest(payload: SuggestRequest, actor: Actor = Depends(get_current_actor)) -> SuggestResponse:
    """The follow-up dates a note names, for the UI to OFFER. Writes nothing."""
    found = service.suggest(payload.text, payload.reference_date)
    return SuggestResponse(suggestions=[DateSuggestionRead(due_date=s.due_date, phrase=s.phrase) for s in found])


@router.post("", response_model=FollowUpRead, status_code=status.HTTP_201_CREATED)
async def create_follow_up(
    payload: FollowUpCreate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> FollowUpRead:
    try:
        row = await service.create(
            db, tenant_id=actor.tenant_id, payload=payload, actor_user_id=actor.user_id, actor_name=actor.name
        )
    except service.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{exc} not found") from exc
    return FollowUpRead(**row)


@router.patch("/{follow_up_id}", response_model=FollowUpRead)
async def update_follow_up(
    follow_up_id: uuid.UUID,
    payload: FollowUpUpdate,
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> FollowUpRead:
    """Move, edit, mark done (`status: done`) or reopen."""
    try:
        row = await service.update(
            db, tenant_id=actor.tenant_id, follow_up_id=follow_up_id, payload=payload,
            actor_user_id=actor.user_id, actor_name=actor.name,
        )
    except service.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "follow-up not found") from exc
    return FollowUpRead(**row)


@router.delete("/{follow_up_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_follow_up(
    follow_up_id: uuid.UUID,
    actor: Actor = Depends(require_admin_to_delete),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """ELI-27: deleting is an admin's job. Everyone else closes a follow-up
    with "Erledigt", which keeps it on the record."""
    try:
        await service.delete(db, tenant_id=actor.tenant_id, follow_up_id=follow_up_id)
    except service.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "follow-up not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
