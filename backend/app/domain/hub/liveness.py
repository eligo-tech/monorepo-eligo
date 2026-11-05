"""Close ads the source took down — and only those.

Measured 2026-11-05 against production: all 648,451 postings were open and
none had ever been closed; of 300 sampled at the Bundesagentur, 125 answered
404. A delta crawl (`--since 1`) never re-lists an old ad, so absence over time
proves nothing, which is why `deactivate_stale_postings` stays off.

Two steps, both driven by the nightly job (`scripts/hub_liveness.py`):

1. **Weekly listing → suspects.** The job reads the source's full listing,
   compares it with our open ads (`active_ids`) and `mark`s the ones it did not
   see. `unlisted_at` makes an ad a SUSPECT, never closes it: the listing
   reaches ~82% of the source, because shards over the 10,000 cap cannot be
   read whole (Verkauf alone is 108k).
2. **Nightly check → verdict.** `check_batch` asks each suspect's own detail
   page. A 404 closes it; a 200 records that it answered and keeps it out of
   the queue for `recheck_days`; anything else — 5xx, 429, a timeout — is no
   evidence and changes nothing. An outage stops the batch.

A closed ad keeps its row (title, company, dates: "they filled it" is a BD
signal) and loses its payload — ad text, raw copy, partner page. That is the
disk the closure frees (GDPR Art. 5(1)(e) storage limitation, too). If the
source publishes the same reference again, the ingest touch path reopens it.

Business logic only: no FastAPI, no outbound I/O except through the adapter.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.hub.models import HubCompany, HubJobPosting, HubPostingPayload

logger = get_logger(__name__)

SOURCE = "bundesagentur"
#: A suspect the source just confirmed live waits this long for its next check.
RECHECK_DAYS = 14


def _open(segment: str | None):
    clauses = [HubJobPosting.source == SOURCE, HubJobPosting.is_active.is_(True)]
    if segment is not None:
        clauses.append(HubJobPosting.segment == segment)
    return clauses


async def active_ids(
    session: AsyncSession, *, segment: str, after: str | None, limit: int
) -> list[tuple[str, bool]]:
    """Our open ads in reference order, each with "already a suspect"."""
    stmt = (
        select(HubJobPosting.external_id, HubJobPosting.unlisted_at.is_not(None))
        .where(*_open(segment))
        .order_by(HubJobPosting.external_id)
        .limit(limit)
    )
    if after is not None:
        stmt = stmt.where(HubJobPosting.external_id > after)
    return [(ext, bool(flag)) for ext, flag in (await session.execute(stmt)).all()]


async def mark(
    session: AsyncSession, *, segment: str, unlisted: list[str], listed: list[str]
) -> dict[str, int]:
    """Record what one listing showed: `unlisted` became suspects, `listed`
    were seen again. The FIRST time an ad went missing is kept."""
    now = dt.datetime.now(dt.UTC)
    flagged = cleared = 0
    if unlisted:
        flagged = (await session.execute(
            update(HubJobPosting)
            .where(*_open(segment), HubJobPosting.external_id.in_(unlisted), HubJobPosting.unlisted_at.is_(None))
            .values(unlisted_at=now)
        )).rowcount or 0
    if listed:
        cleared = (await session.execute(
            update(HubJobPosting)
            .where(*_open(segment), HubJobPosting.external_id.in_(listed), HubJobPosting.unlisted_at.is_not(None))
            .values(unlisted_at=None)
        )).rowcount or 0
    await session.commit()
    return {"unlisted": flagged, "listed": cleared}


async def recount_open_postings(session: AsyncSession, company_ids: set) -> None:
    """Keep `open_postings_count` true after postings close."""
    if not company_ids:
        return
    counts = dict((await session.execute(
        select(HubJobPosting.hub_company_id, func.count(HubJobPosting.id))
        .where(HubJobPosting.hub_company_id.in_(company_ids), HubJobPosting.is_active.is_(True))
        .group_by(HubJobPosting.hub_company_id)
    )).all())
    for company_id in company_ids:
        await session.execute(
            update(HubCompany).where(HubCompany.id == company_id)
            .values(open_postings_count=counts.get(company_id, 0))
        )


async def check_batch(
    session: AsyncSession,
    *,
    adapter,
    limit: int,
    segment: str | None = None,
    recheck_days: int = RECHECK_DAYS,
    delay: float = 0.3,
) -> dict:
    """Ask the source about up to `limit` suspects, longest-missing first."""
    from app.domain.hub.adapters.bundesagentur import SourceUnreachable

    now = dt.datetime.now(dt.UTC)
    due = now - dt.timedelta(days=recheck_days)
    rows = (await session.execute(
        select(HubJobPosting)
        .where(
            *_open(segment),
            HubJobPosting.unlisted_at.is_not(None),
            or_(HubJobPosting.live_checked_at.is_(None), HubJobPosting.live_checked_at < due),
        )
        .order_by(HubJobPosting.unlisted_at, HubJobPosting.posted_at.nulls_first(), HubJobPosting.external_id)
        .limit(limit)
    )).scalars().all()

    result = {"checked": 0, "closed": 0, "live": 0, "unknown": 0, "source_unreachable": False}
    closed: list[HubJobPosting] = []
    for row in rows:
        try:
            verdict = await adapter.check_live(row.external_id)
        except SourceUnreachable as exc:
            # The source is down, not this ad: stop, and leave the rest unstamped.
            logger.warning("liveness: source unreachable, stopping batch (%s)", exc)
            result["source_unreachable"] = True
            break
        result["checked"] += 1
        if verdict == "gone":
            row.is_active = False
            row.closed_at = now
            closed.append(row)
            result["closed"] += 1
        elif verdict == "live":
            row.live_checked_at = now
            result["live"] += 1
        else:
            result["unknown"] += 1
        if delay:
            await asyncio.sleep(delay)

    if closed:
        await session.flush()
        await session.execute(
            delete(HubPostingPayload).where(HubPostingPayload.hub_job_posting_id.in_([r.id for r in closed]))
        )
        await recount_open_postings(session, {r.hub_company_id for r in closed})
    await session.commit()
    logger.info("liveness: %s", result)
    return result
