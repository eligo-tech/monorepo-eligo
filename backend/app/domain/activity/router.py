"""Activity tracking API (ELI-15). Thin: it validates and calls the service."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import Actor, get_current_actor, require_admin
from app.core.database import get_db
from app.domain.activity import service
from app.domain.activity.kpis import PERIODS
from app.domain.activity.schemas import (
    ConsultantRead,
    TargetRead,
    TargetWrite,
    TrackingRead,
)

router = APIRouter(prefix="/activity", tags=["activity"])

#: What the per-consultant switch sends for "the whole workspace". A literal
#: rather than an absent parameter, because absent would be indistinguishable
#: from "the events nobody is recorded for" — which is its own real bucket.
TEAM = "team"


@router.get("/tracking", response_model=TrackingRead)
async def tracking(
    period: str = Query(default="monat"),
    who: str = Query(
        default=TEAM,
        description='"team", "unassigned", or a Clerk user id.',
    ),
    at: dt.datetime | None = Query(
        default=None, description="A moment inside the period. Defaults to now."
    ),
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> TrackingRead:
    """Ist vs. Ziel for one period, for the workspace or one consultant."""
    if period not in PERIODS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"unbekannter Zeitraum {period} — erwartet: {', '.join(PERIODS)}",
        )
    return TrackingRead(
        **await service.tracking(
            db,
            tenant_id=actor.tenant_id,
            period=period,
            at=at,
            everyone=who == TEAM,
            actor_user_id=None if who in (TEAM, "unassigned") else who,
        )
    )


@router.get("/consultants", response_model=list[ConsultantRead])
async def consultants(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[ConsultantRead]:
    """Who the switch can switch to — derived from the record, not a roster.

    There is no users table; membership lives in Clerk. Listing who actually
    has activity means the switch can never offer somebody with nothing to
    show, and it costs no identity-provider call.
    """
    return [
        ConsultantRead(**row)
        for row in await service.consultants(db, tenant_id=actor.tenant_id)
    ]


@router.get("/targets", response_model=list[TargetRead])
async def list_targets(
    actor: Actor = Depends(get_current_actor),
    db: AsyncSession = Depends(get_db),
) -> list[TargetRead]:
    return [
        TargetRead.model_validate(row)
        for row in await service.targets(db, tenant_id=actor.tenant_id)
    ]


@router.put("/targets", response_model=TargetRead)
async def set_target(
    payload: TargetWrite,
    actor: Actor = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> TargetRead:
    """Set a goal. Admin only — a target somebody can set for themselves is
    not a target, and the ticket asks for it the other way round: *"wir als
    Admins [legen] unsere Ziele selbst fest"*."""
    try:
        row = await service.set_target(
            db,
            tenant_id=actor.tenant_id,
            kpi=payload.kpi,
            period=payload.period,
            value=payload.value,
            actor_user_id=payload.actor_user_id,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return TargetRead.model_validate(row)
