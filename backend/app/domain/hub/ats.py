"""Employers' own ATS boards → the corpus (Personio, Ashby, Greenhouse, Lever).

The nightly job (`scripts/hub_ats.py`, machine-only routes) drives two steps:

1. **Discovery** (`add_boards`): board slugs found in public URL indexes
   (Common Crawl, the Wayback Machine) are added as `new`. Nothing is
   fetched then.
2. **Sync** (`sync_due`): each due board's feed is read — one request — and
   merged through `service.merge_fetch`, the same gate, opt-out list,
   identity ladder and recount every source uses.

The feed is a full snapshot, so closing is a diff: a DACH job the previous
snapshot listed and this one does not is closed (`closed_at`, payload
deleted, a `hub_observations` row) — the same end state as `liveness.py`.
Guards keep a broken answer from emptying a board:

  * "no jobs" — an empty feed, a 404/410 or a redirect — closes nothing the
    first time (`empty_streak`); only a second such answer in a row, ~20 h
    later, does. A 404 burst during a Personio incident closes nothing;
  * an unreadable 200 (HTML, truncated XML), a body over 10 MB, 5xx and 429
    close nothing and retry later;
  * a job whose office is not resolved yet (a page that did not answer, the
    per-sync cap) keeps its place in the snapshot: unresolved is not gone.

A board is leased before any HTTP (`next_fetch_at` pushed out and committed),
so two runs never sync the same board and no transaction spans a request.
One board failing (a database error included) costs that board, not the batch.

Each source module (`adapters/personio.py`, `ashby.py`, `greenhouse.py`,
`lever.py` — one per Lever instance) supplies the same pure pieces — `valid_slug`, `feed_url`, `external_id`, `parse_feed`,
`to_result` — and its adapter the HTTP. Only Personio has offices to resolve
(its feed names a town, not an address); the others carry the job's place.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time

from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.hub.adapters import ashby, greenhouse, lever, personio
from app.domain.hub.adapters.base import SourceUnreachable
from app.domain.hub.adapters.boards import FeedUnreadable
from app.domain.hub.models import HubAtsBoard, HubJobPosting, HubObservation, HubPostingPayload

logger = get_logger(__name__)

#: How often a board is read. Daily for a board with DACH jobs; a board with
#: none (or none yet) is looked at weekly; a retired one monthly.
REFRESH = {
    "active": dt.timedelta(hours=20),
    "elsewhere": dt.timedelta(days=7),
    "empty": dt.timedelta(days=7),
    "gone": dt.timedelta(days=30),
}
#: A run's claim on a board, so a crashed run's boards come back on their own.
LEASE = dt.timedelta(hours=2)
#: Failed reads before a board is looked at weekly instead of daily.
FAILING_AFTER = 5
#: New offices resolved per board per sync — one job page each.
OFFICES_PER_SYNC = 10
#: An office whose page named no address is asked again after this long.
UNRESOLVED_RETRY = dt.timedelta(days=7)
#: Status codes that say "this board publishes nothing here".
_NO_BOARD = {301, 302, 303, 307, 308, 404, 410}
_clock = time.monotonic
#: Board sources by name — the `ats` column of `hub_ats_boards`.
SOURCES = {
    personio.SOURCE_NAME: personio,
    ashby.SOURCE_NAME: ashby,
    greenhouse.SOURCE_NAME: greenhouse,
    lever.GLOBAL.ats: lever.GLOBAL,
    lever.EU.ats: lever.EU,
}


def adapter_for(ats: str):
    """The HTTP reader for one board system."""
    if ats == ashby.SOURCE_NAME:
        return ashby.AshbyAdapter()
    if ats == greenhouse.SOURCE_NAME:
        return greenhouse.GreenhouseAdapter()
    if ats == lever.GLOBAL.ats:
        return lever.LeverAdapter(lever.GLOBAL)
    if ats == lever.EU.ats:
        return lever.LeverAdapter(lever.EU)
    return personio.PersonioAdapter()


async def add_boards(session: AsyncSession, *, ats: str, slugs: list[str], discovered_via: str) -> dict[str, int]:
    """Add the slugs not yet known. Invalid slugs are refused, not stored."""
    source = SOURCES[ats]
    valid = sorted({s.lower() for s in slugs if source.valid_slug(s.lower())})
    known = set((await session.execute(
        select(HubAtsBoard.slug).where(HubAtsBoard.ats == ats, HubAtsBoard.slug.in_(valid))
    )).scalars()) if valid else set()
    new = [s for s in valid if s not in known]
    for slug in new:
        session.add(HubAtsBoard(ats=ats, slug=slug, discovered_via=discovered_via, status="new"))
    await session.commit()
    return {"added": len(new), "known": len(known), "invalid": len(slugs) - len(valid)}


async def _lease(
    session: AsyncSession, limit: int, now: dt.datetime, ats: str = personio.SOURCE_NAME
) -> list[HubAtsBoard]:
    stmt = (
        select(HubAtsBoard)
        .where(HubAtsBoard.ats == ats,
               or_(HubAtsBoard.next_fetch_at.is_(None), HubAtsBoard.next_fetch_at <= now))
        # Known boards first: a month's discovery adds thousands of new ones,
        # and they must not starve the daily refresh of jobs already held.
        # New ones in the order they were found (discovery sends the richest
        # hosts first — Greenhouse's EU boards).
        .order_by(HubAtsBoard.next_fetch_at.is_(None), HubAtsBoard.next_fetch_at,
                  HubAtsBoard.created_at, HubAtsBoard.id)
        .limit(limit)
    )
    if session.bind.dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    boards = list((await session.execute(stmt)).scalars())
    for board in boards:
        board.next_fetch_at = now + LEASE
    await session.commit()  # the lease is visible before any request goes out
    return boards


async def _close(session: AsyncSession, board: HubAtsBoard, ids: list[str], why: str) -> int:
    """Close these of the board's open jobs, with evidence. Returns how many."""
    if not ids:
        return 0
    from app.domain.hub.liveness import recount_open_postings

    source = SOURCES[board.ats]
    rows = (await session.execute(
        select(HubJobPosting.id, HubJobPosting.hub_company_id).where(
            HubJobPosting.source == source.SOURCE_NAME,
            HubJobPosting.external_id.in_(ids),
            HubJobPosting.is_active,
        )
    )).all()
    if not rows:
        return 0
    now = dt.datetime.now(dt.UTC)
    observation = HubObservation(
        source=source.SOURCE_NAME, request_url=source.feed_url(board.slug),
        http_status=board.last_http_status, record_count=len(rows), fetched_at=now,
        note=f"ats: {len(rows)} closed — {why}"[:500],
        payload={"closed": ids[:1000], "board": board.slug},
    )
    session.add(observation)
    await session.flush()
    posting_ids = [r.id for r in rows]
    await session.execute(
        update(HubJobPosting).where(HubJobPosting.id.in_(posting_ids), HubJobPosting.is_active)
        .values(is_active=False, closed_at=now, check_due_at=None, observation_id=observation.id)
    )
    await session.execute(delete(HubPostingPayload).where(HubPostingPayload.hub_job_posting_id.in_(posting_ids)))
    await recount_open_postings(session, {r.hub_company_id for r in rows})
    return len(rows)


