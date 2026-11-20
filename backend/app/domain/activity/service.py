"""Counting what happened, and comparing it to what was asked (ELI-15, ELI-64).

Every count here is a query over the row that ALREADY records the fact — a
manager note, a process step, a lead, a mandate, the fee on a closed deal,
the date on a company's framework contract. Nothing is copied into a second
table, so there is nothing that can disagree with the record: delete the
note and the call is gone from the KPI by construction, not by a cleanup
somebody has to remember to write.

No FastAPI imports; the router validates and calls this.
"""

from __future__ import annotations

import datetime as dt
import statistics
import uuid
from collections.abc import Callable

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.activity import kpis as kpi_defs
from app.domain.activity.models import ActivityTarget, TrackingPreference
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.pipeline.models import Application, ProcessStep


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite hands back naive datetimes for a timezone-aware column."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=dt.UTC)


def _notes(
    tenant_id: uuid.UUID,
    start: dt.datetime,
    end: dt.datetime,
    spellings: tuple[str, ...],
) -> Select:
    """Notes on a manager or lead, of the given kinds, in the window.

    `manager_id IS NOT NULL` because a briefing note can be filed against a
    mandate with no contact yet, and that is not contact with anybody.
    """
    return select(ManagerInteraction).where(
        ManagerInteraction.tenant_id == tenant_id,
        ManagerInteraction.manager_id.isnot(None),
        # Lowercased on both sides: the column holds the source's own
        # capitalisation ("BD Call") alongside the canonical value, and
        # `normalise_interaction_type` lowercases before it maps.
        func.lower(ManagerInteraction.interaction_type).in_(
            [k.lower() for k in spellings]
        ),
        ManagerInteraction.occurred_at >= start,
        ManagerInteraction.occurred_at < end,
    )


def _manager_calls(tenant_id: uuid.UUID, start: dt.datetime, end: dt.datetime) -> Select:
    """ELI-64 "Business Call oder Meeting": calls and meetings WITH A MANAGER.

    `candidate_call` is a different conversation and `na` is a call that did
    not connect — the same rule `isContact` applies to "letzter Kontakt".
    """
    return _notes(tenant_id, start, end, kpi_defs.call_or_meeting_spellings())


def _contact_points(tenant_id: uuid.UUID, start: dt.datetime, end: dt.datetime) -> Select:
    """ELI-64 "Kontaktpunkte mit Leads oder Managern": every note that means
    the person was reached (leads are managers with stage bus_dev)."""
    return _notes(tenant_id, start, end, kpi_defs.contact_spellings())


def _reached(step=ProcessStep):  # noqa: ANN001, ANN202 — a mapped class
    """A step counts as reached exactly the way `derive_stage` counts it — a
    done date, a booked date, or a green cell — so this number and the board
    can never tell different stories."""
    return or_(
        step.done_at.isnot(None),
        step.scheduled_at.isnot(None),
        step.outcome == "pass",
    )


def _presentations(tenant_id: uuid.UUID, start: dt.datetime, end: dt.datetime) -> Select:
    """Candidates put in front of a client in the window.

    The date is the one the recruiter recorded, not the row's mtime: a
    presentation entered on Monday for last Thursday belongs in last week.
    """
    when = func.coalesce(ProcessStep.done_at, ProcessStep.scheduled_at)
    return select(ProcessStep).where(
        ProcessStep.tenant_id == tenant_id,
        ProcessStep.step_key == kpi_defs.PRESENTED_STEP,
        ProcessStep.active.is_(True),
        _reached(),
        and_(when >= start, when < end),
    )


