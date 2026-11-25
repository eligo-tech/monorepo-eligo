"""The call list — who to call next, and what happened when we did (ELI-22).

Two views over data that already exists:

  * `market` — "Anrufen": persons open job ads name (`hub_ad_contacts`, filled
    nightly), one row per person per employer, that THIS workspace has not
    called yet. Direct lines first, then employers with the most open ads.
  * `follow_ups` — "Wiedervorlage": this workspace's contacts with a logged
    call outcome, the due call-backs first. "Wrong person / left" drops off.

`log_call` is the one write: the first call to a market person takes them into
the workspace — the employer through the receipted `adopt_company` (or the one
already adopted at any of its sites), the person as a manager sourced from the
ad (`public_web`, so the GDPR Art. 14 notice is owed) — and records the call
with its outcome on the contact history. Later calls reuse both.

A person this workspace erased is held back on both paths, by e-mail, phone
or surname at the employer (`erasure.PersonGuard`): ad contacts rarely carry
an e-mail, so the e-mail fingerprint alone would let them back.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import and_, case, distinct, exists, func, or_, select, tuple_
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.hub.contacts import _fold, person_key
from app.domain.hub.models import EMPLOYER, HubAdContact, HubCompany, HubCompanyLink, HubJobPosting

#: Outcomes after which a person is not called again from the list.
_OFF_THE_LIST = ("wrong_person",)
#: Outcomes of a call that did not reach the person: an agreed call-back
#: survives them (ELI-38 — "keep the status until it is done").
_NOT_REACHED = ("not_reached", "voicemail")
#: Follow-ups shown at most — the most recently called first.
_FOLLOW_UP_LIMIT = 500


class NotOnTheList(LookupError):
    """No open ad of this employer names that person."""


class Erased(Exception):
    """This workspace erased the person (GDPR Art. 17)."""


def _surname_key(last_name: str | None, full_name: str | None) -> str | None:
    name = last_name or full_name
    return person_key(None, name) if name and name.split() else None


async def _called(session: AsyncSession, tenant_id: uuid.UUID) -> set[tuple[str, str]]:
    """(employer normalized name, surname key) of every person this workspace
    has a call outcome for — they live in follow-ups, not in the market tab —
    and of everyone marked "Nicht mehr kontaktieren" (ELI-32), who lives in
    neither."""
    from app.domain.companies.models import Company
    from app.domain.managers.models import Manager, ManagerInteraction

    called = (
        select(HubCompany.normalized_name, Manager.last_name, Manager.full_name)
        .select_from(ManagerInteraction)
        .join(Manager, Manager.id == ManagerInteraction.manager_id)
        .join(Company, Company.id == Manager.company_id)
        .join(HubCompanyLink, HubCompanyLink.company_id == Company.id)
        .join(HubCompany, HubCompany.id == HubCompanyLink.hub_company_id)
        .where(
            ManagerInteraction.tenant_id == tenant_id,
            ManagerInteraction.outcome.is_not(None),
            HubCompanyLink.tenant_id == tenant_id,
        )
    )
    blocked = (
        select(HubCompany.normalized_name, Manager.last_name, Manager.full_name)
        .select_from(Manager)
        .join(Company, Company.id == Manager.company_id)
        .join(HubCompanyLink, HubCompanyLink.company_id == Company.id)
        .join(HubCompany, HubCompany.id == HubCompanyLink.hub_company_id)
        .where(
            Manager.tenant_id == tenant_id,
            Manager.do_not_contact_at.is_not(None),
            HubCompanyLink.tenant_id == tenant_id,
        )
    )
    rows = await session.execute(called.union(blocked))
    out: set[tuple[str, str]] = set()
    for normalized, last, full in rows.all():
        key = _surname_key(last, full)
        if key:
            out.add((normalized, key))
    return out


def _best(rows: list[Any]) -> Any:
    """The mention a recruiter can act on: direct line, then any phone, then a
    first name, then a role."""
    return max(
        rows,
        key=lambda r: (r.phone_kind == "direct", r.phone is not None, r.first_name is not None, r.role_title is not None),
    )


async def market(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    q: str | None = None,
    phone_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """"Anrufen": one row per person per employer, ranked, paged."""
    from app.domain.erasure import service as erasure
    from app.domain.hub.schemas import source_detail_url

    called = await _called(session, tenant_id)
    guard = await erasure.person_guard(session, tenant_id)

    direct = func.max(case((HubAdContact.phone_kind == "direct", 1), else_=0))
    any_phone = func.max(case((HubAdContact.phone.is_not(None), 1), else_=0))
    open_ads = func.count(distinct(HubAdContact.hub_job_posting_id))
    newest = func.max(HubJobPosting.first_seen_at)
    stmt = (
        select(HubCompany.normalized_name, HubAdContact.person_key, open_ads.label("open_ads"))
        .select_from(HubAdContact)
        .join(HubJobPosting, HubJobPosting.id == HubAdContact.hub_job_posting_id)
        .join(HubCompany, HubCompany.id == HubAdContact.hub_company_id)
        .where(HubJobPosting.is_active, HubCompany.kind == EMPLOYER)
        .group_by(HubCompany.normalized_name, HubAdContact.person_key)
        .order_by(
            direct.desc(), any_phone.desc(), open_ads.desc(), newest.desc(),
            HubCompany.normalized_name, HubAdContact.person_key,
        )
    )
    if phone_only:
        stmt = stmt.where(HubAdContact.phone.is_not(None))
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(HubCompany.name).like(like), func.lower(HubAdContact.full_name).like(like)))
    if called:
        stmt = stmt.where(~tuple_(HubCompany.normalized_name, HubAdContact.person_key).in_(list(called)))

    # Erased persons are filtered after the groups are read (their
    # fingerprints are keyed hashes, not something SQL can compare). The
    # window is read with spare rows, and `next_offset` counts the GROUPS
    # consumed — not the rows shown — so the next page starts exactly after
    # this one however many were filtered.
    window = limit * 2 + 20
    groups = (await session.execute(stmt.limit(window).offset(offset))).all()

    details: dict[tuple[str, str], list[Any]] = {}
    if groups:
        found = (
            await session.execute(
                select(
                    HubCompany.normalized_name, HubAdContact.person_key,
                    HubAdContact.full_name, HubAdContact.first_name, HubAdContact.last_name,
                    HubAdContact.salutation, HubAdContact.role_title, HubAdContact.phone,
                    HubAdContact.phone_kind, HubAdContact.email, HubAdContact.quote,
                    HubAdContact.hub_company_id, HubCompany.name.label("company_name"),
                    HubJobPosting.title.label("posting_title"),
                    HubJobPosting.source, HubJobPosting.source_url, HubJobPosting.external_id,
                )
                .join(HubJobPosting, HubJobPosting.id == HubAdContact.hub_job_posting_id)
                .join(HubCompany, HubCompany.id == HubAdContact.hub_company_id)
                .where(
                    tuple_(HubCompany.normalized_name, HubAdContact.person_key).in_([(g[0], g[1]) for g in groups]),
                    HubJobPosting.is_active,
                )
                .order_by(HubJobPosting.first_seen_at.desc())
            )
        ).all()
        for m in found:
            details.setdefault((m.normalized_name, m.person_key), []).append(m)

    rows: list[dict] = []
    consumed = 0
    for normalized, key, count in groups:
        if len(rows) == limit:
            break
        consumed += 1
        mentions = details.get((normalized, key))
        if not mentions:
            continue
        best = _best(mentions)
        named = next((m for m in mentions if m.first_name), best)
        email = best.email or next((m.email for m in mentions if m.email), None)
        if guard.blocks(company_name=best.company_name, surname=best.last_name, phone=best.phone, email=email):
            continue
        rows.append({
            "hub_company_id": best.hub_company_id,
            "person_key": key,
            "company_name": best.company_name,
            "full_name": named.full_name,
            "first_name": named.first_name,
            "last_name": best.last_name,
            "salutation": best.salutation or named.salutation,
            "role_title": best.role_title or next((m.role_title for m in mentions if m.role_title), None),
            "phone": best.phone,
            "phone_kind": best.phone_kind,
            "email": email,
            "open_ads": count,
            "posting_title": best.posting_title,
            "quote": best.quote,
            "source_url": best.source_url or source_detail_url(best.source, best.external_id),
            "reach": "named_phone" if best.phone else "named",
        })
    has_more = consumed < len(groups) or len(groups) == window
    return {"rows": rows, "has_more": has_more, "offset": offset, "next_offset": offset + consumed, "limit": limit}


def _contains(text: str) -> str:
    """A LIKE pattern for "contains", with % and _ taken literally."""
    escaped = text.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _latest_calls(tenant_id: uuid.UUID):
    """Subquery: each manager's latest call with an outcome (rank 1), ties
    broken by when the row was written, then by id."""
    from app.domain.managers.models import ManagerInteraction

    return (
        select(
            ManagerInteraction.id.label("interaction_id"),
            ManagerInteraction.manager_id,
            func.row_number()
            .over(
                partition_by=ManagerInteraction.manager_id,
                order_by=(
                    ManagerInteraction.occurred_at.desc(),
                    ManagerInteraction.created_at.desc(),
                    ManagerInteraction.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(ManagerInteraction.tenant_id == tenant_id, ManagerInteraction.outcome.is_not(None))
        .subquery()
    )


def _open_follow_ups(tenant_id: uuid.UUID):
    """Subquery: each manager's OPEN next call (ELI-38) — `manager_id`,
    `next_action_at`.

    The date of the latest call that set one, kept until a later call
    reaches the person (any outcome but not reached / voicemail). A later
    unanswered call does not close it, and a later dated call replaces it
    (it is then the latest dated call). Interactions without an outcome —
    notes, mails — never touch it.
    """
    from app.domain.managers.models import ManagerInteraction

    dated = (
        select(
            ManagerInteraction.manager_id,
            ManagerInteraction.next_action_at,
            ManagerInteraction.occurred_at,
            ManagerInteraction.created_at,
            func.row_number()
            .over(
                partition_by=ManagerInteraction.manager_id,
                order_by=(
                    ManagerInteraction.occurred_at.desc(),
                    ManagerInteraction.created_at.desc(),
                    ManagerInteraction.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(
            ManagerInteraction.tenant_id == tenant_id,
            ManagerInteraction.outcome.is_not(None),
            ManagerInteraction.next_action_at.is_not(None),
        )
        .subquery()
    )
    later = aliased(ManagerInteraction)
    reached_since = exists().where(
        later.tenant_id == tenant_id,
        later.manager_id == dated.c.manager_id,
        later.outcome.is_not(None),
        later.outcome.not_in(_NOT_REACHED),
        or_(
            later.occurred_at > dated.c.occurred_at,
            and_(later.occurred_at == dated.c.occurred_at, later.created_at > dated.c.created_at),
        ),
    )
    return (
        select(dated.c.manager_id, dated.c.next_action_at)
        .where(dated.c.rank == 1, ~reached_since)
        .subquery()
    )


def _note_totals(tenant_id: uuid.UUID):
    """Subquery: each manager's notes (ELI-62) — `manager_id`, `n`, `last_at`.

    Every row of the contact history counts — a call (also one that did not
    reach the person), a mail, a note, an imported aiFind note in whatever
    raw spelling it was stored — so no `interaction_type` filter. One
    GROUP BY for the whole page, joined, never a query per row.
    """
    from app.domain.managers.models import ManagerInteraction

    return (
        select(
            ManagerInteraction.manager_id,
            func.count(ManagerInteraction.id).label("n"),
            func.max(ManagerInteraction.occurred_at).label("last_at"),
        )
        .where(ManagerInteraction.tenant_id == tenant_id, ManagerInteraction.manager_id.is_not(None))
        .group_by(ManagerInteraction.manager_id)
        .subquery()
    )


#: ELI-62: the Leads list's notes filter.
NOTES_FILTERS = ("none", "with")


async def contacts(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
    company_name: str | None = None,
    q: str | None = None,
    due_only: bool = False,
    notes: str | None = None,
    no_interest: bool = False,
    created_by: str | None = None,
    limit: int = 500,
    now: dt.datetime | None = None,
) -> dict:
    """The Contact List's "Kontakte" tab (ELI-23): every contact in this
    workspace — company, when added, where from (an adopted ad contact
    carries the ad as `source_detail`), the last call, and the open next
    call (`_open_follow_ups`). ELI-38: leads with an open next call come
    first, the earliest date on top (so the overdue ones lead); the rest
    newest first.

    `companies` is the facet the screen filters and groups by — every company
    this workspace holds contacts at, most contacts first. Companies are not a
    screen of their own: they are how this list is cut, for a recruiter and
    for an agent (`contacts.list`).

    ELI-62: `notes="none"` keeps the leads nothing has been recorded on yet
    (no contact history, no free-text note), `notes="with"` the others,
    latest note first (a lead with only the free-text note last).
    `note_counts` counts all / none / with under every OTHER filter, so the
    chips show what each choice would list.
    """
    from app.domain.companies.models import Company
    from app.domain.managers.models import Manager, ManagerInteraction

    now = now or dt.datetime.now(dt.UTC)
    latest = _latest_calls(tenant_id)
    follow_up = _open_follow_ups(tenant_id)
    # ELI-32: a lead marked "Nicht mehr kontaktieren" stays on the list (with
    # the mark) but owes no next call — never due, never on top.
    open_next = case((Manager.do_not_contact_at.is_(None), follow_up.c.next_action_at), else_=None)
    noted = _note_totals(tenant_id)
    has_notes = or_(
        noted.c.n.is_not(None),
        func.length(func.trim(func.coalesce(Manager.notes, ""))) > 0,
    )
    base = (
        select(
            Manager, Company.name, ManagerInteraction, open_next.label("open_next_at"),
            noted.c.n, noted.c.last_at, has_notes.label("has_notes"),
        )
        .join(Company, Company.id == Manager.company_id)
        .outerjoin(latest, (latest.c.manager_id == Manager.id) & (latest.c.rank == 1))
        .outerjoin(ManagerInteraction, ManagerInteraction.id == latest.c.interaction_id)
        .outerjoin(follow_up, follow_up.c.manager_id == Manager.id)
        .outerjoin(noted, noted.c.manager_id == Manager.id)
        # ELI-23: the Bus-Dev-Kontakte — new contacts from Markt, not yet
        # moved to Managers.
        .where(Manager.tenant_id == tenant_id, Company.tenant_id == tenant_id, Manager.stage == "bus_dev")
    )
    if company_id is not None:
        base = base.where(Manager.company_id == company_id)
    # ELI-69 "Angelegt von": an account id, resolved from "me" by the router.
    by_creator = (Manager.created_by_user_id == created_by,) if created_by is not None else ()
    base = base.where(*by_creator)
    if company_name and company_name.strip():
        base = base.where(func.lower(Company.name).like(_contains(company_name), escape="\\"))
    if q and q.strip():
        like = _contains(q)
        base = base.where(or_(
            func.lower(Manager.full_name).like(like, escape="\\"),
            func.lower(Company.name).like(like, escape="\\"),
            func.lower(func.coalesce(Manager.role_title, "")).like(like, escape="\\"),
        ))
    # ELI-60: "Kein Interesse" leaves the list; the filter shows only them.
    # The chip counts them under the same company and search.
    shelved = Manager.no_interest_at.is_not(None) if no_interest else Manager.no_interest_at.is_(None)
    hidden = base.where(Manager.no_interest_at.is_not(None))
    base = base.where(shelved)
    if due_only:
        base = base.where(
            Manager.do_not_contact_at.is_(None),
            follow_up.c.next_action_at.is_not(None), follow_up.c.next_action_at <= now,
        )

    # One aggregate for the total and the notes chips (ELI-62).
    counted = base.subquery()
    n_all, n_with = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(case((counted.c.has_notes, 1), else_=0)), 0))
            .select_from(counted)
        )
    ).one()
    note_counts = {"all": int(n_all or 0), "none": int(n_all or 0) - int(n_with or 0), "with": int(n_with or 0)}
    if notes == "none":
        base = base.where(~has_notes)
        total = note_counts["none"]
    elif notes == "with":
        base = base.where(has_notes)
        total = note_counts["with"]
    else:
        total = note_counts["all"]
    no_interest_total = await session.scalar(select(func.count()).select_from(hidden.subquery()))
    # NULLS LAST: Postgres would put a row without a date first ("newest").
    order = (
        (noted.c.last_at.is_(None), noted.c.last_at.desc())
        if notes == "with"
        else (open_next.is_(None), open_next.asc())
    )
    found = (
        await session.execute(
            base.order_by(
                *order,
                Manager.created_at.desc().nulls_last(),
                Manager.full_name,
            ).limit(limit)
        )
    ).all()

    def aware(value: dt.datetime | None) -> dt.datetime | None:
        return value.replace(tzinfo=dt.UTC) if value is not None and value.tzinfo is None else value

    jobs = await lead_jobs(session, tenant_id, [row[0] for row in found])
    rows = []
    for manager, company, call, open_next_at, note_n, last_note_at, row_has_notes in found:
        nxt = aware(open_next_at)
        rows.append({
            "manager_id": manager.id,
            "company_id": manager.company_id,
            "company_name": company,
            "full_name": manager.full_name,
            "role_title": manager.role_title,
            "phone": manager.phone,
            # ELI-76: every number, the primary first — a number added on the
            # row shows there. `extra_phones` loads selectin, one IN per page.
            "phones": manager.phones,
            "email": manager.email,
            "linkedin_url": manager.linkedin_url,
            "xing_url": manager.xing_url,
            "added_at": aware(manager.created_at),
            "source": manager.source,
            "source_detail": manager.source_detail,
            # ELI-65: entered by hand ("+ Lead"), not taken from Markt.
            "manual": manager.manual_lead,
            "art14_outstanding": bool(manager.art14_outstanding),
            "do_not_contact_at": aware(manager.do_not_contact_at),
            "no_interest_at": aware(manager.no_interest_at),
            "removed_reason": manager.removed_reason,
            "last_outcome": call.outcome if call else None,
            "last_call_at": aware(call.occurred_at) if call else None,
            "last_call_by": call.actor_name if call else None,
            "next_action_at": nxt,
            "due": nxt is not None and nxt <= now,
            "jobs": jobs.get(manager.id, []),
            "note_count": int(note_n or 0),
            "last_note_at": aware(last_note_at),
            "has_notes": bool(row_has_notes),
            "created_by_user_id": manager.created_by_user_id,
            "created_by_name": manager.created_by_name,
        })

    facet = (
        await session.execute(
            select(Company.id, Company.name, func.count(Manager.id).label("n"))
            .join(Manager, Manager.company_id == Company.id)
            .where(Company.tenant_id == tenant_id, Manager.tenant_id == tenant_id, Manager.stage == "bus_dev",
                   shelved, *by_creator)
            .group_by(Company.id, Company.name)
            .order_by(func.count(Manager.id).desc(), Company.name)
        )
    ).all()
    boards = await company_switchboards(session, tenant_id, [cid for cid, _, _ in facet])
    return {
        "rows": rows,
        "total": int(total or 0),
        "truncated": int(total or 0) > len(rows),
        "note_counts": note_counts,
        "no_interest_total": int(no_interest_total or 0),
        "companies": [
            {"company_id": cid, "name": name, "contacts": n, "switchboard": boards.get(cid)} for cid, name, n in facet
        ],
    }


#: Jobs shown per lead at most — the newest ads first.
LEAD_JOBS_LIMIT = 5


async def lead_jobs(session: AsyncSession, tenant_id: uuid.UUID, managers: list) -> dict[uuid.UUID, list[dict]]:
    """ELI-37: the concrete jobs each lead is connected to.

    Two links, both already in the data:
      * the ads that name the person — `hub_ad_contacts` at any site of the
        employer this workspace linked the lead's company to, by the same
        surname key the company card uses to say who is already held;
      * this workspace's jobs — one taken in from such an ad
        (`external_source='hub'`, ELI-22), or one the person owns
        (`jobs.manager_id`).

    Three queries for the whole page, whatever its size: the Leads list is
    read often and the database is Disk-IO bound. The ads are public corpus
    rows (RULE 2); the jobs and links are read for THIS workspace only.
    """
    from sqlalchemy.orm import aliased

    from app.domain.hub.schemas import source_detail_url
    from app.domain.jobs.models import Job

    if not managers:
        return {}
    keys = {m.id: _surname_key(m.last_name, m.full_name) for m in managers}
    company_ids = {m.company_id for m in managers}

    anchor, site = aliased(HubCompany), aliased(HubCompany)
    sites: dict[uuid.UUID, set[uuid.UUID]] = {}
    for company_id, site_id in (
        await session.execute(
            select(HubCompanyLink.company_id, site.id)
            .join(anchor, anchor.id == HubCompanyLink.hub_company_id)
            .join(site, (site.normalized_name == anchor.normalized_name) & (site.kind == anchor.kind))
            .where(HubCompanyLink.tenant_id == tenant_id, HubCompanyLink.company_id.in_(company_ids))
        )
    ).all():
        sites.setdefault(company_id, set()).add(site_id)

    ads: dict[tuple[uuid.UUID, str], list] = {}
    order: dict[uuid.UUID, int] = {}
    all_sites = set().union(*sites.values()) if sites else set()
    wanted = {k for k in keys.values() if k}
    if all_sites and wanted:
        for ad in (
            await session.execute(
                select(
                    HubAdContact.hub_company_id, HubAdContact.person_key, HubJobPosting.id, HubJobPosting.title,
                    HubJobPosting.city, HubJobPosting.location_text, HubJobPosting.source,
                    HubJobPosting.external_id, HubJobPosting.source_url,
                )
                .join(HubJobPosting, HubJobPosting.id == HubAdContact.hub_job_posting_id)
                .where(HubAdContact.hub_company_id.in_(all_sites), HubAdContact.person_key.in_(wanted))
                .order_by(HubJobPosting.is_active.desc(), HubJobPosting.posted_at.desc().nulls_last(), HubJobPosting.title)
            )
        ).all():
            ads.setdefault((ad.hub_company_id, ad.person_key), []).append(ad)
            order.setdefault(ad.id, len(order))

    named: dict[uuid.UUID, list] = {}
    for m in managers:
        key = keys[m.id]
        if not key:
            continue
        found = [ad for s in sites.get(m.company_id, ()) for ad in ads.get((s, key), ())]
        # Merge the sites back into the query's order: open and newest first.
        named[m.id] = sorted(found, key=lambda ad: order[ad.id])

    posting_ids = {str(ad.id) for found in named.values() for ad in found}
    taken: dict[str, uuid.UUID] = {}
    owned: dict[uuid.UUID, list] = {}
    condition = Job.manager_id.in_(list(keys))
    if posting_ids:
        condition = or_(condition, (Job.external_source == "hub") & Job.external_id.in_(posting_ids))
    for job in (
        await session.execute(
            select(Job.id, Job.title, Job.location, Job.manager_id, Job.external_source, Job.external_id)
            .where(Job.tenant_id == tenant_id, condition)
            .order_by(Job.created_at.desc())
        )
    ).all():
        if job.external_source == "hub" and job.external_id in posting_ids:
            taken[job.external_id] = job.id
        if job.manager_id is not None:
            owned.setdefault(job.manager_id, []).append(job)

    from app.domain.managers.service import lead_job_url

    out: dict[uuid.UUID, list[dict]] = {}
    for m in managers:
        entries: list[dict] = []
        if m.lead_job_title:
            # ELI-65: the job a lead entered by hand is about — no ad row
            # exists for it; its link is the ad it came from, if one.
            entries.append({"title": m.lead_job_title, "location": None, "url": lead_job_url(m),
                            "posting_id": None, "job_id": None})
        seen_ads: dict[tuple[str, str | None], dict] = {}
        for ad in named.get(m.id, []):
            location = ad.city or ad.location_text
            # One role relayed by several boards is one job on the lead —
            # carrying the workspace's job whichever copy was taken in.
            same = seen_ads.get((ad.title, location))
            if same is not None:
                same["job_id"] = same["job_id"] or taken.get(str(ad.id))
                continue
            seen_ads[(ad.title, location)] = {
                "title": ad.title,
                "location": location,
                "url": source_detail_url(ad.source, ad.external_id) or ad.source_url,
                "posting_id": ad.id,
                "job_id": taken.get(str(ad.id)),
            }
            entries.append(seen_ads[(ad.title, location)])
        listed = {e["job_id"] for e in entries}
        for job in owned.get(m.id, []):
            if job.id not in listed:
                entries.append({"title": job.title, "location": job.location, "url": None, "posting_id": None, "job_id": job.id})
        if entries:
            out[m.id] = entries[:LEAD_JOBS_LIMIT]
    return out


async def company_switchboards(session: AsyncSession, tenant_id: uuid.UUID, company_ids: list[uuid.UUID]) -> dict:
    """Each of this workspace's companies' Impressum facts: Markt's (ELI-30,
    with the switchboard phone) where a linked site has them, else the
    company's own reading (ELI-39, `companies/impressum.py`, no phone).

    Markt's reading without VAT id and register gives way to the company's
    own (review of #267); its phone is kept only when both read the same
    domain, so a value is never shown under another site's provenance."""
    from app.domain.companies.impressum import board

    out = await corpus_switchboards(session, tenant_id, company_ids)
    rest = [cid for cid in company_ids if not (out.get(cid) or {}).get("vat_id") and not (out.get(cid) or {}).get("register")]
    if rest:
        from app.domain.companies.models import Company

        for company in await session.scalars(
            select(Company).where(Company.tenant_id == tenant_id, Company.id.in_(rest), Company.impressum.is_not(None))
        ):
            if (own := board(company)) is None:
                continue
            markt = out.get(company.id)
            if markt and markt.get("phone") and markt.get("domain") == own["domain"]:
                own = {**own, "phone": markt["phone"]}
            out[company.id] = own
    return out


async def corpus_switchboards(session: AsyncSession, tenant_id: uuid.UUID, company_ids: list[uuid.UUID]) -> dict:
    """ELI-30: each of this workspace's companies' Impressum switchboard,
    through its own `hub_company_link` rows (any linked site)."""
    from app.domain.hub.employer_sites import switchboards

    if not company_ids:
        return {}
    links = (
        await session.execute(
            select(HubCompanyLink.company_id, HubCompanyLink.hub_company_id).where(
                HubCompanyLink.tenant_id == tenant_id, HubCompanyLink.company_id.in_(company_ids)
            )
        )
    ).all()
    boards = await switchboards(session, {hub_id for _, hub_id in links})
    out: dict = {}
    for company_id, hub_id in links:
        if company_id not in out and hub_id in boards:
            out[company_id] = boards[hub_id]
    return out


async def follow_ups(session: AsyncSession, *, tenant_id: uuid.UUID, now: dt.datetime | None = None) -> list[dict]:
    """"Wiedervorlage": the latest call per contact, due call-backs first."""
    from app.domain.companies.models import Company
    from app.domain.managers.models import Manager, ManagerInteraction

    now = now or dt.datetime.now(dt.UTC)
    # The latest call per contact — ties on `occurred_at` broken by when the
    # row was written, then by id, so "wrong person" logged last always wins.
    ranked = (
        select(
            ManagerInteraction.id,
            func.row_number()
            .over(
                partition_by=ManagerInteraction.manager_id,
                order_by=(
                    ManagerInteraction.occurred_at.desc(),
                    ManagerInteraction.created_at.desc(),
                    ManagerInteraction.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(ManagerInteraction.tenant_id == tenant_id, ManagerInteraction.outcome.is_not(None))
        .subquery()
    )
    rows = (
        await session.execute(
            select(ManagerInteraction, Manager, Company.name)
            .join(ranked, (ranked.c.id == ManagerInteraction.id) & (ranked.c.rank == 1))
            .join(Manager, Manager.id == ManagerInteraction.manager_id)
            .join(Company, Company.id == Manager.company_id)
            .where(ManagerInteraction.tenant_id == tenant_id, Manager.tenant_id == tenant_id)
            .order_by(ManagerInteraction.occurred_at.desc())
            .limit(_FOLLOW_UP_LIMIT)
        )
    ).all()

    def aware(value: dt.datetime | None) -> dt.datetime | None:
        return value.replace(tzinfo=dt.UTC) if value is not None and value.tzinfo is None else value

    out: dict[uuid.UUID, dict] = {}
    for call, manager, company_name in rows:
        # ELI-32: "Nicht mehr kontaktieren" takes them off the Wiedervorlage.
        if call.outcome in _OFF_THE_LIST or manager.do_not_contact_at is not None:
            continue
        nxt = aware(call.next_action_at)
        item = {
            "manager_id": manager.id,
            "company_id": manager.company_id,
            "company_name": company_name,
            "full_name": manager.full_name,
            "last_name": manager.last_name or (manager.full_name.split() or [""])[-1],
            "role_title": manager.role_title,
            "phone": manager.phone,
            "email": manager.email,
            "outcome": call.outcome,
            "summary": call.summary,
            "last_call_at": aware(call.occurred_at),
            "last_call_by": call.actor_name,
            "next_action_at": nxt,
            "due": nxt is not None and nxt <= now,
        }
        # Two outcomes logged in the same instant: keep one row per contact.
        out.setdefault(manager.id, item)

    far = dt.datetime.max.replace(tzinfo=dt.UTC)
    return sorted(
        out.values(),
        key=lambda r: (
            not r["due"],
            r["next_action_at"] is None,
            r["next_action_at"] or far,
            -(r["last_call_at"].timestamp() if r["last_call_at"] else 0),
        ),
    )


async def _held_company(
    session: AsyncSession, *, tenant_id: uuid.UUID, normalized_name: str, anchor_id: uuid.UUID
) -> uuid.UUID | None:
    """This workspace's company for the employer, if it holds one — read only."""
    from app.domain.hub.service import _sibling_company_ids

    sites = await _sibling_company_ids(session, normalized_name=normalized_name)
    return await session.scalar(
        select(HubCompanyLink.company_id)
        .where(
            HubCompanyLink.tenant_id == tenant_id,
            HubCompanyLink.hub_company_id.in_(sites or [anchor_id]),
            HubCompanyLink.company_id.is_not(None),
        )
        .order_by(HubCompanyLink.created_at)
        .limit(1)
    )


async def _existing_manager(
    session: AsyncSession, tenant_id: uuid.UUID, company_id: uuid.UUID, key: str, first_name: str | None
):
    """The manager this ad person already is, or None.

    Same surname at the same company, and: the first names agree — or, when
    the ad gives none ("Frau Weber"), there is exactly ONE such manager and it
    came from an ad too. A hand-saved "Peter Weber" is not the "Frau Weber" an
    ad names; a wrong merge would put the call on someone else's history.
    """
    from app.domain.common.enums import ConfidenceSource
    from app.domain.managers.models import Manager

    same = [
        m
        for m in (
            await session.scalars(
                select(Manager)
                .where(Manager.tenant_id == tenant_id, Manager.company_id == company_id)
                .order_by(Manager.created_at, Manager.id)
            )
        ).all()
        if _surname_key(m.last_name, m.full_name) == key
    ]
    def first_of(m) -> str | None:
        # A hand-saved "Anna Kraft" may have no first_name field filled.
        if m.first_name:
            return _fold(m.first_name)
        parts = (m.full_name or "").split()
        return _fold(parts[0]) if len(parts) > 1 else None

    if first_name:
        first = _fold(first_name)
        return next((m for m in same if first_of(m) == first), None) or next(
            (m for m in same if not m.first_name and m.source == ConfidenceSource.PUBLIC_WEB.value), None
        )
    return same[0] if len(same) == 1 and (same[0].first_name is None or same[0].source == ConfidenceSource.PUBLIC_WEB.value) else None


async def log_call(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    hub_company_id: uuid.UUID,
    person_key: str,
    outcome: str,
    summary: str | None = None,
    next_action_at: dt.datetime | None = None,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
) -> dict:
    """One call to a person from the list. Raises `NotOnTheList`, `Erased`,
    and pydantic's ValidationError for a bad outcome / missing call-back date."""
    from app.domain.common.enums import ConfidenceSource, InteractionType
    from app.domain.erasure import service as erasure
    from app.domain.hub.schemas import source_detail_url
    from app.domain.hub.service import workspace_company
    from app.domain.managers import service as managers
    from app.domain.managers.schemas import ManagerCreate, ManagerInteractionCreate

    call = ManagerInteractionCreate(
        interaction_type=InteractionType.BUSINESS_CALL, outcome=outcome,
        next_action_at=next_action_at, summary=summary,
    )
    anchor = await session.get(HubCompany, hub_company_id)
    if anchor is None or anchor.kind != EMPLOYER:
        raise NotOnTheList("no such employer")
    mentions = (
        await session.execute(
            select(HubAdContact, HubJobPosting)
            .join(HubJobPosting, HubJobPosting.id == HubAdContact.hub_job_posting_id)
            .join(HubCompany, HubCompany.id == HubAdContact.hub_company_id)
            .where(
                HubCompany.normalized_name == anchor.normalized_name,
                HubAdContact.person_key == person_key,
                HubJobPosting.is_active,
            )
        )
    ).all()
    if not mentions:
        raise NotOnTheList(person_key)
    contact, posting = max(
        mentions,
        key=lambda m: (m[0].phone_kind == "direct", m[0].phone is not None, m[0].first_name is not None),
    )
    named = next((c for c, _ in mentions if c.first_name), contact)
    # Plain values only from here: adopting the employer may commit or roll
    # back, which expires every loaded row (see `workspace_company`).
    person = {
        "full_name": named.full_name, "first_name": named.first_name, "last_name": contact.last_name,
        "role_title": contact.role_title or next((c.role_title for c, _ in mentions if c.role_title), None),
        "email": contact.email, "phone": contact.phone,
        "source_detail": (posting.source_url or source_detail_url(posting.source, posting.external_id)
                          or f"hub_job_postings/{posting.id}")[:500],
    }
    anchor_id, anchor_name, anchor_normalized = anchor.id, anchor.name, anchor.normalized_name

    # The contact may already be in the workspace (saved from Markt, an
    # earlier call, or re-added by hand after an erasure with the recruiter's
    # confirmation): look before adopting anything.
    held = await _held_company(session, tenant_id=tenant_id, normalized_name=anchor_normalized, anchor_id=anchor_id)
    manager = await _existing_manager(session, tenant_id, held, person_key, person["first_name"]) if held else None

    created = False
    company_id = held
    if manager is None:
        # A new person: never one this workspace erased (e-mail, direct
        # phone, or surname at this employer).
        guard = await erasure.person_guard(session, tenant_id)
        if guard.blocks(
            company_name=anchor_name, surname=person["last_name"], phone=person["phone"], email=person["email"]
        ):
            raise Erased(person_key)
        company_id = await workspace_company(
            session, tenant_id=tenant_id, hub_company_id=anchor_id, normalized_name=anchor_normalized,
            actor=actor_name,
        )
        try:
            manager = await managers.create_manager(
                session, tenant_id=tenant_id,
                payload=ManagerCreate(
                    company_id=company_id, full_name=person["full_name"], first_name=person["first_name"],
                    last_name=person["last_name"], role_title=person["role_title"], email=person["email"],
                    phone=person["phone"], source=ConfidenceSource.PUBLIC_WEB, source_detail=person["source_detail"],
                ),
            )
        except erasure.Suppressed as exc:
            raise Erased(person_key) from exc
        created = True

    row = await managers.log_interaction(
        session, tenant_id=tenant_id, manager_id=manager.id, payload=call,
        actor_user_id=actor_user_id, actor_name=actor_name,
    )
    return {
        "manager_id": manager.id,
        "company_id": company_id,
        "interaction_id": row.id if row else None,
        "created_manager": created,
        "art14_outstanding": bool(manager.art14_outstanding),
    }