def _resolved(offices: dict, office: str | None, now: dt.datetime) -> bool:
    """Known — an address, or a recent "no address" that is not due a retry."""
    if office is None:
        return True  # nothing to resolve: the position has no office at all
    entry = offices.get(office)
    if entry is None:
        return False
    if entry.get("country"):
        return True
    asked = entry.get("unresolved_at")
    try:
        return bool(asked) and now - dt.datetime.fromisoformat(asked) < UNRESOLVED_RETRY
    except (TypeError, ValueError):
        return False


async def _resolve_offices(
    adapter, board: HubAtsBoard, positions: list, *, now: dt.datetime, deadline: float
) -> None:
    """Read one job page per office this board has not resolved yet. A page
    lists every office of its job, so one page often resolves several.

    Each answer is written to the board as it arrives, so a later failure —
    an outage, the time budget — keeps everything already learned."""
    asked = 0
    for pos in positions:
        if _resolved(board.offices or {}, pos.office, now):
            continue
        if asked >= OFFICES_PER_SYNC or _clock() > deadline:
            break
        asked += 1
        page = await adapter.fetch_job_page(board.slug, pos.job_id)
        if page is None:
            continue  # asked again next sync
        found = personio.parse_job_page(page)
        offices = dict(board.offices or {})
        named = {k: v for k, v in found["offices"].items() if k}
        offices.update(named)
        if pos.office not in named:
            # The page's only address is this job's office (schema.org has no
            # office name; a single app-data office may be spelled otherwise).
            single = list(found["offices"].values())
            offices[pos.office] = single[0] if len(single) == 1 else {"unresolved_at": now.isoformat()}
        board.offices = offices
        if board.company_name is None and found["employer"]:
            board.company_name = found["employer"]


