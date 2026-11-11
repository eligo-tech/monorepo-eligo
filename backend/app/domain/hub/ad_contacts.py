"""The nightly ad-contacts pass — who each open ad names, stored (ELI-22).

`hub/contacts.py` reads the person out of an ad text. Doing that per request
caps a view at one employer; a call list across the market needs the result
stored. This pass reads the queued ads (`models.CONTACTS_DUE`: never read,
read under older parser rules, or text fetched since the last read), replaces
their rows in `hub_ad_contacts`, and stamps them.

Machine-only, like every corpus write (ARCHITECTURE.md RULE 1): called by the
nightly job through an operator route, never by a user. It reads text already
in the corpus — no fetch. A suppressed person is kept out twice: their name is
cut from the text before it is read (`Suppressions.redact`), and a parsed
person who is suppressed under any spelling is dropped (`Suppressions.names`).

Concurrency. The description, partner-page and ATS passes run on their own
schedules and may overlap this one:

  * the batch's ads are locked (`FOR UPDATE SKIP LOCKED`), so an ATS close or
    a suppression waits for this batch and its `forget` then removes what the
    batch wrote — never the other way round;
  * the read is stamped with the fetch times it actually READ, not the clock:
    a fetch stamped earlier but committed after the read is newer than the
    stamp, and re-queues the ad.

Batched for the database's disk-IO budget: ad texts are the largest table in
the corpus (2.8 GB). The parsing runs in a worker thread so the API keeps
answering during a batch.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from sqlalchemy import bindparam, delete, func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.hub import suppression
from app.domain.hub.contacts import ContactMention, extract_contacts, person_key, unnamed_reach
from app.domain.hub.models import (
    AD_CONTACT_RULES,
    CONTACTS_DUE,
    HubAdContact,
    HubJobPosting,
    HubPostingPayload,
)

#: The stamp of a read that saw no text at all: any later fetch is newer.
_NOTHING_READ = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def _utc(value: dt.datetime) -> dt.datetime:
    """SQLite returns naive datetimes; they are UTC."""
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _better(new: ContactMention, old: ContactMention) -> bool:
    """Of two mentions of one person in one ad, keep the one a recruiter can
    act on: a phone first, then a first name."""
    return (new.phone is not None, new.first_name is not None) > (
        old.phone is not None,
        old.first_name is not None,
    )


def _people(
    texts: list[tuple[str, str | None, dt.datetime | None]], rules: suppression.Suppressions
) -> list[dict[str, Any]]:
    """One row per person across an ad's texts (ad first, then partner page)."""
    best: dict[str, tuple[ContactMention, str, dt.datetime | None]] = {}
    for origin, body, fetched_at in texts:
        if rules.may_name_someone(body):
            body = rules.redact(body)
        for mention in extract_contacts(body):
            if rules.names(mention.first_name, mention.last_name):
                continue
            key = person_key(mention.first_name, mention.last_name)
            if key not in best or _better(mention, best[key][0]):
                best[key] = (mention, origin, fetched_at)
    return [
        {
            "person_key": key,
            "full_name": m.full_name[:200],
            "salutation": m.salutation,
            "first_name": m.first_name[:120] if m.first_name else None,
            "last_name": m.last_name[:120],
            "role_title": m.role_title[:200] if m.role_title else None,
            "phone": m.phone[:60] if m.phone else None,
            "phone_kind": m.phone_kind,
            "mobile": m.mobile[:60] if m.mobile else None,
            "email": m.email[:320] if m.email else None,
            "quote": m.quote,
            "text_source": origin,
            "source_fetched_at": fetched_at,
        }
        for key, (m, origin, fetched_at) in best.items()
    ]


