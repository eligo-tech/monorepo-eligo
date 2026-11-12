"""Company business logic."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.companies.models import Company
from app.domain.companies.schemas import CompanyCreate


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


async def create_company(
    session: AsyncSession, *, data: CompanyCreate
) -> Company:
    company = Company(
        tenant_id=data.tenant_id or settings.default_tenant_id,
        name=data.name,
        domain=data.domain,
        industry=data.industry,
        location=data.location,
        is_client=data.is_client,
        source=data.source,
        bd_signals=data.bd_signals,
    )
    session.add(company)
    await session.commit()
    await session.refresh(company)
    return company

# ---------------------------------------------------------------------------
# Unternehmen (ELI-33): every company of the workspace, and one page each.
# ---------------------------------------------------------------------------

#: "Kunde" = at least one manager; "Lead" = at least one new contact taken
#: from Markt (stage bus_dev). A client with new contacts is both. Not
#: `is_client`: the imports set it on every row (measured 2026-11-12).
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
    stmt = select(Company.id, Company.name, Company.location, managers, leads, mandates, last_contact).where(
        Company.tenant_id == tenant_id
    )
    if kind == "clients":
        stmt = stmt.where(_count_people("manager") > 0)
    elif kind == "leads":
        stmt = stmt.where(_count_people("bus_dev") > 0)
    if q and q.strip():
        needle = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(func.lower(Company.name).like(f"%{needle}%", escape="\\"))
    rows = await session.execute(stmt.order_by(func.lower(Company.name), Company.id).limit(limit))
    return [
        {
            "id": r.id,
            "name": r.name,
            "location": r.location,
            "managers": int(r.managers or 0),
            "leads": int(r.leads or 0),
            "mandates": int(r.mandates or 0),
            "last_contact_at": _aware(r.last_contact_at),
        }
        for r in rows
    ]


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
    return {
        "company": {
            "id": company.id,
            "name": company.name,
            "location": company.location,
            "domain": company.domain,
            "industry": company.industry,
            "source": company.source,
        },
        "managers": [person(m, at) for m, at in people if m.stage != "bus_dev"],
        "leads": [person(m, at) for m, at in people if m.stage == "bus_dev"],
        "mandates": [{"id": j.id, "title": j.title, "status": j.status, "location": j.location} for j in jobs],
        "switchboard": boards.get(company_id),
    }