async def sync_board(
    session: AsyncSession, *, adapter, board: HubAtsBoard, deadline: float | None = None
) -> dict:
    """Read one board's feed and bring the corpus in line with it."""
    from app.domain.hub import service

    source = SOURCES[board.ats]
    now = dt.datetime.now(dt.UTC)
    deadline = deadline if deadline is not None else _clock() + 60
    outcome = {"board": board.slug, "created": 0, "updated": 0, "closed": 0}
    try:
        answer = await adapter.fetch_feed(board.slug)
    except SourceUnreachable:
        _failed(board, now, None)
        await session.commit()
        outcome["error"] = "unreachable"
        return outcome
    board.last_http_status = answer.status
    board.last_fetched_at = now

    if answer.status in _NO_BOARD:
        positions: list = []
    elif answer.status != 200:
        _failed(board, now, answer.status)
        await session.commit()
        outcome["error"] = f"HTTP {answer.status}"
        return outcome
    else:
        try:
            positions = source.parse_feed(answer.body)
        except FeedUnreadable as exc:
            _failed(board, now, answer.status)
            await session.commit()
            outcome["error"] = f"unreadable: {exc}"[:200]
            return outcome

    try:
        await _resolve_offices(adapter, board, positions, now=now, deadline=deadline)
    except SourceUnreachable:
        pass  # what resolved is on the board already; the rest waits
    has_dach_job = any(getattr(p, "place", None) and not personio._NOT_A_JOB.search(p.title)
                       for p in positions)
    if board.company_name is None and hasattr(adapter, "fetch_company_name") and has_dach_job:
        try:  # one page per board, once — only for a board with a DACH job
            board.company_name = await adapter.fetch_company_name(board.slug)
        except SourceUnreachable:
            pass  # its jobs are dropped as unnamed this time; asked again next sync
    known = {k: v for k, v in (board.offices or {}).items() if v.get("country")}
    result, listed = source.to_result(
        slug=board.slug, positions=positions, offices=known, fetched_at=now,
        company_name=board.company_name, content_hash=answer.content_hash,
    )
    board.failures = 0
    board.jobs_listed = len(positions)
    board.jobs_dach = len(listed)
    if board.company_name is None:
        board.company_name = next((p.company for p in positions if p.company), None)
    await session.commit()

    if result.postings:
        summary = await service.merge_fetch(session, result=result, key=f"{source.SOURCE_NAME}:{board.slug}")
        outcome["created"], outcome["updated"] = summary.postings_created, summary.postings_updated
    outcome["dropped"] = result.dropped

    previous = set(board.open_ids or [])
    # Listed, but its office has no address (yet): not gone — keep it as it was.
    pending = {source.external_id(board.slug, p.job_id) for p in positions
               if p.office is not None and p.office not in known}
    snapshot = sorted(set(listed) | (pending & previous))
    if positions:
        outcome["closed"] = await _close(session, board, sorted(previous - set(snapshot)),
                                         "no longer on the board's feed")
        board.open_ids, board.empty_streak = snapshot, 0
    elif board.empty_streak >= 1:
        why = f"the board answered no jobs twice in a row (last: HTTP {answer.status})"
        outcome["closed"] = await _close(session, board, sorted(previous), why)
        board.open_ids, board.empty_streak = [], board.empty_streak + 1
    else:
        board.empty_streak = 1  # once: maybe a glitch — close nothing yet

    # DACH jobs, but no name to store them under (the board page did not say
    # it): visible as its own status, and asked again weekly, not daily.
    unnamed = bool(listed) and not board.company_name and hasattr(adapter, "fetch_company_name")
    if positions:
        board.status = "active" if snapshot else "elsewhere"
    if unnamed:
        board.status = "unnamed"
        outcome["unnamed"] = True
        logger.warning("ats: %s board %s has DACH jobs but no company name", board.ats, board.slug)
    elif board.empty_streak >= 2:
        board.status = "gone" if answer.status in _NO_BOARD else "empty"
    # Confirm a first "no jobs" tomorrow, not in a week; same for offices due a read.
    unresolved = any(not _resolved(board.offices or {}, p.office, now) for p in positions)
    if board.empty_streak == 1 or unresolved:
        board.next_fetch_at = now + REFRESH["active"]
    elif board.status == "unnamed":
        board.next_fetch_at = now + REFRESH["empty"]
    elif board.status == "elsewhere":
        board.next_fetch_at = now + getattr(source, "ELSEWHERE_REFRESH", REFRESH["elsewhere"])
    else:
        board.next_fetch_at = now + REFRESH.get(board.status, REFRESH["active"])
    await session.commit()
    return outcome