def _deals(tenant_id: uuid.UUID, start: dt.datetime, end: dt.datetime) -> Select:
    """ELI-64 Umsatz: the fee of every deal whose Vertrag date is in the window.

    Attributed to whoever recorded the Vertrag step — the consultant who
    closed it. One row per application: `uq_process_step` allows one
    Vertrag step per process, so a fee can never be added twice.

    A contract only PLANNED for a later day is a forecast, not revenue: it
    counts once it is done, marked green, or its date has passed.
    """
    when = func.coalesce(ProcessStep.done_at, ProcessStep.scheduled_at)
    signed = or_(
        ProcessStep.done_at.isnot(None),
        ProcessStep.outcome == "pass",
        ProcessStep.scheduled_at <= dt.datetime.now(dt.UTC),
    )
    return (
        select(Application.fee_eur.label("fee"), ProcessStep.actor_user_id)
        .select_from(ProcessStep)
        .join(
            Application,
            and_(
                Application.id == ProcessStep.application_id,
                Application.tenant_id == ProcessStep.tenant_id,
            ),
        )
        .where(
            ProcessStep.tenant_id == tenant_id,
            ProcessStep.step_key == kpi_defs.DEAL_STEP,
            ProcessStep.active.is_(True),
            ProcessStep.outcome != "out",
            signed,
            and_(when >= start, when < end),
        )
    )


def _leads(tenant_id: uuid.UUID, start: dt.datetime, end: dt.datetime) -> Select:
    """ELI-64 "Leads hinzugefügt": contacts created as leads in the window.

    A lead is a `managers` row with stage `bus_dev` — taken from Markt or
    entered by hand. One promoted to Manager since (`promoted_at`) was
    still ADDED as a lead, so it keeps counting in the period it came in.
    A manager entered as a manager (or imported) never was a lead.
    """
    return select(Manager).where(
        Manager.tenant_id == tenant_id,
        or_(Manager.stage == "bus_dev", Manager.promoted_at.isnot(None)),
        Manager.created_at >= start,
        Manager.created_at < end,
    )


def _framework_contracts(tenant_id: uuid.UUID, start: dt.datetime, end: dt.datetime) -> Select:
    """ELI-64 "Rahmenvertrag abgeschlossen": the date a person set on the
    company page. A day, not an instant — compared as dates."""
    return select(Company).where(
        Company.tenant_id == tenant_id,
        Company.framework_contract_on.isnot(None),
        Company.framework_contract_on >= start.date(),
        Company.framework_contract_on < end.date(),
    )


def _mandates(tenant_id: uuid.UUID, start: dt.datetime, end: dt.datetime) -> Select:
    """ELI-64 "Mandat hinzugefügt": mandates created in this workspace.

    Imports are not "added": a re-run of the aiFind import would otherwise
    book every historic mandate into the week it ran. A mandate taken from
    Markt (`external_source = "hub"`) IS ours — but only once it is no longer
    a lead. There is no "won at" date, so it counts in the period it was
    taken from Markt.
    """
    from app.domain.common.enums import JobStatus

    return select(Job).where(
        Job.tenant_id == tenant_id,
        or_(Job.external_id.is_(None), Job.external_source == "hub"),
        Job.status != JobStatus.LEAD.value,
        Job.created_at >= start,
        Job.created_at < end,
    )


#: KPI key → (query builder, the row's author column).
_SOURCES: dict[str, tuple[Callable[..., Select], object]] = {
    kpi_defs.MANAGER_CALL: (_manager_calls, ManagerInteraction.actor_user_id),
    kpi_defs.CONTACT_POINT: (_contact_points, ManagerInteraction.actor_user_id),
    kpi_defs.CANDIDATE_PRESENTED: (_presentations, ProcessStep.actor_user_id),
    kpi_defs.REVENUE: (_deals, ProcessStep.actor_user_id),
    kpi_defs.LEAD_ADDED: (_leads, Manager.created_by_user_id),
    kpi_defs.FRAMEWORK_CONTRACT: (_framework_contracts, Company.framework_contract_by),
    kpi_defs.MANDATE_ADDED: (_mandates, Job.created_by_user_id),
}


def _scoped(
    query: Select,
    author,  # noqa: ANN001 — an InstrumentedAttribute
    *,
    everyone: bool,
    actor_user_id: str | None,
    members: list[str] | None,
) -> Select:
    if members:
        return query.where(author.in_(members))
    if everyone:
        return query
    return query.where(
        author.is_(None) if actor_user_id is None else author == actor_user_id
    )


