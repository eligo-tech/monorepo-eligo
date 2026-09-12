"""Managers business logic. No FastAPI imports; tenant_id is always explicit."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager, ManagerInteraction
from app.domain.managers.schemas import (
    ManagerCreate,
    ManagerInteractionCreate,
    ManagerUpdate,
)


class CompanyNotInTenant(Exception):
    """The company does not belong to this tenant (or does not exist).

    Raised rather than returning None so the caller cannot mistake a rejected
    write for an empty result: a manager attached to another tenant's company
    would be a cross-tenant leak, not a 404.
    """


async def _own_company(
    session: AsyncSession, *, tenant_id: uuid.UUID, company_id: uuid.UUID
) -> Company:
    company = await session.scalar(
        select(Company).where(
            Company.id == company_id, Company.tenant_id == tenant_id
        )
    )
    if company is None:
        raise CompanyNotInTenant(str(company_id))
    return company


async def list_managers(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = 100,
) -> list[Manager]:
    """This workspace's contacts, optionally narrowed.

    `q` searches the person AND their employer, because a recruiter looking for
    a contact remembers one or the other — "the CTO at Bergfreunde" is as common
    a way in as the name. Searching only the name would send them scrolling
    through an alphabetical list of 650.
    """
    stmt = select(Manager).where(Manager.tenant_id == tenant_id)
    if company_id is not None:
        stmt = stmt.where(Manager.company_id == company_id)
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.join(Company, Company.id == Manager.company_id).where(
            or_(
                func.lower(Manager.full_name).like(needle),
                func.lower(Manager.role_title).like(needle),
                func.lower(Company.name).like(needle),
            )
        )
    result = await session.execute(
        stmt.order_by(Manager.full_name).limit(limit)
    )
    return list(result.scalars().all())


async def get_manager(
    session: AsyncSession, *, tenant_id: uuid.UUID, manager_id: uuid.UUID
) -> Manager | None:
    manager = await session.scalar(
        select(Manager)
        .options(selectinload(Manager.interactions))
        .where(Manager.id == manager_id, Manager.tenant_id == tenant_id)
    )
    if manager is None:
        return None
    # Counted here rather than in the router so the profile is one request. Set
    # as transient attributes: they are facts ABOUT the row, not columns on it,
    # and storing them would mean keeping two numbers in step with the tables
    # that produce them.
    manager.job_count = (
        await session.scalar(
            select(func.count(Job.id)).where(
                Job.tenant_id == tenant_id, Job.manager_id == manager_id
            )
        )
    ) or 0
    manager.open_job_count = (
        await session.scalar(
            select(func.count(Job.id)).where(
                Job.tenant_id == tenant_id,
                Job.manager_id == manager_id,
                Job.status == "open",
            )
        )
    ) or 0
    manager.note_count = len(manager.interactions)
    return manager


async def create_manager(
    session: AsyncSession, *, tenant_id: uuid.UUID, payload: ManagerCreate
) -> Manager:
    """Add a contact at one of this tenant's own companies.

    The company is verified to belong to the tenant first. `company_id` is a
    client-supplied UUID, and without that check a caller could attach a person
    to another tenant's company — RLS would not catch it, because the write
    itself is perfectly valid for the writer's own tenant.
    """
    await _own_company(session, tenant_id=tenant_id, company_id=payload.company_id)

    manager = Manager(
        tenant_id=tenant_id,
        company_id=payload.company_id,
        full_name=payload.full_name.strip(),
        first_name=payload.first_name,
        last_name=payload.last_name,
        role_title=payload.role_title,
        department=payload.department,
        email=payload.email,
        phone=payload.phone,
        linkedin_url=payload.linkedin_url,
        source=payload.source.value,
        source_detail=payload.source_detail,
        notes=payload.notes,
    )
    session.add(manager)
    await session.commit()
    await session.refresh(manager)
    return manager


async def update_manager(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID,
    payload: ManagerUpdate,
) -> Manager | None:
    manager = await session.scalar(
        select(Manager).where(
            Manager.id == manager_id, Manager.tenant_id == tenant_id
        )
    )
    if manager is None:
        return None
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(manager, field, value)
    await session.commit()
    await session.refresh(manager)
    return manager


async def mark_art14_notified(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID,
    at: dt.datetime | None = None,
) -> Manager | None:
    """Record that the data subject has been informed (GDPR Art. 14).

    Separate from `update_manager` on purpose: this asserts something happened
    in the world, and it should not be settable as a side effect of editing a
    phone number.
    """
    manager = await session.scalar(
        select(Manager).where(
            Manager.id == manager_id, Manager.tenant_id == tenant_id
        )
    )
    if manager is None:
        return None
    manager.art14_notified_at = at or dt.datetime.now(dt.UTC)
    await session.commit()
    await session.refresh(manager)
    return manager


async def managers_owing_art14(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[Manager]:
    """The work queue: people we hold data on who have not been told.

    Filtered in Python over the tenant's rows rather than in SQL, because the
    obligation is derived from `source` by one shared predicate
    (`owes_art14_notice`) and duplicating that set into a WHERE clause is how
    the two definitions drift apart.
    """
    rows = await list_managers(session, tenant_id=tenant_id, limit=10_000)
    return [m for m in rows if m.art14_outstanding]


async def log_interaction(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID,
    payload: ManagerInteractionCreate,
) -> ManagerInteraction | None:
    manager = await session.scalar(
        select(Manager).where(
            Manager.id == manager_id, Manager.tenant_id == tenant_id
        )
    )
    if manager is None:
        return None
    interaction = ManagerInteraction(
        tenant_id=tenant_id,
        manager_id=manager_id,
        candidate_id=payload.candidate_id,
        job_id=payload.job_id,
        interaction_type=payload.interaction_type.value,
        occurred_at=payload.occurred_at or dt.datetime.now(dt.UTC),
        summary=payload.summary,
    )
    session.add(interaction)
    await session.commit()
    await session.refresh(interaction)
    return interaction


async def list_interactions(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    manager_id: uuid.UUID,
    limit: int = 200,
) -> list[ManagerInteraction]:
    result = await session.execute(
        select(ManagerInteraction)
        .where(
            ManagerInteraction.tenant_id == tenant_id,
            ManagerInteraction.manager_id == manager_id,
        )
        .order_by(ManagerInteraction.occurred_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