def _failed(board: HubAtsBoard, now: dt.datetime, status: int | None) -> None:
    board.failures += 1
    board.last_http_status = status
    board.last_fetched_at = now
    if board.failures >= FAILING_AFTER:
        board.status = "failing"
        board.next_fetch_at = now + REFRESH["empty"]
    else:
        board.next_fetch_at = now + dt.timedelta(hours=6)


async def sync_due(
    session: AsyncSession, *, adapter, limit: int, delay: float = 1.0, time_budget: float = 60.0
) -> dict:
    """Sync up to `limit` due boards, oldest due first, inside `time_budget`.

    Boards leased but not reached in time are handed back (due now). The
    budget also bounds job-page reads inside a board."""
    now = dt.datetime.now(dt.UTC)
    boards = await _lease(session, limit, now, adapter.name)
    totals: dict = {"boards": 0, "created": 0, "updated": 0, "closed": 0, "failed": 0, "unnamed": 0}
    started, streak = _clock(), 0
    deadline = started + time_budget
    for i, board in enumerate(boards):
        if _clock() > deadline:
            for rest in boards[i:]:
                rest.next_fetch_at = now  # back in the queue
            await session.commit()
            break
        try:
            outcome = await sync_board(session, adapter=adapter, board=board, deadline=deadline)
        except Exception:  # one board — a bad record, a database error — not the batch
            logger.exception("ats: board %s failed", board.slug)
            await session.rollback()
            await session.refresh(board)
            _failed(board, now, board.last_http_status)
            await session.commit()
            outcome = {"error": "exception"}
        totals["boards"] += 1
        for key in ("created", "updated", "closed"):
            totals[key] += outcome.get(key, 0)
        totals["unnamed"] += bool(outcome.get("unnamed"))
        if outcome.get("error"):
            totals["failed"] += 1
            streak = streak + 1 if outcome["error"] == "unreachable" else 0
            if streak >= 3:
                totals["source_unreachable"] = True
                for rest in boards[i + 1:]:
                    rest.next_fetch_at = now
                await session.commit()
                break
        else:
            streak = 0
        if delay:
            await asyncio.sleep(delay)  # one employer's board at a time, politely
    # Tells the job whether to call again tonight.
    totals["more_due"] = await session.scalar(
        select(HubAtsBoard.id).where(
            HubAtsBoard.ats == adapter.name,
            or_(HubAtsBoard.next_fetch_at.is_(None), HubAtsBoard.next_fetch_at <= dt.datetime.now(dt.UTC)),
        ).limit(1)
    ) is not None
    logger.info("ats sync: %s", totals)
    return totals
