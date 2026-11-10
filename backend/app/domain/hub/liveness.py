"""Close ads the source took down — and only those.

Measured 2026-11-05 against production: all 648,451 postings were open and
none had ever been closed; of 300 sampled at the Bundesagentur, 125 answered
404. A delta crawl (`--since 1`) never re-lists an old ad, so absence over time
proves nothing, which is why `deactivate_stale_postings` stays off.

Two steps, both driven by the nightly job (`scripts/hub_liveness.py`):

1. **Weekly listing → suspects.** The job reads the source's full listing,
   compares it with our open ads (`active_ids`) and `mark`s the ones it did not
   see: `unlisted_at` (when) and `check_due_at` (queued now). A suspect, never a
   verdict: the listing reaches ~82% of the source, because shards over the
   10,000 cap cannot be read whole (Verkauf alone is 108k).
2. **Nightly check → verdict.** `check_batch` asks each due suspect's own
   detail page, after first asking a known-live CONTROL ad. Only the source's
   own "not found" closes (`adapters/bundesagentur.liveness_from_response`);
   the closure is recorded as a `hub_observations` row. A live answer re-queues
   the ad 14 days out (30 once it has answered before); no answer, 1 day out.

The safety argument, measured the same day: 160 of 160 ads on the live listing
answered 200, a made-up reference answered 404 with the source's not-found
code. A systematic failure — the path retired, the key changed, a CDN page —
fails the control first, or answers without that code; either closes nothing.

A closed ad keeps its row (title, company, dates: "they filled it" is a BD
signal) and loses its payload — ad text, raw copy, partner page (GDPR Art.
5(1)(e)). Postgres reuses that space after vacuum; it does not shrink the
files. If the source publishes the same reference again, the ingest touch
path reopens it (`service.ingest`).

No database transaction is held across the source calls: the batch reads its
queue, ends the transaction, asks the source, then writes every verdict in one
short transaction.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.hub import ad_contacts
from app.domain.hub.models import HubCompany, HubJobPosting, HubObservation, HubPostingPayload

logger = get_logger(__name__)

#: The default source. EURES (Austria, Switzerland) runs the same two steps
#: with its own not-found (`adapters/eures.liveness_from_response`); every
#: function takes the source, and a batch checks one source's queue only.
SOURCE = "bundesagentur"
#: Re-queue delays. An ad that answered live once waits two weeks; one that has
#: answered before waits longer — most of those sit in shards the listing
#: cannot reach, and would otherwise crowd out new suspects.
RECHECK_FIRST = dt.timedelta(days=14)
RECHECK_AGAIN = dt.timedelta(days=30)
RETRY_UNKNOWN = dt.timedelta(days=1)
#: Transport failures in a row that mean the source is down, not one ad slow.
OUTAGE_STREAK = 3
#: The control reference, reused for a while: one batch every ~30 s should not
#: re-run its lookup each time. Dropped the moment it fails to answer live.
CONTROL_TTL_SECONDS = 900
_control_cache: dict[tuple[str, str | None], tuple[str, float]] = {}
#: The batch's clock — a seam, so a test can move time without moving asyncio's.
_clock = time.monotonic


def _open(segment: str | None, source: str = SOURCE) -> list:
    # Bare `is_active`, not `.is_(True)`: Postgres renders the latter `IS true`
    # and cannot then prove the partial index's `is_active` predicate.
    clauses = [HubJobPosting.source == source, HubJobPosting.is_active]
    if segment is not None:
        clauses.append(HubJobPosting.segment == segment)
    return clauses


async def active_ids(
    session: AsyncSession, *, segment: str, after: str | None, limit: int, source: str = SOURCE
) -> list[tuple[str, bool]]:
    """Our open ads in reference order, each with "already a suspect"."""
    stmt = (
        select(HubJobPosting.external_id, HubJobPosting.unlisted_at.is_not(None))
        .where(*_open(segment, source))
        .order_by(HubJobPosting.external_id)
        .limit(limit)
    )
    if after is not None:
        stmt = stmt.where(HubJobPosting.external_id > after)
    return [(ext, bool(flag)) for ext, flag in (await session.execute(stmt)).all()]


async def mark(
    session: AsyncSession, *, segment: str, unlisted: list[str], listed: list[str],
    source: str = SOURCE,
) -> dict[str, int]:
    """Record what one listing showed: `unlisted` are queued as suspects,
    `listed` leave the queue. A suspect already queued keeps its place."""
    now = dt.datetime.now(dt.UTC)
    flagged = cleared = 0
    if unlisted:
        flagged = (await session.execute(
            update(HubJobPosting)
            .where(*_open(segment, source), HubJobPosting.external_id.in_(unlisted),
                   HubJobPosting.unlisted_at.is_(None))
            .values(unlisted_at=now, check_due_at=now)
        )).rowcount or 0
    if listed:
        cleared = (await session.execute(
            update(HubJobPosting)
            .where(*_open(segment, source), HubJobPosting.external_id.in_(listed),
                   HubJobPosting.unlisted_at.is_not(None))
            .values(unlisted_at=None, check_due_at=None)
        )).rowcount or 0
    await session.commit()
    return {"unlisted": flagged, "listed": cleared}


async def recount_open_postings(session: AsyncSession, company_ids: set) -> None:
    """Keep `open_postings_count` true after postings close."""
    if not company_ids:
        return
    from app.domain.hub.vacancy import vacancy_count

    counts = dict((await session.execute(
        select(HubJobPosting.hub_company_id, vacancy_count())
        .where(HubJobPosting.hub_company_id.in_(company_ids), HubJobPosting.is_active)
        .group_by(HubJobPosting.hub_company_id)
    )).all())
    for company_id in company_ids:
        await session.execute(
            update(HubCompany).where(HubCompany.id == company_id)
            .values(open_postings_count=counts.get(company_id, 0))
        )


#: Control candidates tried before the source is judged not to be answering:
#: the newest ad may itself have been withdrawn since it was listed.
CONTROL_CANDIDATES = 3


async def _controls(session: AsyncSession, segment: str | None, source: str) -> list[str]:
    """References the listing showed and the queue does not hold — the newest.
    If the source answers 200 for none of them, it is not answering for anyone."""
    cached = _control_cache.get((source, segment))
    if cached and cached[1] > _clock():
        return [cached[0]]
    # `posted_at DESC` with NULLs filtered out is a backward walk of
    # ix_hub_job_postings_posted_at that stops at the first non-suspect;
    # `DESC NULLS LAST` does not match that index and sorted the table.
    return list((await session.execute(
        select(HubJobPosting.external_id)
        .where(*_open(segment, source), HubJobPosting.check_due_at.is_(None),
               HubJobPosting.posted_at.is_not(None))
        .order_by(HubJobPosting.posted_at.desc())
        .limit(CONTROL_CANDIDATES)
    )).scalars())


async def check_batch(
    session: AsyncSession,
    *,
    adapter,
    limit: int,
    segment: str | None = None,
    delay: float = 0.3,
    time_budget: float = 60.0,
) -> dict:
    """Ask `adapter`'s source about up to `limit` of ITS due suspects,
    earliest due first."""
    from app.domain.hub.adapters.base import SourceUnreachable

    source = adapter.name
    now = dt.datetime.now(dt.UTC)
    result = {"checked": 0, "closed": 0, "live": 0, "unknown": 0,
              "source_unreachable": False, "control_failed": False}
    queue = (await session.execute(
        select(HubJobPosting.id, HubJobPosting.external_id, HubJobPosting.hub_company_id,
               HubJobPosting.live_checked_at)
        .where(*_open(segment, source), HubJobPosting.check_due_at <= now)
        .order_by(HubJobPosting.check_due_at, HubJobPosting.id)
        .limit(limit)
    )).all()
    candidates = await _controls(session, segment, source) if queue else []
    await session.commit()  # no transaction across the source calls
    if not queue:
        return result

    control = None
    for candidate in candidates:
        try:
            if await adapter.check_live(candidate) == "live":
                control = candidate
                break
        except SourceUnreachable:
            break
    if control is not None:
        _control_cache[(source, segment)] = (control, _clock() + CONTROL_TTL_SECONDS)
    else:
        _control_cache.pop((source, segment), None)
        logger.warning("liveness: no control of %r answered live — nothing checked", candidates)
        result["control_failed"] = True
        return result

    verdicts: dict[str, list] = {"gone": [], "live": [], "unknown": []}
    started, streak = _clock(), 0
    for row in queue:
        if _clock() - started > time_budget:
            break  # keep a request well inside the caller's timeout
        try:
            verdict = await adapter.check_live(row.external_id)
            streak = 0
        except SourceUnreachable as exc:
            streak += 1
            if streak >= OUTAGE_STREAK:
                logger.warning("liveness: source unreachable, stopping batch (%s)", exc)
                result["source_unreachable"] = True
                verdicts["unknown"].append(row)
                result["checked"] += 1
                result["unknown"] += 1
                break
            verdict = "unknown"  # one slow ad is not an outage
        verdicts[verdict].append(row)
        result["checked"] += 1
        result["closed" if verdict == "gone" else verdict] += 1
        if delay:
            await asyncio.sleep(delay)

    done = dt.datetime.now(dt.UTC)
    gone = verdicts["gone"]
    if gone:
        observation = HubObservation(
            source=source,
            request_url=getattr(adapter, "detail_url_template", "detail/{reference}"),
            http_status=404,
            record_count=len(gone),
            fetched_at=done,
            note=f"liveness: {len(gone)} closed on the source's not-found; control {control} answered 200",
            payload={"closed": [r.external_id for r in gone], "control": control},
        )
        session.add(observation)
        await session.flush()
        ids = [r.id for r in gone]
        await session.execute(
            # Still open and still due: a row reopened by an ingest between the
            # read and this write is not closed behind its back.
            update(HubJobPosting)
            .where(HubJobPosting.id.in_(ids), HubJobPosting.is_active, HubJobPosting.check_due_at <= now)
            .values(
                is_active=False, closed_at=done, check_due_at=None, observation_id=observation.id,
            )
        )
        await session.execute(delete(HubPostingPayload).where(HubPostingPayload.hub_job_posting_id.in_(ids)))
        await ad_contacts.forget(session, ids)  # the people go with the text
        await recount_open_postings(session, {r.hub_company_id for r in gone})
    for rows, due in (
        ([r for r in verdicts["live"] if r.live_checked_at is None], done + RECHECK_FIRST),
        ([r for r in verdicts["live"] if r.live_checked_at is not None], done + RECHECK_AGAIN),
    ):
        if rows:
            await session.execute(
                update(HubJobPosting).where(HubJobPosting.id.in_([r.id for r in rows]))
                .values(live_checked_at=done, check_due_at=due)
            )
    if verdicts["unknown"]:
        await session.execute(
            update(HubJobPosting).where(HubJobPosting.id.in_([r.id for r in verdicts["unknown"]]))
            .values(check_due_at=done + RETRY_UNKNOWN)
        )
    await session.commit()
    logger.info("liveness: %s", result)
    return result
