"""Company business logic."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import and_, case, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.companies.models import Company
from app.domain.common.enums import ConfidenceSource
from app.domain.companies.schemas import CompanyCreate
from app.domain.hub.resolution import normalize_company_name, normalize_domain
from app.domain.verification import service as verification
from app.domain.verification.schemas import ProposedChange

logger = get_logger(__name__)


async def list_companies(
    session: AsyncSession, *, tenant_id: uuid.UUID, limit: int = 100
) -> list[Company]:
    result = await session.execute(
        select(Company)
        .where(Company.tenant_id == tenant_id)
        .order_by(Company.name)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_company(
    session: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> Company | None:
    result = await session.execute(
        select(Company).where(
            Company.tenant_id == tenant_id, Company.id == company_id
        )
    )
    return result.scalar_one_or_none()


class CompanyExists(ValueError):
    """ELI-43: the workspace already has this company (same name, and the
    same town when one was given)."""

    def __init__(self, company_id: uuid.UUID) -> None:
        super().__init__(f"company exists as {company_id}")
        self.company_id = company_id


def _name_key(name: str) -> str:
    return normalize_company_name(name) or name.strip().casefold()


async def find_existing(
    session: AsyncSession, *, tenant_id: uuid.UUID, name: str, location: str | None
) -> Company | None:
    """The workspace's company of the same normalized name — in the same town
    when a town is given (a same-name firm elsewhere is another company)."""
    from app.domain.companies.market import town_key

    key, town = _name_key(name), town_key(location)
    rows = (
        await session.scalars(
            select(Company).where(Company.tenant_id == tenant_id).order_by(Company.created_at, Company.id)
        )
    ).all()
    for row in rows:
        if _name_key(row.name) != key:
            continue
        if town is None or town_key(row.location) == town:
            return row
    return None


async def _record_status(
    session: AsyncSession, *, company: Company, status: str, actor: str | None
) -> None:
    """A person's Lead / Kunde, through the verification gate: an
    `is_client` record + VERIFY/WRITE receipts naming the person. That record
    is what makes the status a decision (see `_decided`). Does not commit."""
    from app.domain.hub.models import HubCompanyLink

    value = status == "client"

    async def _apply(_session: AsyncSession, _change: ProposedChange) -> None:
        company.is_client = value
        # The workspace's Markt links say the same.
        for link in (
            await _session.scalars(
                select(HubCompanyLink).where(
                    HubCompanyLink.tenant_id == company.tenant_id, HubCompanyLink.company_id == company.id
                )
            )
        ).all():
            link.relationship = "client" if value else "prospect"

    result = await verification.verify_and_commit(
        session,
        change=ProposedChange(
            tenant_id=company.tenant_id,
            entity_type="company",
            entity_id=company.id,
            field="is_client",
            proposed_value="true" if value else "false",
            source=ConfidenceSource.HUMAN_VERIFIED,
            source_detail="Status Lead/Kunde von Hand gesetzt",
            confidence=1.0,
        ),
        agent="recruiter_manual_edit",
        apply_hook=_apply,
        actor=actor,
    )
    if not result.committed:  # never at confidence 1.0 — but never silently either
        await session.rollback()
        raise RuntimeError(f"company status not committed: {result.reason}")


async def create_company(
    session: AsyncSession, *, data: CompanyCreate, actor: str | None = None
) -> Company:
    """A company typed in by a person (ELI-43, and the new client of a new
    mandate). Refuses a duplicate with `CompanyExists`. With a town, a Markt
    employer of the same name in the same town is linked at once — the
    daily linker's own rule (`market.exact_matches`), so its job ads and
    Impressum show from the first page view; without one nothing is linked
    (a name alone is ambiguous)."""
    from app.domain.companies import market

    tenant_id = data.tenant_id or settings.default_tenant_id
    existing = await find_existing(session, tenant_id=tenant_id, name=data.name, location=data.location)
    if existing is not None:
        raise CompanyExists(existing.id)
    company = Company(
        tenant_id=tenant_id,
        name=data.name,
        domain=data.domain or normalize_domain(data.website),
        industry=data.industry,
        location=data.location,
        is_client=data.is_client,
        source=data.source or "manual",
        bd_signals=data.bd_signals,
    )
    session.add(company)
    await session.commit()
    await session.refresh(company)
    company_id = company.id
    if data.location:
        # Best effort: the company is saved; a link that fails is retried by
        # the daily linker rather than reported as "nicht gespeichert".
        try:
            for row, sites in await market.exact_matches(session, tenant_id, company_ids=[company.id]):
                towns = sorted({h.city or h.postal_code or "" for h in sites})
                await market.link(
                    session,
                    tenant_id=tenant_id,
                    company=row,
                    sites=sites,
                    basis=f"same name and town ({', '.join(towns)[:120]}), on create",
                    agent="company_market_link",
                    actor=actor,
                )
        except RuntimeError:
            await session.rollback()
            logger.warning("company %s: market link on create failed; the daily job retries", company_id)
        await session.refresh(company)
    if data.status is not None:
        # After the link, so the link's relationship says the same (`_apply`).
        await _record_status(session, company=company, status=data.status, actor=actor)
        await session.commit()
        await session.refresh(company)
    return company


async def set_status(
    session: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID, status: str, actor: str | None
) -> Company:
    """ELI-43: Lead / Kunde on the company page. Raises LookupError for a
    company not in this workspace."""
    company = await get_company(session, tenant_id=tenant_id, company_id=company_id)
    if company is None:
        raise LookupError(str(company_id))
    await _record_status(session, company=company, status=status, actor=actor)
    await session.commit()
    await session.refresh(company)
    return company


def _decided():
    """True where a person set Lead / Kunde (ELI-43): a committed `is_client`
    record. Then `is_client` is that decision; elsewhere it is not (imports
    set it on every row) and the counts decide."""
    from app.domain.verification.models import EnrichmentRecord

    return (
        select(EnrichmentRecord.id)
        .where(
            EnrichmentRecord.tenant_id == Company.tenant_id,
            EnrichmentRecord.entity_type == "company",
            EnrichmentRecord.entity_id == Company.id,
            EnrichmentRecord.field == "is_client",
            EnrichmentRecord.committed.is_(True),
        )
        .correlate(Company)
        .exists()
    )


# ---------------------------------------------------------------------------
# Unternehmen (ELI-33): every company of the workspace, and one page each.
# ---------------------------------------------------------------------------

#: "Kunde" = at least one manager; "Lead" = at least one new contact taken
#: from Markt (stage bus_dev). A client with new contacts is both. Not
#: `is_client`: the imports set it on every row (measured 2026-11-12).
#: ELI-31: a company taken from Markt with "Übernehmen" and no contact yet
#: (source `hub:…`, `is_client = false` since ELI-36, no manager) is a Lead
#: too — the Markt card says "✓ Lead", so the Leads filter has to show it.
#: ELI-43: where a person set Lead / Kunde (`_decided`), that decision wins:
#: a Kunde is under Kunden without a manager, a Lead under Leads without a
#: contact, and a company called Lead is not a Kunde for its managers.
OVERVIEW_KINDS = ("all", "clients", "leads")


def _count_people(stage: str):
    from app.domain.managers.models import Manager

    return (
        select(func.count(Manager.id))
        .where(Manager.company_id == Company.id, Manager.tenant_id == Company.tenant_id, Manager.stage == stage)
        .correlate(Company)
        .scalar_subquery()
    )


async def overview(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    kind: str = "all",
    q: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    """Every company here with how many managers, leads and mandates it has
    and when someone last spoke to anyone there. A–Z."""
    from app.domain.jobs.models import Job
    from app.domain.managers.models import Manager, ManagerInteraction

    managers = _count_people("manager").label("managers")
    leads = _count_people("bus_dev").label("leads")
    mandates = (
        select(func.count(Job.id))
        .where(Job.client_company_id == Company.id, Job.tenant_id == Company.tenant_id)
        .correlate(Company)
        .scalar_subquery()
        .label("mandates")
    )
    last_contact = (
        select(func.max(ManagerInteraction.occurred_at))
        .join(Manager, Manager.id == ManagerInteraction.manager_id)
        .where(Manager.company_id == Company.id, ManagerInteraction.tenant_id == Company.tenant_id)
        .correlate(Company)
        .scalar_subquery()
        .label("last_contact_at")
    )
    markt_lead = and_(
        Company.source.like("hub:%"), Company.is_client.is_(False), _count_people("manager") == 0
    )
    decided = _decided()
    status = case((decided, case((Company.is_client.is_(True), "client"), else_="lead")), else_=None)
    stmt = select(
        Company.id, Company.name, Company.location, managers, leads, mandates, last_contact,
        markt_lead.label("markt_lead"), status.label("status"),
    ).where(Company.tenant_id == tenant_id)
    if kind == "clients":
        stmt = stmt.where(
            or_(and_(decided, Company.is_client.is_(True)), and_(not_(decided), _count_people("manager") > 0))
        )
    elif kind == "leads":
        stmt = stmt.where(
            or_(
                _count_people("bus_dev") > 0,
                and_(decided, Company.is_client.is_(False)),
                and_(not_(decided), markt_lead),
            )
        )
    if q and q.strip():
        needle = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(func.lower(Company.name).like(f"%{needle}%", escape="\\"))
    rows = await session.execute(stmt.order_by(func.lower(Company.name), Company.id).limit(limit))
    from app.domain.companies.market import to_review

    review = await to_review(session, tenant_id)
    return [
        {
            "id": r.id,
            "name": r.name,
            "location": r.location,
            "managers": int(r.managers or 0),
            "leads": int(r.leads or 0),
            "mandates": int(r.mandates or 0),
            "markt_lead": bool(r.markt_lead),
            "status": r.status,
            "last_contact_at": _aware(r.last_contact_at),
            # ELI-33 step 2b: Markt sites of the same name to confirm or dismiss.
            "to_review": review.get(r.id, 0),
        }
        for r in rows
    ]


async def _page_status(session: AsyncSession, company: Company, people) -> dict:
    """Kunde / Lead for one company: a person's decision (`status_set`), else
    the overview's rule (manager → Kunde; new contact or taken from Markt →
    Lead)."""
    decided = bool(await session.scalar(select(_decided()).select_from(Company).where(Company.id == company.id)))
    if decided:
        return {"status": "client" if company.is_client else "lead", "status_set": True}
    stages = {m.stage for m, _ in people}
    status = None
    if "manager" in stages:
        status = "client"
    elif "bus_dev" in stages or ((company.source or "").startswith("hub:") and not company.is_client):
        status = "lead"
    return {"status": status, "status_set": False}


def _aware(value):
    return value.replace(tzinfo=dt.UTC) if value is not None and value.tzinfo is None else value


async def company_page(session: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID) -> dict | None:
    """One company: its managers and leads (each with the last contact), its
    mandates, and the switchboard from its Impressum (ELI-30) if verified."""
    from app.domain.hub.call_list import company_switchboards
    from app.domain.jobs.models import Job
    from app.domain.managers.models import Manager, ManagerInteraction

    company = await get_company(session, tenant_id=tenant_id, company_id=company_id)
    if company is None:
        return None
    last = (
        select(ManagerInteraction.manager_id, func.max(ManagerInteraction.occurred_at).label("at"))
        .where(ManagerInteraction.tenant_id == tenant_id)
        .group_by(ManagerInteraction.manager_id)
        .subquery()
    )
    people = (
        await session.execute(
            select(Manager, last.c.at)
            .outerjoin(last, last.c.manager_id == Manager.id)
            .where(Manager.tenant_id == tenant_id, Manager.company_id == company_id)
            .order_by(func.lower(Manager.full_name))
        )
    ).all()

    def person(m, at) -> dict:
        return {
            "id": m.id,
            "full_name": m.full_name,
            "role_title": m.role_title,
            "email": m.email,
            "phone": m.phone,
            "stage": m.stage,
            "last_contact_at": _aware(at),
        }

    jobs = (
        await session.scalars(
            select(Job)
            .where(Job.tenant_id == tenant_id, Job.client_company_id == company_id)
            .order_by(Job.created_at.desc())
        )
    ).all()
    boards = await company_switchboards(session, tenant_id, [company_id])
    from app.domain.companies.market import open_jobs, suggestions

    in_market = await open_jobs(session, tenant_id=tenant_id, company_id=company_id)
    candidates = [] if in_market["linked"] else await suggestions(session, tenant_id=tenant_id, company=company)
    return {
        "company": {
            "id": company.id,
            "name": company.name,
            "location": company.location,
            "domain": company.domain,
            "industry": company.industry,
            "source": company.source,
            **await _page_status(session, company, people),
        },
        "managers": [person(m, at) for m, at in people if m.stage != "bus_dev"],
        "leads": [person(m, at) for m, at in people if m.stage == "bus_dev"],
        "mandates": [{"id": j.id, "title": j.title, "status": j.status, "location": j.location} for j in jobs],
        "switchboard": boards.get(company_id),
        # ELI-33: what the company is hiring for now, from Markt.
        "market": in_market,
        # ELI-33 step 2b: same name in Markt, another or unknown town.
        "suggestions": candidates,
    }
