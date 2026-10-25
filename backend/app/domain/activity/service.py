"""Counting what happened, and comparing it to what was asked.

No business logic lives in the router; nothing here imports FastAPI.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.activity import kpis as kpi_defs
from app.domain.activity.models import ActivityEvent, ActivityTarget

logger = get_logger(__name__)


async def record(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_type: str,
    occurred_at: dt.datetime,
    ref_type: str,
    ref_id: uuid.UUID,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
) -> None:
    """Note that something countable happened. Idempotent per (type, ref)."""
    if event_type not in kpi_defs.EVENT_TYPES:
        raise ValueError(f"unknown event type {event_type}")

    existing = await session.scalar(
        select(ActivityEvent).where(
            ActivityEvent.tenant_id == tenant_id,
            ActivityEvent.event_type == event_type,
            ActivityEvent.ref_id == ref_id,
        )
    )
    if existing is not None:
        # Editing a note moves WHEN it happened — a call corrected from
        # Friday to Monday belongs in the other week — but never who it
        # belongs to: the first author keeps it, or nobody does.
        existing.occurred_at = occurred_at
        if existing.actor_user_id is None and actor_user_id is not None:
            existing.actor_user_id = actor_user_id
            existing.actor_name = actor_name
        return

    session.add(
        ActivityEvent(
            tenant_id=tenant_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_name=actor_name,
            occurred_at=occurred_at,
            ref_type=ref_type,
            ref_id=ref_id,
        )
    )


async def record_safely(session: AsyncSession, **kwargs) -> None:
    """`record`, with the guarantee that it cannot break the caller.

    The write paths that call this have already done the thing that matters
    — the note is saved, the step is ticked. Losing a KPI row is a wrong
    number on a dashboard; raising here would lose the recruiter's work.
    """
    try:
        await record(session, **kwargs)
    except Exception as exc:  # pragma: no cover - defensive by design
        logger.warning("activity event not recorded: %s", exc)


async def forget(
    session: AsyncSession, *, tenant_id: uuid.UUID, event_type: str, ref_id: uuid.UUID
) -> None:
    """Undo: the step was un-ticked, so it did not happen after all."""
    await session.execute(
        delete(ActivityEvent).where(
            ActivityEvent.tenant_id == tenant_id,
            ActivityEvent.event_type == event_type,
            ActivityEvent.ref_id == ref_id,
        )
    )


async def count(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_type: str,
    start: dt.datetime,
    end: dt.datetime,
    actor_user_id: str | None = None,
    everyone: bool = True,
) -> int:
    """How many of these happened in [start, end).

    `everyone=True` counts the workspace. With `everyone=False` the count is
    for one consultant — and `actor_user_id=None` then means the events
    nobody is recorded for, which is a real bucket worth being able to see.
    """
    query = select(func.count()).where(
        ActivityEvent.tenant_id == tenant_id,
        ActivityEvent.event_type == event_type,
        ActivityEvent.occurred_at >= start,
        ActivityEvent.occurred_at < end,
    )
    if not everyone:
        query = query.where(ActivityEvent.actor_user_id == actor_user_id)
    return int(await session.scalar(query) or 0)


async def targets(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[ActivityTarget]:
    rows = await session.execute(
        select(ActivityTarget).where(ActivityTarget.tenant_id == tenant_id)
    )
    return list(rows.scalars().all())


async def set_target(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    kpi: str,
    period: str,
    value: int,
    actor_user_id: str | None = None,
) -> ActivityTarget:
    if kpi not in kpi_defs.BY_KEY:
        raise ValueError(f"unknown kpi {kpi}")
    if period not in kpi_defs.PERIODS:
        raise ValueError(f"unknown period {period}")

    row = await session.scalar(
        select(ActivityTarget).where(
            ActivityTarget.tenant_id == tenant_id,
            ActivityTarget.actor_user_id.is_(None)
            if actor_user_id is None
            else ActivityTarget.actor_user_id == actor_user_id,
            ActivityTarget.kpi == kpi,
            ActivityTarget.period == period,
        )
    )
    if row is None:
        row = ActivityTarget(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            kpi=kpi,
            period=period,
            value=value,
        )
        session.add(row)
    else:
        row.value = value
    await session.commit()
    await session.refresh(row)
    return row


def _target_for(
    rows: list[ActivityTarget], *, kpi: str, period: str, actor_user_id: str | None
) -> int | None:
    """One consultant's number, or the workspace default they inherit.

    Their own row wins. Nothing at all returns None rather than 0: "no
    target" and "a target of zero" are different statements, and showing
    0/0 as achieved would be a lie about a KPI nobody has set yet.
    """
    own = next(
        (
            r.value
            for r in rows
            if r.kpi == kpi and r.period == period and r.actor_user_id == actor_user_id
        ),
        None,
    )
    if own is not None:
        return own
    if actor_user_id is None:
        return None
    return next(
        (
            r.value
            for r in rows
            if r.kpi == kpi and r.period == period and r.actor_user_id is None
        ),
        None,
    )


async def tracking(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    period: str,
    at: dt.datetime | None = None,
    actor_user_id: str | None = None,
    everyone: bool = True,
) -> dict:
    """The whole instrument panel for one period and one consultant."""
    start, end = kpi_defs.window(period, at or dt.datetime.now(dt.UTC))
    configured = await targets(session, tenant_id=tenant_id)

    out = []
    for kpi in kpi_defs.KPIS:
        ist = (
            await count(
                session,
                tenant_id=tenant_id,
                event_type=kpi.event_type,
                start=start,
                end=end,
                actor_user_id=actor_user_id,
                everyone=everyone,
            )
            if kpi.available and kpi.event_type
            else None
        )
        out.append(
            {
                "key": kpi.key,
                "label": kpi.label,
                "source": kpi.source,
                "ist": ist,
                "ziel": _target_for(
                    configured,
                    kpi=kpi.key,
                    period=period,
                    actor_user_id=None if everyone else actor_user_id,
                ),
                "available": kpi.available,
                "unavailable_because": kpi.unavailable_because,
            }
        )

    return {
        "period": period,
        "period_start": start,
        "period_end": end,
        "actor_user_id": None if everyone else actor_user_id,
        "kpis": out,
    }


async def consultants(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[dict]:
    """Who shows up in the record at all, most active first."""
    rows = await session.execute(
        select(
            ActivityEvent.actor_user_id,
            func.max(ActivityEvent.actor_name),
            func.count().label("events"),
        )
        .where(ActivityEvent.tenant_id == tenant_id)
        .group_by(ActivityEvent.actor_user_id)
        .order_by(func.count().desc())
    )
    return [
        {
            "actor_user_id": user_id,
            # Imported history and anything written before this existed has
            # no author. Naming the bucket beats hiding it: those events are
            # in the workspace total and would otherwise look lost.
            "name": name or ("Nicht zugeordnet" if user_id is None else user_id),
            "events": int(events),
        }
        for user_id, name, events in rows.all()
    ]
