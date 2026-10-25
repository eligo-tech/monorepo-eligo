"""Counting what happened, and comparing it to what was asked (ELI-15).

Every count here is a query over the row that ALREADY records the fact — a
manager note, a process step. Nothing is copied into a second table, so
there is nothing that can disagree with the record: delete the note and the
call is gone from the KPI by construction, not by a cleanup somebody has to
remember to write.

No FastAPI imports; the router validates and calls this.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.activity import kpis as kpi_defs
from app.domain.activity.models import ActivityTarget
from app.domain.managers.models import ManagerInteraction
from app.domain.pipeline.models import ProcessStep


def _manager_calls(tenant_id: uuid.UUID, start: dt.datetime, end: dt.datetime) -> Select:
    """Calls WITH A MANAGER in the window.

    `manager_id IS NOT NULL` because a briefing note can be filed against a
    mandate with no contact yet, and that is not a call with anybody.
    `candidate_call` is a different conversation and `na` is a call that did
    not connect — the same rule `isContact` applies to "letzter Kontakt".
    """
    return select(ManagerInteraction).where(
        ManagerInteraction.tenant_id == tenant_id,
        ManagerInteraction.manager_id.isnot(None),
        ManagerInteraction.interaction_type.in_(kpi_defs.MANAGER_CALL_KINDS),
        ManagerInteraction.occurred_at >= start,
        ManagerInteraction.occurred_at < end,
    )


def _presentations(tenant_id: uuid.UUID, start: dt.datetime, end: dt.datetime) -> Select:
    """Candidates put in front of a client in the window.

    "Reached" is counted exactly the way `derive_stage` counts it — a done
    date, a booked date, or a green cell — so this number and the board can
    never tell different stories. The date is the one the recruiter
    recorded, not the row's mtime: a presentation entered on Monday for last
    Thursday belongs in last week.
    """
    when = func.coalesce(ProcessStep.done_at, ProcessStep.scheduled_at)
    return select(ProcessStep).where(
        ProcessStep.tenant_id == tenant_id,
        ProcessStep.step_key == kpi_defs.PRESENTED_STEP,
        ProcessStep.active.is_(True),
        or_(
            ProcessStep.done_at.isnot(None),
            ProcessStep.scheduled_at.isnot(None),
            ProcessStep.outcome == "pass",
        ),
        and_(when >= start, when < end),
    )


#: KPI key → (query builder, the model's author column).
_SOURCES = {
    kpi_defs.MANAGER_CALL: (_manager_calls, ManagerInteraction.actor_user_id),
    kpi_defs.CANDIDATE_PRESENTED: (_presentations, ProcessStep.actor_user_id),
}


async def count(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    counts: str,
    start: dt.datetime,
    end: dt.datetime,
    actor_user_id: str | None = None,
    everyone: bool = True,
) -> int:
    """How many happened in [start, end).

    `everyone=True` counts the workspace. With `everyone=False` the count is
    for one consultant — and `actor_user_id=None` then means the rows nobody
    is recorded for, which is a real bucket worth being able to look at.
    """
    build, author = _SOURCES[counts]
    query = build(tenant_id, start, end)
    if not everyone:
        query = query.where(
            author.is_(None) if actor_user_id is None else author == actor_user_id
        )
    total = await session.scalar(
        select(func.count()).select_from(query.subquery())
    )
    return int(total or 0)


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
                counts=kpi.counts,
                start=start,
                end=end,
                actor_user_id=actor_user_id,
                everyone=everyone,
            )
            if kpi.available and kpi.counts
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
    """Who shows up in the record at all, busiest first.

    Read from the source tables, so somebody who has only ever ticked a
    process step still appears. There is no users table to list instead —
    membership lives in Clerk, and asking it per render is not worth it.
    """
    tallies: dict[str | None, dict] = {}
    for model in (ManagerInteraction, ProcessStep):
        rows = await session.execute(
            select(
                model.actor_user_id,
                func.max(model.actor_name),
                func.count(),
            )
            .where(model.tenant_id == tenant_id)
            .group_by(model.actor_user_id)
        )
        for user_id, name, total in rows.all():
            seen = tallies.setdefault(
                user_id, {"actor_user_id": user_id, "name": None, "events": 0}
            )
            seen["name"] = seen["name"] or name
            seen["events"] += int(total)

    return sorted(
        (
            {
                "actor_user_id": row["actor_user_id"],
                # The unattributed bucket is named in the UI, which knows the
                # viewer's language; the API just says it has no author.
                "name": row["name"] or (row["actor_user_id"] or ""),
                "events": row["events"],
            }
            for row in tallies.values()
        ),
        key=lambda r: -r["events"],
    )