def _read(rows: list, rules: suppression.Suppressions) -> tuple[list[dict], list[dict]]:
    """CPU part of a batch: the rows to insert and the stamps to write."""
    values: list[dict[str, Any]] = []
    stamps: list[dict[str, Any]] = []
    for r in rows:
        people = _people(
            [
                ("ad", r.description, r.description_fetched_at),
                ("page", r.source_page_text, r.source_page_fetched_at),
            ],
            rules,
        )
        values += [{"hub_job_posting_id": r.id, "hub_company_id": r.hub_company_id, **p} for p in people]
        seen = [_utc(t) for t in (r.description_fetched_at, r.source_page_fetched_at) if t]
        # ELI-25: nobody named, but a phone or e-mail given — the model pass
        # (`hub/contact_model.py`) reads it. Re-reading an ad re-decides.
        model_due = not people and any(
            unnamed_reach(body) for body in (r.description, r.source_page_text) if body
        )
        stamps.append(
            {"b_id": r.id, "b_read_at": max(seen, default=_NOTHING_READ), "b_model_due": model_due}
        )
    return values, stamps


async def backfill(session: AsyncSession, *, limit: int) -> dict[str, int]:
    """Read up to `limit` queued ads; how many were read, how many persons
    were stored, how many ads remain queued."""
    due = text(CONTACTS_DUE)
    # The queue predicate alone on the postings table: the planner proves it
    # against the partial index, and nothing in it can be ambiguous.
    ids = list(
        (
            await session.execute(
                select(HubJobPosting.id)
                .where(due)
                .order_by(HubJobPosting.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    stored = 0
    if ids:
        rows = (
            await session.execute(
                select(
                    HubJobPosting.id,
                    HubJobPosting.hub_company_id,
                    HubJobPosting.description_fetched_at,
                    HubJobPosting.source_page_fetched_at,
                    HubPostingPayload.description,
                    HubPostingPayload.source_page_text,
                )
                .outerjoin(HubPostingPayload, HubPostingPayload.hub_job_posting_id == HubJobPosting.id)
                .where(HubJobPosting.id.in_(ids))
            )
        ).all()
        rules = await suppression.load(session)
        values, stamps = await asyncio.to_thread(_read, rows, rules)

        await session.execute(delete(HubAdContact).where(HubAdContact.hub_job_posting_id.in_(ids)))
        if values:
            await session.execute(insert(HubAdContact), values)
        table = HubJobPosting.__table__
        connection = await session.connection()
        await connection.execute(
            update(table)
            .where(table.c.id == bindparam("b_id"))
            .values(
                contacts_read_at=bindparam("b_read_at"),
                contacts_rules=AD_CONTACT_RULES,
                contacts_model_due=bindparam("b_model_due"),
            ),
            stamps,
        )
        stored = len(values)
    await session.commit()
    remaining = await session.scalar(select(func.count(HubJobPosting.id)).where(due))
    return {"read": len(ids), "contacts": stored, "remaining": int(remaining or 0)}


async def forget(session: AsyncSession, posting_ids: Any) -> None:
    """Drop the stored contacts of these ads and queue them for a re-read.

    Called wherever ad text is removed or rewritten outside a fetch: a closed
    ad (liveness, ATS snapshot, stale sweep), a suppressed company, a redacted
    person. A closed ad is not re-read (the queue holds open ads only); a
    redacted one is, from its redacted text. `posting_ids` is a list or a
    select of ids.
    """
    await session.execute(delete(HubAdContact).where(HubAdContact.hub_job_posting_id.in_(posting_ids)))
    await session.execute(
        update(HubJobPosting)
        .where(HubJobPosting.id.in_(posting_ids))
        .values(contacts_rules=None, contacts_read_at=None)
        .execution_options(synchronize_session=False)
    )


async def forget_person(session: AsyncSession, rules: suppression.Suppressions) -> int:
    """Delete every stored row that names a person in `rules`, whatever the
    spelling the ad used. `person_key` is the folded surname, so the
    candidates are one indexed lookup per suppressed person."""
    surnames = {key.split()[-1] for key in rules.persons}
    if not surnames:
        return 0
    rows = (
        await session.execute(
            select(HubAdContact.id, HubAdContact.first_name, HubAdContact.last_name).where(
                HubAdContact.person_key.in_(surnames)
            )
        )
    ).all()
    doomed = [r.id for r in rows if rules.names(r.first_name, r.last_name)]
    if doomed:
        await session.execute(delete(HubAdContact).where(HubAdContact.id.in_(doomed)))
    return len(doomed)
