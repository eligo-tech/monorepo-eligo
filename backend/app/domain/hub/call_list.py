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

from sqlalchemy import case, distinct, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.hub.contacts import _fold, person_key
from app.domain.hub.models import EMPLOYER, HubAdContact, HubCompany, HubCompanyLink, HubJobPosting

#: Outcomes after which a person is not called again from the list.
_OFF_THE_LIST = ("wrong_person",)


class NotOnTheList(LookupError):
    """No open ad of this employer names that person."""


class Erased(Exception):
    """This workspace erased the person (GDPR Art. 17)."""


def _surname_key(last_name: str | None, full_name: str | None) -> str | None:
    name = last_name or full_name
    return person_key(None, name) if name and name.split() else None


async def _called(session: AsyncSession, tenant_id: uuid.UUID) -> set[tuple[str, str]]:
    """(employer normalized name, surname key) of every person this workspace
    has a call outcome for — they live in follow-ups, not in the market tab."""
    from app.domain.companies.models import Company
    from app.domain.managers.models import Manager, ManagerInteraction

    rows = await session.execute(
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
        .distinct()
    )
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

    # Erased persons are filtered after the page is read (their fingerprints
    # are keyed hashes, not something SQL can compare): read a little more
    # than a page so a filtered row does not shorten it.
    groups = (await session.execute(stmt.limit(limit + 1 + 20).offset(offset))).all()

    rows: list[dict] = []
    for normalized, key, count in groups:
        mentions = (
            await session.execute(
                select(
                    HubAdContact.full_name, HubAdContact.first_name, HubAdContact.last_name,
                    HubAdContact.salutation, HubAdContact.role_title, HubAdContact.phone,
                    HubAdContact.phone_kind, HubAdContact.email, HubAdContact.quote,
                    HubAdContact.hub_company_id, HubCompany.name.label("company_name"),
                    HubJobPosting.id.label("posting_id"), HubJobPosting.title.label("posting_title"),
                    HubJobPosting.source, HubJobPosting.source_url, HubJobPosting.external_id,
                    HubJobPosting.first_seen_at,
                )
                .join(HubJobPosting, HubJobPosting.id == HubAdContact.hub_job_posting_id)
                .join(HubCompany, HubCompany.id == HubAdContact.hub_company_id)
                .where(
                    HubCompany.normalized_name == normalized,
                    HubAdContact.person_key == key,
                    HubJobPosting.is_active,
                )
                .order_by(HubJobPosting.first_seen_at.desc())
            )
        ).all()
        if not mentions:
            continue
        best = _best(mentions)
        named = next((m for m in mentions if m.first_name), best)
        if guard.blocks(company_name=best.company_name, surname=best.last_name, phone=best.phone):
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
            "email": best.email or next((m.email for m in mentions if m.email), None),
            "open_ads": count,
            "posting_title": best.posting_title,
            "quote": best.quote,
            "source_url": best.source_url or source_detail_url(best.source, best.external_id),
            "reach": "named_phone" if best.phone else "named",
        })
        if len(rows) == limit + 1:
            break
    has_more = len(rows) > limit
    return {"rows": rows[:limit], "has_more": has_more, "offset": offset, "limit": limit}


async def follow_ups(session: AsyncSession, *, tenant_id: uuid.UUID, now: dt.datetime | None = None) -> list[dict]:
    """"Wiedervorlage": the latest call per contact, due call-backs first."""
    from app.domain.companies.models import Company
    from app.domain.managers.models import Manager, ManagerInteraction

    now = now or dt.datetime.now(dt.UTC)
    latest = (
        select(ManagerInteraction.manager_id, func.max(ManagerInteraction.occurred_at).label("at"))
        .where(ManagerInteraction.tenant_id == tenant_id, ManagerInteraction.outcome.is_not(None))
        .group_by(ManagerInteraction.manager_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(ManagerInteraction, Manager, Company.name)
            .join(latest, (latest.c.manager_id == ManagerInteraction.manager_id) & (latest.c.at == ManagerInteraction.occurred_at))
            .join(Manager, Manager.id == ManagerInteraction.manager_id)
            .join(Company, Company.id == Manager.company_id)
            .where(
                ManagerInteraction.tenant_id == tenant_id,
                Manager.tenant_id == tenant_id,
                ManagerInteraction.outcome.is_not(None),
            )
        )
    ).all()

    def aware(value: dt.datetime | None) -> dt.datetime | None:
        return value.replace(tzinfo=dt.UTC) if value is not None and value.tzinfo is None else value

    out: dict[uuid.UUID, dict] = {}
    for call, manager, company_name in rows:
        if call.outcome in _OFF_THE_LIST:
            continue
        nxt = aware(call.next_action_at)
        item = {
            "manager_id": manager.id,
            "company_id": manager.company_id,
            "company_name": company_name,
            "full_name": manager.full_name,
            "last_name": manager.last_name or manager.full_name.split()[-1],
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
    from app.domain.managers.models import Manager
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

    guard = await erasure.person_guard(session, tenant_id)
    if guard.blocks(company_name=anchor_name, surname=person["last_name"], phone=person["phone"]):
        raise Erased(person_key)

    company_id = await workspace_company(
        session, tenant_id=tenant_id, hub_company_id=anchor_id, normalized_name=anchor_normalized, actor=actor_name
    )

    # The contact may already be in the workspace (saved from Markt, or an
    # earlier call): same company, same surname, and the first name agrees.
    candidates = (
        await session.scalars(select(Manager).where(Manager.tenant_id == tenant_id, Manager.company_id == company_id))
    ).all()
    first = _fold(person["first_name"]) if person["first_name"] else None
    manager = next(
        (
            m for m in candidates
            if _surname_key(m.last_name, m.full_name) == person_key
            and (first is None or not m.first_name or _fold(m.first_name) == first)
        ),
        None,
    )
    created = False
    if manager is None:
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