async def count(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    counts: str,
    start: dt.datetime,
    end: dt.datetime,
    actor_user_id: str | None = None,
    everyone: bool = True,
    members: list[str] | None = None,
) -> int:
    """How many happened in [start, end) — or, for Umsatz, how many euros.

    `everyone=True` counts the workspace. With `everyone=False` the count is
    for one consultant — and `actor_user_id=None` then means the rows nobody
    is recorded for, which is a real bucket worth being able to look at.
    `members` counts a group: a shared goal's people, together.
    """
    build, author = _SOURCES[counts]
    query = _scoped(
        build(tenant_id, start, end),
        author,
        everyone=everyone,
        actor_user_id=actor_user_id,
        members=members,
    )
    sub = query.subquery()
    if counts == kpi_defs.REVENUE:
        total = await session.scalar(select(func.coalesce(func.sum(sub.c.fee), 0)))
    else:
        total = await session.scalar(select(func.count()).select_from(sub))
    return int(total or 0)


async def deals_without_fee(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: dt.datetime,
    end: dt.datetime,
    actor_user_id: str | None = None,
    everyone: bool = True,
) -> int:
    """Closed deals in the window with no Honorar entered — said next to the
    Umsatz so a missing fee reads as missing, not as a smaller month."""
    query = _scoped(
        _deals(tenant_id, start, end).where(Application.fee_eur.is_(None)),
        ProcessStep.actor_user_id,
        everyone=everyone,
        actor_user_id=actor_user_id,
        members=None,
    )
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    return int(total or 0)


# ── goals ─────────────────────────────────────────────────────────────────


