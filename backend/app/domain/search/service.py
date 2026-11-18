"""Global search over one workspace's own records (ELI-52).

Four small queries, each `WHERE tenant_id = :tenant` (and RLS underneath on
Postgres), each capped at `limit`. The shared Markt corpus (`hub_*`) is NOT
searched here: Markt has its own search, and a name typed into the command bar
means a record of this workspace.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.candidates.models import Candidate
from app.domain.companies.models import Company
from app.domain.jobs.models import Job
from app.domain.managers.models import Manager
from app.domain.search.schemas import ContactHit, SearchHit, SearchResults

#: Below this a term matches half the pool and tells the recruiter nothing.
MIN_LENGTH = 2


def _contains(text: str) -> str:
    """A LIKE pattern for "contains", with % and _ taken literally."""
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _like(column, pattern: str):
    return func.lower(func.coalesce(column, "")).like(pattern, escape="\\")


def _join(*parts: str | None) -> str | None:
    kept = [p.strip() for p in parts if p and p.strip()]
    return " · ".join(kept) or None


async def search(session: AsyncSession, *, tenant_id: uuid.UUID, q: str | None, limit: int = 5) -> SearchResults:
    term = (q or "").strip()
    if len(term) < MIN_LENGTH:
        return SearchResults()
    pattern = _contains(term)

    candidates = (
        await session.execute(
            select(Candidate.id, Candidate.full_name, Candidate.current_title, Candidate.current_company, Candidate.city)
            .where(Candidate.tenant_id == tenant_id, _like(Candidate.full_name, pattern))
            .order_by(Candidate.full_name)
            .limit(limit)
        )
    ).all()

    jobs = (
        await session.execute(
            select(Job.id, Job.title, Job.location, Job.status, Company.name)
            .outerjoin(Company, (Company.id == Job.client_company_id) & (Company.tenant_id == tenant_id))
            .where(Job.tenant_id == tenant_id, _like(Job.title, pattern))
            .order_by(Job.title)
            .limit(limit)
        )
    ).all()

    companies = (
        await session.execute(
            select(Company.id, Company.name, Company.location)
            .where(Company.tenant_id == tenant_id, _like(Company.name, pattern))
            .order_by(Company.name)
            .limit(limit)
        )
    ).all()

    contacts = (
        await session.execute(
            select(Manager.id, Manager.full_name, Manager.role_title, Manager.stage, Company.name)
            .join(Company, (Company.id == Manager.company_id) & (Company.tenant_id == tenant_id))
            .where(
                Manager.tenant_id == tenant_id,
                or_(_like(Manager.full_name, pattern), _like(Company.name, pattern)),
            )
            .order_by(Manager.full_name)
            .limit(limit)
        )
    ).all()

    return SearchResults(
        candidates=[
            SearchHit(id=str(r.id), label=r.full_name, subtitle=_join(r.current_title, r.current_company, r.city))
            for r in candidates
        ],
        jobs=[SearchHit(id=str(r.id), label=r.title, subtitle=_join(r.name, r.location)) for r in jobs],
        companies=[SearchHit(id=str(r.id), label=r.name, subtitle=_join(r.location)) for r in companies],
        contacts=[
            ContactHit(
                id=str(r.id),
                label=r.full_name,
                subtitle=_join(r.role_title, r.name),
                kind="lead" if r.stage == "bus_dev" else "manager",
            )
            for r in contacts
        ],
    )