async def targets(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[ActivityTarget]:
    rows = await session.execute(
        select(ActivityTarget)
        .where(ActivityTarget.tenant_id == tenant_id)
        .order_by(ActivityTarget.created_at)
    )
    return list(rows.scalars().all())


def _members(row: ActivityTarget) -> list[str]:
    return list(row.members or [])


async def set_target(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    kpi: str,
    period: str,
    value: int,
    actor_user_id: str | None = None,
    members: list[str] | None = None,
    label: str | None = None,
    valid_from: dt.date | None = None,
) -> ActivityTarget:
    """Set one goal: the workspace default, one consultant's, or a group's.

    Saving again with the same identity — (kpi, period) plus the same
    consultant or the same group, in any order — updates the goal rather
    than adding a second one that would have to be reconciled with it.
    """
    if kpi not in kpi_defs.BY_KEY:
        raise ValueError(f"unknown kpi {kpi}")
    if period not in kpi_defs.PERIODS:
        raise ValueError(f"unknown period {period}")
    group = sorted({m.strip() for m in (members or []) if m and m.strip()})
    if group and actor_user_id is not None:
        raise ValueError("a goal is either one consultant's or a group's")
    if len(group) == 1:
        # A group of one is that person's own goal, and storing it as a
        # group would hide it from their own view.
        raise ValueError("a shared goal needs at least two consultants")
    label = (label or "").strip() or None

    rows = [
        r
        for r in await targets(session, tenant_id=tenant_id)
        if r.kpi == kpi and r.period == period
    ]
    if group:
        row = next((r for r in rows if sorted(_members(r)) == group), None)
    else:
        row = next(
            (
                r
                for r in rows
                if not _members(r) and r.actor_user_id == actor_user_id
            ),
            None,
        )
    if row is None:
        row = ActivityTarget(
            tenant_id=tenant_id,
            actor_user_id=None if group else actor_user_id,
            kpi=kpi,
            period=period,
            value=value,
            members=group,
            label=label,
            valid_from=valid_from,
        )
        session.add(row)
    else:
        row.value = value
        row.label = label
        row.valid_from = valid_from
    await session.commit()
    await session.refresh(row)
    return row


async def delete_target(
    session: AsyncSession, *, tenant_id: uuid.UUID, target_id: uuid.UUID
) -> bool:
    row = await session.scalar(
        select(ActivityTarget).where(
            ActivityTarget.tenant_id == tenant_id, ActivityTarget.id == target_id
        )
    )
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


def _applies(row: ActivityTarget, end: dt.datetime) -> bool:
    """A goal with a start date is no goal for a period that ends before it."""
    return row.valid_from is None or row.valid_from < end.date()


def _target_for(
    rows: list[ActivityTarget],
    *,
    kpi: str,
    period: str,
    actor_user_id: str | None,
    end: dt.datetime | None = None,
) -> int | None:
    """One consultant's number, or the workspace default they inherit.

    Their own row wins. Nothing at all returns None rather than 0: "no
    target" and "a target of zero" are different statements, and showing
    0/0 as achieved would be a lie about a KPI nobody has set yet. Shared
    goals are not anybody's own number — they are listed as goals.
    """
    candidates = [
        r for r in rows if r.kpi == kpi and r.period == period and not _members(r)
    ]
    live = lambda r: end is None or _applies(r, end)  # noqa: E731
    own = next((r for r in candidates if r.actor_user_id == actor_user_id), None)
    if own is not None:
        # Their own goal that has not started yet means NO goal — not the
        # default they would inherit if they had none at all.
        return own.value if live(own) else None
    if actor_user_id is None:
        return None
    return next(
        (r.value for r in candidates if r.actor_user_id is None and live(r)), None
    )


# ── the Prozess funnel ────────────────────────────────────────────────────


async def process_funnel(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    start: dt.datetime,
    end: dt.datetime,
    actor_user_id: str | None = None,
    everyone: bool = True,
) -> list[dict]:
    """Ratio and median days for each step from Vorgestellt to Deal.

    A cohort per transition: the processes whose FROM step is dated in the
    period, and of those, how many reached the next step (whenever that
    was). Days are from the from-step's date to the next step's — done,
    else booked, the dates the recruiter entered. Attributed to whoever
    recorded the from-step.

    `of = 0` gives no ratio and no days, never 0 % — a transition nobody
    was in has no rate. Days need both dates, so `median_days` can be blank
    while `reached` is not (a green cell without a date).
    """
    rows = (
        await session.execute(
            select(
                ProcessStep.application_id,
                ProcessStep.step_key,
                ProcessStep.label,
                ProcessStep.done_at,
                ProcessStep.scheduled_at,
                ProcessStep.outcome,
                ProcessStep.actor_user_id,
            ).where(
                ProcessStep.tenant_id == tenant_id,
                ProcessStep.active.is_(True),
                _reached(),
            )
        )
    ).all()

    #: application → milestone → (date or None, author)
    reached: dict[uuid.UUID, dict[str, tuple[dt.datetime | None, str | None]]] = {}
    for app_id, key, label, done, scheduled, outcome, author in rows:
        milestone = kpi_defs.milestone_for(key, label)
        if milestone is None:
            continue
        # A red Vertrag is a deal that did NOT happen (Umsatz skips it too).
        # A red interview still happened — it is the verdict after it.
        if milestone == "deal" and outcome == "out":
            continue
        when = _aware(done or scheduled)
        seen = reached.setdefault(app_id, {})
        prior = seen.get(milestone)
        # Several second rounds: the earliest dated one is the second interview.
        if prior is None or (when is not None and (prior[0] is None or when < prior[0])):
            seen[milestone] = (when, author)

    out = []
    keys = [k for k, _ in kpi_defs.FUNNEL]
    labels = dict(kpi_defs.FUNNEL)
    for a, b in zip(keys, keys[1:], strict=False):
        of = hit = 0
        days: list[float] = []
        for steps in reached.values():
            first = steps.get(a)
            if first is None or first[0] is None or not (start <= first[0] < end):
                continue
            if not everyone and first[1] != actor_user_id:
                continue
            of += 1
            nxt = steps.get(b)
            if nxt is None:
                continue
            hit += 1
            if nxt[0] is not None and nxt[0] >= first[0]:
                days.append((nxt[0] - first[0]).total_seconds() / 86400)
        out.append(
            {
                "from_key": a,
                "to_key": b,
                "from_label": labels[a],
                "to_label": labels[b],
                "of": of,
                "reached": hit,
                "ratio": hit / of if of else None,
                "median_days": round(statistics.median(days), 1) if days else None,
                "source": kpi_defs.FUNNEL_SOURCE,
            }
        )
    return out


# ── the panel ─────────────────────────────────────────────────────────────


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
    scope = {"actor_user_id": actor_user_id, "everyone": everyone}

    out = []
    for kpi in kpi_defs.KPIS:
        measurable = kpi.available and kpi.counts
        ist = (
            await count(
                session, tenant_id=tenant_id, counts=kpi.counts,
                start=start, end=end, **scope,
            )
            if measurable
            else None
        )
        missing = (
            await deals_without_fee(session, tenant_id=tenant_id, start=start, end=end, **scope)
            if kpi.counts == kpi_defs.REVENUE
            else 0
        )
        out.append(
            {
                "key": kpi.key,
                "label": kpi.label,
                "source": kpi.source,
                "group": kpi.group,
                "unit": kpi.unit,
                "ist": ist,
                "ziel": _target_for(
                    configured,
                    kpi=kpi.key,
                    period=period,
                    actor_user_id=None if everyone else actor_user_id,
                    end=end,
                ),
                "missing": missing,
                "available": kpi.available,
                "unavailable_because": kpi.unavailable_because,
            }
        )

    goals = []
    for row in configured:
        group = _members(row)
        if row.period != period or (not group and row.actor_user_id is None):
            continue  # another period, or the workspace default (on the KPI)
        people = group or [row.actor_user_id]
        if not everyone and actor_user_id not in people:
            continue
        kpi = kpi_defs.BY_KEY.get(row.kpi)
        if kpi is None or not kpi.counts:
            continue
        goals.append(
            {
                "id": row.id,
                "kpi": row.kpi,
                "label": row.label,
                "members": people,
                "shared": bool(group),
                "ziel": row.value if _applies(row, end) else None,
                "valid_from": row.valid_from,
                "ist": await count(
                    session, tenant_id=tenant_id, counts=kpi.counts,
                    start=start, end=end, members=people,
                ),
            }
        )

    return {
        "period": period,
        "period_start": start,
        "period_end": end,
        "actor_user_id": None if everyone else actor_user_id,
        "kpis": out,
        "goals": goals,
        "funnel": await process_funnel(
            session, tenant_id=tenant_id, start=start, end=end, **scope
        ),
    }


#: Every table that names who did something, with its author and name column.
_AUTHORED = (
    (ManagerInteraction, ManagerInteraction.actor_user_id, ManagerInteraction.actor_name),
    (ProcessStep, ProcessStep.actor_user_id, ProcessStep.actor_name),
    (Manager, Manager.created_by_user_id, Manager.created_by_name),
    (Job, Job.created_by_user_id, Job.created_by_name),
)


async def consultants(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[dict]:
    """Who shows up in the record at all, busiest first.

    Read from the source tables, so somebody who has only ever ticked a
    process step still appears. There is no users table to list instead —
    membership lives in Clerk, and asking it per render is not worth it.
    """
    tallies: dict[str | None, dict] = {}
    for model, author, name_col in _AUTHORED:
        rows = await session.execute(
            select(author, func.max(name_col), func.count())
            .where(model.tenant_id == tenant_id)
            .group_by(author)
        )
        for user_id, name, total in rows.all():
            # A lead or mandate nobody is recorded for is not "activity" of
            # the unattributed bucket — every pre-ELI-64 row would land there.
            if user_id is None and model in (Manager, Job):
                continue
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


# ── Cockpit tiles, per person ─────────────────────────────────────────────


async def tiles(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: str
) -> tuple[list[str], bool]:
    """(tiles, saved) — the person's choice, else the default set."""
    row = await session.scalar(
        select(TrackingPreference).where(
            TrackingPreference.tenant_id == tenant_id,
            TrackingPreference.user_id == user_id,
        )
    )
    if row is None:
        return list(kpi_defs.DEFAULT_TILES), False
    # A tile that no longer exists is dropped rather than rendered empty.
    return [t for t in row.tiles or [] if t in kpi_defs.TILES], True


async def set_tiles(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: str, chosen: list[str]
) -> list[str]:
    unknown = [t for t in chosen if t not in kpi_defs.TILES]
    if unknown:
        raise ValueError(f"unknown tile {', '.join(unknown)}")
    ordered = list(dict.fromkeys(chosen))
    row = await session.scalar(
        select(TrackingPreference).where(
            TrackingPreference.tenant_id == tenant_id,
            TrackingPreference.user_id == user_id,
        )
    )
    if row is None:
        row = TrackingPreference(tenant_id=tenant_id, user_id=user_id, tiles=ordered)
        session.add(row)
    else:
        row.tiles = ordered
    await session.commit()
    return ordered
